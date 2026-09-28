"""Check completed experiment coverage, data separation, receipts and local adapters."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

from data import SYSTEM, canonical, format_check, sha


def read(path):
    return json.loads(path.read_text())


def verify(run):
    from style import score
    if read(run / "status.json")["phase"] != "complete":
        raise ValueError("Run is incomplete")
    sun_roots = [run.parent.parent.parent, run.parent.parent, run, *sorted((run / "arms").iterdir())]
    assert all((root / ".git" / "sun").is_dir() for root in sun_roots)
    prompts = read(run / "prompts.json")
    train_ids = {p["id"] for p in prompts if p["split"] == "train"}
    heldout_ids = {p["id"] for p in prompts if p["split"] == "heldout"}
    assert len(train_ids) == 480 and len(heldout_ids) == 96
    frozen = read(run / "freeze.json")
    assert frozen["prompt_sha"] == sha(prompts)
    for filename in ["data.py", "style.py"]:
        assert frozen["files"][filename] == sha((run.parent.parent / filename).read_text())
    expected_training = {f"weights-{n}-s0" for n in [15, 30, 60, 120, 240, 360, 480]}
    expected_training |= {"weights-480-s1", "weights-480-s2"}
    expected_training |= {f"{family}-480-s{seed}" for family in ["lora-A", "lora-B", "self"] for seed in range(3)}
    manifests = {m["name"]: m for m in read(run / "training_manifest.json")}
    assert set(manifests) == expected_training
    assert len({m["sampling_path"] for m in manifests.values()}) == 18
    exported = {}
    for name, manifest in manifests.items():
        directory = run / "training" / name
        assert read(directory / "checkpoint.json") == manifest
        payload = (directory / "rows.jsonl").read_text()
        assert manifest["dataset_sha"] == sha(payload)
        rows = [json.loads(line) for line in payload.splitlines()]
        assert len(rows) == manifest["rows"]
        assert all(r["prompt_id"] in train_ids and r["messages"][0]["content"] == SYSTEM for r in rows)
        assert manifest["rank"] == 16 and manifest["learning_rate"] == .0004
        metrics = [json.loads(line) for line in (directory / "metrics.jsonl").read_text().splitlines()]
        assert [m["step"] for m in metrics] == list(range(1, manifest["steps"] + 1))
        exported[name] = rows
    for family in ["weights", "lora-A", "lora-B", "self"]:
        assert len({manifests[f"{family}-480-s{s}"]["dataset_sha"] for s in range(3)}) == 1
    matched = [{r["id"] for r in exported[f"{f}-480-s0"]} for f in ["lora-A", "lora-B", "self"]]
    assert len(matched[0]) == 460 and matched[0] == matched[1] == matched[2]
    originals = {r["id"]: r for p in (run / "collections").glob("none-round-*.json") for r in read(p)}
    opposite_edits = read(run / "collections" / "editor-B.json")
    assert {r["id"] for r in opposite_edits} == matched[0]
    assert all(r["story"] == originals[r["id"]]["story"] and
               r["prompt"] == originals[r["id"]]["prompt"] for r in opposite_edits)

    expected_evals = expected_training | {"base", "context-shared-480"}
    expected_evals |= {f"context-{n}" for n in [15, 30, 60, 120, 240, 360, 480]}
    paths = {p.stem: p for p in (run / "evaluations").glob("*.json")}
    assert set(paths) == expected_evals
    samples, reproduced_scores = 0, 0
    for name, path in paths.items():
        rows = read(path)
        assert len(rows) == 384 and len({r["id"] for r in rows}) == 384
        assert Counter(r["prompt"]["id"] for r in rows) == Counter({p: 4 for p in heldout_ids})
        for index, row in enumerate(rows):
            check = format_check(row["story"], row["prompt"]["anchors"])
            assert row["format"] == check
            assert row["U"] == (row["submitted"] and check["pass"])
            system = row["messages"][0]["content"]
            if name.startswith("context-"):
                assert system.startswith(SYSTEM + "\nPreviously edited stories")
                examples = system.split("<examples>\n", 1)[1].split("\n</examples>", 1)[0]
                assignments = {p["text"] for p in prompts if p["split"] == "train"}
                assert all(json.loads(line)["assignment"] in assignments for line in examples.splitlines())
            else:
                assert system == SYSTEM
            if index in [0, 127, 255, 383]:
                assert all(score(row["story"], guide) == row["scores"][guide] for guide in ["A", "B"])
                reproduced_scores += 1
        samples += len(rows)
    ranking = read(run / "best_of_n.json")
    assert len(ranking) == 1536
    assert Counter(r["prompt"]["id"] for r in ranking) == Counter({p: 16 for p in heldout_ids})
    requests = list((run / "requests").glob("*.json"))
    for path in requests:
        receipt = read(path)
        assert receipt["status"] == "complete", path.name
        assert receipt["receipt_sha"] == sha(read(run / "provider" / path.name)), path.name
    preserved_attempts = list((run / "failed_requests").glob("*.json"))
    assert len(preserved_attempts) == len(read(run / "transport-amendment.json")["requests_without_results"]) == 4

    archives = read(run / "archive_manifest.json")
    assert not archives["missing"]
    assert {r["name"] for r in archives["adapters"]} == expected_training
    for receipt in archives["adapters"]:
        path = run / "checkpoint_archives" / receipt["archive"]
        assert path.stat().st_size == receipt["bytes"]
        with path.open("rb") as stream:
            assert hashlib.file_digest(stream, "sha256").hexdigest() == receipt["sha256"]
        assert receipt["sampling_path"] == manifests[receipt["name"]]["sampling_path"]
    result = {"passed": True, "training_checkpoints": len(manifests),
              "matched_control_source_drafts": len(matched[0]), "evaluation_files": len(paths),
              "evaluation_samples": samples, "ranking_samples": len(ranking),
              "reproduced_scorer_samples": reproduced_scores,
              "initialized_sun_repositories": len(sun_roots),
              "preserved_failed_attempts": len(preserved_attempts),
              "verified_request_receipts": len(requests), "verified_adapter_archives": len(archives["adapters"]),
              "archive_bytes": archives["total_bytes"],
              "evaluation_sha256": {name: sha(path.read_text()) for name, path in paths.items()}}
    (run / "integrity.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    run = Path(__file__).resolve().parent / "runs" / sys.argv[1]
    result = verify(run)
    print(canonical({k: v for k, v in result.items() if k != "evaluation_sha256"}))
