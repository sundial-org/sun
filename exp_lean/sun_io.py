"""Small process-isolated adapter to the pinned Sun record/check APIs."""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

SUN = Path(__file__).resolve().parent / "vendor" / "sun.py"


def clean_env():
    return {k: v for k, v in os.environ.items()
            if not k.startswith("GIT_") and not any(s in k for s in ("KEY", "TOKEN", "SECRET"))}


def command(repo, *args, payload=None):
    r = subprocess.run([sys.executable, str(SUN), *args], cwd=repo,
                       input=None if payload is None else json.dumps(payload),
                       text=True, capture_output=True, env=clean_env(), timeout=120)
    if r.returncode:
        raise RuntimeError(f"Sun {args[0]} failed: {r.stderr[:1500]}")
    return r.stdout


def init(repo):
    repo = Path(repo)
    repo.mkdir(parents=True, exist_ok=True)
    if not (repo / ".git").exists():
        subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "bmo"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "sun-experiment@localhost"], check=True)
    return command(repo, "init", "--no-hooks", "--no-share-sessions")


def record(repo, actor, sid, writes, tool_calls=None):
    p = subprocess.run([sys.executable, str(Path(__file__).resolve()), str(repo)],
                       input=json.dumps({"actor": actor, "sid": sid, "writes": writes,
                                         "tool_calls": tool_calls or []}),
                       text=True, capture_output=True, env=clean_env(), timeout=120)
    if p.returncode:
        raise RuntimeError(f"Sun record failed: {p.stderr[:1500]}")
    return json.loads(p.stdout)


def main():
    repo = Path(sys.argv[1]).resolve()
    p = json.load(sys.stdin)
    spec = importlib.util.spec_from_file_location("pinned_sun", SUN)
    sun = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sun)
    os.chdir(repo)
    with sun.lock():
        sun.ensure_branch()
        capture = p["writes"] is None
        if sun.changed_files() and not capture:
            raise RuntimeError("Unrecorded files before attributed turn")
        before = sun.history_head()
        names = sun.changed_files() if capture else list(p["writes"])
        if not names:
            print(json.dumps({"commit": before, "events": []}))
            return
        for name, content in (p["writes"] or {}).items():
            path = (repo / name).resolve()
            if not path.is_relative_to(repo) or ".git" in path.parts:
                raise ValueError("Invalid record path")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        author = "bmo/" + p["actor"]
        commit = sun.commit_files(names, "session " + p["sid"], author)
        patches = sun.patches(before, commit, names)
        agent_names = [n for n in names if not n.startswith(("receipts/", "manifests/"))]
        program_names = [n for n in names if n not in agent_names]
        entries = []
        for actor, files, calls in [(author, agent_names, p["tool_calls"]),
                                    ("bmo/program:lean", program_names, [])]:
            if files:
                entries.append({"type": "agent" if actor == author else "compiler-evidence",
                                "actor": actor, "session_id": p["sid"], "turn": "1",
                                "tool_calls": calls,
                                "edits": [{"file": f, "patch": patches[f],
                                           "attribution": {"method": "experiment-runner"}}
                                          for f in files if f in patches]})
        events = sun.record_batch(commit, entries)
        if sun.changed_files():
            raise RuntimeError("Dirty files after recording")
        print(json.dumps({"commit": commit, "events": [e["id"] for e in events]}))


if __name__ == "__main__":
    main()
