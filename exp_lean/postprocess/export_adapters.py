"""Preserve completed experiment adapters without saving signed download URLs."""
from pathlib import Path
import hashlib
import json
import shutil
import urllib.request
from engine import save


def export(engine):
    from tinker_cookbook.weights._download import _safe_extract_tar
    if not (engine.run / "completed.json").exists():
        raise RuntimeError("Finish the experiment before exporting final artifacts")
    rest = engine.service.create_rest_client()
    exported = []
    for checkpoint in sorted((engine.run / "training").glob("*/checkpoint.json")):
        receipt = json.loads(checkpoint.read_text())
        out = engine.run / "adapters" / checkpoint.parent.name
        out.mkdir(parents=True, exist_ok=True)
        manifest = out / "export-receipt.json"
        if manifest.exists():
            item = json.loads(manifest.read_text())
            if all(hashlib.sha256((out / n).read_bytes()).hexdigest() == h
                   for n, h in item["files"].items()):
                exported.append(item)
                continue
        response = rest.get_checkpoint_archive_url_from_tinker_path(receipt["sampling_path"]).result(timeout=180)
        if not response.url.startswith("https://"):
            raise RuntimeError("Checkpoint archive did not provide an HTTPS URL")
        archive = out / "checkpoint.tar.tmp"
        try:
            try:
                with urllib.request.urlopen(response.url, timeout=120) as source, archive.open("wb") as target:
                    shutil.copyfileobj(source, target)
            except Exception:
                raise RuntimeError("Checkpoint download failed; signed URL omitted") from None
            _safe_extract_tar(archive, out)
        finally:
            archive.unlink(missing_ok=True)
        files = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted(out.rglob("*")) if p.is_file() and p != manifest}
        if not files:
            raise RuntimeError("Empty adapter export")
        item = {"checkpoint": checkpoint.parent.name, "sampling_path": receipt["sampling_path"],
                "directory": str(out), "files": files,
                "bytes": sum((out / p).stat().st_size for p in files)}
        save(manifest, item)
        exported.append(item)
        engine.log("adapter_exported", checkpoint=checkpoint.parent.name, bytes=item["bytes"], files=len(files))
    save(engine.run / "downloaded-adapters.json", exported)
    return {"event": "adapters_exported", "count": len(exported),
            "bytes": sum(x["bytes"] for x in exported)}
