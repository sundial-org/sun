"""Preserve completed sampler adapters locally without storing credentials or URLs."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import getpass
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import sys
import tarfile
import time

from data import canonical
from run_experiment import BASE_URL, write_json


def main():
    logging.disable(logging.CRITICAL)
    os.environ["TINKER_TELEMETRY"] = "0"
    import httpx
    import tinker
    run = Path(__file__).resolve().parent / "runs" / sys.argv[1]
    if not run.is_dir():
        raise ValueError("Unknown run")
    key = getpass.getpass("Tinker credential (memory only): ")
    service = tinker.ServiceClient(api_key=key, base_url=BASE_URL)
    rest = service.create_rest_client()
    folder = run / "checkpoint_archives"
    folder.mkdir(exist_ok=True)
    failures = {}

    def archive(manifest):
        name = manifest["name"]
        if not re.fullmatch(r"[A-Za-z0-9-]+", name):
            raise ValueError("Unsafe checkpoint name")
        target = folder / (name + ".tar")
        receipt = folder / (name + ".json")
        if receipt.exists() and target.exists():
            saved = json.loads(receipt.read_text())
            if saved["bytes"] == target.stat().st_size:
                return saved
        signed = rest.get_checkpoint_archive_url_from_tinker_path(manifest["sampling_path"]).result()
        if not signed.url.startswith("https://"):
            raise ValueError("Non-HTTPS archive URL")
        temporary = target.with_suffix(".part")
        digest, size = hashlib.sha256(), 0
        with httpx.stream("GET", signed.url, timeout=120, follow_redirects=True) as response:
            response.raise_for_status()
            with temporary.open("wb") as output:
                for chunk in response.iter_bytes(1024 * 1024):
                    output.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
        with tarfile.open(temporary) as bundle:
            members = [m.name for m in bundle.getmembers() if m.isfile()]
        if not members or not size:
            raise ValueError("Empty checkpoint archive")
        temporary.replace(target)
        saved = {"name": name, "sampling_path": manifest["sampling_path"],
                 "archive": target.name, "bytes": size, "sha256": digest.hexdigest(), "members": members}
        write_json(receipt, saved)
        print(canonical({"event": "adapter_archived", "name": name, "bytes": size}), flush=True)
        return saved

    while True:
        manifests = [json.loads(p.read_text()) for p in (run / "training").glob("*/checkpoint.json")]
        todo = [m for m in manifests if not (folder / (m["name"] + ".json")).exists()
                and failures.get(m["name"], 0) < 3]
        with ThreadPoolExecutor(max_workers=3) as pool:
            jobs = {pool.submit(archive, m): m["name"] for m in todo}
            for future in as_completed(jobs):
                name = jobs[future]
                try:
                    future.result()
                except Exception as error:
                    failures[name] = failures.get(name, 0) + 1
                    # HTTP errors can contain signed URLs, so never log their text.
                    print(canonical({"event": "archive_error", "name": name,
                                     "error_type": type(error).__name__, "attempt": failures[name]}), flush=True)
        status = json.loads((run / "status.json").read_text()) if (run / "status.json").exists() else {}
        if status.get("phase") == "complete":
            receipts = [json.loads(p.read_text()) for p in folder.glob("*.json")]
            missing = [m["name"] for m in manifests if not (folder / (m["name"] + ".json")).exists()]
            if not missing or all(failures.get(name, 0) >= 3 for name in missing):
                write_json(run / "archive_manifest.json", {"adapters": receipts, "missing": missing,
                           "total_bytes": sum(r["bytes"] for r in receipts)})
                print(canonical({"event": "archiving_complete", "archived": len(receipts), "missing": missing}), flush=True)
                return
        time.sleep(15)


if __name__ == "__main__":
    main()
