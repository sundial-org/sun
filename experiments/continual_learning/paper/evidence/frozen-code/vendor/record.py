"""Write an attributed Sun commit using the checked-in Sun implementation."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

SUN = Path(__file__).resolve().parent.parent / "sun.py"


def initialize(path):
    path = Path(path).resolve()
    path.mkdir(parents=True, exist_ok=True)
    if not (path / ".git").exists():
        subprocess.run(["git", "init", "-b", "main", str(path)], check=True, capture_output=True)
        for key, value in [("user.name", "bmo"), ("user.email", "sun-experiment@localhost")]:
            subprocess.run(["git", "-C", str(path), "config", key, value], check=True)
    result = subprocess.run([sys.executable, str(SUN), "init", "--no-share-sessions", "--no-instructions"],
                            cwd=path, check=True, capture_output=True, text=True)
    return result.stdout


def commit(path, actor, files, label):
    request = {"actor": actor, "files": files, "label": label}
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), str(Path(path).resolve())],
                            input=json.dumps(request), capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def main():
    os.chdir(sys.argv[1])
    spec = importlib.util.spec_from_file_location("sun", SUN)
    sun = importlib.util.module_from_spec(spec)
    sys.modules["sun"] = sun
    spec.loader.exec_module(sun)
    data = json.load(sys.stdin)
    with sun.lock():
        before = sun.history_head()
        for filename, content in data["files"].items():
            path = Path(filename)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("Unsafe recording path")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        actor = "bmo/" + data["actor"]
        sha = sun.commit_files(list(data["files"]), data["label"], actor)
        patches = sun.patches(before, sha, list(data["files"]))
        event = sun.record(type="tool", actor=actor, commit=sha,
                           session=data["label"], harness="exp_writing",
                           edits=[{"file": f, "patch": patches.get(f, ""),
                                   "attribution": {"method": "explicit-harness"}}
                                  for f in data["files"]])
        print(json.dumps({"commit": sha, "event": event["id"], "actor": actor}))


if __name__ == "__main__":
    main()
