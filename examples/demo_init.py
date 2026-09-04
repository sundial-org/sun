#!/usr/bin/env python3
"""Interactive demo: pick any local repo you've used Claude Code on, then `sun init` it.

Scans ~/.claude/projects for project dirs, resolves each to its real repo path (from the
`cwd` field inside its transcripts), lists the git repos it finds, and runs a timed
`sun init` on the one you choose (imports sessions + backfills attribution over history).
"""
import glob, json, os, subprocess, sys, time

SUN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sun.py")
PROJECTS = os.environ.get("SUN_PROJECTS", os.path.expanduser("~/.claude/projects"))


def repo_of(pdir):
    """Real repo path for a project dir: the cwd recorded in its newest transcript."""
    for tp in sorted(glob.glob(os.path.join(pdir, "*.jsonl")),
                     key=os.path.getmtime, reverse=True):
        try:
            for line in open(tp, errors="replace"):
                cwd = json.loads(line).get("cwd")
                if cwd:
                    return cwd
        except (OSError, ValueError):
            continue
    return None


def main():
    repos = {}  # path -> session file count
    for pdir in sorted(glob.glob(os.path.join(PROJECTS, "*"))):
        n = len(glob.glob(os.path.join(pdir, "*.jsonl")))
        if not n:
            continue
        repo = repo_of(pdir)
        if repo and os.path.isdir(os.path.join(repo, ".git")):
            repos[repo] = repos.get(repo, 0) + n
    if not repos:
        sys.exit("no local git repos with Claude Code sessions found in " + PROJECTS)
    items = sorted(repos.items(), key=lambda kv: -kv[1])
    print("local git repos with Claude Code sessions:\n")
    for i, (repo, n) in enumerate(items, 1):
        print(f"  {i:2}. {repo}  ({n} session files)")
    choice = input(f"\nwhich repo do you want to `sun init`? [1-{len(items)}] ").strip()
    repo = items[int(choice) - 1][0]
    print(f"\nsun init will: install Claude Code hooks ({repo}/.claude/settings.json),\n"
          "commit any dirty state as <you>/local, scan this repo's local sessions,\n"
          "and backfill attribution over existing commits. Raw sessions stay local.")
    if input(f"run `sun init` in {repo}? [y/N] ").strip().lower() != "y":
        sys.exit("aborted")
    t0 = time.time()
    subprocess.run([sys.executable, SUN, "init"], cwd=repo, check=True)
    print(f"\ncold init took {time.time() - t0:.1f}s; rerunning (warm, idempotent)...")
    t0 = time.time()
    subprocess.run([sys.executable, SUN, "import"], cwd=repo, check=True)
    print(f"warm import took {time.time() - t0:.1f}s")
    subprocess.run([sys.executable, SUN, "log", "-n", "12"], cwd=repo, check=True)


if __name__ == "__main__":
    main()
