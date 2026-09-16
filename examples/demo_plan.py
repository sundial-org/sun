#!/usr/bin/env python3
"""Two people, two agents, one experiment plan, and what the next agent sees.

alice's Claude Code writes EXPERIMENT_PLAN.md. bob's Codex adds a section to it
from his own clone. alice's next Claude session can then read why bob's Codex
did what it did. Mirrors the example in the README.

Usage: python3 examples/demo_plan.py   ->  examples/demo-plan/
"""
import json, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SUN = os.path.join(os.path.dirname(HERE), "sun.py")
DEMO = os.path.join(HERE, "demo-plan")
EMPTY = os.path.join(DEMO, "no-sessions")  # keep init away from real ~/.claude and ~/.codex
ENV = {**os.environ, "SUN_PROJECTS": EMPTY, "SUN_CODEX_SESSIONS": EMPTY}
PLAN = "EXPERIMENT_PLAN.md"


def sh(*cmd, cwd=None, stdin="", show=False):
    out = subprocess.run(cmd, cwd=cwd, env=ENV, input=stdin, text=True,
                         check=True, capture_output=True).stdout
    if show: print(out, end="")


def sun(clone, *args, **kw):  # subprocess, not import: user() is memoized per process
    sh(sys.executable, SUN, *args, cwd=clone, **kw)


def hook(clone, event, sid, harness, show=False, **extra):
    sun(clone, "hook", "--harness", harness, show=show, stdin=json.dumps(
        {"hook_event_name": event, "session_id": sid, "cwd": clone, **extra}))


def agent_turn(clone, sid, harness, prompt, reasoning, text):
    """One turn: prompt, one edit tool call on the plan, Stop. The transcript is a
    stand-in for the harness's own file: the prompt, the agent's text, the tool call."""
    tool, inp = ("Write", {"file_path": os.path.join(clone, PLAN)}) if harness == "claude" \
        else ("apply_patch", {"command": f"*** Begin Patch\n*** Update File: {PLAN}\n*** End Patch"})
    tid, tp = f"call_{sid[:8]}", os.path.join(DEMO, f"{sid}.jsonl")
    open(tp, "w").close()
    hook(clone, "UserPromptSubmit", sid, harness, transcript_path=tp)
    hook(clone, "PreToolUse", sid, harness, tool_name=tool, tool_input=inp, tool_use_id=tid)
    open(os.path.join(clone, PLAN), "w").write(text)
    hook(clone, "PostToolUse", sid, harness, tool_name=tool, tool_input=inp, tool_use_id=tid)
    recs = [{"type": "user", "message": {"role": "user", "content": prompt}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "text", "text": reasoning},
                {"type": "tool_use", "id": tid, "name": tool, "input": inp}]}}] if harness == "claude" else [
           {"type": "event_msg", "payload": {"type": "user_message", "message": prompt}},
           {"type": "response_item", "payload": {"type": "message", "role": "assistant",
                                                 "content": [{"type": "output_text", "text": reasoning}]}},
           {"type": "response_item", "payload": {"type": "function_call", "name": tool, "call_id": tid}}]
    open(tp, "w").write("".join(json.dumps(r) + "\n" for r in recs))
    hook(clone, "Stop", sid, harness, transcript_path=tp)


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
    # both hook files, so bob's init is a no-op commit-wise; --share-sessions so the
    # transcripts travel with the repo and the next agent can read them
    sun(path, "init", "--claude", "--codex", "--share-sessions", "--no-instructions")
    return path


shutil.rmtree(DEMO, ignore_errors=True)
os.makedirs(EMPTY)
ORIGIN = os.path.join(DEMO, "origin.git")
sh("git", "-c", "init.defaultBranch=main", "init", "-q", "--bare", ORIGIN)

PLAN_TEXT = ("# Experiment: small model vs big model\n\n"
             "Can the 1B model replace the 7B on our classification task?\n\n"
             "## Hypothesis\n\n- The 1B model scores within 2 points of the 7B\n- It runs 5x cheaper\n\n"
             "## Method\n\n- Fine-tune both on the same 10k examples\n- Score both on the same held-out set\n")
NOT_MEASURING = "\n## Not measuring\n\n- Latency\n"

# 1. alice sets up sun; her Claude writes the plan; she commits and pushes
alice = clone("alice")
agent_turn(alice, "7c1e42ab-0000-4000-8000-000000000001", "claude",
           f"Write {PLAN}: can the 1B model replace the 7B for classification?",
           "One hypothesis on quality, one on cost, and the simplest fair method: same data, same eval.",
           PLAN_TEXT)
commit_and_push(alice, "Add experiment plan", "-u")

# 2. bob clones and sets up sun; his Codex adds a section; he commits and pushes
bob = clone("bob")
agent_turn(bob, "d9b0f5e1-0000-4000-8000-000000000002", "codex",
           f"Add a Not measuring section to {PLAN}.",
           "Leaving latency out: both models run in a nightly batch job, so speed per request "
           "does not matter for this decision.",
           PLAN_TEXT + NOT_MEASURING)
commit_and_push(bob, "Add Not measuring section")

# 3. alice pulls; bob's commit, his ops and his Codex transcript come along
sh("git", "pull", "-q", cwd=alice)
print("$ sun log")
sun(alice, "log", show=True)

# 4. alice's next Claude session: SessionStart tells it where every session is,
#    and blame gives it the conversation behind the line bob's Codex wrote
print("\n$ claude   # SessionStart hook output, injected into the agent's context")
hook(alice, "SessionStart", "7c1e42ab-0000-4000-8000-000000000003", "claude", show=True)
print(f"\n$ sun blame {PLAN} 17")
sun(alice, "blame", PLAN, "17", show=True)

# 5. the same story as a page: commits + actors left, ops + patches right
print("\n$ sun viz --html")
sun(alice, "viz", "-o", os.path.join(DEMO, "viz.html"), show=True)
