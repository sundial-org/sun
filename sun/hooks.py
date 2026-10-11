"""Agent hooks and the before/after boundaries used to attribute file changes."""

import json
import os
import re
import shlex
import sys
import uuid
from typing import Dict, List, TypedDict

from . import checks
from . import cli
from . import git_store
from . import history
from . import sessions as session_store


# Per-session turn bookkeeping persisted in turns.json.
class TurnState(TypedDict, total=False):
    n: int
    start: str
    transcript: str
    toffset: int  # Transcript byte position where the next turn slice starts.
    soffset: int  # Transcript byte position through which prompts have been scanned.
    seen: int  # Nonzero once the starting prompt has been encountered.
    stopped: bool
    squashed: bool
    branch: str


# One in-flight invocation, persisted in active.json between its pre/post hooks.
class ActiveCall(TypedDict, total=False):
    files: List[str]
    id: str
    branch: str
    pre: str
    before: str
    turn: int
    all_files: bool
    overlap: List[str]
    ambiguous_actor: bool
    actor: str
    git: str
    input: dict
    tool: str


READ_TOOLS = {"Read", "Glob", "Grep", "LS", "WebFetch", "WebSearch", "view_image"}


HOOK_EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
               "PostToolUseFailure", "Stop", "SessionEnd")


CODEX_HOOK_EVENTS = tuple(e for e in HOOK_EVENTS if e != "PostToolUseFailure") + (
    "SubagentStart", "SubagentStop", "Interrupt")


call_key = lambda sid, payload, harness="claude": \
    f"{git_store.session_key(sid, harness)}/{payload.get('tool_use_id') or ''}"


tool_file = lambda inp: inp.get("file_path") or inp.get("notebook_path")


def patch_files(text):
    if not isinstance(text, str): return []
    # Tool wrappers may carry the patch inside a JSON or JavaScript string.
    text = text.replace("\\r\\n", "\n").replace("\\n", "\n")
    paths = re.findall(r"^\*\*\* (?:Update|Add|Delete) File: (.+)$", text, re.M)
    paths += re.findall(r"^\*\*\* Move to: (.+)$", text, re.M)
    paths += [p for p in re.findall(r"^\+\+\+ (?:b/)?(.+)$", text, re.M)
              if p != "/dev/null"]
    cleaned = [p.strip().rstrip("\\\"'`,);") for p in paths]
    return list(dict.fromkeys(p for p in cleaned if p and p != "/dev/null"))


def tool_files(tool, inp):
    if not isinstance(inp, dict): return patch_files(inp)
    f = tool_file(inp)
    if f: return [f]
    if tool == "apply_patch":
        return patch_files(inp.get("command") or inp.get("patch") or inp.get("input") or "")
    return []


def relative_tool_files(tool, inp):
    return [git_store.rel_to_root(f) for f in tool_files(tool, inp)]


# Attribution covers the observed pre/post hook interval. Background writes after
# completion, or writes without paired hooks, cannot reliably belong to this call.
def finish_call(sid, active: Dict[str, ActiveCall], payload, harness="claude"):
    key = call_key(sid, payload, harness)
    if key not in active: key = call_key(sid, {}, harness)
    st = active.get(key)
    if not st: return  # duplicate completion, or no observed pre-call boundary
    others = {f for k, s in active.items() if k != key for f in s["files"]}
    def release():
        active.pop(key, None)
        git_store.save_state("active.json", active)
        if st.get("id"): git_store.git("update-ref", "-d", "refs/sun/pending/" + st["id"])
    if st.get("branch") != git_store.shadow_ref():
        print("sun: branch changed during tool call; attribution unavailable", file=sys.stderr)
        release()
        return
    # Retrying after a crash between the ref transaction and claim cleanup is harmless.
    if st.get("id") and git_store.ref_oid(f"refs/sun/events/{st['id']}"):
        release()
        return
    if not st.get("before"):
        release()
        history.sync(method="uncertain")
        return
    after, tip = git_store.snapshot_tree(), git_store.history_head()
    recorded = set(git_store.tree_changes(st["pre"], tip))
    dirty = set(git_store.tree_changes(tip, after))
    files = [f for f in git_store.tree_changes(st["before"], after)
             if (f not in others or f in st.get("overlap", []) or "*" in st.get("overlap", []))
             and (f not in recorded or f in dirty)]
    if not files:
        release()
        return
    tool, inp = payload.get("tool_name", "?"), payload.get("tool_input") or {}
    paths = relative_tool_files(tool, inp)
    call_input = ({"file": paths[0]} if len(paths) == 1 else
                  {"files": paths} if paths else inp)
    call = {"id": payload.get("tool_use_id"), "tool": tool, "input": call_input}
    claimed = set(st["files"])
    # Edit/Write only touch their own file -> the rest of the diff is a concurrent local
    # overlay; for other tools (Bash, ...) the whole diff is the agent's
    a_files = ([f for f in files if f in claimed] if claimed else
               files if st.get("all_files") else [])
    if not st.get("all_files") and any(s.get("all_files") for k, s in active.items() if k != key):
        files = a_files
    if not files:
        release()
        return
    h_files = [f for f in files if f not in a_files]
    # Establish pre-existing contents separately, never as part of this tool's edit.
    baseline = [f for f in git_store.tree_changes(tip, st["before"]) if f in files and f not in recorded]
    if baseline:
        c = git_store.make_shadow_commit(git_store.snapshot_tree(baseline, st["before"]),
                               "sun: observed pre-tool state", "unknown", [tip])
        p = git_store.patches(tip, c, baseline)
        history.record(type="observe", actor="unknown", commit=c, edits=[
            {"file": f, "patch": p[f], "attribution": {"method": "observed"}} for f in baseline])
    action = history.pull_action(st.get("git"), git_store.ref_oid("HEAD"))
    if action:
        # A paired, exclusive shell call must name the exact pull. Wrappers and
        # compound commands remain unknown rather than guessing their executor.
        original = st.get("input") or {}
        command = (original.get("command") or original.get("cmd") or "") if isinstance(original, dict) else ""
        try:
            matches = shlex.split(command) == shlex.split(action["command"])
        except ValueError:
            matches = False
        if (matches and st.get("tool") in ("Bash", "exec_command") and st.get("all_files")
                and len(active) == 1 and not st.get("overlap") and not st.get("ambiguous_actor")
                and payload.get("hook_event_name") == "PostToolUse"):
            action["executor"] = st["actor"]
        pre = git_store.history_head()
        c = git_store.make_shadow_commit(git_store.snapshot_tree(files, after),
                                        history.observed_subject(action), "unknown", [pre])
        patches = git_store.patches(pre, c, files)
        history.record(id=st["id"], type="observe", actor="unknown", commit=c,
                       git_action=action, tool_calls=[call], edits=[
                           {"file": f, "patch": patches[f], "attribution": {"method": "observed"}}
                           for f in files])
        release()
        start = git_store.state("turns.json", {}).get(git_store.session_key(sid, harness), {}).get("start") or pre
        return {"at": c, "since": pre, "turn": start, "in_turn": True, "files": a_files} if a_files else None
    actor, pre = st["actor"], git_store.history_head()
    turn = st.get("turn", 0)
    c = git_store.make_shadow_commit(git_store.snapshot_tree(files, after),
                           f"sun: {actor} {tool}" if a_files else history.edits_msg(git_store.local(), files),
                           actor if a_files else git_store.local(), [pre])
    p = git_store.patches(pre, c, files)
    entries = []
    if a_files:
        overlap = st.get("overlap", [])
        uncertain = a_files if payload.get("hook_event_name") == "PostToolUseFailure" or "*" in overlap \
            else [f for f in a_files if f in overlap]
        unknown_actor = st.get("ambiguous_actor") or payload.get("hook_event_name") == "PostToolUseFailure"
        for owner, group, method in ((actor, [f for f in a_files if f not in uncertain], "hook"),
                                      ("unknown" if unknown_actor else actor, uncertain, "uncertain")):
            if group:
                entries.append(dict(type="edit", actor=owner, session_id=sid, turn=f"turn{turn}",
                       patch_id=git_store.patch_id(c), tool_calls=[call], edits=[
                           {"file": f, "patch": p[f], "tool_call_id": call["id"],
                            "attribution": {"method": method}} for f in group]))
    if h_files:
        entries.append(dict(type="edit", actor=git_store.local(),
               edits=[{"file": f, "patch": p[f],
                       "attribution": {"method": "hook"}} for f in h_files]))
    if entries: entries[0]["id"] = st["id"]
    history.record_batch(c, entries)
    release()
    start = git_store.state("turns.json", {}).get(git_store.session_key(sid, harness), {}).get("start") or pre
    return {"at": c, "since": pre, "turn": start, "in_turn": True, "files": a_files} if a_files else None


def prompt_boundary(sid, payload, harness="claude"):
    # PreToolUse: a prompt can reach the transcript with no hook between turns (queued
    # message, missed Stop); a user line past the first scan means a new turn started
    turns: Dict[str, TurnState] = git_store.state("turns.json", {})
    t = turns.get(git_store.session_key(sid, harness))
    tp = payload.get("transcript_path") or (t or {}).get("transcript", "")
    if not (t and tp and os.path.exists(tp)): return
    with open(tp, "rb") as f:
        prompts = []
        f.seek(t.get("soffset", t.get("toffset", 0)))
        while True:
            pos, line = f.tell(), f.readline()
            if not line:
                break
            kind = session_store.prompt_line(line, harness)
            if kind:
                prompts.append((pos, kind))
        end = f.tell()
        kinds = {kind for _, kind in prompts}
        # Codex mirrors one prompt across records. Prefer task_started, otherwise
        # count just one of the duplicate user-record kinds.
        if 3 in kinds:
            prompts = [item for item in prompts if item[1] == 3]
        elif {1, 2} <= kinds:
            prompts = [item for item in prompts if item[1] == 1]
        seen = t.get("seen", 0)
        boundaries = prompts[0 if seen else 1:]
        for boundary, _ in boundaries:
            history.squash_turn(sid, harness)
            f.seek(t.get("toffset", 0))
            data = f.read(boundary - f.tell())
            if data and not t.get("stopped") and git_store.cfg_share_sessions():
                session_store.store_chunks(sid, {f"turn-{t['n']:04d}.jsonl": data})
            history.sync(method="hook")
            t.update(n=t["n"] + 1, start=git_store.history_head(), toffset=boundary)
            t.pop("stopped", None)
            t.pop("squashed", None)
    t.update(soffset=end, seen=1 if boundaries else seen + len(prompts))
    turns[git_store.session_key(sid, harness)] = t
    git_store.save_state("turns.json", turns)


def stop_chunk(sid, payload, harness="claude"):
    # Stop: append this turn's transcript slice to the session ref
    turns: Dict[str, TurnState] = git_store.state("turns.json", {})
    t = turns.get(git_store.session_key(sid, harness))
    tp = payload.get("transcript_path") or (t or {}).get("transcript", "")
    if not (t and tp and os.path.exists(tp) and git_store.cfg_share_sessions()): return
    with open(tp, errors="replace") as f:
        f.seek(t.get("toffset", 0))
        data = f.read()
    if data: session_store.store_chunks(sid, {f"turn-{t['n']:04d}.jsonl": data})
    t.update(toffset=os.path.getsize(tp), stopped=True); git_store.save_state("turns.json", turns)


def subagent_chunk(sid, payload):
    tp, sub = payload.get("agent_transcript_path"), payload.get("agent_id")
    if not (tp and sub and os.path.exists(tp) and git_store.cfg_share_sessions()): return
    session_store.store_chunks(sid, {f"subagents/{sub}/transcript.jsonl": git_store.read_text(tp, errors="replace")})


def turn_unit(sid, harness, t):
    """The session's own work in a turn, for rules and extraction: {at, since, turn, files, in_turn}."""
    tip = git_store.history_head(False)
    if not (t.get("start") and tip and t.get("branch") == git_store.shadow_ref()): return None
    n, mine = t.get("n"), []
    for e in history.events():  # after the squash, the turn's events sit on the turn commit
        if e.get("session_id") == sid and e.get("turn") == f"turn{n}" and e["actor"] == git_store.agent(sid, harness):
            mine.append(e)
    files = sorted({d["file"] for e in mine for d in e.get("edits") or []})
    at = mine[-1]["commit"] if mine and git_store.quiet("git", "merge-base", "--is-ancestor", mine[-1]["commit"], tip).returncode == 0 else tip
    return {"at": at, "since": t["start"], "turn": t["start"], "in_turn": True, "files": files}


def cmd_hook(a):
    try: payload = json.load(sys.stdin)
    except (ValueError, OSError): payload = {}
    try: payload.get("cwd") and os.chdir(payload["cwd"])
    except OSError: return
    p = git_store.quiet("git", "rev-parse", "--show-toplevel")
    if p.returncode: return  # not a Git repo; hooks must never break the harness
    os.chdir(p.stdout.strip())
    if not cli.adopt(): return  # not a Sun repo
    with git_store.lock():  # serialize concurrent hooks (parallel sessions/subagents)
        history.ensure_branch()
        unit = handle_hook(a, payload)
    if unit and not os.environ.get("SUN_CHECKING"):  # rules run outside the lock: a judge has hooks of its own
        try: checks.hook_checks(a, payload, unit)
        except (SystemExit, Exception) as exc: print(f"sun: {exc}", file=sys.stderr)


def handle_hook(a, payload):
    event, sid, harness = (payload.get("hook_event_name", ""),
                           payload.get("session_id", "?"), a.harness)
    tp = payload.get("transcript_path")
    sub, subpath = payload.get("agent_id"), payload.get("agent_transcript_path")
    if tp or (sub and subpath):
        paths = git_store.state("session-paths.json", {})
        entry = paths.setdefault(git_store.session_key(sid, harness),
                                 {"id": sid, "harness": harness, "path": None, "subagents": {}})
        if tp: entry["path"] = os.path.abspath(tp)
        if sub and subpath: entry["subagents"][sub] = os.path.abspath(subpath)
        git_store.save_state("session-paths.json", paths)
    active: Dict[str, ActiveCall] = git_store.state("active.json", {})
    # Old-format claims cannot identify a live call or provide a before snapshot.
    obsolete = [key for key, claim in active.items() if not claim.get("id") or not claim.get("branch")]
    if obsolete:
        for key in obsolete: active.pop(key)
        git_store.save_state("active.json", active)
        history.sync(method="uncertain")
    if event in ("SessionStart", "UserPromptSubmit", "Stop", "SessionEnd", "Interrupt"):
        prefix = git_store.session_key(sid, harness) + "/"
        stale = [key for key in active if key.startswith(prefix)]
        for key in stale:
            claim = active.pop(key)
            if claim.get("id"): git_store.git("update-ref", "-d", "refs/sun/pending/" + claim["id"])
        if stale:
            git_store.save_state("active.json", active)
            history.sync(method="uncertain")
    if event == "UserPromptSubmit" and not git_store.state("turns.json", {}).get(
            git_store.session_key(sid, harness), {}).get("stopped"):  # Stop never fired:
        history.squash_turn(sid, harness)  # squash the turn + store its transcript slice
        stop_chunk(sid, payload, harness)
    elif event == "PreToolUse": prompt_boundary(sid, payload, harness)
    if event in ("SessionStart", "SubagentStart", "UserPromptSubmit", "PreToolUse"):
        history.sync(method="hook")  # everything dirty before an agent tool runs is local
    if event == "SessionStart":  # stdout lands in the agent's context
        if not git_store.cfg_share_sessions(): return
        session_store.export_sessions()
        print("sun: " + git_store.CLAUDE_LINE)
    elif event == "SubagentStart":
        if not git_store.cfg_share_sessions(): return
        print("sun: " + git_store.CLAUDE_LINE)
    elif event == "UserPromptSubmit":
        turns, tp = git_store.state("turns.json", {}), payload.get("transcript_path", "")
        key = git_store.session_key(sid, harness)
        turns[key] = {"n": turns.get(key, {}).get("n", 0) + 1, "start": git_store.history_head(),
                      "transcript": tp, "branch": git_store.shadow_ref(),
                      "toffset": os.path.getsize(tp) if os.path.exists(tp) else 0}
        git_store.save_state("turns.json", turns)
    elif event == "PreToolUse":  # claim the file BEFORE the write exists
        tool, inp = payload.get("tool_name", "?"), payload.get("tool_input") or {}
        key = call_key(sid, payload, harness)
        if key in active: return
        files = relative_tool_files(tool, inp) if tool not in READ_TOOLS else []
        broad = not files and tool not in READ_TOOLS
        overlap, ambiguous_actor = set(), False
        for other_key, other in active.items():
            shared = set(files) & set(other["files"])
            if broad: shared.update(other["files"])
            if other.get("all_files"): shared.update(files)
            other["overlap"] = sorted(set(other.get("overlap", [])) | shared)
            overlap.update(shared)
            if broad and other.get("all_files"):
                other["overlap"] = ["*"]
                overlap.add("*")
            if (shared or broad and other.get("all_files")) and not other_key.startswith(
                    git_store.session_key(sid, harness) + "/"):
                other["ambiguous_actor"] = ambiguous_actor = True
        active[key] = {"files": files, "all_files": broad, "overlap": sorted(overlap),
                       "ambiguous_actor": ambiguous_actor,
                       "id": uuid.uuid4().hex,
                       "actor": git_store.agent(sid, harness),
                       "git": git_store.ref_oid("HEAD"), "input": inp, "tool": tool,
                       "branch": git_store.shadow_ref(), "pre": git_store.history_head(), "before": git_store.snapshot_tree(),
                       "turn": git_store.state("turns.json", {}).get(git_store.session_key(sid, harness), {}).get("n", 0)}
        git_store.git("update-ref", "refs/sun/pending/" + active[key]["id"], active[key]["before"])
        git_store.save_state("active.json", active)
    elif event in ("PostToolUse", "PostToolUseFailure"):
        return finish_call(sid, active, payload, harness)
    elif event == "Stop":  # a queued prompt may end in a text-only turn: no PreToolUse
        before = dict(git_store.state("turns.json", {}).get(git_store.session_key(sid, harness)) or {})
        prompt_boundary(sid, payload, harness)
        history.squash_turn(sid, harness)
        stop_chunk(sid, payload, harness)
        t = git_store.state("turns.json", {}).get(git_store.session_key(sid, harness)) or {}
        if before.get("n") and t.get("n") != before.get("n"): t = before  # a queued prompt already opened the next turn
        return turn_unit(sid, harness, t)
    elif event == "SubagentStop":
        subagent_chunk(sid, payload)
