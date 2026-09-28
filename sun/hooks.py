"""Agent hooks and the before/after boundaries used to attribute file changes."""

import json
import os
import re
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
    ambiguous_actor: bool  # overlaps another session's call: the edit's actor is unknown
    ambiguous_agent: bool  # overlaps a sibling subagent's call: credit the session, not one agent
    actor: str
    session: str  # session key
    lane: str  # session key, plus /<agent id> for a subagent's call
    agent: str  # subagent id, or None in the session's main thread


# Tools that never write to the repository: their calls claim no files.
READ_TOOLS = {"Read", "Glob", "Grep", "LS", "WebFetch", "WebSearch", "view_image",
              "ToolSearch", "TodoWrite", "TaskCreate", "TaskGet", "TaskList", "TaskUpdate",
              "TaskOutput", "TaskStop", "SendMessage", "ListAgents", "AskUserQuestion", "Skill"}


# Tools that start subagents. The subagents' own tool calls carry their agent_id and are
# attributed to them, so the delegating call claims nothing (a claim would span the whole run).
DELEGATING_TOOLS = {"Agent", "Task", "Workflow"}


HOOK_EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
               "PostToolUseFailure", "Stop", "SubagentStart", "SubagentStop", "SessionEnd")


CODEX_HOOK_EVENTS = tuple(e for e in HOOK_EVENTS if e != "PostToolUseFailure") + ("Interrupt",)


def agent_of(payload):  # the subagent a hook fires in; None in the session's main thread
    sub = payload.get("agent_id")
    return re.sub(r"[^\w-]", "_", str(sub))[:80] if sub else None  # one safe path segment


lane_key = lambda sid, payload, harness="claude": \
    git_store.session_key(sid, harness) + (f"/{agent_of(payload)}" if agent_of(payload) else "")


call_key = lambda sid, payload, harness="claude": \
    f"{lane_key(sid, payload, harness)}/{payload.get('tool_use_id') or ''}"


# Claims recorded before subagent lanes carry neither field: their key is <session>/<call>.
claim_session = lambda key, claim: claim.get("session") or key.rsplit("/", 1)[0]
claim_lane = lambda key, claim: claim.get("lane") or key.rsplit("/", 1)[0]


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
    if payload.get("tool_name") in DELEGATING_TOOLS: return  # never claimed
    key = call_key(sid, payload, harness)
    if key not in active: key = call_key(sid, {"agent_id": payload.get("agent_id")}, harness)
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
    # An unknown-scope call never absorbs a file its own session's sibling call names: that
    # call is live and records it. Another session's claim may be abandoned, so share it.
    siblings = {f for k, s in active.items() if k != key and claim_session(k, s) == claim_session(key, st)
                for f in s["files"]} if st.get("all_files") else set()
    files = [f for f in git_store.tree_changes(st["before"], after)
             if (f not in others or f not in siblings and (f in st.get("overlap", []) or "*" in st.get("overlap", [])))
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
        session_actor = actor.rsplit("/", 1)[0] if st.get("agent") else actor
        for owner, group, method in ((actor, [f for f in a_files if f not in uncertain], "hook"),
                                      ("unknown" if unknown_actor else session_actor if st.get("ambiguous_agent")
                                       else actor, uncertain, "uncertain")):
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
    tp, sub = payload.get("agent_transcript_path"), agent_of(payload)
    if not (tp and sub and os.path.exists(tp) and git_store.cfg_share_sessions()): return
    session_store.store_chunks(sid, {f"subagents/{sub}/transcript.jsonl": git_store.read_text(tp, errors="replace")})


def turn_unit(sid, harness, t):
    """The session's own work in a turn, for rules and extraction: {at, since, turn, files, in_turn}."""
    tip = git_store.history_head(False)
    if not (t.get("start") and tip and t.get("branch") == git_store.shadow_ref()): return None
    n, mine = t.get("n"), []
    for e in history.events():  # after the squash, the turn's events sit on the turn commit
        if e.get("session_id") == sid and e.get("turn") == f"turn{n}" and git_store.in_session(e["actor"], sid, harness):
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


def record_paths(sid, payload, harness):
    # Claude hooks inside a subagent carry the parent's session_id and transcript_path plus
    # agent_id; only SubagentStop names the subagent's own transcript, so look for it earlier.
    tp, sub, subpath = payload.get("transcript_path"), agent_of(payload), payload.get("agent_transcript_path")
    if not (tp or (sub and subpath)): return
    paths = git_store.state("session-paths.json", {})
    entry = paths.setdefault(git_store.session_key(sid, harness),
                             {"id": sid, "harness": harness, "path": None, "subagents": {}})
    if tp: entry["path"] = os.path.abspath(tp)
    if sub:
        known = entry.setdefault("subagents", {})
        found = subpath or (sub not in known and tp and session_store.subagent_transcript(tp, sub))
        if found: known[sub] = os.path.abspath(found)
        if payload.get("agent_type"): entry.setdefault("agents", {}).setdefault(sub, {})["type"] = payload["agent_type"]
    git_store.save_state("session-paths.json", paths)


def release_stale(event, sid, payload, harness, active: Dict[str, ActiveCall]):
    """Release claims whose tool call can no longer complete, scoped to who stopped.

    A session start or end releases the whole session. A subagent's stop releases its own calls.
    The main thread's Stop or prompt releases its own calls and those of subagents not known to
    be running: workflow and background subagents keep working across the parent's turns."""
    session, sub = git_store.session_key(sid, harness), agent_of(payload)
    lanes = git_store.state("subagents.json", {})
    running = lanes.get(session, {})
    whole = event in ("SessionEnd", "Interrupt") or event == "SessionStart" and payload.get("source") != "compact"
    stale = [key for key, claim in active.items() if claim_session(key, claim) == session and (
        whole or (claim.get("agent") == sub if sub else claim.get("agent") not in running))]
    for key in stale:
        claim = active.pop(key)
        if claim.get("id"): git_store.git("update-ref", "-d", "refs/sun/pending/" + claim["id"])
    if stale:
        git_store.save_state("active.json", active)
        history.sync(method="uncertain")
    if whole and session in lanes or sub and event in ("SubagentStart", "SubagentStop"):
        if whole: running = {}
        elif event == "SubagentStart": running[sub] = payload.get("agent_type") or ""
        else: running.pop(sub, None)
        if running: lanes[session] = running
        else: lanes.pop(session, None)
        git_store.save_state("subagents.json", lanes)


def handle_hook(a, payload):
    event, sid, harness = (payload.get("hook_event_name", ""),
                           payload.get("session_id", "?"), a.harness)
    record_paths(sid, payload, harness)
    active: Dict[str, ActiveCall] = git_store.state("active.json", {})
    # Old-format claims cannot identify a live call or provide a before snapshot.
    obsolete = [key for key, claim in active.items() if not claim.get("id") or not claim.get("branch")]
    if obsolete:
        for key in obsolete: active.pop(key)
        git_store.save_state("active.json", active)
        history.sync(method="uncertain")
    if event in ("SessionStart", "UserPromptSubmit", "Stop", "SubagentStart", "SubagentStop",
                 "SessionEnd", "Interrupt"):
        release_stale(event, sid, payload, harness, active)
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
        if tool in DELEGATING_TOOLS: return
        key, lane, sub = call_key(sid, payload, harness), lane_key(sid, payload, harness), agent_of(payload)
        if key in active: return
        files = relative_tool_files(tool, inp) if tool not in READ_TOOLS else []
        broad = not files and tool not in READ_TOOLS
        overlap, ambiguous_actor, ambiguous_agent = set(), False, False
        for other_key, other in active.items():
            shared = set(files) & set(other["files"])
            if broad: shared.update(other["files"])
            if other.get("all_files"): shared.update(files)
            other["overlap"] = sorted(set(other.get("overlap", [])) | shared)
            overlap.update(shared)
            if broad and other.get("all_files"):
                other["overlap"] = ["*"]
                overlap.add("*")
            if not (shared or broad and other.get("all_files")): continue
            if claim_session(other_key, other) != git_store.session_key(sid, harness):
                other["ambiguous_actor"] = ambiguous_actor = True
            # Sibling subagents: a named file stays with the call naming it, but two calls
            # naming it, or two unknown-scope calls, leave only the session certain.
            elif claim_lane(other_key, other) != lane and bool(files) == bool(other["files"]):
                other["ambiguous_agent"] = ambiguous_agent = True
        active[key] = {"files": files, "all_files": broad, "overlap": sorted(overlap),
                       "ambiguous_actor": ambiguous_actor, "ambiguous_agent": ambiguous_agent,
                       "id": uuid.uuid4().hex, "session": git_store.session_key(sid, harness),
                       "lane": lane, "agent": sub,
                       "actor": git_store.agent(sid, harness, sub=sub),
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
