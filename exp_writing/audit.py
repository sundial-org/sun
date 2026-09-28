"""Verify saved Sun provenance and produce a human-readable editor smoke test."""
import argparse
import json
from pathlib import Path
import subprocess

from data import sha
from style import edit_metrics

ROOT = Path(__file__).resolve().parent


def audit(run):
    count, actors = 0, set()
    for path in (run / "provenance").glob("*.json"):
        p = json.loads(path.read_text())
        contents = []
        for role in ("writer", "editor"):
            commit = p[role]["commit"]
            text = subprocess.check_output(["git", "show", commit+":"+p["file"]], cwd=p["repository"], text=True)
            author = subprocess.check_output(["git", "show", "-s", "--format=%an", commit], cwd=p["repository"], text=True).strip()
            if author != p[role]["actor"]:
                raise ValueError("Sun actor mismatch: " + str(path))
            contents.append(text)
            actors.add(author)
        if p["writer"]["commit"] == p["editor"]["commit"]:
            raise ValueError("Draft and edit must be distinct commits")
        metrics = edit_metrics(*contents)
        if any(abs(metrics[key]-p[key]) > 1e-12 for key in metrics):
            raise ValueError("Commit-derived edit metric mismatch: " + str(path))
        count += 1
    result = {"verified_pairs": count, "distinct_actors": sorted(actors)}
    (run / "audit.json").write_text(json.dumps(result, indent=2)+"\n")
    return result


def smoke_test(run):
    from style import RULES
    rows = json.loads((run / "calibration.json").read_text())
    lines = ["# Editor smoke test", "", "These are measured development-set drafts and edits, not held-out results.",
             "Check whether the editor catches every rule, preserves meaning, and avoids unnecessary rewriting.",
             "No human review has been recorded yet.", ""]
    for guide in ("A", "B"):
        lines += [f"## Editor {guide}: private rules", ""] + [f"{i+1}. {r}" for i, r in enumerate(RULES[guide])]
        selected = sorted((r for r in rows if guide in r["edits"]), key=lambda r: r["row"]["prompt"]["id"])[:3]
        for item in selected:
            row, edit = item["row"], item["edits"][guide]
            lines += ["", f"### {row['prompt']['id']}", "", row["prompt"]["text"], "", "**Original**", "", row["story"],
                      "", "**Edited**", "", edit["edited"], "", "**Program checks**", "",
                      f"Rules passed: {item['before'][guide]['S']:.3f} → {item['after'][guide]['S']:.3f}. "
                      f"Kept: {edit['provenance']['kept']:.3f}. Valid edit: {edit['valid']}."]
    path = ROOT / "editor-smoke-test.md"
    path.write_text("\n".join(lines)+"\n")
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run", nargs="?", default="ten-writers-20260926-inkling")
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args()
    run = ROOT / "runs" / args.run
    print(smoke_test(run) if args.smoke_test else json.dumps(audit(run)))
