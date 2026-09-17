#!/usr/bin/env python3
"""Record human and agent edits in an independent Git-backed operation history.

Each Git branch has its own Sun history. Unpublished, non-interleaved agent calls are grouped
per turn while remaining individually inspectable and undoable. Fetch does not move your local
Sun tip; use `sun merge` to combine shared history. Normal Git commits and the index stay intact.
Raw transcripts are shared only when you explicitly enable session sharing."""
import argparse, difflib, fcntl, glob, json, os, re, shutil, subprocess, sys
import time, uuid
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
    branch: str
    sequence: int


class TurnState(TypedDict, total=False):
    n: int
    start: str
    transcript: str
    toffset: int
    soffset: int
    seen: int
    stopped: bool
    squashed: bool
    branch: str


class ActiveCall(TypedDict, total=False):
    files: List[str]
    id: str
    branch: str
    pre: str
    turn: int
    all_files: bool
    overlap: List[str]
    ambiguous_actor: bool
    actor: str


READ_TOOLS = {"Read", "Glob", "Grep", "LS", "WebFetch", "WebSearch", "view_image"}
HOOK_EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
               "PostToolUseFailure", "Stop", "SessionEnd")
CODEX_HOOK_EVENTS = tuple(e for e in HOOK_EVENTS if e != "PostToolUseFailure") + (
    "SubagentStart", "SubagentStop", "Interrupt")
CLAUDE_LINE = CODEX_LINE = (
    "Use `sun data` for attributed history and session paths. Your sessions stay in their "
    "native harness directories; only collaborators' shared sessions are cached in "
    ".git/sun/sessions/. Read the returned session path instead of guessing a location.")
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
    return {f: git("--literal-pathspecs", "diff", "--binary", pre, post, "--", f) for f in files}


def changed_files():
    tip, ix = history_head(False), shadow_index()
    env = {**os.environ, "GIT_INDEX_FILE": ix}
    if os.path.exists(ix): os.remove(ix)
    if tip: git("read-tree", tip, env=env)
    else: git("read-tree", "--empty", env=env)
    quiet("git", "update-index", "--refresh", env=env)
    tracked = (git("-c", "core.quotepath=false", "-c", "diff.renames=false",
                   "diff-index", "--name-only", "-z", tip, "--", env=env).split("\0") if tip else [])
    untracked = git("-c", "core.quotepath=false", "ls-files", "--others",
                    "--exclude-standard", "-z", env=env).split("\0")
    return list(dict.fromkeys(f for f in tracked + untracked if f))
def patch_id(commit):
    output = git("patch-id", "--stable", check=False,
                 input=git("show", "--format=", commit, check=False))
    return (output.split() or [None])[0]


def blob(data):
    return subprocess.run(["git", "hash-object", "-w", "--stdin"],
                          input=data.encode() if isinstance(data, str) else data,
                          capture_output=True, check=True).stdout.decode().strip()


def refs(prefix):  # [(refname, sha)]
    output = git("for-each-ref", "--format=%(refname)\t%(objectname)", prefix, check=False)
    return [line.split("\t") for line in output.splitlines()]


def sun_dir(must=True):  # per-worktree hook state; shared history lives in Git refs
    key = (os.getcwd(), "sun-dir")
    if key not in _r: _r[key] = os.path.join(git("rev-parse", "--absolute-git-dir").strip(), "sun")
    d = _r[key]
    if must and not os.path.isdir(d): sys.exit("sun: not initialized here (run `sun init`)")
    return d
def jread(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as exc:
        sys.exit(f"sun: cannot read {path}: {exc}")


def jwrite(path, obj):
    with open(path + ".tmp", "w") as f:
        json.dump(obj, f, indent=1)
    os.replace(path + ".tmp", path)


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
def shadow_ref():
    branch = git("symbolic-ref", "-q", "--short", "HEAD", check=False).strip()
    if not branch: sys.exit("sun: detached HEAD is not supported; switch to a branch first")
    return "refs/sun/heads/" + branch
def remote_ref():
    return shadow_ref().replace("refs/sun/heads/", "refs/sun/remotes/origin/")
def check_format():
    if state("config.json", {}).get("format") != 2 and (refs("refs/sun/log/") or
            os.path.exists(os.path.join(sun_dir(), "events.jsonl"))):
        sys.exit("sun: legacy event-log format; this build requires a separate history migration. "
                 "Existing history has not been changed")
def ensure_branch():
    """Follow the checked-out Git branch, without mistaking checkout changes for edits."""
    check_format()
    ref, normal = shadow_ref(), ref_oid("HEAD")
    previous = state("branch.json", {})
    anchors = state("branches.json", {})
    tip = history_head(False)
    if not tip:
        source = previous.get("ref") if previous.get("git") == normal else None
        tip = ref_oid(source) if source else ""
        if tip: git("update-ref", ref, tip)
        else:
            # A freshly cloned branch starts at its Git checkout, not the possibly newer
            # remote Sun tree. Import the remote lineage only when the trees agree.
            remote = ref_oid(remote_ref())
            tree = ref_oid(f"{normal}^{{tree}}") if normal else git("mktree", input="").strip()
            if remote and ref_oid(f"{remote}^{{tree}}") == tree:
                git("update-ref", ref, remote)
            else:
                c = make_shadow_commit(tree, "sun: initial state", local())
                record(type="init", actor=local(), commit=c, edits=[])
    switched = previous.get("ref") not in (None, ref)
    old = previous.get("git") if switched else anchors.get(ref)
    committed = not switched and old != normal and git(
        "reflog", "-1", "--format=%gs", "HEAD", check=False).startswith("commit")
    # A user's ordinary commit does not erase the dirty diff Sun still needs to record.
    if committed: old = normal
    if old and normal and old != normal:
        if not switched and quiet("git", "merge-base", "--is-ancestor", old, normal).returncode:
            sys.exit("sun: Git history was rewritten; automatic Sun reconciliation is unsupported")
        tip = history_head()
        result = quiet("git", "merge-tree", "--write-tree", f"--merge-base={old}", tip, normal)
        if result.returncode:
            sys.exit("sun: Git checkout conflicts with recorded Sun edits; reconcile before recording")
        tree = result.stdout.splitlines()[0]
        if tree != ref_oid(f"{tip}^{{tree}}"):
            remote = ref_oid(remote_ref())
            shared = quiet("git", "merge-tree", "--write-tree", "--allow-unrelated-histories",
                           tip, remote) if remote else None
            merged = shared and not shared.returncode and shared.stdout.splitlines()[0] == tree
            parents = [tip, remote] if merged and remote != tip else [tip]
            kind = "merge" if len(parents) == 2 else "checkout"
            c = make_shadow_commit(tree, f"sun: Git {kind} baseline", local(), parents)
            record(type=kind, actor=local(), commit=c, edits=[])
    anchors[ref] = normal
    save_state("branches.json", anchors)
    save_state("branch.json", {"ref": ref, "git": normal})
def history_head(required=True):
    oid = ref_oid(shadow_ref())
    if required and not oid: sys.exit("sun: shadow history has no commits (run `sun init`)")
    return oid
def history_refs():
    return [r for r in (shadow_ref(), remote_ref()) if ref_oid(r)]
def resolve_history_rev(rev):
    if rev == "HEAD": rev = shadow_ref()
    return git("rev-parse", rev).strip()
def shadow_index():
    return os.path.join(sun_dir(), "shadow-index")
def make_shadow_commit(tree, message, author, parents=()):
    ident = {**os.environ, "GIT_AUTHOR_NAME": author, "GIT_AUTHOR_EMAIL": "sun@sun",
             "GIT_COMMITTER_NAME": author, "GIT_COMMITTER_EMAIL": "sun@sun"}
    args = ["-c", "commit.gpgsign=false", "commit-tree", tree]
    for parent in parents: args += ["-p", parent]
    return git(*args, "-m", message, env=ident).strip()
def commit_files(files, message, author):
    """Snapshot files into an independent commit graph without touching HEAD or the real index."""
    parent, ix = history_head(False), shadow_index()
    if os.path.exists(ix): os.remove(ix)
    env = {**os.environ, "GIT_INDEX_FILE": ix}
    if parent: git("read-tree", parent, env=env)
    else: git("read-tree", "--empty", env=env)
    git("--literal-pathspecs", "add", "-A", "--", *files, env=env)
    tree = git("write-tree", env=env).strip()
    commit = make_shadow_commit(tree, message, author, [parent] if parent else [])
    # record() publishes this commit and its attribution in one Git ref transaction.
    return commit
def parse_events(text: str) -> List[Event]:  # skips torn lines rather than bricking every command
    out: List[Event] = []
    for l in text.splitlines():
        try: out.append(json.loads(l))
        except ValueError: pass
    return out
def events(include_unreachable=False) -> List[Event]:
    entries = refs("refs/sun/events/")
    if not entries: return []
    data = subprocess.run(["git", "cat-file", "--batch"],
                          input="".join(sha + "\n" for _, sha in entries).encode(),
                          capture_output=True, check=True).stdout
    evs, pos = [], 0
    while pos < len(data):
        end = data.index(b"\n", pos)
        size = int(data[pos:end].split()[-1])
        ev = json.loads(data[end + 1:end + 1 + size])
        if not re.fullmatch(r"[0-9a-f]{32}", ev.get("id", "")) or \
                entries[len(evs)][0] != f"refs/sun/events/{ev['id']}":
            sys.exit("sun: invalid operation ID in fetched history")
        evs.append(ev)
        pos = end + size + 2
    scope = history_refs()
    order = {c: i for i, c in enumerate(git("rev-list", "--topo-order", "--reverse",
                                            *scope).split())} if scope else {}
    # Git ancestry orders causes before effects. Concurrent branches have no total time order.
    return sorted((e for e in evs if e.get("commit") in order or
                   include_unreachable and e.get("branch") == shadow_ref()),
                  key=lambda e: (order.get(e["commit"], len(order)), e.get("sequence", 0), e["id"]))
def lock():
    common = git("rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    lk = open(os.path.join(common, "sun.lock"), "a")
    fcntl.flock(lk, fcntl.LOCK_EX)
    return lk  # closing the file releases the lock
def publish(commit, evs, before=None):
    if before is None:
        parents = git("rev-list", "--parents", "-n1", commit).split()[1:]
        before = parents[0] if parents else ""
    updates = [f"update {shadow_ref()} {commit} {before or '0' * len(commit)}"]
    for ev in evs:
        ref = f"refs/sun/events/{ev['id']}"
        updates.append(f"update {ref} {blob(json.dumps(ev))} {ref_oid(ref) or '0' * len(commit)}")
        snapshot = ev.get("snapshot", commit)
        updates.append(f"update refs/sun/ops/{snapshot} {snapshot}")
    git("update-ref", "--stdin", input="start\n" + "\n".join(dict.fromkeys(updates)) +
        "\nprepare\ncommit\n")
def record_batch(commit, entries):
    evs = [{"id": uuid.uuid4().hex, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "sequence": i, "commit": commit, "branch": shadow_ref(), **e} for i, e in enumerate(entries)]
    publish(commit, evs)
    return evs
def record(**ev: Any) -> Event:
    return record_batch(ev["commit"], [ev])[0]
def store_chunks(sid, files, u=None):  # {path: text} -> refs/sun/sessions/<u>/<sid> tree
    if not files: return
    ref, ix = f"refs/sun/sessions/{u or user()}/{sid}", os.path.join(sun_dir(), "tmpindex")
    env = {**os.environ, "GIT_INDEX_FILE": ix}
    if os.path.exists(ix): os.remove(ix)
    if not quiet("git", "rev-parse", "-q", "--verify", ref).returncode:
        git("read-tree", ref, env=env)
    git("update-index", "--index-info", env=env,
        input="".join(f"100644 blob {blob(c)}\t{p}\n" for p, c in files.items()))
    parent = ref_oid(ref)
    args = ["commit-tree", git("write-tree", env=env).strip(), "-m", sid]
    if parent: args += ["-p", parent]
    commit = git(*args).strip()
    git("update-ref", ref, commit, parent or "0" * len(commit))
_u = {}
def user():  # the git user on whose machine the change happened; owns every event
    _u or _u.setdefault("u", (git("config", "user.name", check=False).strip()
                              or os.environ.get("USER", "unknown")).replace(" ", "-").lower())
    return _u["u"]
local = lambda u=None: f"{u or user()}/local"
agent = lambda sid, harness="claude", u=None: f"{u or user()}/agent:{harness}/{sid}"
session_key = lambda sid, harness="claude": sid if harness == "claude" else f"{harness}/{sid}"
call_key = lambda sid, payload, harness="claude": \
    f"{session_key(sid, harness)}/{payload.get('tool_use_id') or ''}"
tool_file = lambda inp: inp.get("file_path") or inp.get("notebook_path")
rel_to_root = lambda path: os.path.relpath(os.path.abspath(path), root())
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
def sync(exclude=(), method="sync"):  # commit unclaimed changes as local
    if state("merge.json", {}): sys.exit("sun: finish or abort the Sun merge before recording")
    active = state("active.json", {})
    if any(s.get("all_files") for s in active.values()): return
    exclude = set(exclude) | {f for s in active.values() for f in s["files"]}
    files = [f for f in changed_files() if f not in exclude]
    if not files: return None
    pre, actor = history_head(), "unknown" if method == "uncertain" else local()
    c = commit_files(files, edits_msg(actor, files), actor)
    p = patches(pre, c, files)
    return record(type="edit", actor=actor, commit=c, patch_id=patch_id(c),
                  edits=[{"file": f, "patch": p[f],
                          "attribution": {"method": method}} for f in files])
def maybe_sync(exclude=()):
    sync(exclude)  # sync itself excludes in-flight files and unknown-scope shell calls
def finish_call(sid, active: Dict[str, ActiveCall], payload, harness="claude"):
    key = call_key(sid, payload, harness)
    if key not in active: key = call_key(sid, {}, harness)
    st = active.get(key)
    if not st: return  # duplicate completion, or no observed pre-call boundary
    others = {f for k, s in active.items() if k != key for f in s["files"]}
    def release():
        active.pop(key, None)
        save_state("active.json", active)
    if st.get("branch") != shadow_ref():
        print("sun: branch changed during tool call; attribution unavailable", file=sys.stderr)
        release()
        return
    # Retrying after a crash between the ref transaction and claim cleanup is harmless.
    if st.get("id") and ref_oid(f"refs/sun/events/{st['id']}"):
        release()
        return
    files = [f for f in changed_files() if f not in others or f in st.get("overlap", [])]
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
    actor, pre = st["actor"], history_head()
    turn = st.get("turn", 0)
    c = commit_files(files, f"sun: {actor} {tool}" if a_files else edits_msg(local(), files),
                     actor if a_files else local())
    p = patches(pre, c, files)
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
                       patch_id=patch_id(c), tool_calls=[call], edits=[
                           {"file": f, "patch": p[f], "tool_call_id": call["id"],
                            "attribution": {"method": method}} for f in group]))
    if h_files:
        entries.append(dict(type="edit", actor=local(),
               edits=[{"file": f, "patch": p[f],
                       "attribution": {"method": "hook"}} for f in h_files]))
    if entries: entries[0]["id"] = st["id"]
    record_batch(c, entries)
    release()
def squash_turn(sid, harness="claude"):
    # Stop: squash the turn's agent calls and intervening local edits into one turn commit.
    # A different agent or an already-aggregated commit remains a hard boundary.
    t = state("turns.json", {}).get(session_key(sid, harness))
    tip = history_head()
    if not t or t.get("branch") != shadow_ref() or t.get("squashed") or \
            quiet("git", "merge-base", "--is-ancestor", t["start"], tip).returncode: return
    start, actor = t["start"], agent(sid, harness)
    rng = git("rev-list", f"{start}..{tip}").split()
    published = [sha for _, sha in refs("refs/sun/published/")] + [ref_oid(remote_ref())]
    if any(p and not quiet("git", "merge-base", "--is-ancestor", c, p).returncode
           for p in published for c in rng): return
    ops = [e for e in events() if e.get("commit") in rng]
    mine = [e for e in ops if e["actor"] == actor]
    allowed = {actor, local()}
    raw = [e for e in ops if e.get("type") == "edit" and e["actor"] in allowed
           and not e.get("snapshot")]
    if not rng or not mine or len(raw) != len(ops) or set(rng) - {e["commit"] for e in raw}:
        return
    # Rewriting the turn removes these commits from the main shadow lineage. Keep every
    # operation snapshot, including intervening human edits, reachable and shareable.
    # commit-tree + update-ref never touch the worktree/index: edits after the last call stay dirty
    c = make_shadow_commit(git("rev-parse", f"{tip}^{{tree}}").strip(),
                           f"sun: {actor} turn {t['n']} ({len(mine)} tool calls)",
                           actor, [start])
    turn_pid = patch_id(c)
    revisions = [{**e, "commit": c, "snapshot": e["commit"], "sequence": i,
                  "patch_id": turn_pid} for i, e in enumerate(ops)]
    publish(c, revisions, tip)
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
            t.pop("squashed", None)
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
    if p.returncode or not os.path.isdir(sun_dir(False)):
        return  # not a sun repo; hooks must never break the harness
    os.chdir(p.stdout.strip())
    with lock():  # serialize concurrent hooks (parallel sessions/subagents)
        ensure_branch()
        handle_hook(a, payload)


def handle_hook(a, payload):
    event, sid, harness = (payload.get("hook_event_name", ""),
                           payload.get("session_id", "?"), a.harness)
    tp = payload.get("transcript_path")
    sub, subpath = payload.get("agent_id"), payload.get("agent_transcript_path")
    if tp or (sub and subpath):
        paths = state("session-paths.json", {})
        entry = paths.setdefault(session_key(sid, harness),
                                 {"id": sid, "harness": harness, "path": None, "subagents": {}})
        if tp: entry["path"] = os.path.abspath(tp)
        if sub and subpath: entry["subagents"][sub] = os.path.abspath(subpath)
        save_state("session-paths.json", paths)
    active: Dict[str, ActiveCall] = state("active.json", {})
    if event in ("SessionStart", "UserPromptSubmit", "Stop", "SessionEnd", "Interrupt"):
        prefix = session_key(sid, harness) + "/"
        stale = [key for key in active if key.startswith(prefix)]
        for key in stale: active.pop(key)
        if stale:
            save_state("active.json", active)
            sync(method="uncertain")
    if event == "UserPromptSubmit" and not state("turns.json", {}).get(
            session_key(sid, harness), {}).get("stopped"):  # Stop never fired:
        squash_turn(sid, harness)  # squash the turn + store its transcript slice
        stop_chunk(sid, payload, harness)
    elif event == "PreToolUse": prompt_boundary(sid, payload, harness)
    if event in ("SessionStart", "SubagentStart", "UserPromptSubmit", "PreToolUse"):
        sync(method="hook")  # everything dirty before an agent tool runs is local
    if event == "SessionStart":  # stdout lands in the agent's context
        if not cfg_share_sessions(): return
        export_sessions()
        print("sun: " + CLAUDE_LINE)
    elif event == "SubagentStart":
        if not cfg_share_sessions(): return
        print("sun: " + CLAUDE_LINE)
    elif event == "UserPromptSubmit":
        turns, tp = state("turns.json", {}), payload.get("transcript_path", "")
        key = session_key(sid, harness)
        turns[key] = {"n": turns.get(key, {}).get("n", 0) + 1, "start": history_head(),
                      "transcript": tp, "branch": shadow_ref(),
                      "toffset": os.path.getsize(tp) if os.path.exists(tp) else 0}
        save_state("turns.json", turns)
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
                    session_key(sid, harness) + "/"):
                other["ambiguous_actor"] = ambiguous_actor = True
        active[key] = {"files": files, "all_files": broad, "overlap": sorted(overlap),
                       "ambiguous_actor": ambiguous_actor,
                       "id": uuid.uuid4().hex,
                       "actor": agent(sid, harness),
                       "branch": shadow_ref(), "pre": history_head(),
                       "turn": state("turns.json", {}).get(session_key(sid, harness), {}).get("n", 0)}
        save_state("active.json", active)
    elif event in ("PostToolUse", "PostToolUseFailure"):
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
    chunks, cur, seen = [], [], False
    for line in read_text(path, errors="replace").splitlines(keepends=True):
        if prompt_line(line):
            if seen: chunks.append("".join(cur)); cur = []
            seen = True
        cur.append(line)
    if cur: chunks.append("".join(cur))
    return chunks
def scan_codex_transcript(path):
    lines = read_text(path, errors="replace").splitlines(keepends=True)
    kinds = [prompt_line(line, "codex") for line in lines]
    boundary = 3 if 3 in kinds else 1 if 1 in kinds else 2
    chunks, cur, seen = [], [], False
    for line, kind in zip(lines, kinds):
        if kind == boundary:
            if seen: chunks.append("".join(cur)); cur = []
            seen = True
        cur.append(line)
    if cur: chunks.append("".join(cur))
    return chunks
def scan_transcript(path, harness="claude"):
    return scan_claude_transcript(path) if harness == "claude" else scan_codex_transcript(path)
def do_import(harnesses=("claude",)):
    if not cfg_share_sessions():
        return "session sharing disabled; transcripts remain in their native harness directories"
    t0, seen, ns, nsub = time.time(), state("imported.json", {}), 0, 0
    for harness in harnesses:
        for path, sid, sub in transcript_sources(harness):
            st = os.stat(path)
            if seen.get(path) == [st.st_size, int(st.st_mtime)]:
                continue  # idempotent: only new/changed transcripts are re-read
            chunks = scan_transcript(path, harness)
            pre = f"subagents/{sub}/" if sub else ""
            store_chunks(sid, {f"{pre}turn-{i:04d}.jsonl": c for i, c in enumerate(chunks, 1)})
            seen[path] = [st.st_size, int(st.st_mtime)]
            ns, nsub = ns + (not sub), nsub + bool(sub)
    save_state("imported.json", seen)
    return f"stored {ns} sessions, {nsub} subagents in {time.time() - t0:.1f}s"
session_rows = lambda: [(r.split("/", 4)[4], r.split("/")[3], r)  # (sid, user, ref)
                        for r, _ in refs("refs/sun/sessions/")]
def session_text(ref, sub=None):
    pre = f"subagents/{sub}/" if sub else ""
    names = sorted(n for n in git("ls-tree", "-r", "--name-only", ref).splitlines()
                   if n.startswith(pre) and n.count("/") == pre.count("/"))
    return "".join(git("cat-file", "blob", f"{ref}:{n}") for n in names)
def session_export_dir(): return os.path.join(sun_dir(), "sessions", enc(root()))
def session_data():
    base, owner = session_export_dir(), user()
    local_paths = state("session-paths.json", {})
    for harness in ("claude", "codex"):
        for path, sid, sub in transcript_sources(harness):
            entry = local_paths.setdefault(session_key(sid, harness),
                         {"id": sid, "harness": harness, "path": None, "subagents": {}})
            if sub: entry["subagents"][sub] = os.path.abspath(path)
            else: entry["path"] = os.path.abspath(path)
    # Older installs already recorded native paths in their turn state.
    for key, turn in state("turns.json", {}).items():
        harness, sid = key.split("/", 1) if "/" in key else ("claude", key)
        if turn.get("transcript") and key not in local_paths:
            local_paths[key] = {"id": sid, "harness": harness,
                               "path": os.path.abspath(turn["transcript"]), "subagents": {}}
    idx = [{**entry, "user": owner, "origin": "local", "ref": None}
           for entry in local_paths.values()]
    for entry in idx:
        if entry["path"] and not os.path.isfile(entry["path"]): entry["path"] = None
        entry["subagents"] = {s: p for s, p in entry["subagents"].items() if os.path.isfile(p)}
    for sid, u, ref in session_rows():
        if u == owner:
            # Remove the old materialized copy, never the native transcript.
            legacy = os.path.join(base, sid)
            if os.path.isfile(legacy + ".jsonl"): os.remove(legacy + ".jsonl")
            shutil.rmtree(os.path.join(legacy, "subagents"), ignore_errors=True)
            try: os.rmdir(legacy)
            except OSError: pass
            matches = [entry for entry in idx if entry["id"] == sid]
            if not matches:
                matches = [{"id": sid, "harness": None, "user": u, "origin": "local",
                            "path": None, "subagents": {}}]
                idx.extend(matches)
            for entry in matches: entry["ref"] = ref
            continue
        dest = os.path.join(base, u)
        os.makedirs(dest, exist_ok=True)
        fp = os.path.join(dest, sid + ".jsonl")
        write_text(fp, session_text(ref))
        subs = {}
        for sub in sorted({n.split("/")[1] for n in git("ls-tree", "-r", "--name-only", ref)
                           .splitlines() if n.startswith("subagents/")}):
            subdir = os.path.join(dest, sid, "subagents")
            os.makedirs(subdir, exist_ok=True)
            subs[sub] = os.path.join(subdir, sub + ".jsonl")
            write_text(subs[sub], session_text(ref, sub))
        idx.append({"id": sid, "user": u, "harness": None, "path": fp,
                    "subagents": subs, "origin": "team", "ref": ref})
    return idx

def export_sessions():
    idx = session_data()
    os.makedirs(session_export_dir(), exist_ok=True)
    jwrite(os.path.join(session_export_dir(), "sessions-index.json"), idx)
    return len(idx)
def cmd_sessions(a):
    if a.session_cmd == "import":
        if not cfg_share_sessions():
            sys.exit("sun: session sharing is disabled; run `sun init --share-sessions`")
        return print("sun: " + do_import(configured_harnesses()))
    if a.session_cmd == "export":
        return print(f"sun: exported {export_sessions()} sessions to .git/sun/sessions/")
    if a.session_cmd == "prune":
        if a.older_than < 0: sys.exit("sun: --older-than must be zero or greater")
        prefix = f"refs/sun/sessions/{user()}/"
        cutoff = time.time() - a.older_than * 86400
        old = [r for r, sha in refs(prefix)
               if int(git("show", "-s", "--format=%ct", sha).strip()) < cutoff]
        if a.remote and old:
            if "origin" not in git("remote", check=False).split():
                sys.exit("sun: cannot prune remote sessions without an origin remote")
            git("push", "--no-verify", "origin", "--delete", *old)
        for ref in old:
            git("update-ref", "-d", ref)
            sid = ref[len(prefix):]
            try: os.remove(os.path.join(session_export_dir(), sid + ".jsonl"))
            except FileNotFoundError: pass
            shutil.rmtree(os.path.join(session_export_dir(), sid), ignore_errors=True)
        if os.path.isdir(session_export_dir()): export_sessions()
        where = "local and remote" if a.remote else "local"
        return print(f"sun: pruned {len(old)} {where} session refs; "
                     "Git may garbage-collect their objects later")
    rows = session_rows()
    if a.session_cmd == "show":
        matches = [row for row in rows if row[0] == a.id] or \
                  [row for row in rows if row[0].startswith(a.id)]
        if not matches: sys.exit("sun: no such session")
        if len(matches) > 1: sys.exit("sun: session prefix is ambiguous; use more of the ID")
        return print(session_text(matches[0][2]), end="")
    pat = a.grep
    for sid, u, ref in rows:
        text = session_text(ref)
        if pat and not re.search(pat, text): continue
        if a.contains and a.contains not in text: continue
        count = len(git("ls-tree", "-r", "--name-only", ref).splitlines())
        print(f"{sid}  {u}  {count} transcript chunks")
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
    evs, merged = events(), {}
    for e in evs:
        if e.get("type") not in ("edit", "undo", "restore") or not e.get("edits"): continue
        key = (e["actor"], e.get("session_id"), e["turn"]) if e.get("turn") else e["id"]
        m = merged.setdefault(key, {**e, "tool_calls": e.get("tool_calls", [])[:],
                                    "edits": e["edits"][:]})
        if m["id"] != e["id"]: m["tool_calls"] += e.get("tool_calls", []); m["edits"] += e["edits"]
    out = open(a.output, "w") if a.output else sys.stdout
    for e in merged.values():
        sid, prompt = e.get("session_id"), None
        tid = next((tc.get("id") for tc in e["tool_calls"] if tc.get("id")), None)
        hit = sid and operation_transcript(e, tid)
        if hit: prompt = chunk_prompt(hit[1])
        out.write(json.dumps({"timestamp": e["timestamp"], "actor": e["actor"], "session": sid,
                              "turn": e.get("turn"), "prompt": prompt,
                              "tool_calls": e["tool_calls"],
                              "edits": [{"file": d["file"], "patch": d["patch"] or git(
                                  "show", "--format=", e.get("commit") or "", "--", d["file"],
                                  check=False)} for d in e["edits"]]}) + "\n")
    if a.output: out.close(); print(f"sun: exported to {a.output}")
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
    specs = ["refs/sun/events/*:refs/sun/events/*", "refs/sun/ops/*:refs/sun/ops/*",
             "+refs/sun/heads/*:refs/sun/remotes/origin/*"]
    return specs + (["+refs/sun/sessions/*:refs/sun/sessions/*"] if share_sessions else [])
def install_push(share_sessions=False):
    if "origin" in git("remote", check=False).split():
        for old in ("+refs/sun/*:refs/sun/*", "+refs/sun/sessions/*:refs/sun/sessions/*",
                    "+refs/sun/heads/*:refs/sun/heads/*", "+refs/sun/log/*:refs/sun/log/*",
                    "+refs/sun/ops/*:refs/sun/ops/*"):
            git("config", "--fixed-value", "--unset-all", "remote.origin.fetch", old, check=False)
        current = git("config", "--get-all", "remote.origin.fetch", check=False).splitlines()
        for spec in refspecs(share_sessions):
            if spec not in current: git("config", "--add", "remote.origin.fetch", spec)
    hp = git("rev-parse", "--git-path", "hooks/pre-push").strip()
    os.makedirs(os.path.dirname(hp), exist_ok=True)
    old = read_text(hp) if os.path.exists(hp) else ""
    legacy = ('#!/bin/sh\n# sun: mirror op log + sessions, fail-soft\n'
              'git push --no-verify "$1" "+refs/sun/*:refs/sun/*" >/dev/null 2>&1 || true\n')
    managed = old == legacy or any(old.startswith(f'#!/bin/sh\n{marker}\n') for marker in (
        '# sun: mirror shared refs', '# sun: mirror shared refs, fail-soft'))
    if not old or managed:
        lines = ['#!/bin/sh', '# sun: mirror shared refs', 'exec sun push "$1"']
        write_text(hp, "\n".join(lines) + "\n")
        os.chmod(hp, 0o755)
    else:
        print("sun: existing pre-push hook preserved; run `sun push` to publish Sun history")
def cmd_push(a):
    # The common Git lock prevents Stop from rewriting anything while publication runs.
    specs = ["refs/sun/heads/*:refs/sun/heads/*", "refs/sun/events/*:refs/sun/events/*",
             "refs/sun/ops/*:refs/sun/ops/*"]
    if cfg_share_sessions() and refs(f"refs/sun/sessions/{user()}/"):
        specs.append(f"refs/sun/sessions/{user()}/*:refs/sun/sessions/{user()}/*")
    # Mark first: even an interrupted push with an unknown outcome must not be squashed.
    for ref, sha in refs("refs/sun/heads/"):
        git("update-ref", ref.replace("refs/sun/heads/", "refs/sun/published/"), sha)
    git("push", "--atomic", "--no-verify", "--", a.remote, *specs)
def agent_instructions(harnesses, choice, flags=""):  # one prompt covering every harness file
    todo = []
    for h in harnesses:
        name, line = ("CLAUDE.md", CLAUDE_LINE) if h == "claude" else ("AGENTS.md", CODEX_LINE)
        p = os.path.join(root(), name)
        cur = read_text(p) if os.path.exists(p) else ""
        old = re.compile(r"^Past sessions for this repo, yours and other team members', are in "
                         r"\.git/sun/sessions/ .*Look there instead of .*\.$", re.M)
        cleaned = old.sub(line, cur)
        if cleaned != cur:
            todo.append((p, cleaned, None, name))
        elif line not in cur: todo.append((p, cur, line, name))
    if not todo: return
    if choice is None and sys.stdin.isatty():
        choice = input(f"sun: add one line to {'/'.join(t[3] for t in todo)} so agents find "
                       "team sessions? [Y/n] ").strip().lower() != "n"
    if choice:
        for p, cur, line, _ in todo:
            if line is None: write_text(p, cur)
            else: write_text(p, ("\n" if cur and not cur.endswith("\n") else "") + line + "\n", "a")
    else:
        print(f"sun: run `sun init{flags} --instructions` later to enable team session sharing")
def cmd_init(a):
    if quiet("git", "rev-parse", "--git-dir").returncode: sh("git", "init", "-q")
    os.makedirs(sun_dir(False), exist_ok=True)
    with lock():
        init_locked(a)
def init_locked(a):
    check_format()
    explicit = [h for h, f in (("claude", a.claude), ("codex", a.codex)) if f]
    harnesses = explicit or detect_harnesses()
    cfg = state("config.json", {}); cfg.pop("harness", None)
    cfg["format"] = 2
    cfg["harnesses"] = harnesses
    cfg.pop("shadow_history", None)
    save_state("config.json", cfg)
    share_sessions = configure_session_sharing(a.share_sessions)
    if "origin" in git("remote", check=False).split():  # fresh clone: fetch team refs
        git("fetch", "-q", "origin", *refspecs(share_sessions))
    installed = ", ".join(install_hooks(h) for h in harnesses); install_push(share_sessions)
    for h in ("claude", "codex"):
        if explicit and h not in explicit: remove_hooks(h)
    if share_sessions:
        agent_instructions(harnesses, a.instructions, "".join(" --" + h for h in explicit))
    if not history_head(False):
        c = commit_files(["."], "sun: initial state", local())
        remote, tree = ref_oid(remote_ref()), ref_oid(f"{c}^{{tree}}")
        matches = [line.split()[0] for line in git("log", remote, "--format=%H %T").splitlines()
                   if line.split()[1] == tree] if remote else []
        if matches: git("update-ref", shadow_ref(), matches[0])
        else: record(type="init", actor=local(), commit=c, edits=[])
    ensure_branch()
    sync()
    print(f"sun: initialized {root()} (hooks: {installed}); {do_import(harnesses)}")
    if "codex" in harnesses:
        print("sun: Codex requires separate hook approval; open `/hooks`, review "
              "`.codex/hooks.json`, and trust the Sun hooks before testing")
    print("run `sun viz` to explore your attributed history")
def cmd_sync(a):
    if a.recover: save_state("active.json", {})
    ev = sync(method="uncertain" if a.recover else "sync")
    print(f"sun: recorded edits as op {ev['id']}" if ev else "sun: nothing to sync")
def cmd_merge(a):
    if state("active.json", {}): sys.exit("sun: wait for active tool calls before merging")
    pending = state("merge.json", {})
    if a.abort:
        if not pending: sys.exit("sun: no Sun merge in progress")
        if pending["branch"] != shadow_ref(): sys.exit("sun: return to the branch with the pending merge")
        patch = git("diff", "--binary", pending["tree"], pending["local"])
        apply_checked(patch, False, "sun: merge files have changed; preserve your resolution before aborting")
        save_state("merge.json", {})
        return print("sun: merge aborted")
    if a.continue_merge:
        if not pending or pending["branch"] != shadow_ref(): sys.exit("sun: no Sun merge on this branch")
        if history_head() != pending["local"]:
            parents = git("rev-list", "--parents", "-n1", history_head()).split()[1:]
            if parents == [pending["local"], pending["remote"]]:
                save_state("merge.json", {})
                return print("sun: merge already completed")
            sys.exit("sun: history changed during merge")
        # The real Git index remains untouched. Only these Sun conflict paths are resolved.
        ix = shadow_index()
        env = {**os.environ, "GIT_INDEX_FILE": ix}
        git("read-tree", pending["tree"], env=env)
        if pending["files"]:
            git("--literal-pathspecs", "add", "-A", "--", *pending["files"], env=env)
        tree = git("write-tree", env=env).strip()
        if quiet("git", "diff", "--check", pending["tree"], tree).returncode:
            sys.exit("sun: resolve conflict markers before continuing")
        c = make_shadow_commit(tree, "sun: resolve shared shadow history", local(),
                               [pending["local"], pending["remote"]])
        p = patches(pending["tree"], c, pending["files"])
        record(type="merge", actor=local(), commit=c, edits=[
            {"file": f, "patch": p[f], "attribution": {"method": "resolution"}}
            for f in pending["files"] if p[f]])
        save_state("merge.json", {})
        return print(f"sun: merged shared shadow history in {c[:8]}")
    if pending: sys.exit("sun: finish `sun merge --continue` or `sun merge --abort` first")
    if "origin" in git("remote", check=False).split():
        git("fetch", "-q", "origin", *refspecs(cfg_share_sessions()))
    remote = ref_oid(remote_ref())
    if not remote: sys.exit("sun: no shared shadow history found on origin")
    local_tip = history_head()
    if local_tip == remote or not quiet(
            "git", "merge-base", "--is-ancestor", remote, local_tip).returncode:
        return print("sun: shadow history is already up to date")
    result = quiet("git", "merge-tree", "--write-tree", "--allow-unrelated-histories", local_tip, remote)
    if result.returncode not in (0, 1): sys.exit(f"sun: merge failed: {result.stderr}")
    tree = result.stdout.splitlines()[0]
    # Do not attribute remote content already brought in by normal Git to this user.
    dirty = changed_files()
    matching = []
    for f in dirty:
        p = git("--literal-pathspecs", "diff", "--binary", local_tip, tree, "--", f)
        if p and not quiet("git", "apply", "-R", "--check", input=p).returncode: matching.append(f)
    if set(dirty) - set(matching):
        sys.exit("sun: run `sun sync` for pending local edits before merging")
    files = [f for f in git("diff", "--name-only", "-z", local_tip, tree).split("\0") if f]
    remaining = [f for f in files if f not in matching]
    patch = git("--literal-pathspecs", "diff", "--binary", local_tip, tree, "--", *remaining) if remaining else ""
    save_state("merge.json", {"branch": shadow_ref(), "local": local_tip,
                              "remote": remote, "tree": tree, "files": files})
    if patch:
        try: apply_checked(patch, False, "sun: merge would overwrite working edits; sync them first")
        except SystemExit:
            save_state("merge.json", {})
            raise
    if result.returncode:
        sys.exit("sun: merge conflicts written to worktree; resolve, then `sun merge --continue`\n" +
                 result.stdout)
    commit = make_shadow_commit(tree, "sun: merge shared shadow history", local(), [local_tip, remote])
    record(type="merge", actor=local(), commit=commit, parents=[local_tip, remote], edits=[])
    save_state("merge.json", {})
    print(f"sun: merged shared shadow history in {commit[:8]}")
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
            + (f" {e['type']}" if e["type"] in ("undo", "restore") else "") + "]"
            for e in by_commit.get(H, [])))
        print(f"{h} {date} {subj}{tags or '  [untracked]'}")
def cmd_show(a):
    maybe_sync(); H = resolve_history_rev(a.commit)
    print(git("show", "--stat", "--pretty=format:commit %h  %ad%n%s%n", "--date=short", H))
    evs = [e for e in events(True) if H in (e.get("commit"), e.get("snapshot"))]
    if not evs:  # squash-merge/rebase moved the sha: match events by patch-id instead
        pid = patch_id(H); evs = [e for e in events(True) if pid and e.get("patch_id") == pid]
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
        item = p.get("item") or {}
        if item.get("id") == tid and item.get("type") == "FileChange": tool = "apply_patch"
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
def operation_transcript(ev, tid):
    if not tid: return None
    info = actor_info(ev.get("actor"))
    sid = ev.get("session_id")
    if info["user"] == user():
        entry = state("session-paths.json", {}).get(session_key(sid, info["harness"]), {})
        paths = [entry.get("path")] + list(entry.get("subagents", {}).values())
        if not any(paths):
            paths = [p for p, s, _ in transcript_sources(info["harness"]) if s == sid]
        for path in paths:
            if path and os.path.isfile(path):
                for chunk in scan_transcript(path, info["harness"]):
                    if tid in chunk: return path, chunk
    for stored, owner, ref in session_rows():
        if stored == sid and owner == info["user"]:
            for name in git("ls-tree", "-r", "--name-only", ref).splitlines():
                chunk = git("cat-file", "blob", f"{ref}:{name}")
                if tid in chunk: return name, chunk
    return None
def cmd_blame(a):
    maybe_sync()
    d, b = os.path.split(a.file)  # blame a symlink itself: resolve only its directory
    f = os.path.relpath(os.path.join(os.path.realpath(d or "."), b), root())
    out = git("--literal-pathspecs", "-c", "core.quotepath=false", "blame", "--porcelain",
              "-L", f"{a.line},{a.line}", history_head(), "--", f)
    H, orig = out.split()[:2]  # originating commit + the line's number in it
    if H == "0" * 40: sys.exit(f"sun: {f}:{a.line} is uncommitted")
    of = next((l[9:] for l in out.splitlines() if l.startswith("filename ")), f)  # pre-rename path
    touches = lambda e: any(ed.get("file") == of for ed in e.get("edits") or [])
    all_ev = events(True)
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
        o = tip and orig and quiet("git", "--literal-pathspecs", "-c", "core.quotepath=false", "blame", "--porcelain",
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
    hit = operation_transcript(ev, tid)
    if not hit: return print("no transcript stored for this edit")
    n, chunk = hit
    prompt, ctx, tool = blame_context(chunk, tid)
    print(f"session {sid} ({n}):")
    if prompt: print(f"user: {prompt.strip()}")
    if ctx: print(f"agent: {ctx.strip()}")
    print(f"[{tool or '?'} {tid}]")
def apply_checked(patch, reverse, failure, dry_run=False):
    args = ["apply"] + (["-R"] if reverse else [])
    if quiet("git", *args, "--check", input=patch).returncode: sys.exit(failure)
    if not dry_run: git(*args, input=patch)
def cmd_undo(a):
    if state("active.json", {}): sys.exit("sun: wait for active tool calls before undoing")
    actor = local()
    if a.commit is not None:
        H = resolve_history_rev(a.commit)
        parents = git("rev-list", "--parents", "-n1", H).split()[1:]
        if not parents: sys.exit("sun: cannot undo the initial shadow commit")
        if len(parents) != 1: sys.exit("sun: cannot undo a merge commit; restore a parent instead")
        patch = git("diff", "--binary", parents[0], H)
        if not a.dry_run: maybe_sync()
        apply_checked(patch, True, f"sun: cannot undo commit {H[:8]} cleanly", a.dry_run)
        if a.dry_run: return print(f"sun: can undo commit {H[:8]}")
        files, pre = changed_files(), history_head()
        c = commit_files(files or ["."], f"sun: undo commit {H[:8]}", actor)
        record(type="undo", actor=actor, commit=c, target_commit=H,
               edits=[{"file": f, "patch": patches(pre, c, files)[f]} for f in files])
        return print(f"sun: undid commit {H[:8]} in {c[:8]}")
    target = next((e for e in reversed(events())
                   if (e["id"] == a.op or not a.op) and e.get("edits")), None)
    if not target: sys.exit("sun: no such operation")
    combined = "".join(ed["patch"] for ed in target["edits"] if ed["patch"].strip())
    if not a.dry_run: maybe_sync()
    apply_checked(combined, True,
                  f"sun: cannot undo op {target['id']}: its patch no longer applies cleanly",
                  a.dry_run)
    files = list(dict.fromkeys(ed["file"] for ed in target["edits"]))
    if a.dry_run:
        return print(f"sun: can undo op {target['id']} by {target['actor']} "
                     f"({', '.join(files)})")
    pre = history_head()
    c = commit_files(files, f"sun: undo op {target['id']}", actor)
    record(type="undo", actor=actor, commit=c, target_op=target["id"],
           edits=[{"file": f, "patch": patches(pre, c, files)[f]} for f in files])
    print(f"sun: undid op {target['id']} in {c[:8]}")
def cmd_restore(a):
    if state("active.json", {}): sys.exit("sun: wait for active tool calls before restoring")
    target = resolve_history_rev(a.commit)
    maybe_sync(); pre = history_head()
    patch = git("diff", "--binary", pre, target)
    if not patch: return print(f"sun: already at {target[:8]}")
    apply_checked(patch, False, f"sun: cannot restore {target[:8]} cleanly")
    files = changed_files()
    c = commit_files(files or ["."], f"sun: restore {target[:8]}", local())
    record(type="restore", actor=local(), commit=c, target_commit=target,
           edits=[{"file": f, "patch": patches(pre, c, files)[f]} for f in files])
    print(f"sun: restored {target[:8]} in {c[:8]}")
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
    sessions = session_data()
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
        for op in operations:
            info = op["actor_info"]
            candidates = [s for s in sessions if s["id"] == op["session_id"]
                          and s["user"] == info["user"]
                          and s["harness"] in (None, info["harness"])]
            op["session_path"] = candidates[0]["path"] if len(candidates) == 1 else None
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
    return {"commits": commits, "events": all_events, "actors": actors, "sessions": sessions,
            "summary": {"commits": len(commits), "operations": sum(counts.values())}}
def operation_lines(op, prefix=""):
    info = op["actor_info"]
    out = [f"{prefix}operation {op['id']}  {op['type']}",
           f"{prefix}edited by     {actor_label(info)}"]
    if op.get("session_id"): out.append(f"{prefix}session       {op['session_id']}")
    if op.get("turn"): out.append(f"{prefix}turn          {op['turn']}")
    if op.get("timestamp"): out.append(f"{prefix}timestamp     {op['timestamp']}")
    if "uncertain" in op.get("attribution_methods", []):
        out.append(f"{prefix}attribution   uncertain: overlapping or interrupted writes")
    if op.get("target_op"): out.append(f"{prefix}undoes        operation {op['target_op']}")
    if op.get("target_commit"):
        verb = "restores" if op["type"] == "restore" else "undoes"
        out.append(f"{prefix}{verb:<14}commit {op['target_commit'][:8]}")
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
        sys.exit("sun: `sun viz` needs an interactive terminal; use `sun data` for JSON")
    import curses
    curses.wrapper(viz_tui, data)
def write_viz_html(data, out):
    encoded = json.dumps(data).replace("</", "<\\/")
    write_text(out, VIZ.replace("__DATA__", encoded))
    print(f"sun: wrote {out}")
def cmd_viz(a):
    with lock():
        ensure_branch()
        maybe_sync([rel_to_root(a.output)] if a.output else stdout_file())
        data = viz_data(a.n)
    if getattr(a, "html", False) or a.output:
        return write_viz_html(data, a.output or os.path.join(sun_dir(), "viz.html"))
    if a.cmd == "data": return print(json.dumps(data))
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
    _u.clear()
    ap = argparse.ArgumentParser(
        prog="sun", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Start with `sun init`, then use `sun viz` to explore recorded work.")
    sub = ap.add_subparsers(dest="cmd", required=True, title="commands", metavar="COMMAND")
    ps = {c: sub.add_parser(c, help=h) for c, h in [
        ("init", "initialize Sun and install agent hooks"),
        ("sync", "snapshot pending human edits into Sun history"),
        ("log", "list Sun commits with attributed actors and turns"),
        ("show", "show a Sun commit and its recorded operations"),
        ("viz", "browse attributed history in an interactive terminal"),
        ("data", "emit attributed history and session paths as JSON"),
        ("blame", "show who changed a line and its stored conversation, when available"),
        ("undo", "reverse an operation or Sun commit and record the undo"),
        ("restore", "restore files to a Sun commit and record the restoration"),
        ("sessions", "manage explicitly shared agent transcripts"),
        ("merge", "merge shared Sun history using Git's three-way merge"),
        ("push", "publish Sun history and attribution atomically"),
        ("export", "export operations as fine-tuning JSONL"),
        ("update", "upgrade the uv-installed Sun CLI")]}
    ps["hook"] = sub.add_parser("hook", help=argparse.SUPPRESS)
    sub._choices_actions = [choice for choice in sub._choices_actions if choice.dest != "hook"]
    ps["init"].add_argument("--claude", action="store_true",
                            help="set up Claude Code only (default: every detected harness)")
    ps["init"].add_argument("--codex", action="store_true",
                            help="set up Codex only (default: every detected harness)")
    ps["init"].add_argument("--share-sessions", dest="share_sessions", action="store_true",
                            default=None, help="share raw transcripts through git refs")
    ps["init"].add_argument("--no-share-sessions", dest="share_sessions", action="store_false",
                            help="keep raw transcripts only in their native harness directories")
    ps["init"].add_argument("--instructions", "--claude-md", dest="instructions",
                            action="store_true", default=None,
                            help="add agent instructions for finding shared sessions")
    ps["init"].add_argument("--no-instructions", "--no-claude-md", dest="instructions",
                            action="store_false", help="do not edit agent instruction files")
    ps["hook"].add_argument("--harness", choices=("claude", "codex"), default="claude")
    ps["push"].add_argument("remote", nargs="?", default="origin")
    ps["sync"].add_argument("--recover", action="store_true",
                            help="after stopping agents, release abandoned calls and record uncertain edits")
    merge_action = ps["merge"].add_mutually_exclusive_group()
    merge_action.add_argument("--continue", dest="continue_merge", action="store_true")
    merge_action.add_argument("--abort", action="store_true")
    session_sub = ps["sessions"].add_subparsers(
        dest="session_cmd", required=True, title="session commands", metavar="ACTION")
    session_ps = {c: session_sub.add_parser(c, help=h) for c, h in [
        ("list", "list stored transcripts"), ("show", "print one stored transcript"),
        ("import", "store new or changed native transcripts in Sun refs"),
        ("export", "index native paths and cache collaborators' shared transcripts"),
        ("prune", "delete your old stored transcript refs")]}
    session_ps["list"].add_argument("--grep", metavar="REGEX",
                                    help="show transcripts matching a regular expression")
    session_ps["list"].add_argument("--contains", metavar="TEXT",
                                    help="show transcripts containing literal text")
    session_ps["show"].add_argument("id", help="full session ID or unique prefix")
    session_ps["prune"].add_argument("--older-than", type=int, required=True, metavar="DAYS",
                                     help="prune sessions last stored more than DAYS ago")
    session_ps["prune"].add_argument("--remote", action="store_true",
                                     help="also delete the selected refs from origin")
    ps["log"].add_argument("-n", type=int, default=30, metavar="COUNT",
                           help="maximum commits to show (default: 30)")
    ps["show"].add_argument("commit", help="Sun commit, snapshot, or ref")
    undo_target = ps["undo"].add_mutually_exclusive_group()
    undo_target.add_argument("--op", nargs="?", const="", default=None, metavar="ID",
                             help="operation ID (default: latest operation)")
    undo_target.add_argument("--commit", nargs="?", const="HEAD", default=None, metavar="HASH",
                             help="Sun commit (default with flag: current Sun commit)")
    ps["undo"].add_argument("--dry-run", action="store_true",
                            help="check whether the reversal applies without changing files")
    ps["restore"].add_argument("commit", help="Sun commit, snapshot, or ref to restore")
    viz_format = ps["viz"].add_mutually_exclusive_group()
    viz_format.add_argument("--html", action="store_true", help="export self-contained HTML")
    viz_format.add_argument("--tui", action="store_true", help="open interactive terminal history")
    ps["data"].add_argument("-n", type=int, default=0, metavar="COUNT")
    ps["data"].set_defaults(output=None)
    ps["viz"].add_argument("-o", "--output", default=None,
                            help="HTML output path (implies --html)")
    ps["viz"].add_argument("-n", type=int, default=0, metavar="COUNT",
                           help="maximum commits to load (default: all)")
    ps["export"].add_argument("-o", "--output", default=None,
                              help="output path (default: stdout)")
    ps["blame"].add_argument("file", help="path to inspect")
    ps["blame"].add_argument("line", type=int, help="1-based line number")
    a = ap.parse_args(argv)
    commands = {
        "init": cmd_init, "hook": cmd_hook, "sync": cmd_sync, "merge": cmd_merge, "push": cmd_push,
        "log": cmd_log, "show": cmd_show, "undo": cmd_undo, "restore": cmd_restore,
        "viz": cmd_viz, "data": cmd_viz, "sessions": cmd_sessions, "update": cmd_update,
        "export": cmd_export, "blame": cmd_blame,
    }
    if a.cmd not in ("init", "hook", "update"):  # hook locates its repo from the payload
        if a.cmd == "blame": a.file = os.path.abspath(a.file)  # resolve before the chdir
        os.chdir(root())
        sun_dir()
        if a.cmd in ("viz", "data"):
            commands[a.cmd](a)
        else:
            with lock():
                ensure_branch()
                commands[a.cmd](a)
    else:
        commands[a.cmd](a)
if __name__ == "__main__":
    main()
