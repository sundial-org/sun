#!/usr/bin/env python3
"""sun: an operation log for humans + agents on top of git.

Commits are attributed as <user>/<source>: <user>/local, or <user>/agent:<harness>/<session>.
PreToolUse commits dirty state as local; PostToolUse commits the pre->post diff as the agent's;
Commits form an independent DAG under refs/sun/heads/main and never touch normal Git history.
Stop squashes each turn while hidden operation snapshots stay under refs/sun/ops. Raw
transcripts are shared under refs/sun/sessions/<user>/<id> only when the user opts in.
Events: .git/sun/events.jsonl (cache) mirrored to refs/sun/log/<user>, one writer each, merged
by timestamp at read; refs/sun/* are the source of truth and travel via the refspec + pre-push
hook init installs. .git/sun/lock (flock) serializes everything, like git's index.lock."""
import argparse, difflib, fcntl, glob, hashlib, json, os, re, subprocess, sys
import time, uuid, zlib
from typing import Any, Dict, List, Optional, TypedDict


class Attribution(TypedDict, total=False):
    method: str


class Edit(TypedDict, total=False):
    file: str
    patch: str
    tool_call_id: Optional[str]
    attribution: Attribution


class ToolCall(TypedDict, total=False):
    id: Optional[str]
    tool: str
    input: Dict[str, Any]


class Event(TypedDict, total=False):
    id: str
    timestamp: str
    type: str
    actor: str
    session_id: str
    commit: str
    snapshot: str
    patch_id: Optional[str]
    turn: str
    tool_calls: List[ToolCall]
    edits: List[Edit]
    target_op: str
    target_commit: str
    parents: List[str]
    pr: int


class TurnState(TypedDict, total=False):
    n: int
    start: str
    transcript: str
    toffset: int
    soffset: int
    seen: int
    stopped: bool
    squashed: bool


class ActiveCall(TypedDict):
    files: List[str]


EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "apply_patch"}
SHADOW_REF = "refs/sun/heads/main"
SHADOW_REMOTE_REF = "refs/sun/remotes/origin/main"
HOOK_EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop")
CODEX_HOOK_EVENTS = HOOK_EVENTS + ("SubagentStart", "SubagentStop")
CLAUDE_LINE = ("Past sessions for this repo, yours and other team members', are in "
               ".git/sun/sessions/ (same layout as ~/.claude/projects/, with a "
               "sessions-index.json). Look there instead of ~/.claude/projects/.")
CODEX_LINE = ("Past sessions for this repo, yours and other team members', are in "
              ".git/sun/sessions/ (with a sessions-index.json). Look there instead of "
              "~/.codex/sessions/, or use `sun sessions` to search them.")
def projects():
    return os.environ.get("SUN_PROJECTS", os.path.expanduser("~/.claude/projects"))


def codex_sessions():
    return os.environ.get("SUN_CODEX_SESSIONS", os.path.expanduser("~/.codex/sessions"))


def sh(*a, input=None, check=True, env=None):
    p = subprocess.run(a, capture_output=True, text=True, input=input, env=env)
    if check and p.returncode: sys.exit(f"sun: `{' '.join(a)}` failed: {p.stderr.strip()}")
    return p.stdout
def git(*args, **kwargs):
    return sh("git", *args, **kwargs)


_r = {}
def root():  # memoized per cwd: called on every event, and hooks chdir before using it
    return _r.get(os.getcwd()) or _r.setdefault(os.getcwd(), git("rev-parse", "--show-toplevel").strip())
def quiet(*args, **kwargs):
    return subprocess.run(args, capture_output=True, text=True, **kwargs)


def patches(pre, post, files):
    return {f: git("diff", pre, post, "--", f) for f in files}


def changed_files():
    tip, ix = history_head(False), shadow_index()
    env = {**os.environ, "GIT_INDEX_FILE": ix}
    if os.path.exists(ix): os.remove(ix)
    if tip: git("read-tree", tip, env=env)
    else: git("read-tree", "--empty", env=env)
    quiet("git", "update-index", "--refresh", env=env)
    tracked = (git("-c", "core.quotepath=false", "-c", "diff.renames=false",
                   "diff-index", "--name-only", tip, "--", env=env,
                   check=False).splitlines() if tip else [])
    untracked = git("-c", "core.quotepath=false", "ls-files", "--others",
                    "--exclude-standard", env=env, check=False).splitlines()
    return list(dict.fromkeys(tracked + untracked))
def commit_files(files, message, author, reconcile=True):
    return commit_shadow(files, message, author, reconcile)
def patch_id(commit):
    output = git("patch-id", "--stable", check=False,
                 input=git("show", "--format=", commit, check=False))
    return (output.split() or [None])[0]


def blob(data):  # loose object via hashlib+zlib: no subprocess per chunk (sha1 repos)
    b = data.encode() if isinstance(data, str) else data
    hdr = b"blob %d\x00" % len(b); sha = hashlib.sha1(hdr + b).hexdigest()
    p = os.path.join(root(), ".git", "objects", sha[:2], sha[2:])
    if not os.path.exists(p):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(zlib.compress(hdr + b))
    return sha


def refs(prefix):  # [(refname, sha)]
    output = git("for-each-ref", "--format=%(refname)\t%(objectname)", prefix, check=False)
    return [line.split("\t") for line in output.splitlines()]


def sun_dir(must=True):  # .git/sun is a per-machine cache; refs/sun/* are the source of truth
    d = os.path.join(root(), ".git", "sun")
    if must and not os.path.isdir(d): sys.exit("sun: not initialized here (run `sun init`)")
    return d
def jread(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def jwrite(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f, indent=1)


def read_text(path, errors=None):
    with open(path, errors=errors) as f:
        return f.read()


def write_text(path, text, mode="w"):
    with open(path, mode) as f:
        f.write(text)


def state(name, default):
    return jread(os.path.join(sun_dir(), name), default)


def save_state(name, obj):
    jwrite(os.path.join(sun_dir(), name), obj)


def ref_oid(ref):
    return git("rev-parse", "-q", "--verify", ref, check=False).strip()
def history_head(required=True):
    oid = ref_oid(SHADOW_REF)
    if required and not oid: sys.exit("sun: shadow history has no commits (run `sun init`)")
    return oid
def history_refs():
    return [r for r in (SHADOW_REF, SHADOW_REMOTE_REF) if ref_oid(r)]
def resolve_history_rev(rev):
    if rev == "HEAD": rev = SHADOW_REF
    return git("rev-parse", rev).strip()
def fast_forward_shadow():
    """Adopt a fetched shared tip when doing so cannot discard local Sun commits."""
    local, remote = ref_oid(SHADOW_REF), ref_oid(SHADOW_REMOTE_REF)
    if not remote or local == remote: return
    if not local or not quiet("git", "merge-base", "--is-ancestor", local, remote).returncode:
        git("update-ref", SHADOW_REF, remote, local or "0" * 40)
    elif quiet("git", "merge-base", "--is-ancestor", remote, local).returncode:
        sys.exit("sun: local and remote shadow histories diverged; run `sun merge`")
def shadow_index():
    return os.path.join(sun_dir(), "shadow-index")
def make_shadow_commit(tree, message, author, parents=()):
    ident = {**os.environ, "GIT_AUTHOR_NAME": author, "GIT_AUTHOR_EMAIL": "sun@sun",
             "GIT_COMMITTER_NAME": author, "GIT_COMMITTER_EMAIL": "sun@sun"}
    args = ["-c", "commit.gpgsign=false", "commit-tree", tree]
    for parent in parents: args += ["-p", parent]
    return git(*args, "-m", message, env=ident).strip()
def commit_shadow(files, message, author, reconcile=True):
    """Snapshot files into an independent commit graph without touching HEAD or the real index."""
    if reconcile: fast_forward_shadow()
    parent, ix = history_head(False), shadow_index()
    if os.path.exists(ix): os.remove(ix)
    env = {**os.environ, "GIT_INDEX_FILE": ix}
    if parent: git("read-tree", parent, env=env)
    else: git("read-tree", "--empty", env=env)
    git("add", "-A", "--", *files, env=env, check=False)
    tree = git("write-tree", env=env).strip()
    commit = make_shadow_commit(tree, message, author, [parent] if parent else [])
    git("update-ref", SHADOW_REF, commit, parent or "0" * 40)
    return commit
def parse_events(text: str) -> List[Event]:  # skips torn lines rather than bricking every command
    out: List[Event] = []
    for l in text.splitlines():
        try: out.append(json.loads(l))
        except ValueError: pass
    return out
def events() -> List[Event]:
    try: evs = parse_events(read_text(os.path.join(sun_dir(), "events.jsonl")))
    except OSError: evs = []
    for ref, sha in refs("refs/sun/log/"):
        if ref.split("/")[-1] != user():
            evs += parse_events(git("cat-file", "blob", sha, check=False))
    return sorted(evs, key=lambda e: e.get("timestamp", ""))
def lock():
    lk = open(os.path.join(sun_dir(False), "lock"), "a")
    fcntl.flock(lk, fcntl.LOCK_EX)
    return lk  # closing the file releases the lock
def mirror_log():  # one writer per user: refs/sun/log/<user> mirrors the local cache
    p = os.path.join(sun_dir(), "events.jsonl")
    if os.path.exists(p): git("update-ref", f"refs/sun/log/{user()}", blob(read_text(p)))
def record(mirror: bool = True, **ev: Any) -> Event:
    ev = {"id": uuid.uuid4().hex[:8], "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **ev}
    with open(os.path.join(sun_dir(), "events.jsonl"), "a") as f:
        f.write(json.dumps(ev) + "\n")
    if mirror:
        mirror_log()
    return ev
def store_chunks(sid, files, u=None):  # {path: text} -> refs/sun/sessions/<u>/<sid> tree
    if not files: return
    ref, ix = f"refs/sun/sessions/{u or user()}/{sid}", os.path.join(sun_dir(), "tmpindex")
    env = {**os.environ, "GIT_INDEX_FILE": ix}
    if os.path.exists(ix): os.remove(ix)
    if not quiet("git", "rev-parse", "-q", "--verify", ref).returncode:
        git("read-tree", ref, env=env)
    git("update-index", "--index-info", env=env,
        input="".join(f"100644 blob {blob(c)}\t{p}\n" for p, c in files.items()))
    git("update-ref", ref, git("commit-tree", git("write-tree", env=env).strip(), "-m", sid).strip())
_u = {}
def user():  # the git user on whose machine the change happened; owns every event
    _u or _u.setdefault("u", (git("config", "user.name", check=False).strip()
                              or os.environ.get("USER", "unknown")).replace(" ", "-").lower())
    return _u["u"]
local = lambda u=None: f"{u or user()}/local"
agent = lambda sid, harness="claude", u=None: f"{u or user()}/agent:{harness}/{sid[:8]}"
session_key = lambda sid, harness="claude": sid if harness == "claude" else f"{harness}/{sid}"
call_key = lambda sid, payload, harness="claude": \
    f"{session_key(sid, harness)}/{payload.get('tool_use_id') or ''}"
tool_file = lambda inp: inp.get("file_path") or inp.get("notebook_path")
rel_to_root = lambda path: os.path.relpath(os.path.realpath(path), root())
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
    return [rel_to_root(f) for f in tool_files(tool, inp)]
edits_msg = lambda actor, files: (f"sun: {actor} edits " + ", ".join(files[:3])
                                  + (f" +{len(files) - 3} more" if len(files) > 3 else ""))
def sync(exclude=(), reconcile=True, method="sync"):  # commit unclaimed changes as local
    if reconcile: fast_forward_shadow()
    exclude = set(exclude) | {f for s in state("active.json", {}).values() for f in s["files"]}
    files = [f for f in changed_files() if f not in exclude]
    if not files: return None
    pre, actor = history_head(), local()
    c = commit_files(files, edits_msg(actor, files), actor, reconcile)
    p = patches(pre, c, files)
    return record(type="edit", actor=actor, commit=c, patch_id=patch_id(c),
                  edits=[{"file": f, "patch": p[f],
                          "attribution": {"method": method}} for f in files])
def maybe_sync(exclude=()):  # skipped while an agent tool call is in flight
    state("active.json", {}) or sync(exclude)
def finish_call(sid, active: Dict[str, ActiveCall], payload, harness="claude"):
    # PostToolUse: the pre->post diff is the agent's tool call
    st = (active.pop(call_key(sid, payload, harness), None)  # or an id-less claim
          or active.pop(call_key(sid, {}, harness), None) or {"files": []})
    save_state("active.json", active)
    others = {f for s in active.values() for f in s["files"]}
    files = [f for f in changed_files() if f not in others]
    if not files: return
    tool, inp = payload.get("tool_name", "?"), payload.get("tool_input") or {}
    paths = relative_tool_files(tool, inp)
    call_input = ({"file": paths[0]} if len(paths) == 1 else
                  {"files": paths} if paths else inp)
    call = {"id": payload.get("tool_use_id"), "tool": tool, "input": call_input}
    claimed = set(st["files"]) | set(paths)
    # Edit/Write only touch their own file -> the rest of the diff is a concurrent local
    # overlay; for other tools (Bash, ...) the whole diff is the agent's
    a_files = [f for f in files if f in claimed] if tool in EDIT_TOOLS and claimed else files
    h_files = [f for f in files if f not in a_files]
    actor, pre = agent(sid, harness), history_head()
    turn = state("turns.json", {}).get(session_key(sid, harness), {}).get("n", 0)
    c = commit_files(files, f"sun: {actor} {tool}" if a_files else edits_msg(local(), files),
                     actor if a_files else local())
    p = patches(pre, c, files)
    if a_files:
        git("update-ref", f"refs/sun/ops/{c}", c)  # survives the turn squash + git gc
        record(type="edit", actor=actor, session_id=sid, turn=f"turn{turn}", commit=c,
               patch_id=patch_id(c),
               tool_calls=[call], edits=[{"file": f, "patch": p[f], "tool_call_id": call["id"],
                                          "attribution": {"method": "hook"}} for f in a_files])
    if h_files:
        record(type="edit", actor=local(), commit=c,
               edits=[{"file": f, "patch": p[f],
                       "attribution": {"method": "hook"}} for f in h_files])
def squash_turn(sid, harness="claude"):
    # Stop: squash the turn's agent calls and intervening local edits into one turn commit.
    # A different agent or an already-aggregated commit remains a hard boundary.
    t = state("turns.json", {}).get(session_key(sid, harness))
    tip = history_head()
    if not t or t.get("squashed") or \
            quiet("git", "merge-base", "--is-ancestor", t["start"], tip).returncode: return
    start, actor = t["start"], agent(sid, harness)
    rng = git("rev-list", f"{start}..{tip}").split()
    ops = [e for e in events() if e.get("commit") in rng]
    mine = [e for e in ops if e["actor"] == actor]
    allowed = {actor, local()}
    raw = [e for e in ops if e.get("type") == "edit" and e["actor"] in allowed]
    if not rng or not mine or len(raw) != len(ops) or set(rng) - {e["commit"] for e in raw}:
        return
    # Rewriting the turn removes these commits from the main shadow lineage. Keep every
    # operation snapshot, including intervening human edits, reachable and shareable.
    for H in rng: git("update-ref", f"refs/sun/ops/{H}", H)
    # commit-tree + update-ref never touch the worktree/index: edits after the last call stay dirty
    c = make_shadow_commit(git("rev-parse", f"{tip}^{{tree}}").strip(),
                           f"sun: {actor} turn {t['n']} ({len(mine)} tool calls)",
                           actor, [start])
    git("update-ref", SHADOW_REF, c, tip)
    turn_pid = patch_id(c)
    revisions = {e["id"]: {**e, "commit": c, "snapshot": e["commit"],
                            "patch_id": turn_pid} for e in ops}
    p = os.path.join(sun_dir(), "events.jsonl"); tmp = p + ".tmp"
    write_text(tmp, "".join(json.dumps(revisions.get(e["id"], e)) + "\n"
                            for e in parse_events(read_text(p))))
    os.replace(tmp, p); mirror_log()
    turns = state("turns.json", {})
    turns[session_key(sid, harness)]["squashed"] = True
    save_state("turns.json", turns)
def prompt_line(l, harness="claude"):
    try: obj = json.loads(l)  # both harnesses write one JSON record per line
    except ValueError: return False
    if harness == "claude":  # a user record of only tool_results is not a prompt, but a
        content = (obj.get("message") or {}).get("content")  # queued message may ride
        return obj.get("type") == "user" and not (isinstance(content, list) and all(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in content))
    p = obj.get("payload") or {}
    if obj.get("type") == "event_msg":
        return {"user_message": 1, "task_started": 3}.get(p.get("type"), 0)
    return 2 * (obj.get("type") == "response_item" and p.get("type") == "message"
                and p.get("role") == "user")
def prompt_boundary(sid, payload, harness="claude"):
    # PreToolUse: a prompt can reach the transcript with no hook between turns (queued
    # message, missed Stop); a user line past the first scan means a new turn started
    turns: Dict[str, TurnState] = state("turns.json", {})
    t = turns.get(session_key(sid, harness))
    tp = payload.get("transcript_path") or (t or {}).get("transcript", "")
    if not (t and tp and os.path.exists(tp)): return
    with open(tp, "rb") as f:
        prompts = []
        f.seek(t.get("soffset", t.get("toffset", 0)))
        while True:
            pos, line = f.tell(), f.readline()
            if not line:
                break
            kind = prompt_line(line, harness)
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
            squash_turn(sid, harness)
            f.seek(t.get("toffset", 0))
            data = f.read(boundary - f.tell())
            if data and not t.get("stopped") and cfg_share_sessions():
                store_chunks(sid, {f"turn-{t['n']:04d}.jsonl": data})
            sync(method="hook")
            t.update(n=t["n"] + 1, start=history_head(), toffset=boundary)
            t.pop("stopped", None)
    t.update(soffset=end, seen=1 if boundaries else seen + len(prompts))
    turns[session_key(sid, harness)] = t
    save_state("turns.json", turns)
def stop_chunk(sid, payload, harness="claude"):
    # Stop: append this turn's transcript slice to the session ref
    turns: Dict[str, TurnState] = state("turns.json", {})
    t = turns.get(session_key(sid, harness))
    tp = payload.get("transcript_path") or (t or {}).get("transcript", "")
    if not (t and tp and os.path.exists(tp) and cfg_share_sessions()): return
    with open(tp, errors="replace") as f:
        f.seek(t.get("toffset", 0))
        data = f.read()
    if data: store_chunks(sid, {f"turn-{t['n']:04d}.jsonl": data})
    t.update(toffset=os.path.getsize(tp), stopped=True); save_state("turns.json", turns)
def subagent_chunk(sid, payload):
    tp, sub = payload.get("agent_transcript_path"), payload.get("agent_id")
    if not (tp and sub and os.path.exists(tp) and cfg_share_sessions()): return
    store_chunks(sid, {f"subagents/{sub}/transcript.jsonl": read_text(tp, errors="replace")})
def cmd_hook(a):
    try: payload = json.load(sys.stdin)
    except (ValueError, OSError): payload = {}
    try: payload.get("cwd") and os.chdir(payload["cwd"])
    except OSError: return
    p = quiet("git", "rev-parse", "--show-toplevel")
    if p.returncode or not os.path.isdir(os.path.join(p.stdout.strip(), ".git", "sun")):
        return  # not a sun repo; hooks must never break the harness
    os.chdir(p.stdout.strip())
    with lock():  # serialize concurrent hooks (parallel sessions/subagents)
        handle_hook(a, payload)


def handle_hook(a, payload):
    event, sid, harness = (payload.get("hook_event_name", ""),
                           payload.get("session_id", "?"), a.harness)
    active: Dict[str, ActiveCall] = state("active.json", {})
    if event == "UserPromptSubmit" and not state("turns.json", {}).get(
            session_key(sid, harness), {}).get("stopped"):  # Stop never fired:
        squash_turn(sid, harness)  # squash the turn + store its transcript slice
        stop_chunk(sid, payload, harness)
    elif event == "PreToolUse": prompt_boundary(sid, payload, harness)
    if event in ("SessionStart", "SubagentStart", "UserPromptSubmit", "PreToolUse"):
        sync(method="hook")  # everything dirty before an agent tool runs is local
    if event == "SessionStart":  # stdout lands in the agent's context
        if not cfg_share_sessions(): return
        native = "~/.claude/projects" if harness == "claude" else "~/.codex/sessions"
        print(f"sun: past sessions for this repo (yours + teammates') are in "
              f".git/sun/sessions/, not {native}; {export_sessions()} sessions")
    elif event == "SubagentStart":
        if not cfg_share_sessions(): return
        print("sun: past sessions for this repo are in .git/sun/sessions/; "
              "use `sun sessions` to search them")
    elif event == "UserPromptSubmit":
        turns, tp = state("turns.json", {}), payload.get("transcript_path", "")
        key = session_key(sid, harness)
        turns[key] = {"n": turns.get(key, {}).get("n", 0) + 1, "start": history_head(),
                      "transcript": tp,
                      "toffset": os.path.getsize(tp) if os.path.exists(tp) else 0}
        save_state("turns.json", turns)
    elif event == "PreToolUse":  # claim the file BEFORE the write exists
        tool, inp = payload.get("tool_name", "?"), payload.get("tool_input") or {}
        active[call_key(sid, payload, harness)] = {"files": relative_tool_files(tool, inp)}
        save_state("active.json", active)
    elif event == "PostToolUse":
        finish_call(sid, active, payload, harness)
    elif event == "Stop":  # a queued prompt may end in a text-only turn: no PreToolUse
        prompt_boundary(sid, payload, harness)
        squash_turn(sid, harness)
        stop_chunk(sid, payload, harness)
    elif event == "SubagentStop":
        subagent_chunk(sid, payload)
enc = lambda path: re.sub(r"[/.]", "-", path)
def project_dirs():  # every ~/.claude project dir that maps to this repo (worktrees too)
    wt = [l.split(" ", 1)[1] for l in git("worktree", "list", "--porcelain", check=False)
          .splitlines() if l.startswith("worktree ")]
    names = {enc(p) for r in [root()] + wt for p in (r, os.path.realpath(r))}
    return [d for d in glob.glob(os.path.join(projects(), "*")) if os.path.basename(d) in names
            or any(os.path.basename(d).startswith(n + "--claude-worktrees-") for n in names)]
def repo_locations():
    wt = [l.split(" ", 1)[1] for l in git("worktree", "list", "--porcelain", check=False)
          .splitlines() if l.startswith("worktree ")]
    return {os.path.realpath(p) for p in [root()] + wt}
def codex_meta(path):
    try:
        for line in read_text(path, errors="replace").splitlines():
            try: obj = json.loads(line)
            except ValueError: continue
            if obj.get("type") == "session_meta": return obj.get("payload") or {}
    except OSError: pass
    return {}
def transcript_sources(harness="claude"):
    if harness == "claude":
        for d in project_dirs():
            for path in glob.glob(os.path.join(d, "**", "*.jsonl"), recursive=True):
                rp = os.path.relpath(path, d).split(os.sep)
                sid, sub = (rp[0], rp[-1][:-6]) if len(rp) > 1 else (rp[0][:-6], None)
                yield path, sid, sub
        return
    roots = repo_locations()
    for path in glob.glob(os.path.join(codex_sessions(), "**", "*.jsonl"), recursive=True):
        meta = codex_meta(path); cwd = os.path.realpath(meta.get("cwd") or "")
        if not cwd or not any(cwd == r or cwd.startswith(r + os.sep) for r in roots): continue
        sid = meta.get("id") or os.path.basename(path)[:-6].rsplit("-", 5)[-1]
        source = str(meta.get("source") or "").lower()
        yield path, sid, sid if "subagent" in source else None
def scan_claude_transcript(path):
    chunks, cur = [], []
    for line in read_text(path, errors="replace").splitlines(keepends=True):
        if cur and "tool_result" not in line \
                and ('"type":"user"' in line or '"type": "user"' in line):
            chunks.append("".join(cur)); cur = []
        cur.append(line)
    if cur: chunks.append("".join(cur))
    return chunks
def scan_codex_transcript(path):
    lines = read_text(path, errors="replace").splitlines(keepends=True)
    parsed = []
    for line in lines:
        try: parsed.append(json.loads(line))
        except ValueError: parsed.append({})
    task_boundaries = any(o.get("type") == "event_msg" and
                          (o.get("payload") or {}).get("type") == "task_started" for o in parsed)
    chunks, cur = [], []
    for line, obj in zip(lines, parsed):
        payload = obj.get("payload") or {}
        boundary = (obj.get("type") == "event_msg" and payload.get("type") == "task_started")
        if not task_boundaries:
            boundary = ((obj.get("type") == "response_item" and
                         payload.get("type") == "message" and payload.get("role") == "user") or
                        (obj.get("type") == "event_msg" and payload.get("type") == "user_message"))
        if boundary and cur: chunks.append("".join(cur)); cur = []
        cur.append(line)
    if cur: chunks.append("".join(cur))
    return chunks
def scan_transcript(path, harness="claude"):
    return scan_claude_transcript(path) if harness == "claude" else scan_codex_transcript(path)
def do_import(harnesses=("claude",)):
    t0, seen, ns, nsub = time.time(), state("imported.json", {}), 0, 0
    share = cfg_share_sessions()
    for harness in harnesses:
        for path, sid, sub in transcript_sources(harness):
            st = os.stat(path)
            if share and seen.get(path) == [st.st_size, int(st.st_mtime)]:
                continue  # idempotent: only new/changed transcripts are re-read
            chunks = scan_transcript(path, harness)
            if share:
                pre = f"subagents/{sub}/" if sub else ""
                store_chunks(sid, {f"{pre}turn-{i:04d}.jsonl": c for i, c in enumerate(chunks, 1)})
                seen[path] = [st.st_size, int(st.st_mtime)]
            ns, nsub = ns + (not sub), nsub + bool(sub)
    if share: save_state("imported.json", seen)
    return f"imported {ns} sessions, {nsub} subagents in {time.time() - t0:.1f}s"
session_rows = lambda: [(r.split("/", 4)[4], r.split("/")[3], r)  # (sid, user, ref)
                        for r, _ in refs("refs/sun/sessions/")]
def session_text(ref, sub=None):
    pre = f"subagents/{sub}/" if sub else ""
    names = sorted(n for n in git("ls-tree", "-r", "--name-only", ref).splitlines()
                   if n.startswith(pre) and n.count("/") == pre.count("/"))
    return "".join(git("cat-file", "blob", f"{ref}:{n}") for n in names)
def export_sessions():  # mirror session refs to .git/sun/sessions/ in ~/.claude/projects layout
    base, idx = os.path.join(sun_dir(), "sessions", enc(root())), []
    os.makedirs(base, exist_ok=True)
    for sid, u, ref in session_rows():
        fp = os.path.join(base, sid + ".jsonl")
        write_text(fp, session_text(ref))
        for s in sorted({n.split("/")[1] for n in git("ls-tree", "-r", "--name-only", ref)
                        .splitlines() if n.startswith("subagents/")}):
            os.makedirs(os.path.join(base, sid, "subagents"), exist_ok=True)
            write_text(os.path.join(base, sid, "subagents", s + ".jsonl"), session_text(ref, s))
        idx.append({"id": sid, "user": u, "path": fp, "origin": "local" if u == user() else "team"})
    jwrite(os.path.join(base, "sessions-index.json"), idx)
    return len(idx)
def cmd_sessions(a):
    if a.id == "export":
        return print(f"sun: exported {export_sessions()} sessions to .git/sun/sessions/")
    rows = session_rows()
    if a.id:
        for sid, u, ref in rows:
            if sid.startswith(a.id): return print(session_text(ref), end="")
        sys.exit("sun: no such session")
    pat = a.grep or (a.file and re.escape(a.file))
    for sid, u, ref in rows:
        if pat and not re.search(pat, session_text(ref)): continue
        print(f"{sid}  {u}  {len(git('ls-tree', '--name-only', ref).splitlines())} turns")
def chunk_prompt(text):  # first user message of a stored transcript chunk (claude or codex)
    for o in parse_events(text):
        m, p = o.get("message") or {}, o.get("payload") or {}
        if o.get("type") == "user" and isinstance(m, dict):
            c = m.get("content")
            t = c if isinstance(c, str) else "\n".join(
                b.get("text", "") for b in c or []
                if isinstance(b, dict) and b.get("type") == "text")
            if t: return t
        if o.get("type") == "event_msg" and p.get("type") == "user_message":
            return p.get("message")
        if o.get("type") == "response_item" and p.get("type") == "message" \
                and p.get("role") == "user":
            return "".join(b.get("text", "") for b in p.get("content") or []
                           if isinstance(b, dict))
def stdout_file():  # file backing a redirected stdout (`sun export > dump.jsonl`)
    try:
        p = (fcntl.fcntl(1, fcntl.F_GETPATH, bytes(1024)).rstrip(b"\0").decode()
             if hasattr(fcntl, "F_GETPATH") else os.readlink("/proc/self/fd/1"))
        return [rel_to_root(p)] if os.path.isfile(p) else []
    except OSError: return []
def cmd_export(a):  # JSONL fine-tuning dump: one record per turn/op, prompt paired with edits
    maybe_sync([rel_to_root(a.output)] if a.output else stdout_file())  # never re-ingest our dump
    rows, evs, merged = session_rows(), events(), {}
    for e in evs:
        if e.get("type") not in ("edit", "undo") or not e.get("edits"): continue
        key = (e["actor"], e["turn"]) if e.get("turn") else e["id"]  # unsquashed turns regroup
        m = merged.setdefault(key, {**e, "tool_calls": e.get("tool_calls", [])[:],
                                    "edits": e["edits"][:]})
        if m["id"] != e["id"]: m["tool_calls"] += e.get("tool_calls", []); m["edits"] += e["edits"]
    out = open(a.output, "w") if a.output else sys.stdout
    for e in merged.values():
        sid, prompt = e.get("session_id"), None
        owner = e["actor"].split("/", 1)[0]
        hit = sid and next(((s, r) for s, u, r in rows if u == owner and s == sid), None)
        if hit:
            n = int(e.get("turn", "turn0")[4:])
            prompt = n and chunk_prompt(git("cat-file", "blob",
                                            f"{hit[1]}:turn-{n:04d}.jsonl", check=False)) or None
        out.write(json.dumps({"timestamp": e["timestamp"], "actor": e["actor"], "session": sid,
                              "turn": e.get("turn"), "prompt": prompt,
                              "tool_calls": e["tool_calls"],
                              "edits": [{"file": d["file"], "patch": d["patch"] or git(
                                  "show", "--format=", e.get("commit") or "", "--", d["file"],
                                  check=False)} for d in e["edits"]]}) + "\n")
    if a.output: out.close(); print(f"sun: exported to {a.output}")
def cmd_gc(a):
    old = [r for r, sha in refs("refs/sun/sessions/")
           if int(git("show", "-s", "--format=%ct", sha).strip()) < time.time() - a.older_than * 86400]
    for r in old: git("update-ref", "-d", r)
    print(f"sun: dropped {len(old)} session refs (git gc will prune the objects)")
def cfg_share_sessions(): return state("config.json", {}).get("share_sessions", False)
def configure_session_sharing(choice):
    cfg = state("config.json", {})
    if choice is None and "share_sessions" in cfg: return cfg["share_sessions"]
    if choice is None:
        choice = (sys.stdin.isatty() and input(
            "sun: share raw agent transcripts with everyone who can read this remote? "
            "They may contain secrets and private data. [y/N] ").strip().lower() == "y")
    cfg["share_sessions"] = choice; save_state("config.json", cfg)
    return choice
def detect_harnesses():  # every harness with state on this machine (SUN_* overrides apply)
    hs = [h for h, home, d in (("claude", "~/.claude", projects()),
                               ("codex", "~/.codex", codex_sessions()))
          if os.path.isdir(os.path.expanduser(home)) or os.path.isdir(d)]
    return hs or ["claude"]
def configured_harnesses():
    cfg = state("config.json", {})
    return cfg.get("harnesses") or [cfg.get("harness", "claude")]
hook_file = lambda h: ".claude/settings.json" if h == "claude" else ".codex/hooks.json"
hook_cmd = lambda h: "sun hook" if h == "claude" else "sun hook --harness codex"
def install_hooks(harness="claude"):
    rel = hook_file(harness)
    path = os.path.join(root(), rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cfg = jread(path, {})
    if not isinstance(cfg.setdefault("hooks", {}), dict):
        sys.exit(f"sun: unexpected 'hooks' format in {rel}")
    command = hook_cmd(harness)
    hook_events = HOOK_EVENTS if harness == "claude" else CODEX_HOOK_EVENTS
    for event in hook_events:
        group = cfg["hooks"].setdefault(event, [])
        if not any(h.get("command") == command for g in group for h in g.get("hooks", [])):
            group.append({"hooks": [{"type": "command", "command": command}]})
    jwrite(path, cfg)
    return f"{harness} ({rel})"
def remove_hooks(harness):  # a restrictive re-init un-installs the excluded harness's hook
    path, command = os.path.join(root(), hook_file(harness)), hook_cmd(harness)
    cfg = jread(path, {})
    if not isinstance(cfg.get("hooks"), dict): return
    for event in list(cfg["hooks"]):
        for g in cfg["hooks"][event]:
            g["hooks"] = [h for h in g.get("hooks", []) if h.get("command") != command]
        cfg["hooks"][event] = [g for g in cfg["hooks"][event] if g.get("hooks")]
        if not cfg["hooks"][event]: del cfg["hooks"][event]
    jwrite(path, cfg)
def refspecs(share_sessions=False):
    specs = ["+refs/sun/log/*:refs/sun/log/*", "+refs/sun/ops/*:refs/sun/ops/*",
             "+refs/sun/heads/*:refs/sun/remotes/origin/*"]
    return specs + (["+refs/sun/sessions/*:refs/sun/sessions/*"] if share_sessions else [])
def install_push(share_sessions=False):
    if "origin" in git("remote", check=False).split():
        for old in ("+refs/sun/*:refs/sun/*", "+refs/sun/sessions/*:refs/sun/sessions/*",
                    "+refs/sun/heads/*:refs/sun/heads/*"):
            git("config", "--fixed-value", "--unset-all", "remote.origin.fetch", old, check=False)
        current = git("config", "--get-all", "remote.origin.fetch", check=False).splitlines()
        for spec in refspecs(share_sessions):
            if spec not in current: git("config", "--add", "remote.origin.fetch", spec)
    hp = os.path.join(root(), ".git", "hooks", "pre-push")
    old = read_text(hp) if os.path.exists(hp) else ""
    legacy = ('#!/bin/sh\n# sun: mirror op log + sessions, fail-soft\n'
              'git push --no-verify "$1" "+refs/sun/*:refs/sun/*" >/dev/null 2>&1 || true\n')
    managed = old == legacy or any(old.startswith(f'#!/bin/sh\n{marker}\n') for marker in (
        '# sun: mirror shared refs', '# sun: mirror shared refs, fail-soft'))
    if not old or managed:
        lines = ['#!/bin/sh', '# sun: mirror shared refs',
                 f'git push --no-verify "$1" "+refs/sun/log/{user()}:refs/sun/log/{user()}" >/dev/null 2>&1 || true',
                 'git push --no-verify "$1" "+refs/sun/ops/*:refs/sun/ops/*" >/dev/null 2>&1 || true']
        lines.insert(2, 'git push --no-verify "$1" "refs/sun/heads/*:refs/sun/heads/*" || { echo "sun: shadow history push rejected; fetch and reconcile before pushing" >&2; exit 1; }')
        if share_sessions:
            lines.append(f'git push --no-verify "$1" "+refs/sun/sessions/{user()}/*:refs/sun/sessions/{user()}/*" >/dev/null 2>&1 || true')
        write_text(hp, "\n".join(lines) + "\n")
        os.chmod(hp, 0o755)
def agent_instructions(harnesses, choice, flags=""):  # one prompt covering every harness file
    todo = []
    for h in harnesses:
        name, line = ("CLAUDE.md", CLAUDE_LINE) if h == "claude" else ("AGENTS.md", CODEX_LINE)
        p = os.path.join(root(), name)
        cur = read_text(p) if os.path.exists(p) else ""
        if line not in cur: todo.append((p, cur, line, name))
    if not todo: return
    if choice is None and sys.stdin.isatty():
        choice = input(f"sun: add one line to {'/'.join(t[3] for t in todo)} so agents find "
                       "team sessions? [Y/n] ").strip().lower() != "n"
    if choice:
        for p, cur, line, _ in todo:
            write_text(p, ("\n" if cur and not cur.endswith("\n") else "") + line + "\n", "a")
    else:
        print(f"sun: run `sun init{flags} --instructions` later to enable team session sharing")
def cmd_init(a):
    if quiet("git", "rev-parse", "--git-dir").returncode: sh("git", "init", "-q")
    os.makedirs(os.path.join(root(), ".git", "sun"), exist_ok=True)
    explicit = [h for h, f in (("claude", a.claude), ("codex", a.codex)) if f]
    harnesses = explicit or detect_harnesses()
    cfg = state("config.json", {}); cfg.pop("harness", None)
    cfg["harnesses"] = harnesses
    cfg.pop("shadow_history", None)
    save_state("config.json", cfg)
    share_sessions = configure_session_sharing(a.share_sessions)
    if "origin" in git("remote", check=False).split():  # fresh clone: fetch team refs
        git("fetch", "-q", "origin", *refspecs(share_sessions), check=False)
    fast_forward_shadow()
    p, sha = os.path.join(sun_dir(), "events.jsonl"), git(  # rebuild cache from our own ref
        "rev-parse", "-q", "--verify", f"refs/sun/log/{user()}", check=False).strip()
    if sha and not os.path.exists(p): write_text(p, git("cat-file", "blob", sha))
    installed = ", ".join(install_hooks(h) for h in harnesses); install_push(share_sessions)
    for h in ("claude", "codex"):
        if explicit and h not in explicit: remove_hooks(h)
    if share_sessions:
        agent_instructions(harnesses, a.instructions, "".join(" --" + h for h in explicit))
    if not history_head(False) or changed_files():
        c = commit_files(["."], "sun: initial state", local())
        record(type="init", actor=local(), commit=c, edits=[])
    print(f"sun: initialized {root()} (hooks: {installed}); {do_import(harnesses)}")
    if "codex" in harnesses:
        print("sun: Codex requires separate hook approval; open `/hooks`, review "
              "`.codex/hooks.json`, and trust the Sun hooks before testing")
    print("run `sun viz` to explore your attributed history")
def cmd_sync(a):
    ev = sync(); print(f"sun: committed local edits as op {ev['id']}" if ev else "sun: nothing to sync")
def cmd_merge(a):
    if "origin" in git("remote", check=False).split():
        git("fetch", "-q", "origin",
            "+refs/sun/heads/*:refs/sun/remotes/origin/*", check=False)
    remote = ref_oid(SHADOW_REMOTE_REF)
    if not remote: sys.exit("sun: no shared shadow history found on origin")
    sync(reconcile=False)  # the current worktree is the user's merge resolution
    local_tip = history_head()
    if local_tip == remote or not quiet(
            "git", "merge-base", "--is-ancestor", remote, local_tip).returncode:
        return print("sun: shadow history is already up to date")
    if not quiet("git", "merge-base", "--is-ancestor", local_tip, remote).returncode:
        git("update-ref", SHADOW_REF, remote, local_tip)
        return print(f"sun: fast-forwarded shadow history to {remote[:8]}")
    tree = git("rev-parse", f"{local_tip}^{{tree}}").strip()
    actor = local()
    commit = make_shadow_commit(tree, "sun: merge shared shadow history", actor,
                                [local_tip, remote])
    git("update-ref", SHADOW_REF, commit, local_tip)
    record(type="merge", actor=actor, commit=commit, parents=[local_tip, remote], edits=[])
    print(f"sun: merged shared shadow history in {commit[:8]}")
def cmd_import(a):
    print("sun: " + do_import(configured_harnesses()))
def installed_git_source():
    from importlib.metadata import distribution
    try:
        source = json.loads(distribution("sun").read_text("direct_url.json") or "{}")
        return source.get("url"), (source.get("vcs_info") or {}).get("commit_id")
    except (LookupError, TypeError, ValueError):
        return None, None
def cmd_update(a):  # uv re-resolves the git source to the latest commit
    url, installed = installed_git_source()
    if url and installed:
        head = quiet("git", "ls-remote", url, "HEAD")
        if not head.returncode and (head.stdout.split() or [None])[0] == installed:
            return print("sun: already up to date")
    try: p = quiet("uv", "tool", "upgrade", "sun")
    except OSError: p = None
    if not p or p.returncode:
        sys.exit("sun: could not update via uv; run "
                 "`uv tool install --force git+https://github.com/sundial-org/sun`")
    print(f"sun: {(p.stderr.strip().splitlines() or ['updated'])[-1]}")
def cmd_log(a):
    maybe_sync()
    by_commit = {}
    for ev in events(): by_commit.setdefault(ev.get("commit"), []).append(ev)
    revisions = history_refs()
    for line in git("log", *revisions, f"-{a.n}", "--pretty=%H\t%h\t%ad\t%s",
                    "--date=short").splitlines():
        H, h, date, subj = line.split("\t", 3)
        tags = "".join(dict.fromkeys(
            f"  [{e['actor']}" + (f" {e['turn']}" if e.get("turn") else "")
            + (f" pr#{e['pr']}" if e.get("pr") else "")
            + (" undo" if e["type"] == "undo" else "") + "]"
            for e in by_commit.get(H, [])))
        print(f"{h} {date} {subj}{tags or '  [untracked]'}")
def cmd_show(a):
    maybe_sync(); H = resolve_history_rev(a.commit)
    print(git("show", "--stat", "--pretty=format:commit %h  %ad%n%s%n", "--date=short", H))
    evs = [e for e in events() if H in (e.get("commit"), e.get("snapshot"))]
    if not evs:  # squash-merge/rebase moved the sha: match events by patch-id instead
        pid = patch_id(H); evs = [e for e in events() if pid and e.get("patch_id") == pid]
    if not evs: print("no sun operations recorded for this commit")
    for e in evs: print(json.dumps(e, indent=2))
def blame_context(chunk, tid):  # first user prompt + last agent text before tool call `tid`
    prompt = ctx = tool = None
    for obj in parse_events(chunk):
        p = obj.get("payload") or {}
        m = obj.get("message") or (p if p.get("type") == "message" else {})
        if p.get("type") in ("function_call", "custom_tool_call") and \
                tid in (p.get("call_id"), p.get("id")):
            tool = p.get("name")
        if p.get("type") == "user_message" and not prompt: prompt = p.get("message")
        c, role = m.get("content"), m.get("role")
        for b in [{"type": "text", "text": c}] if isinstance(c, str) else \
                (c if isinstance(c, list) else []):
            if not isinstance(b, dict): continue
            if b.get("type") == "tool_use" and b.get("id") == tid: tool = b.get("name")
            elif b.get("type") in ("text", "input_text") and role == "user" and not prompt:
                prompt = b.get("text")
            elif b.get("type") in ("text", "output_text") and role == "assistant":
                ctx = b.get("text")
        if tool: break
    return prompt, ctx, tool
def cmd_blame(a):
    maybe_sync()
    d, b = os.path.split(a.file)  # blame a symlink itself: resolve only its directory
    f = os.path.relpath(os.path.join(os.path.realpath(d or "."), b), root())
    out = git("-c", "core.quotepath=false", "blame", "--porcelain",
              "-L", f"{a.line},{a.line}", history_head(), "--", f)
    H, orig = out.split()[:2]  # originating commit + the line's number in it
    if H == "0" * 40: sys.exit(f"sun: {f}:{a.line} is uncommitted")
    of = next((l[9:] for l in out.splitlines() if l.startswith("filename ")), f)  # pre-rename path
    touches = lambda e: any(ed.get("file") == of for ed in e.get("edits") or [])
    all_ev = events()
    evs = [e for e in all_ev if e.get("commit") == H]
    if not evs:  # squash-merge/rebase moved the sha: match events by patch-id instead
        pid = patch_id(H); evs = [e for e in all_ev if pid and e.get("patch_id") == pid]
    ev = next((e for e in evs if touches(e)), evs[0] if evs else None)
    snapshots = [e for e in evs if e.get("snapshot") and e.get("snapshot") != e.get("commit")]
    if snapshots:  # re-blame the preserved snapshots: exact call + actor by line position
        tip, turn_commit = snapshots[-1]["snapshot"], snapshots[0]["commit"]
        if turn_commit != H:  # patch-id match: translate the line into the original squash
            ws = lambda rev: ["".join(l.split()) for l in  # patch-id ignores all whitespace
                              quiet("git", "show", f"{rev}:{of}").stdout.splitlines()]
            i, sm = int(orig) - 1, difflib.SequenceMatcher(None, ws(H), ws(turn_commit))
            orig = next((j1 + i - i1 + 1 for t, i1, i2, j1, j2 in sm.get_opcodes()
                         if t == "equal" and i1 <= i < i2), None)
        o = tip and orig and quiet("git", "-c", "core.quotepath=false", "blame", "--porcelain",
                                   "-L", f"{orig},{orig}", tip, "--", of)
        if o and not o.returncode and o.stdout:
            c = o.stdout.split(None, 1)[0]  # renamed within the turn: events use the old path
            of = next((l[9:] for l in o.stdout.splitlines() if l.startswith("filename ")), of)
            ev = next((e for e in all_ev
                       if c in (e.get("snapshot"), e.get("commit")) and touches(e)), ev)
    print(f"{f}:{a.line}  {H[:8]}  " + (f"{ev['actor']}"
          + (f" {ev['turn']}" if ev.get("turn") else "") + f"  op {ev['id']}" if ev else "untracked"))
    print("> " + next((l[1:] for l in out.splitlines() if l.startswith("\t")), ""))
    if not ev: return print("no sun operations recorded for this commit")
    if "/agent:" not in ev["actor"]:
        return print(f"human edit ({ev['actor']}): no conversation\n" + json.dumps(ev, indent=2))
    u, sid, tcs = ev["actor"].split("/", 1)[0], ev.get("session_id"), ev.get("tool_calls") or []
    mine = [tc for tc in tcs if of in ((tc.get("input") or {}).get("files")
                                       or [(tc.get("input") or {}).get("file")])]
    tid = next((ed["tool_call_id"] for ed in ev.get("edits") or []
                if ed.get("file") == of and ed.get("tool_call_id")), None) \
        or next((tc["id"] for tc in mine + tcs if tc.get("id")), None)
    hit = next(((stored, ref) for stored, ru, ref in session_rows()
                if ru == u and stored == sid), None)
    if not (tid and hit): return print("no transcript stored for this edit")
    sid, ref = hit
    for n in sorted(git("ls-tree", "-r", "--name-only", ref).splitlines()):
        chunk = git("cat-file", "blob", f"{ref}:{n}")
        if tid in chunk: break
    else: return print(f"tool call {tid} not found in session {sid}")
    prompt, ctx, tool = blame_context(chunk, tid)
    print(f"session {sid} ({n}):")
    if prompt: print(f"user: {prompt.strip()}")
    if ctx: print(f"agent: {ctx.strip()}")
    print(f"[{tool or '?'} {tid}]")
def cmd_undo(a):
    maybe_sync(); actor = local()
    if a.commit is not None:
        H = resolve_history_rev(a.commit)
        parents = git("rev-list", "--parents", "-n1", H).split()[1:]
        if not parents: sys.exit("sun: cannot undo the initial shadow commit")
        patch = git("diff", parents[0], H)
        if quiet("git", "apply", "-R", input=patch).returncode:
            sys.exit(f"sun: cannot revert {H[:8]} cleanly")
        files, pre = changed_files(), history_head()
        c = commit_files(files or ["."], f"sun: undo commit {H[:8]}", actor)
        record(type="undo", actor=actor, commit=c, target_commit=H,
               edits=[{"file": f, "patch": patches(pre, c, files)[f]} for f in files])
        return print(f"sun: undid commit {H[:8]} in {c[:8]}")
    target = next((e for e in reversed(events())
                   if (e["id"] == a.op or not a.op) and e.get("edits")), None)
    if not target: sys.exit("sun: no such operation")
    combined = "".join(ed["patch"] for ed in target["edits"] if ed["patch"].strip())
    if quiet("git", "apply", "-R", input=combined).returncode:  # atomic: all or nothing
        sys.exit(f"sun: cannot undo op {target['id']}: its patch no longer applies cleanly; "
                 "try `sun undo --commit <hash>` instead")
    files, pre = [ed["file"] for ed in target["edits"]], history_head()
    c = commit_files(files, f"sun: undo op {target['id']}", actor)
    record(type="undo", actor=actor, commit=c, target_op=target["id"],
           edits=[{"file": f, "patch": patches(pre, c, files)[f]} for f in files])
    print(f"sun: undid op {target['id']} in {c[:8]}")
def actor_info(actor):
    """Split a stable actor id into fields the visualizations can present."""
    actor = actor or "unknown"
    owner, source = (actor.split("/", 1) + [""])[:2]
    if source.startswith("agent:"):
        harness, _, session = source[6:].partition("/")
        return {"id": actor, "user": owner, "kind": "agent", "harness": harness,
                "session": session}
    return {"id": actor, "user": owner, "kind": "human", "harness": None,
            "session": None}
def actor_label(info):
    if info["kind"] == "agent":
        return {"claude": "Claude Code", "codex": "Codex"}.get(
            info["harness"], info["harness"] or "agent")
    return info["user"] or info["id"]
def display_subject(subject, actors):
    for actor in actors:
        prefix = f"sun: {actor['id']} "
        if subject.startswith(prefix): return subject[len(prefix):]
    return subject[5:] if subject.startswith("sun: ") else subject
def viz_operation(ev):
    methods = sorted({(ed.get("attribution") or {}).get("method")
                      for ed in ev.get("edits") or []
                      if (ed.get("attribution") or {}).get("method")})
    return {"id": ev.get("id"), "type": ev.get("type", "edit"),
            "actor": ev.get("actor", "unknown"),
            "actor_info": actor_info(ev.get("actor", "unknown")),
            "session_id": ev.get("session_id"), "timestamp": ev.get("timestamp"),
            "turn": ev.get("turn"), "pr": ev.get("pr"),
            "target_op": ev.get("target_op"), "target_commit": ev.get("target_commit"),
            "attribution_methods": methods, "tool_calls": ev.get("tool_calls") or [],
            "edits": ev.get("edits") or []}
def viz_data(n=0):
    limit = [f"-{n}"] if n else []
    scope = history_refs()
    log = git("log", *scope, *limit, "--date=iso",
              "--pretty=%H\x1f%h\x1f%P\x1f%D\x1f%ad\x1f%s\x1f%an\x1f%ae\x1f%cn\x1f%ce")
    cols = ["hash", "short", "parents", "refs", "date", "subject", "author_name",
            "author_email", "committer_name", "committer_email"]
    commits = [dict(zip(cols, l.split("\x1f"))) for l in log.splitlines()]
    all_events, by_commit, by_pid = events(), {}, {}
    for ev in all_events:
        by_commit.setdefault(ev.get("commit"), []).append(ev)
        if ev.get("patch_id"): by_pid.setdefault(ev["patch_id"], []).append(ev)
    hash_pids = {}
    if by_pid and any(c["hash"] not in by_commit for c in commits):
        patches_log = git("log", *scope, *limit,
                          "--pretty=format:%H", "-p")
        hash_pids = {H: pid for pid, H in (line.split()[:2] for line in
                     git("patch-id", "--stable", input=patches_log).splitlines())}
    counts = {}
    for commit in commits:
        matched, match = by_commit.get(commit["hash"], []), "commit"
        if not matched:
            pid = hash_pids.get(commit["hash"])
            matched, match = by_pid.get(pid, []), "patch_id" if pid in by_pid else None
        operations = [viz_operation(ev) for ev in matched]
        actor_ids = list(dict.fromkeys(op["actor"] for op in operations))
        commit["git_author"] = {"name": commit.pop("author_name"),
                                "email": commit.pop("author_email")}
        commit["git_committer"] = {"name": commit.pop("committer_name"),
                                   "email": commit.pop("committer_email")}
        commit["attribution"] = {"matched_by": match,
                                 "actors": [actor_info(a) for a in actor_ids]}
        commit["operations"] = operations
        for op in operations:
            counts[op["actor"]] = counts.get(op["actor"], 0) + 1
    actors = [{**actor_info(actor), "operations": count}
              for actor, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]
    return {"commits": commits, "events": all_events, "actors": actors,
            "summary": {"commits": len(commits), "operations": sum(counts.values())}}
def operation_lines(op, prefix=""):
    info = op["actor_info"]
    out = [f"{prefix}operation {op['id']}  {op['type']}",
           f"{prefix}edited by     {actor_label(info)}"]
    if op.get("session_id"): out.append(f"{prefix}session       {op['session_id']}")
    if op.get("turn"): out.append(f"{prefix}turn          {op['turn']}")
    if op.get("timestamp"): out.append(f"{prefix}timestamp     {op['timestamp']}")
    if op.get("target_op"): out.append(f"{prefix}undoes        operation {op['target_op']}")
    if op.get("target_commit"):
        out.append(f"{prefix}undoes        commit {op['target_commit'][:8]}")
    for call in op["tool_calls"]:
        target = (call.get("input") or {}).get("file") or \
                 ", ".join((call.get("input") or {}).get("files") or [])
        out.append(f"{prefix}tool          {call.get('tool', '?')} {call.get('id') or ''}" +
                   (f"  {target}" if target else ""))
    for edit in op["edits"]:
        out.append(f"{prefix}file          {edit.get('file', '?')}" +
                   (f"  tool {edit['tool_call_id']}" if edit.get("tool_call_id") else ""))
        if edit.get("patch"):
            out.extend(prefix + "  " + line for line in edit["patch"].splitlines())
    return out
def commit_lines(commit):
    actors = commit["attribution"]["actors"]
    author, committer = commit["git_author"], commit["git_committer"]
    identity = lambda p: f"{actor_label(actor_info(p['name']))} <{p['email']}>"
    git_identity = identity(author) if author == committer else \
        f"{identity(author)} authored; {identity(committer)} committed"
    out = [f"commit        {commit['hash']}",
           f"subject       {display_subject(commit['subject'], actors)}",
           f"timestamp     {commit['date']}", f"git identity  {git_identity}"]
    if commit["refs"]: out.append(f"refs          {commit['refs']}")
    if actors:
        out.append("attributed to " + ", ".join(actor_label(a) for a in actors))
        if commit["attribution"]["matched_by"] == "patch_id":
            out.append("matched via   patch-id (commit was rewritten)")
    else: out.append("attributed to untracked")
    for op in commit["operations"]:
        out.append("")
        out.extend(operation_lines(op))
    if not commit["operations"]: out.extend(["", "no sun operations recorded for this commit"])
    return out
def _tui_put(screen, y, x, text, width, attr=0):
    try: screen.addnstr(y, x, text.expandtabs(4), max(width, 0), attr)
    except Exception: pass  # terminal resize can invalidate the last row mid-draw
def viz_tui(screen, data):
    import curses
    try: curses.curs_set(0)
    except curses.error: pass
    screen.keypad(True)
    # Preserve the terminal's real theme instead of mapping ANSI black to a palette color.
    if curses.has_colors():
        curses.start_color()
        try: curses.use_default_colors()
        except curses.error: pass
    commits, selected, visible = data["commits"], 0, len(data["commits"])
    detail_scroll, replaying = 0, False
    while True:
        screen.erase(); height, width = screen.getmaxyx()
        if height < 8 or width < 45:
            _tui_put(screen, 0, 0, "sun viz needs a terminal at least 45 x 8", width - 1)
        else:
            first = len(commits) - visible
            selected = min(max(selected, first), max(len(commits) - 1, 0))
            title = (f" sun viz  {data['summary']['commits']} commits  "
                     f"{data['summary']['operations']} operations ")
            _tui_put(screen, 0, 0, title, width - 1, curses.A_REVERSE)
            _tui_put(screen, height - 1, 0,
                     " j/k navigate  J/K details  left/right replay  r autoplay  q quit ",
                     width - 1, curses.A_REVERSE)
            split = max(30, min(52, width * 2 // 5))
            rows = height - 2
            if commits:
                start = max(first, min(selected - rows // 2, len(commits) - rows))
                for y, i in enumerate(range(start, min(len(commits), start + rows)), 1):
                    commit = commits[i]
                    actors = commit["attribution"]["actors"]
                    who = ",".join(actor_label(a) for a in actors) if actors else "untracked"
                    line = f" {commit['short']} {who}  {display_subject(commit['subject'], actors)}"
                    _tui_put(screen, y, 0, line, split - 1,
                             curses.A_REVERSE if i == selected else 0)
                details = commit_lines(commits[selected])
                for y, line in enumerate(details[detail_scroll:detail_scroll + rows], 1):
                    _tui_put(screen, y, split + 1, line, width - split - 2)
                for y in range(1, height - 1): _tui_put(screen, y, split, "│", 1)
            else: _tui_put(screen, 2, 2, "No commits found", width - 4)
        screen.refresh()
        screen.timeout(80 if replaying else -1)
        key = screen.getch()
        if key in (ord("q"), 27): break
        if replaying and key == -1:
            visible = min(len(commits), visible + 1)
            selected = len(commits) - visible
            if visible == len(commits): replaying = False
            continue
        if key in (ord("j"), curses.KEY_DOWN) and commits:
            selected = min(len(commits) - 1, selected + 1); detail_scroll = 0
        elif key in (ord("k"), curses.KEY_UP) and commits:
            selected = max(len(commits) - visible, selected - 1); detail_scroll = 0
        elif key == ord("J") and commits:
            detail_scroll = min(max(0, len(commit_lines(commits[selected])) - (height - 2)),
                                detail_scroll + 1)
        elif key == ord("K"): detail_scroll = max(0, detail_scroll - 1)
        elif key in (curses.KEY_LEFT, ord("h")) and commits:
            visible = max(1, visible - 1); selected = max(selected, len(commits) - visible)
            detail_scroll = 0
        elif key in (curses.KEY_RIGHT, ord("l")) and commits:
            visible = min(len(commits), visible + 1); selected = len(commits) - visible
            detail_scroll = 0
        elif key == ord("r") and commits:
            visible, selected, detail_scroll, replaying = 1, len(commits) - 1, 0, True
def run_viz_tui(data):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        sys.exit("sun: `sun viz` needs an interactive terminal; use `sun viz --html` to export")
    import curses
    curses.wrapper(viz_tui, data)
def write_viz_html(data, out):
    encoded = json.dumps(data).replace("</", "<\\/")
    write_text(out, VIZ.replace("__DATA__", encoded))
    print(f"sun: wrote {out}")
def cmd_viz(a):
    with lock():
        maybe_sync()
        data = viz_data(a.n)
    if getattr(a, "html", False) or a.output:
        return write_viz_html(data, a.output or os.path.join(sun_dir(), "viz.html"))
    run_viz_tui(data)
VIZ = """<!doctype html><meta charset="utf-8"><title>sun viz</title>
<style>body{margin:0;font:12px/1.5 ui-monospace,Menlo,monospace;background:#fff;color:#000}
header{display:flex;gap:12px;align-items:center;flex-wrap:wrap;padding:8px 14px;border-bottom:1px solid #000}#st{margin-left:auto}
main{display:grid;grid-template-columns:1fr 1fr;height:calc(100vh - 40px)}
#c{margin:0;padding:6px 0;list-style:none;overflow:auto;border-right:1px solid #000}
#c li{padding:1px 14px;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#c li:hover{background:#eee}#c li.sel{background:#000;color:#fff}
#d{margin:0;padding:10px 14px;overflow:auto;white-space:pre-wrap}
button,input{font:inherit;background:#fff;border:1px solid #000;accent-color:#000}</style>
<header><b>sun</b><button id=play>replay</button><input type=range id=s min=0><span id=pos></span><span id=st></span></header>
<main><ol id=c></ol><pre id=d>select a commit</pre></main>
<script>const D=__DATA__,cs=D.commits;
const esc=t=>(t||'').replace(/&/g,'&amp;').replace(/</g,'&lt;');
const total=D.summary.operations||1;
st.innerHTML=D.actors.map(a=>`<b>${esc(a.id)}</b> ${a.operations} op${a.operations==1?'':'s'} (${Math.round(100*a.operations/total)}%)`).join(' | ')||'<b>no attributed operations</b>';
c.innerHTML=cs.map(x=>`<li>${x.short} ${x.date.slice(0,10)} ${esc(x.subject)} ${(x.attribution.actors.length?x.attribution.actors:[{id:'untracked'}]).map(a=>`<b>[${esc(a.id)}]</b>`).join('')}</li>`).join('');
const rows=[...c.children];rows.forEach((li,i)=>li.onclick=()=>{rows.forEach(r=>r.classList.remove('sel'));li.classList.add('sel');detail(cs[i]);});
s.max=cs.length;s.value=cs.length;
function cut(){const n=+s.value;pos.textContent=n+'/'+cs.length;rows.forEach((li,i)=>li.style.display=cs.length-1-i<n?'':'none');}
function operation(e,p=''){let i=e.actor_info,o=`${p}operation ${e.id}  ${e.type}\\n${p}generated by  ${e.actor}\\n${p}source        ${i.kind}${i.kind=='agent'?` via ${i.harness}`:''}\\n`;
if(e.session_id)o+=`${p}session       ${e.session_id}\\n`;
if(e.turn)o+=`${p}turn          ${e.turn}\\n`;if(e.timestamp)o+=`${p}observed      ${e.timestamp}\\n`;
if(e.attribution_methods.length)o+=`${p}attribution   ${e.attribution_methods.join(', ')}\\n`;
for(const tc of e.tool_calls){const input=tc.input||{},target=input.file||(input.files||[]).join(', ');o+=`${p}tool          ${tc.tool||'?'} ${tc.id||''}${target?'  '+target:''}\\n`;}
for(const ed of e.edits)o+=`${p}file          ${ed.file||'?'}${ed.tool_call_id?'  tool '+ed.tool_call_id:''}\\n`+(ed.patch||'').split('\\n').filter(Boolean).map(l=>p+'  '+l).join('\\n')+'\\n';return o;}
function detail(x){let actors=x.attribution.actors.map(a=>a.id).join(', ')||'untracked';
let o=`commit        ${x.hash}\\nsubject       ${x.subject}\\ndate          ${x.date}\\ngit author    ${x.git_author.name} <${x.git_author.email}>\\ngit committer ${x.git_committer.name} <${x.git_committer.email}>\\nsun actors    ${actors}\\n`;
if(x.attribution.matched_by=='patch_id')o+='matched via   patch-id (commit was rewritten)\\n';
for(const e of x.operations)o+='\\n'+operation(e);if(!x.operations.length)o+='\\nno sun operations recorded for this commit';d.textContent=o;}
let t=null;play.onclick=()=>{if(t){clearInterval(t);t=null;return}s.value=0;cut();
t=setInterval(()=>{s.value=+s.value+Math.max(1,Math.ceil(cs.length/150));cut();if(+s.value>=cs.length){clearInterval(t);t=null}},80)};
s.oninput=cut;cut();if(rows.length)rows[0].click();</script>
"""
def main(argv=None):
    ap = argparse.ArgumentParser(prog="sun", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    ps = {c: sub.add_parser(c, help=h) for c, h in [
        ("init", "git repo + .git/sun + hooks + session import"), ("sync", "commit pending local edits"),
        ("merge", "join divergent local and shared shadow histories"),
        ("hook", "agent-harness hook entrypoint (JSON on stdin)"), ("show", "show operations for a commit"),
        ("import", "re-import sessions"), ("gc", "drop session refs older than N days"),
        ("sessions", "list/read/export sessions in refs/sun/sessions"), ("log", "git log with actors + turns"),
        ("undo", "undo one operation (default: latest) or a commit"),
        ("viz", "terminal visualization of the op log"),
        ("update", "update sun to the latest version"),
        ("export", "dump history as fine-tuning JSONL (prompt + tool_calls + edits per turn)"),
        ("blame", "the conversation behind a file:line")]}
    ps["init"].add_argument("--claude", action="store_true",
                            help="set up Claude Code only (default: every detected harness)")
    ps["init"].add_argument("--codex", action="store_true",
                            help="set up Codex only (default: every detected harness)")
    ps["init"].add_argument("--share-sessions", dest="share_sessions", action="store_true",
                            default=None, help="share raw transcripts through git refs")
    ps["init"].add_argument("--no-share-sessions", dest="share_sessions", action="store_false")
    ps["init"].add_argument("--instructions", "--claude-md", dest="instructions",
                            action="store_true", default=None)
    ps["init"].add_argument("--no-instructions", "--no-claude-md", dest="instructions",
                            action="store_false")
    ps["hook"].add_argument("--harness", choices=("claude", "codex"), default="claude")
    ps["sessions"].add_argument("id", nargs="?"); ps["sessions"].add_argument("--grep")
    ps["sessions"].add_argument("--file"); ps["gc"].add_argument("--older-than", type=int, required=True)
    ps["log"].add_argument("-n", type=int, default=30); ps["show"].add_argument("commit")
    ps["undo"].add_argument("--op", nargs="?", const="", default=None, metavar="ID")
    ps["undo"].add_argument("--commit", nargs="?", const="HEAD", default=None, metavar="HASH")
    ps["viz"].add_argument("--html", action="store_true", help="export self-contained HTML")
    ps["viz"].add_argument("-o", "--output", default=None,
                            help="HTML output path (implies --html)")
    ps["viz"].add_argument("-n", type=int, default=0)
    ps["export"].add_argument("-o", "--output", default=None)
    ps["blame"].add_argument("file"); ps["blame"].add_argument("line", type=int)
    a = ap.parse_args(argv)
    commands = {
        "init": cmd_init, "hook": cmd_hook, "sync": cmd_sync, "merge": cmd_merge,
        "log": cmd_log, "show": cmd_show, "undo": cmd_undo, "viz": cmd_viz,
        "import": cmd_import, "sessions": cmd_sessions, "gc": cmd_gc,
        "update": cmd_update, "export": cmd_export, "blame": cmd_blame,
    }
    if a.cmd not in ("init", "hook", "update"):  # hook locates its repo from the payload
        if a.cmd == "blame": a.file = os.path.abspath(a.file)  # resolve before the chdir
        os.chdir(root())
        sun_dir()
        if a.cmd == "viz":
            commands[a.cmd](a)
        else:
            with lock():
                commands[a.cmd](a)
    else:
        commands[a.cmd](a)
if __name__ == "__main__":
    main()
