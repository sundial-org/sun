#!/usr/bin/env python3
"""Twelve concurrent agents for one person, none for the other, and what the
thirteenth agent sees.

alice runs twelve Claude Code sessions at once in one checkout, one handbook page
each. bob uses no agents and fixes one page by hand. Then a fresh session asks which
of the twelve wrote a page. Mirrors examples/twelve-agents.md.

Usage: python3 examples/demo_twelve.py   ->  examples/demo-twelve/
"""
import json, os, shutil, subprocess, sys, uuid
from threading import Thread

HERE = os.path.dirname(os.path.abspath(__file__))
SUN = os.path.join(os.path.dirname(HERE), "sun.py")
DEMO = os.path.join(HERE, "demo-twelve")
EMPTY = os.path.join(DEMO, "no-sessions")  # keep init away from real ~/.claude and ~/.codex
ENV = {**os.environ, "SUN_PROJECTS": EMPTY, "SUN_CODEX_SESSIONS": EMPTY}
PAGES = ["intro", "install", "cli", "config", "hooks", "sessions",
         "log", "undo", "viz", "export", "codex", "faq"]


def sh(*cmd, cwd=None, stdin="", show=False):
    out = subprocess.run(cmd, cwd=cwd, env=ENV, input=stdin, text=True,
                         check=True, capture_output=True).stdout
    if show: print(out, end="")


def sun(clone, *args, **kw):  # subprocess, not import: user() is memoized per process
    sh(sys.executable, SUN, *args, cwd=clone, **kw)


def hook(clone, event, sid, show=False, **extra):
    sun(clone, "hook", show=show, stdin=json.dumps(
        {"hook_event_name": event, "session_id": sid, "cwd": clone, **extra}))


def write(clone, rel, text):
    path = os.path.join(clone, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").write(text)


def agent_turn(clone, sid, rel, text):
    """One session's whole turn, run in its own thread: prompt, claim, write, Stop."""
    inp, tid, tp = {"file_path": os.path.join(clone, rel)}, f"toolu_{sid[:8]}", os.path.join(DEMO, f"{sid}.jsonl")
    open(tp, "w").close()
    hook(clone, "UserPromptSubmit", sid, transcript_path=tp)
    hook(clone, "PreToolUse", sid, tool_name="Write", tool_input=inp, tool_use_id=tid)
    write(clone, rel, text)
    hook(clone, "PostToolUse", sid, tool_name="Write", tool_input=inp, tool_use_id=tid)
    recs = [{"type": "user", "message": {"role": "user", "content": f"Write the handbook page {rel}."}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "text", "text": f"One short page. Keeping {rel} to what a new user needs first."},
                {"type": "tool_use", "id": tid, "name": "Write", "input": inp}]}}]
    open(tp, "w").write("".join(json.dumps(r) + "\n" for r in recs))
    hook(clone, "Stop", sid, transcript_path=tp)


def commit_and_push(clone, message, *push_args):
    """sun keeps its own history under refs/sun/*; the normal branch is still the person's.
    The pre-push hook `sun init` installed mirrors refs/sun/* with the push."""
    sh("git", "add", "-A", cwd=clone)
    sh("git", "commit", "-q", "-m", message, cwd=clone)
    sh("git", "push", "-q", *push_args, "origin", "main", cwd=clone)


def clone(name):
    path = os.path.join(DEMO, name)
    sh("git", "-c", "init.defaultBranch=main", "clone", "-q", ORIGIN, path)
    sh("git", "config", "user.name", name, cwd=path)
    sh("git", "config", "user.email", f"{name}@example.com", cwd=path)
    return path


shutil.rmtree(DEMO, ignore_errors=True)
os.makedirs(EMPTY)
ORIGIN = os.path.join(DEMO, "origin.git")
sh("git", "-c", "init.defaultBranch=main", "init", "-q", "--bare", ORIGIN)

# 1. alice: twelve stub pages, then sun init (sharing sessions, so the thirteenth
#    session can read the twelve)
alice = clone("alice")
for i, name in enumerate(PAGES, 1):
    write(alice, f"docs/{i:02d}-{name}.md", f"# {name.title()}\n\nTODO\n")
sun(alice, "init", "--claude", "--share-sessions", "--no-instructions")

# 2. twelve Claude sessions at once, one page each; their hooks interleave under the repo lock
threads = [Thread(target=agent_turn, args=(
    alice, f"pg{i:02d}{uuid.uuid4().hex}", f"docs/{i:02d}-{name}.md",  # actor = first 8 chars of the id
    f"# {name.title()}\n\nHow {name} works in sun.\n")) for i, name in enumerate(PAGES, 1)]
for t in threads: t.start()
for t in threads: t.join()
commit_and_push(alice, "Write the handbook", "-u")

# 3. bob, no agents: clone, init, fix one page by hand, sync, commit, push
bob = clone("bob")
sun(bob, "init", "--claude", "--share-sessions", "--no-instructions")
open(os.path.join(bob, "docs/03-cli.md"), "a").write("\nNote: the flag is `--claude`, not `--claude-only`.\n")
sun(bob, "sync")
commit_and_push(bob, "Fix the CLI page")

# 4. alice pulls and reads the log
sh("git", "pull", "-q", cwd=alice)
print("$ sun log")
sun(alice, "log", show=True)

# 5. the thirteenth session: SessionStart tells it there are twelve sessions to draw on;
#    blame tells it which one wrote this page, and that the note under it is bob's
print("\n$ claude   # SessionStart hook output, injected into the agent's context")
hook(alice, "SessionStart", "pg13" + uuid.uuid4().hex, show=True)
print("\n$ sun blame docs/03-cli.md 3")
sun(alice, "blame", "docs/03-cli.md", "3", show=True)
print("\n$ sun blame docs/03-cli.md 5")
sun(alice, "blame", "docs/03-cli.md", "5", show=True)
