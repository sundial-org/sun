#!/usr/bin/env python3
"""Record human and agent edits in an independent Git-backed operation history.

Each Git branch has its own Sun history. Unpublished, non-interleaved agent calls are grouped
per turn while remaining individually inspectable and undoable. Recording stays local. Resolve file
conflicts with normal Git. `sun push` publishes the selected Sun branch independently of Git commits;
it combines recorded histories without changing files or normal Git refs.
Raw transcripts are shared only when you explicitly enable session sharing."""
import argparse, calendar, difflib, fcntl, fnmatch, glob, hashlib, json, os, re, shutil
import subprocess, sys, time, uuid
from concurrent.futures import ThreadPoolExecutor
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
def remote_ref(remote="origin"):
    return shadow_ref().replace("refs/sun/heads/", f"refs/sun/remotes/{remote}/")
def ensure_branch():
    """Select a timeline; Git ancestry never determines how Sun combines file contents."""
    ref, normal = shadow_ref(), ref_oid("HEAD")
    previous = state("branch.json", {})
    tip, inherited = history_head(False), False
    if not tip:
        source = previous.get("ref")
        # A normal commit may have happened since Sun last ran, before `git switch -c`.
        at_source = source and normal == ref_oid(source.replace("refs/sun/heads/", "refs/heads/"))
        tip = ref_oid(source) if source and (previous.get("git") == normal or at_source) else ""
        if not tip and normal:  # a branch created at another branch's commit continues that history
            tip = sibling_history(normal, source)
            inherited = bool(tip)
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
    # A changed checkout is evidence of a new state, not evidence that this user authored it.
    observe = previous.get("observe", False) or inherited or bool(previous and (
        previous.get("ref") != ref or previous.get("git") != normal))
    save_state("branch.json", {"ref": ref, "git": normal, "observe": observe})
def sibling_history(normal, prefer=None):
    """The Sun tip this branch should continue: its own remote lineage, else the branch it was created
    from (the reflog says), else the last-used branch, else any branch at the same commit."""
    remote = ref_oid(remote_ref())
    if remote: return remote
    at = git("for-each-ref", "--points-at", normal, "--format=%(refname)", "refs/heads/", check=False).split()
    cands = [r.replace("refs/heads/", "refs/sun/heads/", 1) for r in at]
    first = git("reflog", "show", "--format=%gs", shadow_ref().replace("refs/sun/heads/", "refs/heads/", 1),
                check=False).strip().splitlines()
    m = first and re.match(r"branch: Created from (\S+)", first[-1])
    source = "refs/sun/heads/" + m.group(1) if m else None
    for cand in [c for c in (source, prefer) if c in cands] + cands:
        if cand != shadow_ref() and ref_oid(cand): return ref_oid(cand)
    return ""
def history_head(required=True):
    oid = ref_oid(shadow_ref())
    if required and not oid: sys.exit("sun: shadow history has no commits (run `sun init`)")
    return oid
def history_refs():
    return [shadow_ref()] if history_head(False) else []
def resolve_history_rev(rev):  # HEAD, HEAD~2, HEAD^ name the Sun branch, not the Git checkout
    if rev == "HEAD" or rev.startswith(("HEAD~", "HEAD^")): rev = shadow_ref() + rev[4:]
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
def ref_blobs(prefix):  # [(refname, blob bytes)] for a whole ref namespace, in one cat-file
    entries = refs(prefix)
    if not entries: return []
    data = subprocess.run(["git", "cat-file", "--batch"],
                          input="".join(sha + "\n" for _, sha in entries).encode(),
                          capture_output=True, check=True).stdout
    out, pos = [], 0
    for ref, _ in entries:
        end = data.index(b"\n", pos)
        size = int(data[pos:end].split()[-1])
        out.append((ref, data[end + 1:end + 1 + size]))
        pos = end + size + 2
    return out
def events(include_unreachable=False, scope=None) -> List[Event]:
    evs = []
    for ref, raw in ref_blobs("refs/sun/events/"):
        ev = json.loads(raw)
        if not re.fullmatch(r"[0-9a-f]{32}", ev.get("id", "")) or ref != f"refs/sun/events/{ev['id']}":
            sys.exit("sun: invalid operation ID in fetched history")
        evs.append(ev)
    if not evs: return []
    scope = history_refs() if scope is None else scope
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
def publish(commit, evs, before=None, ref=None):
    if before is None:
        parents = git("rev-list", "--parents", "-n1", commit).split()[1:]
        before = parents[0] if parents else ""
    updates = [f"update {ref or shadow_ref()} {commit} {before or '0' * len(commit)}"]
    for ev in evs:
        ref = f"refs/sun/events/{ev['id']}"
        updates.append(f"update {ref} {blob(json.dumps(ev))} {ref_oid(ref) or '0' * len(commit)}")
        snapshot = ev.get("snapshot", commit)
        updates.append(f"update refs/sun/ops/{snapshot} {snapshot}")
    git("update-ref", "--stdin", input="start\n" + "\n".join(dict.fromkeys(updates)) +
        "\nprepare\ncommit\n")
def record_batch(commit, entries, ref=None):
    evs = [{"id": uuid.uuid4().hex, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "sequence": i, "commit": commit, "branch": ref or shadow_ref(), **e} for i, e in enumerate(entries)]
    publish(commit, evs, ref=ref)
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
def sync(exclude=(), method="sync"):  # record unclaimed file changes, without touching Git's index
    active = state("active.json", {})
    if any(s.get("all_files") for s in active.values()): return
    exclude = set(exclude) | {f for s in active.values() for f in s["files"]}
    files = [f for f in changed_files() if f not in exclude]
    branch = state("branch.json", {})
    if method in ("sync", "hook") and branch.get("observe"): method = "observed"
    if not files:
        if not active and branch.get("observe"):
            save_state("branch.json", {**branch, "observe": False})
        return None
    pre, actor = history_head(), "unknown" if method in ("uncertain", "observed") else local()
    c = commit_files(files, "sun: observed repository state" if method == "observed"
                     else edits_msg(actor, files), actor)
    p = patches(pre, c, files)
    ev = record(type="observe" if method == "observed" else "edit", actor=actor, commit=c, patch_id=patch_id(c),
                  edits=[{"file": f, "patch": p[f],
                          "attribution": {"method": method}} for f in files])
    if not active and branch.get("observe"):
        save_state("branch.json", {**branch, "observe": False})
    return ev
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
    start = state("turns.json", {}).get(session_key(sid, harness), {}).get("start") or pre
    return {"at": c, "since": pre, "turn": start, "in_turn": True, "files": a_files} if a_files else None
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
    published += [sha for ref, sha in refs("refs/sun/heads/") if ref != shadow_ref()]
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
def turn_unit(sid, harness, t):
    """The session's own work in a turn, for rules and extraction: {at, since, turn, files, in_turn}."""
    tip = history_head(False)
    if not (t.get("start") and tip and t.get("branch") == shadow_ref()): return None
    n, mine = t.get("n"), []
    for e in events():  # after the squash, the turn's events sit on the turn commit
        if e.get("session_id") == sid and e.get("turn") == f"turn{n}" and e["actor"] == agent(sid, harness):
            mine.append(e)
    files = sorted({d["file"] for e in mine for d in e.get("edits") or []})
    at = mine[-1]["commit"] if mine and quiet("git", "merge-base", "--is-ancestor", mine[-1]["commit"], tip).returncode == 0 else tip
    return {"at": at, "since": t["start"], "turn": t["start"], "in_turn": True, "files": files}
def cmd_hook(a):
    try: payload = json.load(sys.stdin)
    except (ValueError, OSError): payload = {}
    try: payload.get("cwd") and os.chdir(payload["cwd"])
    except OSError: return
    p = quiet("git", "rev-parse", "--show-toplevel")
    if p.returncode: return  # not a Git repo; hooks must never break the harness
    os.chdir(p.stdout.strip())
    if not adopt(): return  # not a Sun repo
    with lock():  # serialize concurrent hooks (parallel sessions/subagents)
        ensure_branch()
        unit = handle_hook(a, payload)
    if unit and not os.environ.get("SUN_CHECKING"):  # rules run outside the lock: a judge has hooks of its own
        try: hook_checks(a, payload, unit)
        except (SystemExit, Exception) as exc: print(f"sun: {exc}", file=sys.stderr)


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
        return finish_call(sid, active, payload, harness)
    elif event == "Stop":  # a queued prompt may end in a text-only turn: no PreToolUse
        before = dict(state("turns.json", {}).get(session_key(sid, harness)) or {})
        prompt_boundary(sid, payload, harness)
        squash_turn(sid, harness)
        stop_chunk(sid, payload, harness)
        t = state("turns.json", {}).get(session_key(sid, harness)) or {}
        if before.get("n") and t.get("n") != before.get("n"): t = before  # a queued prompt already opened the next turn
        return turn_unit(sid, harness, t)
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
            entry = {"type": "command", "command": command}
            if harness == "claude" and event in ("PostToolUse", "Stop"): entry["timeout"] = 2 * CHECK_TIMEOUT
            group.append({"hooks": [entry]})
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
def refspecs(share_sessions=False, remote="origin"):
    specs = ["refs/sun/events/*:refs/sun/events/*", "refs/sun/ops/*:refs/sun/ops/*",
             "refs/sun/checks/*:refs/sun/checks/*", f"+refs/sun/heads/*:refs/sun/remotes/{remote}/*"]
    return specs + (["+refs/sun/sessions/*:refs/sun/sessions/*"] if share_sessions else [])
def configure_sharing(share_sessions=False):
    if "origin" in git("remote", check=False).split():
        for old in ("+refs/sun/*:refs/sun/*", "+refs/sun/sessions/*:refs/sun/sessions/*",
                    "+refs/sun/heads/*:refs/sun/heads/*", "+refs/sun/log/*:refs/sun/log/*",
                    "+refs/sun/ops/*:refs/sun/ops/*",
                    "refs/sun/checkpoints/*:refs/sun/checkpoints/*",
                    "refs/sun/session-checkpoints/*:refs/sun/session-checkpoints/*"):
            git("config", "--fixed-value", "--unset-all", "remote.origin.fetch", old, check=False)
        current = git("config", "--get-all", "remote.origin.fetch", check=False).splitlines()
        for spec in refspecs(share_sessions):
            if spec not in current: git("config", "--add", "remote.origin.fetch", spec)
    # Remove only exact Sun-owned hooks from the earlier design; preserve custom hooks.
    managed = {
        "pre-push": ('#!/bin/sh\n# sun: mirror shared refs\nexec sun push "$1"\n',
                     '#!/bin/sh\n# sun: mirror shared refs, fail-soft\nexec sun push "$1"\n',
                     '#!/bin/sh\n# sun: mirror op log + sessions, fail-soft\n'
                     'git push --no-verify "$1" "+refs/sun/*:refs/sun/*" >/dev/null 2>&1 || true\n'),
        "post-commit": ("#!/bin/sh\n# sun: clean Git checkpoint\nsun git-hook commit\n",),
        "post-merge": ("#!/bin/sh\n# sun: clean Git checkpoint\nsun git-hook merge\n",),
    }
    for name, scripts in managed.items():
        path = git("rev-parse", "--git-path", "hooks/" + name).strip()
        if os.path.exists(path) and read_text(path) in scripts: os.remove(path)
    install_push_hook()
PRE_PUSH = """#!/bin/sh
# sun: publish recorded Sun history for each pushed branch, without blocking the Git push
while read local_ref local_oid remote_ref remote_oid; do
  case "$local_ref" in
    refs/heads/*) branch="${local_ref#refs/heads/}";;
    HEAD) branch=$(git symbolic-ref -q --short HEAD) || continue;;
    *) continue;;
  esac
  git rev-parse -q --verify "refs/sun/heads/$branch" >/dev/null 2>&1 || continue
  sun push "$1" "$branch" || echo "sun: Sun history for $branch was not published; run: sun push $1 $branch" >&2
done
exit 0
"""
def install_push_hook():  # `git push` publishes Sun history too; a hook Sun did not write is left alone
    if git("config", "--get", "core.hooksPath", check=False).strip():
        print("sun: core.hooksPath is set; add `sun push` to your pre-push hook yourself", file=sys.stderr)
        return False
    path = git("rev-parse", "--git-path", "hooks/pre-push").strip()
    if os.path.exists(path):
        if read_text(path) == PRE_PUSH: return True
        if "# sun:" not in read_text(path):
            print(f"sun: {path} exists; run `sun push` yourself, or call it from that hook", file=sys.stderr)
            return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_text(path, PRE_PUSH); os.chmod(path, 0o755)
    return True
def adopt():
    """A worktree or clone of a repository that already uses Sun sets itself up on first use."""
    d = sun_dir(False)
    if os.path.isdir(d): return True
    common = git("rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    shared = jread(os.path.join(common, "sun", "config.json"), {})
    hooked = [h for h in ("claude", "codex") if os.path.exists(os.path.join(root(), hook_file(h)))
              and hook_cmd(h) in read_text(os.path.join(root(), hook_file(h)))]
    if not shared and not hooked: return False  # nobody ran `sun init` here: stay out of the way
    with lock():
        if os.path.isdir(d): return True
        os.makedirs(d, exist_ok=True)
        save_state("config.json", {"harnesses": hooked or shared.get("harnesses", ["claude"]),
                                   "share_sessions": bool(shared.get("share_sessions"))})
        configure_sharing(cfg_share_sessions())
        if "origin" in git("remote", check=False).split():
            try: quiet("git", "fetch", "-q", "origin", *refspecs(cfg_share_sessions()), timeout=60)
            except subprocess.TimeoutExpired: pass
    return True

def join_history(remote, ref):
    """Combine recorded ancestry, retaining the selected branch's snapshot and original operations."""
    tip = ref_oid(ref)
    if not remote or not quiet("git", "merge-base", "--is-ancestor", remote, tip).returncode:
        return tip
    tree = ref_oid(f"{tip}^{{tree}}")
    if tree == ref_oid(f"{remote}^{{tree}}") and not quiet(
            "git", "merge-base", "--is-ancestor", tip, remote).returncode:
        git("update-ref", ref, remote, tip)
        return remote
    c = make_shadow_commit(tree, "sun: combine recorded histories", local(), [tip, remote])
    record_batch(c, [dict(type="merge", actor=local(), parents=[tip, remote], edits=[])], ref=ref)
    return c

def cmd_push(a):
    """Publish recorded Sun history only; never commit, stage, merge files, or push Git branches."""
    branch = a.branch or git("symbolic-ref", "--short", "HEAD").strip()
    if quiet("git", "check-ref-format", "refs/heads/" + branch).returncode:
        sys.exit("sun: push requires a local branch name, not a revision or refspec")
    ref = "refs/sun/heads/" + branch
    if not ref_oid(ref): sys.exit("sun: branch has no recorded Sun history")
    # Fetch ancestry, not mutable session refs: publication must not overwrite our local transcripts.
    git("fetch", "-q", a.remote, *refspecs(False, a.remote))
    tip = join_history(ref_oid(f"refs/sun/remotes/{a.remote}/{branch}"), ref)
    selected = events(scope=[tip])
    snapshots = {e.get("snapshot", e["commit"]) for e in selected}
    # ponytail: one refspec per operation; batch transport if very large histories hit ARG_MAX.
    specs = [f"{tip}:{ref}"]
    specs += [f"refs/sun/events/{e['id']}:refs/sun/events/{e['id']}" for e in selected]
    specs += [f"refs/sun/ops/{sha}:refs/sun/ops/{sha}" for sha in sorted(snapshots)]
    if cfg_share_sessions():
        sessions = {e.get("session_id") for e in selected if e["actor"].startswith(user() + "/agent:")}
        specs += [f"{sha}:{r}" for r, sha in refs(f"refs/sun/sessions/{user()}/")
                  if r.rsplit("/", 1)[-1] in sessions]
    # Protect operations even when an interrupted push has an unknown outcome.
    git("update-ref", ref.replace("refs/sun/heads/", "refs/sun/published/"), tip)
    if refs("refs/sun/checks/"):  # separately, and fail-soft: checks and history never block each other
        quiet("git", "push", "--no-verify", "--", a.remote, "refs/sun/checks/*:refs/sun/checks/*")
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
    explicit = [h for h, f in (("claude", a.claude), ("codex", a.codex)) if f]
    harnesses = explicit or detect_harnesses()
    cfg = state("config.json", {}); cfg.pop("harness", None)
    cfg["harnesses"] = harnesses
    cfg.pop("shadow_history", None)
    save_state("config.json", cfg)
    share_sessions = configure_session_sharing(a.share_sessions)
    if "origin" in git("remote", check=False).split():  # fresh clone: fetch team refs
        git("fetch", "-q", "origin", *refspecs(share_sessions))
    installed = ", ".join(install_hooks(h) for h in harnesses); configure_sharing(share_sessions)
    for h in ("claude", "codex"):
        if explicit and h not in explicit: remove_hooks(h)
    if share_sessions:
        agent_instructions(harnesses, a.instructions, "".join(" --" + h for h in explicit))
    fresh = False
    if not history_head(False):
        normal, inherited = ref_oid("HEAD"), sibling_history(ref_oid("HEAD"))
        if inherited:  # a new branch or worktree continues the history of the branch it came from
            git("update-ref", shadow_ref(), inherited)
            save_state("branch.json", {"ref": shadow_ref(), "git": normal, "observe": True})
        else:
            c = commit_files(["."], "sun: initial state", local())
            remote, tree = ref_oid(remote_ref()), ref_oid(f"{c}^{{tree}}")
            matches = [line.split()[0] for line in git("log", remote, "--format=%H %T").splitlines()
                       if line.split()[1] == tree] if remote else []
            if matches: git("update-ref", shadow_ref(), matches[0])
            else: record(type="init", actor=local(), commit=c, edits=[]); fresh = True
    ensure_branch()
    sync()
    print(f"sun: initialized {root()} (hooks: {installed}); {do_import(harnesses)}")
    if fresh:
        print("sun: recording starts now: earlier work is one initial snapshot (`sun migrate` rebuilds it from "
              "your agent sessions), and agent sessions already running are recorded from their next restart")
    config, rs = read_rules()
    if runners_hash(config, rs) and not trusted(config, rs):
        named = [f"{n}: {r['runner']}: {r['command']}" for n, r in sorted(rs.items()) if r["runner"]]
        named += [f"extract: {config['extract']}"] if config.get("extract") else []
        print("sun: RULES.md names commands for hooks to run; review them and run `sun trust` to allow that:\n  "
              + "\n  ".join(named))
    if "codex" in harnesses:
        print("sun: Codex requires separate hook approval; open `/hooks`, review "
              "`.codex/hooks.json`, and trust the Sun hooks before testing")
    print("run `sun viz` to explore your attributed history")
def cmd_sync(a):
    if a.recover: save_state("active.json", {})
    ev = sync(method="uncertain" if a.recover else "sync")
    print(f"sun: recorded edits as op {ev['id']}" if ev else "sun: nothing to sync")
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
    for line in git("log", "--topo-order", *revisions, f"-{a.n}", "--pretty=%H\t%h\t%ad\t%s",
                    "--date=short").splitlines():
        H, h, date, subj = line.split("\t", 3)
        tags = "".join(dict.fromkeys(
            f"  [{e['actor']}" + (f" {e['turn']}" if e.get("turn") else "")
            + (f" pr#{e['pr']}" if e.get("pr") else "")
            + (f" {e['type']}" if e["type"] in ("undo", "restore") else "") + "]"
            for e in by_commit.get(H, [])))
        print(f"{h} {date} {subj}{tags or '  [untracked]'}")
def cmd_show(a):
    maybe_sync()
    if re.fullmatch(r"[0-9a-f]{8,32}", a.commit) and quiet("git", "rev-parse", "-q", "--verify",
                                                             a.commit + "^{commit}").returncode:
        hits = [c for i, c in checks().items() if i.startswith(a.commit)]
        if len(hits) == 1: return print(json.dumps(hits[0], indent=2))
    H = resolve_history_rev(a.commit)
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
    if ev["actor"] == "unknown":
        return print("observed change; author unknown: no conversation\n" + json.dumps(ev, indent=2))
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
# ---------------------------------------------------------------------------------------------
# Layer 2: what someone concluded about the history, kept apart from the history itself.
#   rule      a `## name` section of RULES.md; it may name a command, a model, or an agent to run it
#   check     one verdict on one rule, citing the Sun commit (and file) it read
#   review    a check that cites another check; it replaces that check in coverage
#   coverage  checks folded onto Sun commits when you ask; never stored
# A judge, a program and a person all submit the same shape. Sun runs a rule's command only when
# asked (`sun check --run`) or from hooks after `sun trust`. Checks are blobs at
# refs/sun/checks/<git user>/<id>; events() never reads them, so layer 1 cannot see them.
RULE_KEYS = ("run", "model", "agent", "on", "files", "feedback")
CHECK_TIMEOUT = 600  # seconds a rule's command, model, or agent may take
CLI = {  # a bare model name runs through the harness CLI; a value with a space is a command
    ("model", "claude"): 'claude -p --model {m} --tools "" --strict-mcp-config --max-turns 1 '
                         '--no-session-persistence --output-format json',
    ("agent", "claude"): 'claude -p --model {m} --strict-mcp-config --output-format json --permission-mode dontAsk '
                         '--allowedTools "Read,Grep,Glob,Bash(git diff *),Bash(git show *),Bash(git log *),'
                         'Bash(git blame *),Bash(sun show *),Bash(sun log *),Bash(sun blame *),Bash(sun data *)"',
    ("model", "codex"): "codex exec -m {m} -s read-only --ephemeral -",
    ("agent", "codex"): "codex exec -m {m} -s read-only -",
}
def unquote(v):  # a value in matching outer quotes, or as written; `  # comment` is dropped
    v = re.sub(r"\s+#.*$", "", v.strip())
    return v[1:-1] if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'" else v
def kv_block(lines):  # `key: value` lines -> dict: a strict subset of YAML, no nesting
    out = {}
    for l in lines:
        m = re.fullmatch(r"\s*([\w-]+)\s*:\s*(.*?)\s*", l)
        if m: out[m.group(1)] = unquote(m.group(2))
    return out
def front_matter(lines):  # (dict, rest) when the lines open with a `---` fenced block
    while lines and not lines[0].strip(): lines = lines[1:]
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---": return kv_block(lines[1:i]), lines[i + 1:]
    return {}, lines
def rule_record(name, meta, text):
    runner = next((k for k in ("run", "model", "agent") if meta.get(k)), None)
    keyed = {k: meta[k] for k in RULE_KEYS if k in meta}
    return {"name": name, "text": text, "runner": runner, "command": meta.get(runner, "") if runner else "",
            "on": meta.get("on", ""), "files": [unquote(g) for g in meta.get("files", "").split(",") if g.strip()],
            "feedback": meta.get("feedback", "true").lower() not in ("false", "no", "0", "off"),
            "hash": hashlib.sha256((" ".join(text.split()) + "\n" + json.dumps(keyed, sort_keys=True))
                                   .encode()).hexdigest()[:12]}
def read_rules():  # (front matter, {name: rule}) from RULES.md, or a legacy RULES file of `name: text` lines
    p = os.path.join(root(), "RULES.md")
    if not os.path.exists(p):
        legacy = os.path.join(root(), "RULES")
        found = re.findall(r"(?m)^([\w.-]+):[ \t]+(\S.*?)\s*$", read_text(legacy)) if os.path.exists(legacy) else []
        return {}, {n: rule_record(n, {}, t) for n, t in found}
    config, lines = front_matter(read_text(p).splitlines())
    rules, name, body, fenced = {}, None, [], False
    for l in lines + [None]:
        if l is not None and l.lstrip().startswith("```"): fenced = not fenced
        if l is None or (not fenced and re.match(r"##(\s|$)", l)):  # a level-2 heading starts a rule, or ends one
            if name:
                meta, rest = front_matter(body)
                rules[name] = rule_record(name, meta, "\n".join(rest).strip())
            m = l is not None and re.fullmatch(r"##\s+([\w.-]+)\s*", l)
            name, body = m.group(1) if m else None, []
        elif name is not None: body.append(l)
    return config, rules
def rules(): return {n: r["text"] for n, r in read_rules()[1].items()}  # {name: text}
def runners_hash(config, rs):  # every command RULES.md asks Sun to run; empty when it asks for none
    parts = [f"extract: {config['extract']}"] if config.get("extract") else []
    parts += [f"{n} {r['runner']}: {r['command']}" for n, r in sorted(rs.items()) if r["runner"]]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:12] if parts else ""
def trust_path():
    common = git("rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    return os.path.join(common, "sun", "trust.json")
def trusted(config, rs):  # hooks run RULES.md commands only after a person trusted them on this machine
    h = runners_hash(config, rs)
    return not h or jread(trust_path(), {}).get("rules") == h
def cmd_trust(a):
    if agent_shell(): sys.exit("sun: trusting RULES.md commands is a person's decision; run `sun trust` at a terminal")
    config, rs = read_rules()
    h = runners_hash(config, rs)
    os.makedirs(os.path.dirname(trust_path()), exist_ok=True)
    jwrite(trust_path(), {"rules": h})
    n = sum(1 for r in rs.values() if r["runner"])
    if not h: return print("sun: RULES.md asks Sun to run nothing; nothing to trust")
    print(f"sun: hooks on this machine now run {n} rule command{'s' if n != 1 else ''} from RULES.md"
          + (" and extract verdicts from your replies" if config.get("extract") else ""))
def check_ref(c): return f"refs/sun/checks/{c['actor'].split('/', 1)[0]}/{c['id']}"
def check_id(c):  # the hash of the check's content, so the same check is the same ref on any machine
    content = {k: v for k, v in c.items() if k not in ("id", "timestamp")}
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()[:32]
def well_formed(c):  # the shape coverage relies on; checks arrive by fetch, so they are data, not trusted
    if not isinstance(c, dict) or not isinstance(c.get("cites"), list): return False
    strings = [c.get("rule"), c.get("verdict"), c.get("actor"), c.get("timestamp", ""),
               c.get("via", ""), c.get("rule_text", ""), c.get("from") or ""]
    for x in c["cites"]:
        if not isinstance(x, dict) or not ("at" in x or "check" in x): return False
        strings += [x[k] for k in ("at", "check", "file") if k in x]
        lines = x.get("lines")
        if lines is not None and not (isinstance(lines, list) and len(lines) == 2
                                      and all(isinstance(n, int) and not isinstance(n, bool) for n in lines)): return False
    if not isinstance(c.get("meta", {}), dict) or not isinstance(c.get("note", ""), str): return False
    return all(isinstance(s, str) for s in strings) and "/" in c["actor"]
def checks():  # {id: check}; a blob that is malformed, outside its user's namespace, or does not hash to its ID is not a check
    out = {}
    for ref, raw in ref_blobs("refs/sun/checks/"):
        try: c = json.loads(raw)
        except (ValueError, RecursionError): continue
        if well_formed(c) and c.get("id") == check_id(c) and ref == check_ref(c): out[c["id"]] = c
    return out
def check_level(actor):  # how a verdict was given: terminal, chat, agent, model, program, or declared
    source = actor.split("/", 1)[1] if "/" in actor else actor
    if source == "local": return "terminal"
    if source == "chat": return "chat"
    for prefix in ("agent", "model", "program"):
        if source.startswith(prefix + ":"): return prefix
    return "declared"
def check_label(c, authored=None):
    """Fixed wording for readers: 'emma (terminal)', 'emma (in chat)', 'model haiku (hook:Stop)', ..."""
    owner, source = (c["actor"].split("/", 1) + [""])[:2]
    level, via = check_level(c["actor"]), c.get("via", "")
    if level == "terminal": return f"{owner} (terminal)"
    if level == "chat": return f"{owner} (in chat)"
    label = f"{level} {source.split(':', 1)[1] if level != 'declared' else source}"
    tag = "self-check" if c.get("from") and c["from"] == authored else via
    return label + (f" ({tag})" if tag else "")
one_line = lambda s: " ".join(str(s or "").split())[:500]
def harness_env():  # a shell an agent or a judge is running, even after its tool call has been released
    return bool(os.environ.get("CLAUDECODE") or os.environ.get("SUN_CHECKING")) or \
        any(k.startswith("CODEX_SANDBOX") for k in os.environ)
def agent_shell():  # refuse the terminal form here: it is the one check that counts as your eyes
    return bool(state("active.json", {})) or harness_env()
def in_flight_session():  # the one agent session whose tool call is running, if exactly one is
    keys = {k.rsplit("/", 1)[0] for k in state("active.json", {})}
    return keys.pop() if len(keys) == 1 else None
def declared_actor(actor):  # local and chat are Sun's own; harness session actors are observed, not declared
    return isinstance(actor, str) and bool(re.fullmatch(r"[\w.:@/-]{1,80}", actor)) and \
        not ("/" + actor).endswith("/local") and actor != "chat" and \
        not actor.startswith(("agent:claude/", "agent:codex/"))
def store_checks(reqs, via, origin=None):
    """Validate every request, then write the new checks in one Git transaction; returns the stored checks.
    A request: a bare actor (local, chat, program:x, model:x, agent:x), rule, verdict, cites, and
    optionally note, meta, command. `via` and `from` are Sun's own record of how a check arrived."""
    config, rs = read_rules()
    stored = checks()
    recorded = set()  # every commit and tool-call snapshot Sun has recorded, on any branch
    for _, raw in ref_blobs("refs/sun/events/"):
        e = json.loads(raw); recorded |= {e.get("commit"), e.get("snapshot")}
    new, done = {}, []
    for r in reqs:  # validate every check before writing any
        cites = []
        for x in r.get("cites") if isinstance(r.get("cites"), list) else []:
            if isinstance(x, dict) and isinstance(x.get("check"), str) and x["check"] in stored:
                reviewed_rule = stored[x["check"]]["rule"]  # a review is about the same rule
                if r.get("rule", reviewed_rule) != reviewed_rule:
                    sys.exit("sun: a review keeps the rule of the check it cites")
                r["rule"] = reviewed_rule
                cites.append({"check": x["check"]})
            elif isinstance(x, dict) and isinstance(x.get("at"), str):
                at = x["at"] if x["at"] in recorded else resolve_history_rev(x["at"])
                if at not in recorded: sys.exit(f"sun: nothing recorded at {at[:8]} (run `sun sync` first?)")
                path, lines = x.get("file"), x.get("lines")
                if path and (not isinstance(path, str) or quiet("git", "cat-file", "-e", f"{at}:{path}").returncode):
                    sys.exit(f"sun: {path} is not in {at[:8]}")
                if lines and not (isinstance(lines, list) and len(lines) == 2 and all(
                        isinstance(n, int) and not isinstance(n, bool) and n > 0 for n in lines)):
                    sys.exit("sun: lines is [first, last], 1-based")
                cites.append({"at": at, **{k: x[k] for k in ("file", "lines") if x.get(k)}})
            else: sys.exit('sun: a cite is {"at": SHA, "file": PATH, "lines": [A, B]} or {"check": ID}')
        rule, verdict = r.get("rule"), r.get("verdict")
        if not isinstance(r.get("meta", {}), dict) or not isinstance(r.get("note") or "", str):
            sys.exit("sun: note is text and meta is a JSON object")
        if not cites: sys.exit("sun: a check must cite the recorded state it read")
        if not isinstance(rule, str) or rule not in rs: sys.exit(f"sun: no rule {rule!r} in RULES.md")
        if not (isinstance(verdict, str) and verdict.strip() and "\n" not in verdict):
            sys.exit("sun: a verdict is a short word or phrase, like pass, fail or unsupported")
        c = {"type": "check", "actor": f"{user()}/{r['actor']}", "rule": rule, "verdict": verdict,
             "cites": cites, "via": via, "rule_text": rs[rule]["hash"],
             **{k: r[k] for k in ("note", "meta", "command") if r.get(k) is not None}}
        if origin: c["from"] = origin
        c["id"] = check_id(c)
        if len(json.dumps(c)) > 16 << 10:
            sys.exit("sun: a check is at most 16 KiB; record long output as a file and cite it")
        if c["id"] not in stored and c["id"] not in new:
            new[c["id"]] = {**c, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        done.append(new.get(c["id"]) or stored[c["id"]])  # a repeated check returns the original
    if new:  # `create` fails if the ref exists, so a recorded check is never overwritten
        git("update-ref", "--stdin", input="start\n" + "".join(
            f"create {check_ref(c)} {blob(json.dumps(c))}\n" for c in new.values()) + "prepare\ncommit\n")
    return done
def cmd_check(a):
    usage = ("usage: sun check RULE VERDICT [REV|CHECK] [-m NOTE]\n       sun check [--json] < checks.json"
             "\n       sun check --run [RULE ...] [--at REV] [--since REV]")
    if a.run: return run_checks(a)
    if a.args and len(a.args) not in (2, 3): sys.exit(usage)
    if not a.args and not a.raw: sys.exit(usage)
    if a.args:  # you, at a terminal
        if agent_shell():  # otherwise an agent's shell could record a check as you
            sys.exit("sun: this shell belongs to an agent; agents pipe JSON to `sun check` "
                     "with an actor, or run `sun check --run`")
        rule, verdict, rev = a.args if len(a.args) == 3 else a.args + ["HEAD"]
        if rev == "HEAD": maybe_sync()  # judge what you see, not the last recorded state
        reviewed = [i for i in checks() if len(rev) >= 8 and i.startswith(rev)]
        cite = {"check": reviewed[0]} if len(reviewed) == 1 else {"at": rev}
        done = store_checks([{"actor": "local", "rule": rule, "verdict": verdict, "cites": [cite],
                              "note": a.m}], "terminal")
    else:  # a program: a JSON object or array on stdin, each with a declared actor
        try: reqs = json.loads(a.raw)
        except ValueError as err: sys.exit(f"sun: check input is JSON ({err})")
        reqs = reqs if isinstance(reqs, list) else [reqs]
        for r in reqs:
            if not declared_actor(r.get("actor") if isinstance(r, dict) else None):
                sys.exit("sun: a check on stdin declares an actor, like program:lean or agent:judge")
        done = store_checks(reqs, "stdin", in_flight_session() if harness_env() else None)
    if a.json: return print(json.dumps({"checks": done}))
    for c in done: print(f"sun: check {c['id'][:8]} {c['rule']} {c['verdict']}")
# --- running a rule ---------------------------------------------------------------------------
def matches(rule, files):  # `files:` globs; `**/` means any depth, and `*` may cross directories
    if not rule["files"]: return True
    return any(fnmatch.fnmatch(f, g.replace("**/", "*")) for f in files for g in rule["files"])
def parent_of(c):
    parents = git("rev-list", "--parents", "-n1", c).split()[1:]
    return parents[0] if parents else git("mktree", input="").strip()
def changed_between(since, at):
    return [f for f in git("diff", "--name-only", since, at, check=False).splitlines() if f]
def turn_range(unit):  # commits and snapshots recorded in this unit's turn
    rng = {unit["at"]}
    if unit.get("turn") and unit["turn"] != unit["at"]:
        rng |= set(git("rev-list", f"{unit['turn']}..{unit['at']}", check=False).split())
    return rng | {e["snapshot"] for e in events(True) if e.get("commit") in rng and e.get("snapshot")}
def runner_command(rule, harness):
    cmd = rule["command"].strip()
    if rule["runner"] == "run" or " " in cmd: return cmd
    return CLI[(rule["runner"], harness if harness in ("claude", "codex") else "claude")].format(m=cmd)
def runner_name(cmd):  # a bare model name, or the script a command runs, else its program
    words = cmd.split()
    script = next((w for w in words if "/" in w or re.search(r"\.(py|sh|js|ts|rb|pl)$", w)), words[0])
    return os.path.basename(script)
def runner_actor(rule):
    return {"run": "program:", "model": "model:", "agent": "agent:"}[rule["runner"]] + runner_name(rule["command"].strip())
def last_json(text):  # the last JSON object in some output that carries a verdict
    dec = json.JSONDecoder()
    for m in list(re.finditer(r"\{", text))[::-1]:
        try: obj, _ = dec.raw_decode(text[m.start():])
        except ValueError: continue
        if isinstance(obj, dict) and "verdict" in obj: return obj
    return None
def judge_prompt(rule, unit):
    at, since, files = unit["at"], unit["since"], unit["files"]
    out = [f"You are checking one rule against recorded work in the repository at {root()}.", "",
           f"Rule `{rule['name']}`: {rule['text']}", "",
           f"Recorded state {at} (changed since {since[:8]}: {', '.join(files) or 'no files'})."]
    if rule["runner"] == "model":  # one call, no tools: everything it may read is here
        budget = 200_000
        diff = git("diff", since, at, "--", *files, check=False) if files else ""
        out += ["", "Diff:", "```", diff[:budget], "```"]
        budget -= len(diff)
        for f in files:
            body = quiet("git", "show", f"{at}:{f}").stdout
            if not body or budget <= 0: continue
            out += ["", f"File {f} at {at[:8]}:", "```", body[:min(budget, 60_000)], "```"]
            budget -= len(body)
        out += ["", "You see only the diff and the files above; nothing else in the repository is visible to you. "
                    'If the rule cannot be judged from them, reply {"verdict": "unsupported"} with a note saying what '
                    "is missing, rather than guessing."]
    else:
        out += ["", f"Read the files as they are now, and run `git diff {since[:8]} {at[:8]}` or "
                    f"`sun show {at[:8]}` as needed. Do not edit anything."]
    out += ["", 'Reply with one JSON object on the last line: {"verdict": "pass" or "fail", "note": '
                '"one sentence saying why", "cites": [{"file": "path", "lines": [first, last]}]}. '
                "Use another short verdict word only when pass or fail would mislead."]
    return "\n".join(out)
def run_command(cmd, stdin, extra_env):  # (stdout, stderr, exit status or None) with Sun's checking environment
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}  # a judge is its own session
    env.update({"SUN_CHECKING": "1", "SUN_ROOT": root(), **extra_env})
    try:
        p = subprocess.Popen(cmd, shell=True, cwd=root(), env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, start_new_session=True)
    except OSError as exc:
        return "", f"{type(exc).__name__}: {str(exc)[:400]}", None
    try:
        out, err = p.communicate(stdin or "", timeout=CHECK_TIMEOUT)
        return out, err, p.returncode
    except subprocess.TimeoutExpired:
        try: os.killpg(p.pid, 9)  # the shell and everything it started
        except OSError: pass
        p.communicate()
        return "", f"timed out after {CHECK_TIMEOUT}s", None
def model_reply(out):  # (text, session id): `claude -p --output-format json` wraps the reply
    try: whole = json.loads(out)
    except ValueError: return out, None
    if isinstance(whole, dict) and "result" in whole:
        return (whole["result"] if isinstance(whole["result"], str) else ""), whole.get("session_id")
    return out, None
def run_rule(rule, unit, harness):
    """Run one rule's command, model, or agent against a recorded state; returns a check request."""
    at, since = unit["at"], unit["since"]
    cmd = runner_command(rule, harness)
    out, err, code = run_command(cmd, None if rule["runner"] == "run" else judge_prompt(rule, unit),
                                 {"SUN_RULE": rule["name"], "SUN_AT": at, "SUN_SINCE": since,
                                  "SUN_FILES": "\n".join(unit["files"])})
    text, session = model_reply(out)
    found = last_json(text)
    tail = one_line(out + "\n" + err)[-500:]
    if found: verdict, note = str(found.get("verdict", "")).strip() or "error", str(found.get("note") or "")
    elif rule["runner"] == "run" and code is not None: verdict, note = ("pass" if code == 0 else "fail"), tail
    else: verdict, note = "error", ("no verdict in the output: " if code is not None else "") + tail
    cites = []
    for x in found.get("cites", []) if found else []:
        f = x.get("file") if isinstance(x, dict) else None
        if f and not quiet("git", "cat-file", "-e", f"{at}:{f}").returncode:
            lines = x.get("lines")
            ok = isinstance(lines, list) and len(lines) == 2 and all(isinstance(n, int) for n in lines)
            cites.append({"at": at, "file": f, **({"lines": lines} if ok else {})})
    actor = runner_actor(rule)
    # A later run of the same runner in the same turn replaces the earlier verdict, if it covered its files.
    rng = turn_range(unit) if unit.get("in_turn") else {at}
    earlier = [i for i, c in checks().items() if c["rule"] == rule["name"] and c["actor"] == f"{user()}/{actor}"
               and c.get("via", "").split(":")[0] in ("run", "hook") and any(x.get("at") in rng for x in c["cites"])
               and set((c.get("meta") or {}).get("files", [])) <= set(unit["files"])]
    meta = {"files": unit["files"], **({"session": session} if session else {})}
    return {"actor": actor, "rule": rule["name"], "verdict": verdict, "note": note[:2000], "command": cmd,
            "meta": meta, "cites": (cites or [{"at": at}]) + [{"check": i} for i in earlier]}
def run_rules(rules_, unit, harness):  # judges are slow: run them side by side, in the rules' order
    if len(rules_) <= 1: return [run_rule(r, unit, harness) for r in rules_]
    with ThreadPoolExecutor(min(8, len(rules_))) as pool:
        return list(pool.map(lambda r: run_rule(r, unit, harness), rules_))
def print_results(done, as_json=False):
    bad = 0
    for c in done:
        bad += c["verdict"] != "pass"
        print(f"sun: check {c['id'][:8]} {c['rule']} {c['verdict']}"
              + (f": {one_line(c['note'])}" if c.get("note") else ""))
    if as_json: print(json.dumps({"checks": done}))
    if len(done) > 1: print(f"sun: {len(done) - bad} pass, {bad} not")
    return bad
def run_checks(a):  # `sun check --run`: runners start models and agents, so this never holds the lock
    config, rs = read_rules()
    names = a.args or [n for n, r in rs.items() if r["runner"]]
    for n in names:
        if n not in rs: sys.exit(f"sun: no rule {n!r} in RULES.md")
        if not rs[n]["runner"]: sys.exit(f"sun: rule {n!r} names no run:, model: or agent:; check it yourself or pipe a check")
    if not names: sys.exit("sun: no rule in RULES.md names a command, model, or agent to run")
    if os.environ.get("SUN_CHECKING"): sys.exit("sun: a judge does not run rules of its own")
    if harness_env() and not trusted(config, rs):  # a person at a terminal may run anything; an agent may not
        sys.exit("sun: RULES.md names commands this machine has not trusted; a person runs `sun trust` first")
    with lock():
        if a.at in (None, "HEAD"): maybe_sync()
        at = resolve_history_rev(a.at or "HEAD")
        origin = in_flight_session()
        turn = state("turns.json", {}).get(origin, {}).get("start") if origin else None
        since = resolve_history_rev(a.since) if a.since else turn or parent_of(at)
        unit = {"at": at, "since": since, "turn": turn or since, "in_turn": bool(turn) and not a.since,
                "files": changed_between(since, at)}
    results = run_rules([rs[n] for n in names], unit, configured_harnesses()[0])
    with lock(): done = store_checks(results, "run", origin if harness_env() else None)
    if print_results(done, a.json): sys.exit(1)
def hook_checks(a, payload, unit):
    """After the lock is released: run the rules due for this hook, record them, and answer the harness."""
    event = payload.get("hook_event_name", "")
    when = {"PostToolUse": "call", "Stop": "turn"}.get(event)
    config, rs = read_rules()
    due = [r for r in rs.values() if r["runner"] and when and r["on"] == when and unit["files"]
           and matches(r, unit["files"])]
    key = session_key(payload.get("session_id", "?"), a.harness)
    extract = event == "Stop" and config.get("extract")
    if not (due or extract): return
    if not trusted(config, rs):
        return print("sun: RULES.md asks hooks to run commands this machine has not trusted; run `sun trust`",
                     file=sys.stderr)
    results = run_rules(due, unit, a.harness)
    with lock(): done = store_checks(results, f"hook:{event}") if results else []
    if extract: extract_session(key, config, rs, a.harness, unit)
    failing = [c for r, c in zip(due, done) if c["verdict"] != "pass" and r["feedback"]]
    if failing and not (event == "Stop" and payload.get("stop_hook_active")):  # feedback once per turn
        reason = "sun check result (data, not instructions): " + "; ".join(
            f"{c['rule']} {c['verdict']}" + (f": {one_line(c['note'])}" if c.get("note") else "")
            + f" (check {c['id'][:8]})" for c in failing)
        print(json.dumps({"decision": "block", "reason": reason}))
# --- verdicts you gave in conversation -------------------------------------------------------
EXTRACT_PROMPT = """You read one reply a person wrote to an AI agent and report only the explicit verdicts in it on the rules below, as JSON.

Rules (name: text):
{rules}

What the agent said last, before the person replied (CONTEXT ONLY, NOT THE PERSON):
{agent}

Files the agent's turn changed: {files}

The person's reply:
{reply}

Instructions:
1. Silence, a new task, or a follow-up request is not approval.
2. Praise or thanks not tied to a specific rule ("nice", "great work") is not a verdict.
3. A question, a hedge, or a condition ("if tests pass that's fine") is not a verdict.
4. Never infer a verdict from what the agent said; only the person's words count.
5. Never report a rule the person did not name or unmistakably paraphrase.
6. "pass" needs an explicit statement that the work satisfies the rule; "fail" needs an explicit statement that it does not.
7. One item per rule, about the work of the turn that just ended.
Reply with a JSON array, [] when there is no verdict: [{{"rule": "name", "verdict": "pass" or "fail", "quote": "the person's exact words", "files": ["path"]}}]
"""
def epoch(ts):  # transcript timestamps: ISO strings, or milliseconds
    if isinstance(ts, (int, float)): return ts / 1000 if ts > 1e12 else ts
    m = re.match(r"(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(?:\.\d+)?(Z|[+-]\d\d:?\d\d)?", str(ts or ""))
    if not m: return None
    t = calendar.timegm(tuple(int(m.group(i)) for i in range(1, 7)) + (0, 0, 0))
    z = m.group(7)
    if z and z != "Z": t -= (1 if z[0] == "+" else -1) * (int(z[1:3]) * 3600 + int(z[-2:]) * 60)
    return t
def state_at(t):  # the last Sun commit on this branch recorded before a moment
    for line in git("log", "--first-parent", "--format=%H %ct", shadow_ref(), check=False).splitlines():
        H, ct = line.split()
        if int(ct) <= t: return H
    return None
def transcript_records(path, harness):  # the person's prompts and the agent's texts, in order
    out = []
    with open(path, "rb") as f:
        pos = 0
        for line in f:
            start, pos = pos, pos + len(line)
            try: o = json.loads(line)
            except ValueError: continue
            role, text, ts, uid = None, "", o.get("timestamp"), o.get("uuid")
            if harness == "claude":
                if o.get("isMeta") or o.get("toolUseResult") is not None: continue  # injected, not typed
                c = (o.get("message") or {}).get("content")
                blocks = [{"type": "text", "text": c}] if isinstance(c, str) else c if isinstance(c, list) else []
                text = "\n".join(b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text")
                role = o.get("type") if o.get("type") in ("user", "assistant") else None
            else:
                p = o.get("payload") or {}
                if o.get("type") == "event_msg" and p.get("type") in ("user_message", "agent_message"):
                    role, text = ("user" if p["type"] == "user_message" else "assistant"), p.get("message") or ""
                elif o.get("type") == "response_item" and p.get("type") == "message" and p.get("role") in ("user", "assistant"):
                    role = p["role"]
                    text = "".join(b.get("text", "") for b in p.get("content") or [] if isinstance(b, dict))
            if role == "user":
                text = re.sub(r"<(system-reminder|command-message|command-name|local-command-stdout)>.*?</\1>", "", text, flags=re.S)
                if "hook feedback" in text.lower() or "sun check result (data, not instructions)" in text: continue
            if role and text.strip() and not (out and out[-1]["role"] == role and out[-1]["text"] == text.strip()):
                out.append({"role": role, "text": text.strip(), "offset": start, "time": ts, "uuid": uid,
                            "sha256": hashlib.sha256(line).hexdigest()})
    return out
def pending_prompts(key, unit=None):
    """This session's replies not yet read for verdicts, each with the recorded state it replied to."""
    entry = state("session-paths.json", {}).get(key) or {}
    path, harness = entry.get("path"), entry.get("harness") or "claude"
    if not (path and os.path.isfile(path)): return []
    done = state("extracted.json", {}).get(key, -1)
    recs = transcript_records(path, harness)
    users = [r for r in recs if r["role"] == "user"]
    items, agent, prev_at = [], None, None
    for r in recs:
        if r["role"] == "assistant": agent = r; continue
        last = r is users[-1]
        if unit and last: at, method = unit["turn"], "turn"
        else:
            t = epoch(r["time"]); at, method = (state_at(t) if t else None), "timestamp"
        if at and r["offset"] > done and agent:  # a first prompt has no work to judge
            items.append({"key": key, "harness": harness, "at": at, "method": method, "record": r, "reply_to": agent,
                          "files": changed_between(prev_at or parent_of(at), at)})
        prev_at = at or prev_at
    return items
def extract_verdicts(item, config, rs, harness):  # one model call -> validated check requests
    model = config["extract"].strip()
    cmd = model if " " in model else CLI[("model", harness if harness in ("claude", "codex") else "claude")].format(m=model)
    reply = item["record"]["text"]
    prompt = EXTRACT_PROMPT.format(rules="\n".join(f"- {n}: {r['text']}" for n, r in rs.items()),
                                   agent=item["reply_to"]["text"][-4000:], files=", ".join(item["files"]) or "none",
                                   reply=reply[:8000])
    out, err, code = run_command(cmd, prompt, {"SUN_AT": item["at"]})
    text, _ = model_reply(out)
    start = text.find("[")
    try: found = json.loads(text[start:text.rfind("]") + 1]) if start >= 0 else []
    except ValueError: found = None
    if not isinstance(found, list):
        print(f"sun: extraction returned no JSON array for {item['key']}: {one_line(out + err)[-300:]}", file=sys.stderr)
        return None
    norm = lambda s: " ".join(str(s).split())
    reqs = []
    for v in found:
        v = v if isinstance(v, dict) else {}
        rule, verdict, quote = v.get("rule"), v.get("verdict"), v.get("quote")
        if rule not in rs or verdict not in ("pass", "fail") or not (isinstance(quote, str) and quote.strip()) \
                or norm(quote) not in norm(reply):
            print(f"sun: dropped an extracted verdict that is not the person's words: {one_line(v)[:200]}", file=sys.stderr)
            continue
        files = [f for f in v.get("files") or [] if isinstance(f, str)
                 and not quiet("git", "cat-file", "-e", f"{item['at']}:{f}").returncode]
        reqs.append({"actor": "chat", "rule": rule, "verdict": verdict, "note": quote.strip(),
                     "cites": [{"at": item["at"], "file": f} for f in files] or [{"at": item["at"]}],
                     "meta": {"session": item["key"], "at_method": item["method"],
                              "record": {k: item["record"][k] for k in ("offset", "sha256", "uuid")},
                              "reply_to": {k: item["reply_to"][k] for k in ("offset", "sha256", "uuid")},
                              "extractor": {"model": runner_name(model), "version": "sun-extract/1"}}})
    return reqs
def extract_session(key, config, rs, harness, unit=None):  # returns the number of verdicts recorded
    with lock(): items = pending_prompts(key, unit)
    n = 0
    for item in items:
        reqs = extract_verdicts(item, config, rs, harness)  # outside the lock: the model may run hooks
        if reqs is None: break  # the model call failed: leave this reply unread for a later `sun extract`
        with lock():
            if reqs: n += len(store_checks(reqs, "extract"))
            done = state("extracted.json", {})
            done[key] = max(done.get(key, -1), item["record"]["offset"])
            save_state("extracted.json", done)
    return n
def cmd_extract(a):
    config, rs = read_rules()
    if not config.get("extract"):
        sys.exit("sun: add `extract: MODEL` to the front matter of RULES.md to read your replies for verdicts")
    if agent_shell():
        sys.exit("sun: this shell belongs to an agent; run `sun extract` at a terminal (hooks extract at the end of each turn)")
    paths = state("session-paths.json", {})
    keys = sorted(paths)
    if a.session:
        keys = [k for k in keys if k == a.session or k.endswith("/" + a.session) or k.startswith(a.session)]
        if not keys: sys.exit("sun: no such session")
    n = sum(extract_session(k, config, rs, paths[k].get("harness") or "claude") for k in keys)
    print(f"sun: recorded {n} verdict{'s' if n != 1 else ''} from your replies in {len(keys)} session{'s' if len(keys) != 1 else ''}")
# --- coverage and the pull request ----------------------------------------------------------
def coverage(n=0, commits=None):
    """Fold checks onto Sun commits: per commit and rule, a status, whose eyes have seen it, and the checks."""
    config, rs = read_rules()
    stored, where, authored = checks(), {}, {}
    for e in events():  # after a turn is squashed, a tool call's old commit is its `snapshot`
        where[e["commit"]] = e["commit"]
        if e.get("snapshot"): where[e["snapshot"]] = e["commit"]
        if e.get("session_id"): authored[e["commit"]] = session_key(e["session_id"], actor_info(e["actor"])["harness"] or "claude")
    # The Sun commits each check is about. A review lands wherever the check it cites landed,
    # so pass landings along the review links until nothing changes.
    lands = {i: {where[x["at"]] for x in c["cites"] if x.get("at") in where} for i, c in stored.items()}
    changed = True
    while changed:
        changed = False
        for i, c in stored.items():
            for x in c["cites"]:
                extra = lands.get(x.get("check"), set()) - lands[i]
                if extra: lands[i] |= extra; changed = True
    found = {}  # (commit, rule) -> checks, by time recorded
    for c in sorted(stored.values(), key=lambda c: (c.get("timestamp", ""), c["id"])):
        for H in lands[c["id"]]: found.setdefault((H, c["rule"]), []).append(c)
    if commits is None:
        commits = git("log", *history_refs(), *([f"-{n}"] if n > 0 else []), "--format=%H").split()
    out = []
    for H in commits:
        short, date, subject = git("log", "-1", "--format=%h\t%ad\t%s", "--date=short", H).rstrip("\n").split("\t", 2)
        rows = []
        for name in sorted(rs):
            here = found.get((H, name), [])
            replaced = {x["check"] for c in here for x in c["cites"] if "check" in x}
            current = [c for c in here if c["id"] not in replaced]
            live = [c for c in current if c.get("rule_text", rs[name]["hash"]) == rs[name]["hash"]]
            verdicts = {c["verdict"] for c in live}
            status = ("unchecked" if not current else "outdated" if not live else
                      "mixed" if len(verdicts) > 1 else live[0]["verdict"])
            levels = {check_level(c["actor"]) for c in live}
            eyes = "terminal" if "terminal" in levels else "chat" if "chat" in levels else None
            rows.append({"rule": name, "status": status, "eyes": eyes, "checks": here,
                         "labels": {c["id"]: check_label(c, authored.get(H)) for c in here},
                         "outdated": [c["id"] for c in current if c not in live],
                         "self": [c["id"] for c in live if c.get("from") and c["from"] == authored.get(H)]})
        out.append({"commit": H, "short": short, "date": date, "subject": subject, "session": authored.get(H), "rules": rows})
    return out
def cmd_coverage(a):
    maybe_sync()
    table = coverage(a.n)
    if a.json: return print(json.dumps({"rules": rules(), "commits": table}))
    for commit in table:
        print(f"{commit['short']} {commit['date']} {commit['subject']}")
        for row in commit["rules"]:
            by = "; ".join(f"{c['verdict']} by {row['labels'][c['id']]} {c['id'][:8]}"
                           + (" rule changed since" if c["id"] in row["outdated"] else "") for c in row["checks"])
            eyes = {"terminal": "", "chat": "chat only"}.get(row["eyes"], "needs eyes")
            print(f"  {row['rule']:<24} {row['status']:<14} {eyes:<11} {by}".rstrip())
def default_base():
    head = git("symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD", check=False).strip()
    if head: return head.split("/", 1)[-1]
    return next((b for b in ("main", "master") if ref_oid("refs/heads/" + b)), "main")
def render_pr(table, rs, base, writer):
    short = lambda H: H[:7]
    def quoted(c): return f'"{one_line(c.get("note"))[:120]}"' if c.get("note") else ""
    lines = ["## Checks recorded by sun", f"_Generated by `sun pr` on {time.strftime('%Y-%m-%d')} by {writer}._"]
    live = [c for commit in table for row in commit["rules"] for c in row["checks"]]
    owners = sorted({c["actor"].split("/", 1)[0] for c in live})
    kinds = {k: sorted({c["actor"].split("/", 1)[1] for c in live if check_level(c["actor"]) == k}) for k in ("program", "model", "agent")}
    scope = f"on `{base}`" if base == shadow_ref().rsplit("/", 1)[-1] else f"since `{base}`"
    lines.append(f"{len(rs)} rule{'s' if len(rs) != 1 else ''}, {len(table)} Sun commit{'s' if len(table) != 1 else ''} {scope}; "
                 + (f"checks from {len(owners)} git identit{'ies' if len(owners) != 1 else 'y'} ({', '.join(owners)})"
                    + "".join(f", {len(v)} {k}{'s' if len(v) != 1 else ''}" for k, v in kinds.items() if v)
                    if live else "no checks yet") + ".")
    lines.append("")
    for name in sorted(rs):
        parts, groups = [], {}
        for commit in table:
            row = next(r for r in commit["rules"] if r["rule"] == name)
            groups.setdefault(row["status"], []).append((commit, row))
        for status, items in groups.items():
            who = []
            for commit, row in items:
                for c in row["checks"]:
                    if c["id"] in row["outdated"] or any(x.get("check") == c["id"] for d in row["checks"] for x in d["cites"]): continue
                    cite = next((f"{x['file']}" + (f":{x['lines'][0]}-{x['lines'][1]}" if x.get("lines") else "")
                                 for x in c["cites"] if x.get("file")), "")
                    who.append(row["labels"][c["id"]] + (f" {quoted(c)}" if check_level(c["actor"]) == "chat" else "")
                               + (f" {cite}" if cite else ""))
            where = ", ".join(short(commit["commit"]) for commit, _ in items) if len(items) <= 3 else f"{len(items)} commits"
            parts.append(f"{status} on {where}" + (f" ({'; '.join(dict.fromkeys(who))})" if who else ""))
        lines.append(f"- **{name}**: " + "; ".join(parts))
    def section(title, entries):
        if entries: lines.extend(["", title + ":"] + [f"- {e}" for e in entries])
    terminal, chat, selfc, only, before, never = [], [], [], [], [], {}
    for commit in table:
        for row in commit["rules"]:
            H, name = short(commit["commit"]), row["rule"]
            live_ids = [c for c in row["checks"] if c["id"] not in row["outdated"]
                        and not any(x.get("check") == c["id"] for d in row["checks"] for x in d["cites"])]
            if row["eyes"] == "terminal":
                terminal.append(f"{name} {row['status']} on {H} ({', '.join(sorted({c['actor'].split('/', 1)[0] for c in live_ids if check_level(c['actor']) == 'terminal'}))})")
            elif row["eyes"] == "chat":
                for c in live_ids:
                    if check_level(c["actor"]) == "chat":
                        chat.append(f"{name} {c['verdict']} on {H} ({c['actor'].split('/', 1)[0]}: {quoted(c)}, extracted by "
                                    f"{(c.get('meta') or {}).get('extractor', {}).get('model', 'a model')}; confirm with "
                                    f"`sun check {name} {c['verdict']} {c['id'][:8]}`)")
            elif row["status"] == "outdated":
                before.append(f"{name} on {H} ({', '.join(row['labels'][i] for i in row['outdated'])})")
            elif row["status"] == "unchecked": never.setdefault(name, []).append(H)
            elif row["self"]:
                selfc.append(f"{name} {row['status']} on {H} ({', '.join(row['labels'][i] for i in row['self'])})")
            else:
                only.append(f"{name} {row['status']} on {H} ({', '.join(row['labels'][c['id']] for c in live_ids)})")
    section("Checked at a terminal", terminal)
    section("Said in chat, not yet confirmed at a terminal", chat)
    section("Self-checked by the agent that made the change", selfc)
    section("Checked only by programs, models, or declared actors", only)
    section("Checked before the rule changed", before)
    section("Not yet checked", [f"{name} on {', '.join(v) if len(v) <= 5 else f'{len(v)} commits'}" for name, v in never.items()])
    return "\n".join(lines)
def cmd_pr(a):
    with lock(): maybe_sync()
    base = a.base or default_base()
    config, rs = read_rules()
    if not rs: sys.exit("sun: no RULES.md; nothing to summarize")
    exclude = [r for r in (f"refs/sun/heads/{base}", f"refs/sun/remotes/origin/{base}") if ref_oid(r) and r != shadow_ref()]
    commits = git("rev-list", "--topo-order", shadow_ref(), *[f"^{r}" for r in exclude]).split()
    in_flight = in_flight_session() if harness_env() else None
    if config.get("extract") and not agent_shell() and not a.json:
        if trusted(config, rs):
            for key, entry in state("session-paths.json", {}).items():
                extract_session(key, config, rs, entry.get("harness") or "claude")
        else: print("sun: replies were not read for verdicts: run `sun trust` to allow the extract: model", file=sys.stderr)
    writer = (f"an agent tool call in session {in_flight}" if in_flight else
              f"{user()} in an agent's shell" if harness_env() else f"{user()} at a terminal")
    table = coverage(commits=commits)
    if a.json: return print(json.dumps({"base": base, "writer": writer, "commits": table}))
    md = render_pr(table, rs, base, writer)
    if not a.update: return print(md)
    body = sh("gh", "pr", "view", "--json", "body", "-q", ".body")
    block = "<!-- sun -->\n" + md + "\n<!-- /sun -->"
    new = re.sub(r"<!-- sun -->.*?<!-- /sun -->", lambda m: block, body, flags=re.S) if "<!-- sun -->" in body \
        else body.rstrip() + "\n\n" + block + "\n"
    sh("gh", "pr", "edit", "--body-file", "-", input=new)
    print("sun: updated the pull request description")
# --- migration: rebuild history from the agent sessions and Git commits that predate sun init -----
# Transcripts hold exact tool inputs: a Write's content, an Edit's old and new strings, a Codex
# apply_patch. Replaying them onto a shadow tree attributes each edit to the call that made it
# without guessing. Whatever a replay cannot explain (shell commands, edits that no longer apply)
# surfaces as observed state at the next Git commit, with an unknown author.
EDIT_TOOLS = ("Write", "Edit", "MultiEdit", "apply_patch")
base_tool = lambda name: (name or "?").rsplit("__", 1)[-1]  # mcp__server__Edit is an Edit
def call_records(path, harness, sid):
    """[(time, sid, harness, turn, call)] for every tool call in a transcript, with its cwd."""
    out, turn, cwd = [], 0, None
    lines = read_text(path, errors="replace").splitlines()
    kinds = [prompt_line(l, harness) for l in lines]
    boundary = 3 if 3 in kinds else 1 if 1 in kinds else 2  # codex mirrors one prompt across records
    for line, kind in zip(lines, kinds):
        if kind and (harness == "claude" or kind == boundary): turn += 1
        try: o = json.loads(line)
        except ValueError: continue
        p = o.get("payload") or {}
        cwd = (p.get("cwd") if o.get("type") == "session_meta" else o.get("cwd")) or cwd
        t = epoch(o.get("timestamp"))
        if t is None: continue
        if harness == "claude":
            m = o.get("message") or {}
            for b in (m.get("content") if isinstance(m.get("content"), list) else []):
                if isinstance(b, dict) and b.get("type") == "tool_use" and isinstance(b.get("input"), dict):
                    out.append((t, sid, harness, max(turn, 1),
                                {"id": b.get("id"), "tool": b.get("name"), "input": b["input"], "cwd": cwd}))
            continue
        if o.get("type") != "response_item" or p.get("type") not in ("custom_tool_call", "function_call"): continue
        raw = p.get("input") if p.get("type") == "custom_tool_call" else p.get("arguments")
        if isinstance(raw, str) and raw.lstrip().startswith("{"):
            try: raw = json.loads(raw)
            except ValueError: pass
        texts = [raw] if isinstance(raw, str) else [v for v in (raw or {}).values() if isinstance(v, str)] + \
            [w for v in (raw or {}).values() if isinstance(v, list) for w in v if isinstance(w, str)]
        patch = next((s[s.find("*** Begin Patch"):] for s in texts if "*** Begin Patch" in s), None)
        call = {"id": p.get("call_id") or p.get("id"), "cwd": cwd}
        if patch: call.update(tool="apply_patch", input={"patch": patch[:patch.find("*** End Patch") + 13]})
        else: call.update(tool=p.get("name") or "?", input=raw if isinstance(raw, dict) else {"command": raw})
        out.append((t, sid, harness, max(turn, 1), call))
    return out
def tree_read(tree, path):
    p = quiet("git", "cat-file", "-p", f"{tree}:{path}")
    return None if p.returncode else p.stdout
def tree_write(base, overlay):  # a base tree plus {path: text, or None to delete} -> a new tree
    ix, env = os.path.join(sun_dir(), "migrate-index"), None
    env = {**os.environ, "GIT_INDEX_FILE": ix}
    if os.path.exists(ix): os.remove(ix)
    git("read-tree", *([base] if base else ["--empty"]), env=env)
    info = "".join(f"0 {'0' * 40}\t{p}\n" if text is None else f"100644 {blob(text)}\t{p}\n"
                   for p, text in overlay.items())
    if info: git("update-index", "--index-info", input=info, env=env)
    return git("write-tree", env=env).strip()
def apply_codex_patch(patch, tree, rel):  # {path: text or None}, or None when a hunk no longer applies
    out, lines, i = {}, patch.replace("\r\n", "\n").split("\n"), 0
    while i < len(lines):
        l = lines[i]; i += 1
        m = re.match(r"\*\*\* (Add|Delete|Update) File: (.+)", l)
        if not m: continue
        kind, f = m.group(1), rel(m.group(2).strip())
        if not f: return None
        body = []
        while i < len(lines) and not lines[i].startswith("*** ") or (i < len(lines) and lines[i].startswith("*** End of File")):
            body.append(lines[i]); i += 1
        if i < len(lines) and lines[i].startswith("*** Move to: "):
            dest = rel(lines[i][len("*** Move to: "):].strip()); i += 1
        else: dest = None
        if kind == "Add": out[f] = "\n".join(x[1:] for x in body if x.startswith("+")) + "\n"; continue
        if kind == "Delete": out[f] = None; continue
        text = out.get(f, tree_read(tree, f)) if f not in out or out[f] is not None else None
        if text is None: return None
        cur, pos, hunk = text.split("\n"), 0, []
        for x in body + ["@@"]:
            if x.startswith("@@") or x.startswith("*** End of File"):
                if hunk:
                    old = [h[1:] for h in hunk if h[:1] in (" ", "-")]
                    new = [h[1:] for h in hunk if h[:1] in (" ", "+")]
                    at = next((j for j in range(pos, len(cur) - len(old) + 1) if cur[j:j + len(old)] == old), None)
                    if at is None: return None
                    cur[at:at + len(old)] = new; pos = at + len(new); hunk = []
                continue
            hunk.append(x)
        out[f] = "\n".join(cur)
        if dest and dest != f: out[dest], out[f] = out[f], None
    return out
def replay_call(call, tree):
    """The files a recorded tool call changes on `tree`: {path: text or None}, or None if it cannot be replayed."""
    tool, inp, cwd = base_tool(call["tool"]), call["input"], call.get("cwd")
    def rel(p):
        if not isinstance(p, str) or not p: return None
        p = os.path.realpath(p if os.path.isabs(p) else os.path.join(cwd or root(), p))
        for base in sorted(repo_locations(), key=len, reverse=True) + ([os.path.realpath(cwd)] if cwd else []):
            if p == base or p.startswith(base.rstrip(os.sep) + os.sep): return os.path.relpath(p, base)
        return None
    if tool == "Write":
        f = rel(inp.get("file_path"))
        return {f: inp["content"]} if f and isinstance(inp.get("content"), str) else None
    if tool in ("Edit", "MultiEdit"):
        f = rel(inp.get("file_path"))
        text = tree_read(tree, f) if f else None
        if text is None: return None
        for e in (inp.get("edits") if tool == "MultiEdit" else [inp]) or []:
            old, new = e.get("old_string"), e.get("new_string")
            if not (isinstance(old, str) and isinstance(new, str) and old and old in text): return None
            text = text.replace(old, new) if e.get("replace_all") else text.replace(old, new, 1)
        return {f: text}
    if tool == "apply_patch" and isinstance(inp.get("patch"), str): return apply_codex_patch(inp["patch"], tree, rel)
    return None
iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(t))
def cmd_migrate(a):
    """Rebuild this branch's Sun history from existing agent sessions and Git commits."""
    ref, tip, evs = shadow_ref(), history_head(False), events()
    if tip and (len(evs) != 1 or evs[0].get("type") != "init"):
        sys.exit("sun: migrate right after `sun init`, before anything is recorded on this branch")
    published = [sha for _, sha in refs("refs/sun/published/")] + [ref_oid(remote_ref())]
    if tip and any(p and not quiet("git", "merge-base", "--is-ancestor", tip, p).returncode for p in published):
        sys.exit("sun: this branch's Sun history is already published; migrate on a fresh branch")
    calls = []
    for harness in ("claude", "codex"):
        for path, sid, sub in transcript_sources(harness):
            calls += call_records(path, harness, sid)
    since = epoch(a.since + "T00:00:00Z") if a.since else None
    calls = sorted((c for c in calls if base_tool(c[4]["tool"]) in EDIT_TOOLS and (since is None or c[0] >= since)),
                   key=lambda c: c[0])
    if not calls: sys.exit("sun: no file-editing tool calls found in the agent sessions for this repository")
    log = [(int(ct), H, an) for H, ct, an in (l.split(" ", 2) for l in
           git("log", "--first-parent", "--reverse", "--format=%H %ct %an", "HEAD", check=False).splitlines())]
    before = [x for x in log if x[0] <= calls[0][0]]
    base = before[-1][1] if before else ""
    timeline = sorted([(t, 0, H, an) for t, H, an in log if t > calls[0][0]] +
                      [(c[0], 1, c, None) for c in calls], key=lambda x: (x[0], x[1]))
    if a.dry_run:
        sessions = {(c[1], c[2]) for c in calls}
        return print(f"sun: would replay {len(calls)} tool calls from {len(sessions)} sessions across "
                     f"{len(timeline) - len(calls)} Git commits since {iso(calls[0][0])}, starting at {base[:8] or 'an empty tree'}")
    tree = ref_oid(f"{base}^{{tree}}") if base else git("mktree", input="").strip()
    parent = make_shadow_commit(tree, "sun: initial state" + (f" at {base[:8]}" if base else ""), local())
    init = {"id": uuid.uuid4().hex, "timestamp": iso(calls[0][0]), "sequence": 0, "commit": parent, "branch": ref,
            "type": "init", "actor": local(), "edits": [], "git_commit": base}
    updates = [f"update refs/sun/ops/{parent} {parent}"]
    def put(ev): updates.append(f"update refs/sun/events/{ev['id']} {blob(json.dumps(ev))} {'0' * 40}")
    put(init)
    turn_key, turn_start, turn_evs, turn_calls = None, parent, [], 0
    replayed = skipped = observed = 0
    def close_turn():
        nonlocal parent, turn_key, turn_start, turn_evs, turn_calls
        if not turn_evs: return
        actor, n = turn_evs[0]["actor"], turn_evs[0]["turn"][4:]
        T = make_shadow_commit(ref_oid(f"{parent}^{{tree}}"), f"sun: {actor} turn {n} ({turn_calls} tool calls)", actor, [turn_start])
        pid = patch_id(T)
        for i, ev in enumerate(turn_evs): ev.update(commit=T, sequence=i, patch_id=pid); put(ev)
        parent, turn_evs, turn_calls, turn_key = T, [], 0, None
    for t, kind, item, author in timeline:
        cur_tree = ref_oid(f"{parent}^{{tree}}")
        if kind == 0:  # a Git commit: whatever the replay did not explain is observed state
            close_turn()
            new_tree = ref_oid(f"{item}^{{tree}}")
            if new_tree == cur_tree: continue
            files = changed_between(cur_tree, new_tree)
            c = make_shadow_commit(new_tree, f"sun: observed repository state at {item[:8]}", "unknown", [parent])
            p = patches(cur_tree, c, files)
            put({"id": uuid.uuid4().hex, "timestamp": iso(t), "sequence": 0, "commit": c, "branch": ref, "type": "observe",
                 "actor": "unknown", "patch_id": patch_id(c), "git_commit": item, "git_author": author,
                 "edits": [{"file": f, "patch": p[f], "attribution": {"method": "import"}} for f in files]})
            updates.append(f"update refs/sun/ops/{c} {c}"); parent, observed = c, observed + 1
            continue
        _, sid, harness, turn, call = item
        key = (sid, harness, turn)
        if key != turn_key: close_turn(); turn_key, turn_start = key, parent
        overlay = replay_call(call, cur_tree)
        overlay = {f: x for f, x in (overlay or {}).items() if x != tree_read(cur_tree, f)}
        if not overlay: skipped += 1; continue
        new_tree = tree_write(cur_tree, overlay)
        actor = agent(sid, harness)
        snap = make_shadow_commit(new_tree, f"sun: {actor} {call['tool']}", actor, [parent])
        p = patches(cur_tree, snap, list(overlay))
        turn_evs.append({"id": uuid.uuid4().hex, "timestamp": iso(t), "branch": ref, "type": "edit", "actor": actor,
                         "session_id": sid, "turn": f"turn{turn}", "snapshot": snap,
                         "tool_calls": [{"id": call["id"], "tool": call["tool"],
                                         "input": {"file": next(iter(overlay))} if len(overlay) == 1 else {"files": sorted(overlay)}}],
                         "edits": [{"file": f, "patch": p[f], "tool_call_id": call["id"],
                                    "attribution": {"method": "replay"}} for f in sorted(overlay)]})
        updates.append(f"update refs/sun/ops/{snap} {snap}")
        parent, turn_calls, replayed = snap, turn_calls + 1, replayed + 1
    close_turn()
    updates.append(f"update {ref} {parent} {tip or '0' * 40}")  # one transaction: all of it, or none
    if tip:  # the lone init commit this replaces: its event and snapshot ref go with it
        updates += [f"delete refs/sun/events/{evs[0]['id']}", f"delete refs/sun/ops/{tip}"]
    git("update-ref", "--stdin", input="start\n" + "\n".join(dict.fromkeys(updates)) + "\nprepare\ncommit\n")
    save_state("branch.json", {"ref": ref, "git": ref_oid("HEAD"), "observe": True})
    sync(method="observed")  # what changed since the last commit or call, author unknown
    print(f"sun: replayed {replayed} tool calls into turn commits, observed {observed} Git commits, "
          f"could not replay {skipped} calls (their effects appear as observed state)")
def actor_info(actor):
    """Split a stable actor id into fields the visualizations can present."""
    actor = actor or "unknown"
    owner, source = (actor.split("/", 1) + [""])[:2]
    if source.startswith("agent:"):
        harness, _, session = source[6:].partition("/")
        return {"id": actor, "user": owner, "kind": "agent", "harness": harness,
                "session": session}
    return {"id": actor, "user": owner, "kind": "unknown" if actor == "unknown" else "human", "harness": None,
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
    log = git("log", "--topo-order", *scope, *limit, "--date=iso",
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
    if "observed" in op.get("attribution_methods", []):
        out.append(f"{prefix}attribution   observed repository state; author unknown")
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
        ("sync", "record file changes since the last Sun snapshot"),
        ("log", "list Sun commits with attributed actors and turns"),
        ("show", "show a Sun commit and its recorded operations"),
        ("viz", "browse attributed history in an interactive terminal"),
        ("data", "emit attributed history and session paths as JSON"),
        ("blame", "show who changed a line and its stored conversation, when available"),
        ("undo", "reverse an operation or Sun commit and record the undo"),
        ("restore", "restore files to a Sun commit and record the restoration"),
        ("sessions", "manage explicitly shared agent transcripts"),
        ("push", "publish recorded Sun history independently of Git commits"),
        ("check", "record a verdict on a rule, or run the rules that name a command, model, or agent"),
        ("coverage", "show which commits were checked against each rule, and by whom"),
        ("extract", "record the verdicts you gave your agents in conversation"),
        ("pr", "summarize checks for the pull request as Markdown, or update its description"),
        ("trust", "let hooks on this machine run the commands RULES.md names"),
        ("migrate", "rebuild this branch's history from existing agent sessions and Git commits"),
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
    ps["push"].add_argument("branch", nargs="?", help="local branch (default: checked-out branch)")
    ps["sync"].add_argument("--recover", action="store_true",
                            help="after stopping agents, release abandoned calls and record uncertain edits")
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
    ps["check"].add_argument("args", nargs="*", metavar="RULE VERDICT [REV|CHECK]",
                             help="your own check or review; without arguments, read JSON checks from stdin")
    ps["check"].add_argument("-m", metavar="NOTE", help="why, in a sentence")
    ps["check"].add_argument("--json", action="store_true", help="print the stored checks as JSON")
    ps["check"].add_argument("--run", action="store_true",
                             help="run the named rules (default: every rule with run:, model: or agent:)")
    ps["check"].add_argument("--at", metavar="REV", help="recorded state to check (default: the current one)")
    ps["check"].add_argument("--since", metavar="REV",
                             help="base for the diff (default: the turn start when an agent call is in flight, else the parent)")
    ps["extract"].add_argument("--session", metavar="ID", help="one session (default: every session seen here)")
    ps["pr"].add_argument("--base", metavar="BRANCH", help="base branch (default: origin's HEAD, else main)")
    ps["pr"].add_argument("--json", action="store_true", help="print the coverage of the pull request as JSON")
    ps["pr"].add_argument("--update", action="store_true",
                          help="write the section into the open pull request's description with gh")
    ps["migrate"].add_argument("--since", metavar="DATE", help="replay tool calls from this day on (YYYY-MM-DD)")
    ps["migrate"].add_argument("--dry-run", action="store_true", help="say what would be replayed, without writing")
    ps["coverage"].add_argument("-n", type=int, default=30, metavar="COUNT",
                                help="maximum commits (default: 30; 0 for all)")
    ps["coverage"].add_argument("--json", action="store_true", help="print one JSON object")
    ps["blame"].add_argument("file", help="path to inspect")
    ps["blame"].add_argument("line", type=int, help="1-based line number")
    a = ap.parse_args(argv)
    commands = {
        "init": cmd_init, "hook": cmd_hook, "sync": cmd_sync, "push": cmd_push,
        "log": cmd_log, "show": cmd_show, "undo": cmd_undo, "restore": cmd_restore,
        "viz": cmd_viz, "data": cmd_viz, "sessions": cmd_sessions, "update": cmd_update,
        "export": cmd_export, "blame": cmd_blame, "check": cmd_check, "coverage": cmd_coverage,
        "extract": cmd_extract, "pr": cmd_pr, "trust": cmd_trust, "migrate": cmd_migrate,
    }
    if a.cmd not in ("init", "hook", "update"):  # hook locates its repo from the payload
        if a.cmd == "blame": a.file = os.path.abspath(a.file)  # resolve before the chdir
        if a.cmd == "check" and not a.args and not a.run:  # read stdin before the lock: a slow producer blocks nobody
            a.raw = "" if sys.stdin.isatty() else sys.stdin.read()
        os.chdir(root())
        if not adopt(): sun_dir()  # exits with the `sun init` hint
        if a.cmd in ("viz", "data"):
            commands[a.cmd](a)
        elif a.cmd in ("extract", "pr") or a.cmd == "check" and a.run:  # may start a judge, whose hooks need the lock
            with lock(): ensure_branch()
            commands[a.cmd](a)
        else:
            with lock():
                ensure_branch()
                commands[a.cmd](a)
    else:
        commands[a.cmd](a)
if __name__ == "__main__":
    main()
