#!/usr/bin/env python3
"""Build a demo repo with a synthetically populated sun operation log.

Simulates the sundial story: a human scaffolds an app, two Claude sessions
implement features (one commit per tool call, squashed per turn at Stop),
a human edits during and between agent turns, and one operation is undone.

Usage: python3 examples/demo_fresh.py   ->  examples/demo/ + examples/demo.html
"""
import json, os, shutil, subprocess, sys
sys.stdin = open(os.devnull)  # demos never prompt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import sun

DEMO = os.path.join(HERE, "demo")


def write(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def hook(event, sid, **extra):
    old = sys.stdin
    sys.stdin = __import__("io").StringIO(json.dumps(
        {"hook_event_name": event, "session_id": sid, "cwd": DEMO, **extra}))
    try:
        sun.main(["hook"])
    finally:
        sys.stdin = old


def agent_turn(sid, files, human_edits=()):
    """One turn: prompt, one Write tool call per file, Stop (squash)."""
    hook("UserPromptSubmit", sid)
    for i, (f, text) in enumerate(files.items()):
        inp = {"file_path": os.path.join(DEMO, f)}
        hook("PreToolUse", sid, tool_name="Write", tool_input=inp)
        write(os.path.join(DEMO, f), text)
        hook("PostToolUse", sid, tool_name="Write", tool_input=inp,
             tool_use_id=f"toolu_{sid[-3:]}_{i}")
    for f, text in human_edits:
        write(os.path.join(DEMO, f), text)
    hook("Stop", sid)


shutil.rmtree(DEMO, ignore_errors=True)
os.makedirs(DEMO)
os.chdir(DEMO)
subprocess.run(["git", "init", "-q"], check=True)
subprocess.run(["git", "config", "user.name", "belinda"], check=True)
subprocess.run(["git", "config", "user.email", "belinda@sundial.md"], check=True)

# 1. human scaffolds the app, then `sun init` snapshots it
write("README.md", "# sundial demo\nA tiny app used to demo the sun op log.\n")
write("src/app.ts", 'export const app = () => "hello";\n')
sun.main(["init", "--no-claude-md"])

# 2. Claude session 1: implements auth over two turns
agent_turn("claude-auth-001", {
    "src/auth.ts": 'export const login = (user: string) => `token:${user}`;\n'})
agent_turn("claude-auth-001", {
    "src/auth.ts": 'export const login = (user: string) => sign(user);\n'
                   'const sign = (u: string) => `signed:${u}`;\n'})

# 3. human edits between turns (picked up by the next sun command, jj-style)
write("src/app.ts", 'import { login } from "./auth";\n'
                    'export const app = () => login("belinda");\n')
sun.main(["sync"])

# 4. Claude session 2 adds tests; the human tweaks the README after the last
#    tool call -> it stays dirty through the squash and is synced as human
agent_turn("claude-test-002",
           {"src/auth.test.ts": 'import { login } from "./auth";\n'
                                'test("login", () => login("x"));\n'},
           human_edits=[("README.md",
                         "# sundial demo\nNow with auth + tests.\n")])

# 5. undo the latest operation, then show the log and visualization
sun.main(["undo"])
print("\n$ sun log")
sun.main(["log"])
out = os.path.join(HERE, "demo.html")
sun.main(["viz", "-o", out])
print(f"\nopen {out} to replay the history")
