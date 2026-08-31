#!/usr/bin/env python3
"""sun: an operation log for humans + agents on top of git.

Commits are attributed as <user>/<source>: <user>/local, or <user>/agent:<harness>/<session>.
PreToolUse commits dirty state as local; PostToolUse commits the pre->post diff as the agent's;
Stop squashes the turn (per-call commits stay under refs/sun/ops) and appends the turn's
transcript chunk to refs/sun/sessions/<user>/<id>; init imports existing sessions + backfills.
Events: .git/sun/events.jsonl (cache) mirrored to refs/sun/log/<user>, one writer each, merged
by timestamp at read; refs/sun/* are the source of truth and travel via the refspec + pre-push
hook init installs. .git/sun/lock (flock) serializes everything, like git's index.lock."""
import argparse, difflib, fcntl, glob, hashlib, json, os, re, subprocess, sys
import time, uuid, zlib
from datetime import datetime
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "apply_patch"}
HOOK_EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop")
CODEX_HOOK_EVENTS = HOOK_EVENTS + ("SubagentStart", "SubagentStop")
CLAUDE_LINE = ("Past sessions for this repo, yours and other team members', are in "
               ".git/sun/sessions/ (same layout as ~/.claude/projects/, with a "
               "sessions-index.json). Look there instead of ~/.claude/projects/.")
CODEX_LINE = ("Past sessions for this repo, yours and other team members', are in "
              ".git/sun/sessions/ (with a sessions-index.json). Look there instead of "
              "~/.codex/sessions/, or use `sun sessions` to search them.")
projects = lambda: os.environ.get("SUN_PROJECTS", os.path.expanduser("~/.claude/projects"))
codex_sessions = lambda: os.environ.get(
    "SUN_CODEX_SESSIONS", os.path.expanduser("~/.codex/sessions"))
def sh(*a, input=None, check=True, env=None):
    p = subprocess.run(a, capture_output=True, text=True, input=input, env=env)
    if check and p.returncode: sys.exit(f"sun: `{' '.join(a)}` failed: {p.stderr.strip()}")
    return p.stdout
git = lambda *a, **k: sh("git", *a, **k)
_r = {}
def root():  # memoized per cwd: called on every event, and hooks chdir before using it
    return _r.get(os.getcwd()) or _r.setdefault(os.getcwd(), git("rev-parse", "--show-toplevel").strip())
head = lambda: git("rev-parse", "HEAD").strip()
quiet = lambda *a, **k: subprocess.run(a, capture_output=True, text=True, **k)
patches = lambda pre, post, files: {f: git("diff", pre, post, "--", f) for f in files}
def changed_files():
    return [l[3:].split(" -> ")[-1].strip('"') for l in
            git("-c", "core.quotepath=false", "status", "--porcelain", "-uall").splitlines()]
def commit_files(files, message, author):
    git("add", "-A", "--", *files, check=False)  # pathspec may legitimately match nothing
    c = ("-c", "commit.gpgsign=false", "commit", "-q", "--no-verify", "--allow-empty",
         "--author", f"{author} <sun@sun>", "-m", message)
    # --only keeps unrelated pre-staged paths out; empty repo matches no pathspec -> plain commit
    quiet("git", *c, "--only", "--", *files).returncode and git(*c)
    return head()
patch_id = lambda c: (git("patch-id", "--stable", check=False,
                          input=git("show", "--format=", c, check=False)).split() or [None])[0]
def blob(data):  # loose object via hashlib+zlib: no subprocess per chunk (sha1 repos)
    b = data.encode() if isinstance(data, str) else data
    hdr = b"blob %d\x00" % len(b); sha = hashlib.sha1(hdr + b).hexdigest()
    p = os.path.join(root(), ".git", "objects", sha[:2], sha[2:])
    if not os.path.exists(p):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "wb").write(zlib.compress(hdr + b))
    return sha
refs = lambda prefix: [l.split("\t") for l in git(  # [(refname, sha)]
    "for-each-ref", "--format=%(refname)\t%(objectname)", prefix, check=False).splitlines()]
def sun_dir(must=True):  # .git/sun is a per-machine cache; refs/sun/* are the source of truth
    d = os.path.join(root(), ".git", "sun")
    if must and not os.path.isdir(d): sys.exit("sun: not initialized here (run `sun init`)")
    return d
def jread(path, default):
    try: return json.load(open(path))
    except (OSError, ValueError): return default
jwrite = lambda path, obj: json.dump(obj, open(path, "w"), indent=1)
state = lambda name, default: jread(os.path.join(sun_dir(), name), default)
save_state = lambda name, obj: jwrite(os.path.join(sun_dir(), name), obj)
def parse_events(text):  # skips torn lines rather than bricking every command
    out = []
    for l in text.splitlines():
        try: out.append(json.loads(l))
        except ValueError: pass
    return out
def events():  # own cache first (file order), then teammates' logs; stable-sorted
    try: evs = parse_events(open(os.path.join(sun_dir(), "events.jsonl")).read())
    except OSError: evs = []
    for ref, sha in refs("refs/sun/log/"):
        if ref.split("/")[-1] != user():
            evs += parse_events(git("cat-file", "blob", sha, check=False))
    return sorted(evs, key=lambda e: e.get("timestamp", ""))
def lock():
    lk = open(os.path.join(sun_dir(False), "lock"), "a")
    fcntl.flock(lk, fcntl.LOCK_EX)
    return lk  # held until process exit
def mirror_log():  # one writer per user: refs/sun/log/<user> mirrors the local cache
    p = os.path.join(sun_dir(), "events.jsonl")
    if os.path.exists(p): git("update-ref", f"refs/sun/log/{user()}", blob(open(p).read()))
def record(mirror=True, **ev):
    ev = {"id": uuid.uuid4().hex[:8], "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **ev}
    with open(os.path.join(sun_dir(), "events.jsonl"), "a") as f:
        f.write(json.dumps(ev) + "\n")
    return mirror and mirror_log() or ev
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
def char_edits(patch):  # character-level ranges for paired -/+ lines of a unified patch
    out, o, n, minus = [], 0, 0, []
    for l in patch.splitlines():
        if l.startswith("@@"):
            nums = l.split("@@")[1].split()[:2]
            if len(nums) < 2: break
            (o, n), minus = tuple(int(x.lstrip("-+").split(",")[0]) for x in nums), []
        elif l.startswith("-") and not l.startswith("---"):
            minus.append((o, l[1:])); o += 1
        elif l.startswith("+") and not l.startswith("+++"):
            if minus:
                ol, old = minus.pop(0)
                out += [{"old_line": ol, "new_line": n, "old_range": [a, b], "new_range": [c, d],
                         "old_text": old[a:b], "new_text": l[1:][c:d]} for t, a, b, c, d in
                        difflib.SequenceMatcher(None, old, l[1:]).get_opcodes() if t != "equal"]
            n += 1
        elif not l.startswith("\\") and not l.startswith("diff "):
            o, n, minus = o + 1, n + 1, []
    return out
def sync(exclude=()):  # commit unclaimed changes as <user>/local
    exclude = set(exclude) | {f for s in state("active.json", {}).values() for f in s["files"]}
    files = [f for f in changed_files() if f not in exclude]
    if not files: return None
    pre, actor = head(), local()
    c = commit_files(files, f"sun: {actor} edits", actor)
    p = patches(pre, c, files)
    return record(type="edit", actor=actor, commit=c, patch_id=patch_id(c),
                  edits=[{"file": f, "patch": p[f], "char_edits": char_edits(p[f]),
                          "attribution": {"method": "hook"}} for f in files])
def maybe_sync(exclude=()):  # skipped while an agent tool call is in flight
    state("active.json", {}) or sync(exclude)
def finish_call(sid, active, payload, harness="claude"):
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
    actor, pre = agent(sid, harness), head()
    turn = state("turns.json", {}).get(session_key(sid, harness), {}).get("n", 0)
    c = commit_files(files, f"sun: {actor} {tool}" if a_files else f"sun: {local()} edits",
                     actor if a_files else local())
    p = patches(pre, c, files)
    if a_files:
        git("update-ref", f"refs/sun/ops/{c}", c)  # survives the turn squash + git gc
        record(type="edit", actor=actor, turn=f"turn{turn}", commit=c, patch_id=patch_id(c),
               tool_calls=[call], edits=[{"file": f, "patch": p[f], "tool_call_id": call["id"],
                                          "attribution": {"method": "hook"}} for f in a_files])
    if h_files:
        record(type="edit", actor=local(), commit=c,
               edits=[{"file": f, "patch": p[f], "char_edits": char_edits(p[f]),
                       "attribution": {"method": "hook"}} for f in h_files])
def squash_turn(sid, harness="claude"):
    # Stop: squash the turn's tool-call commits into one commit per turn;
    # skipped when a foreign commit landed mid-turn, and per-call commits stay either way
    t = state("turns.json", {}).get(session_key(sid, harness))
    if not t or quiet("git", "merge-base", "--is-ancestor", t["start"], "HEAD").returncode: return
    start, actor = t["start"], agent(sid, harness)
    rng = git("rev-list", f"{start}..HEAD").split()
    ops = [e for e in events() if e.get("commit") in rng]
    mine = [e for e in ops if e["actor"] == actor and "squashes" not in e]
    if not rng or set(rng) - {e["commit"] for e in mine}: return
    # commit-tree + update-ref never touch the worktree/index: edits after the last call stay dirty
    c = git("-c", f"user.name={actor}", "-c", "user.email=sun@sun", "commit-tree",
            git("rev-parse", "HEAD^{tree}").strip(), "-p", start,
            "-m", f"sun: {actor} turn {t['n']} ({len(rng)} tool calls)").strip()
    git("update-ref", "HEAD", c, head())
    files = git("diff", "--name-only", start, c).splitlines()
    p = patches(start, c, files)
    record(type="edit", actor=actor, turn=f"turn{t['n']}", commit=c, patch_id=patch_id(c),
           squashes=[e["id"] for e in mine], tool_calls=[tc for e in mine for tc in e["tool_calls"]],
           edits=[{"file": f, "patch": p[f], "attribution": {"method": "squash"}} for f in files])
    for e in ops:  # local overlays inside the agent's commits follow the squash
        if e not in mine:
            record(type=e["type"], actor=e["actor"], commit=c, edits=e["edits"], overlay_of=e["id"])
def stop_chunk(sid, payload, harness="claude"):
    # Stop: append this turn's transcript slice to the session ref
    turns = state("turns.json", {}); t = turns.get(session_key(sid, harness))
    tp = payload.get("transcript_path") or (t or {}).get("transcript", "")
    if not (t and tp and os.path.exists(tp) and cfg_track()): return
    f = open(tp, errors="replace"); f.seek(t.get("toffset", 0)); data = f.read()
    if data: store_chunks(sid, {f"turn-{t['n']:04d}.jsonl": data})
    t["toffset"] = os.path.getsize(tp); save_state("turns.json", turns)
def subagent_chunk(sid, payload):
    tp, sub = payload.get("agent_transcript_path"), payload.get("agent_id")
    if not (tp and sub and os.path.exists(tp) and cfg_track()): return
    store_chunks(sid, {f"subagents/{sub}/transcript.jsonl": open(tp, errors="replace").read()})
def cmd_hook(a):
    try: payload = json.load(sys.stdin)
    except (ValueError, OSError): payload = {}
    try: payload.get("cwd") and os.chdir(payload["cwd"])
    except OSError: return
    p = quiet("git", "rev-parse", "--show-toplevel")
    if p.returncode or not os.path.isdir(os.path.join(p.stdout.strip(), ".git", "sun")):
        return  # not a sun repo; hooks must never break the harness
    os.chdir(p.stdout.strip())
    lk = lock()  # serialize concurrent hooks (parallel sessions/subagents)
    event, sid, harness = (payload.get("hook_event_name", ""),
                           payload.get("session_id", "?"), a.harness)
    active = state("active.json", {})
    if event in ("SessionStart", "SubagentStart", "UserPromptSubmit", "PreToolUse"):
        sync()  # everything dirty before an agent tool runs is <user>/local
    if event == "SessionStart":  # stdout lands in the agent's context
        native = "~/.claude/projects" if harness == "claude" else "~/.codex/sessions"
        print(f"sun: past sessions for this repo (yours + teammates') are in "
              f".git/sun/sessions/, not {native}; {export_sessions()} sessions")
    elif event == "SubagentStart":
        print("sun: past sessions for this repo are in .git/sun/sessions/; "
              "use `sun sessions` to search them")
    elif event == "UserPromptSubmit":
        turns, tp = state("turns.json", {}), payload.get("transcript_path", "")
        key = session_key(sid, harness)
        turns[key] = {"n": turns.get(key, {}).get("n", 0) + 1, "start": head(),
                      "transcript": tp,
                      "toffset": os.path.getsize(tp) if os.path.exists(tp) else 0}
        save_state("turns.json", turns)
    elif event == "PreToolUse":  # claim the file BEFORE the write exists
        tool, inp = payload.get("tool_name", "?"), payload.get("tool_input") or {}
        active[call_key(sid, payload, harness)] = {"files": relative_tool_files(tool, inp)}
        save_state("active.json", active)
    elif event == "PostToolUse":
        finish_call(sid, active, payload, harness)
    elif event == "Stop":
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
        for line in open(path, errors="replace"):
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
def scan_claude_transcript(path, sid):
    chunks, cur, calls = [], [], []
    for line in open(path, errors="replace"):
        if cur and "tool_result" not in line \
                and ('"type":"user"' in line or '"type": "user"' in line):
            chunks.append("".join(cur)); cur = []
        cur.append(line)
        if '"tool_use"' not in line or '"tool_result"' in line: continue
        try: obj = json.loads(line)
        except ValueError: continue
        for b in (obj.get("message") or {}).get("content") or []:
            f = (isinstance(b, dict) and b.get("type") == "tool_use"
                 and b.get("name") in EDIT_TOOLS and tool_file(b.get("input") or {}))
            if f and obj.get("timestamp"):
                try:
                    t = datetime.fromisoformat(obj["timestamp"].replace("Z", "+00:00"))
                    calls.append((t.timestamp(), sid, b.get("id"), f, obj.get("cwd") or ""))
                except ValueError: pass
    if cur: chunks.append("".join(cur))
    return chunks, calls
def scan_codex_transcript(path, sid):
    lines = open(path, errors="replace").readlines()
    parsed = []
    for line in lines:
        try: parsed.append(json.loads(line))
        except ValueError: parsed.append({})
    task_boundaries = any(o.get("type") == "event_msg" and
                          (o.get("payload") or {}).get("type") == "task_started" for o in parsed)
    chunks, cur, calls, cwd = [], [], [], ""
    for line, obj in zip(lines, parsed):
        payload = obj.get("payload") or {}
        if obj.get("type") in ("session_meta", "turn_context"):
            cwd = payload.get("cwd") or cwd
        boundary = (obj.get("type") == "event_msg" and payload.get("type") == "task_started")
        if not task_boundaries:
            boundary = ((obj.get("type") == "response_item" and
                         payload.get("type") == "message" and payload.get("role") == "user") or
                        (obj.get("type") == "event_msg" and payload.get("type") == "user_message"))
        if boundary and cur: chunks.append("".join(cur)); cur = []
        cur.append(line)
        if obj.get("type") != "response_item" or payload.get("type") not in (
                "function_call", "custom_tool_call"): continue
        tool = payload.get("name") or ""
        raw = payload.get("arguments") if payload.get("arguments") is not None \
            else payload.get("input")
        inp = raw
        if isinstance(raw, str):
            try: inp = json.loads(raw)
            except ValueError: inp = {}
        files = tool_files(tool, inp) or patch_files(raw)
        if not (files and obj.get("timestamp")): continue
        try: epoch = datetime.fromisoformat(obj["timestamp"].replace("Z", "+00:00")).timestamp()
        except ValueError: continue
        calls += [(epoch, sid, payload.get("call_id") or payload.get("id"), f, cwd)
                  for f in files]
    if cur: chunks.append("".join(cur))
    return chunks, calls
def scan_transcript(path, sid, harness="claude"):
    return (scan_claude_transcript(path, sid) if harness == "claude" else
            scan_codex_transcript(path, sid))
def backfill(index):  # attribute pre-existing commits: transcript_backfill on a files+time
    # window match, else <author>/local with method import; commits with events are skipped
    have, att, tot, cs, cur = {e.get("commit") for e in events()}, 0, 0, [], None
    # -c: merges list their conflict-resolution files (result differs from every parent)
    for l in git("log", "--name-only", "-c", "--pretty=#%H\t%an\t%at", check=False).splitlines():
        if l.startswith("#"): cur = l[1:].split("\t") + [[]]; cs.append(cur)
        elif l.strip() and cur: cur[3].append(l)
    for H, an, at, files in cs:
        if H in have: continue
        tot += 1
        m = {f: c for f in files for c in  # nearest call in the window, across harnesses
             [min((c for c in index.get(f, []) if abs(c[0] - int(at)) < 1800),
                  key=lambda c: abs(c[0] - int(at)), default=None)] if c}
        u = an.replace(" ", "-").lower()
        match = min(m.values(), key=lambda c: abs(c[0] - int(at)), default=None)
        actor = agent(match[1], match[3], u) if match else local(u)
        record(mirror=False, type="edit", actor=actor, commit=H, edits=[
            {"file": f, "patch": "", "tool_call_id": m[f][2] if f in m else None,
             "attribution": {"method": "transcript_backfill" if f in m else "import"}}
            for f in files])
        att += bool(m)
    return att, tot
def do_import(harnesses=("claude",)):  # index every harness first: backfill runs once
    t0, seen, index, ns, nsub = time.time(), state("imported.json", {}), {}, 0, 0
    for harness in harnesses:
        for path, sid, sub in transcript_sources(harness):
            st = os.stat(path)
            if seen.get(path) == [st.st_size, int(st.st_mtime)]:
                continue  # idempotent: only new/changed transcripts are re-read
            chunks, calls = scan_transcript(path, sid, harness)
            for t, s, tid, f, cw in calls:  # strip repo root or the transcript's own cwd,
                pre = next((p + "/" for p in (root(), os.path.realpath(root()), cw)  # clones too
                            if p and f.startswith(p + "/")), "")
                fr = re.sub(r"^\.claude/worktrees/[^/]+/", "", f[len(pre):].lstrip("/"))
                index.setdefault(fr, []).append((t, s, tid, harness))
            if cfg_track():
                pre = f"subagents/{sub}/" if sub else ""
                store_chunks(sid, {f"{pre}turn-{i:04d}.jsonl": c for i, c in enumerate(chunks, 1)})
            seen[path] = [st.st_size, int(st.st_mtime)]
            ns, nsub = ns + (not sub), nsub + bool(sub)
    save_state("imported.json", seen)
    att, tot = backfill(index); mirror_log()
    return (f"imported {ns} sessions, {nsub} subagents; "
            f"attributed {att}/{tot} commits in {time.time() - t0:.1f}s")
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
        open(fp, "w").write(session_text(ref))
        for s in sorted({n.split("/")[1] for n in git("ls-tree", "-r", "--name-only", ref)
                        .splitlines() if n.startswith("subagents/")}):
            os.makedirs(os.path.join(base, sid, "subagents"), exist_ok=True)
            open(os.path.join(base, sid, "subagents", s + ".jsonl"), "w").write(session_text(ref, s))
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
    squashed = {i for e in evs for i in e.get("squashes", [])}
    for e in evs:  # squashed calls and overlay re-records are subsumed by their turn events
        if e.get("type") not in ("edit", "undo") or e["id"] in squashed or "overlay_of" in e \
                or not e.get("edits"): continue
        key = (e["actor"], e["turn"]) if e.get("turn") else e["id"]  # unsquashed turns regroup
        m = merged.setdefault(key, {**e, "tool_calls": e.get("tool_calls", [])[:],
                                    "edits": e["edits"][:]})
        if m["id"] != e["id"]: m["tool_calls"] += e.get("tool_calls", []); m["edits"] += e["edits"]
    out = open(a.output, "w") if a.output else sys.stdout
    for e in merged.values():
        sid = prompt = None
        m = re.match(r"([^/]+)/agent:[^/]+/(.+)", e["actor"])
        hit = m and next(((s, r) for s, u, r in rows
                          if u == m.group(1) and s.startswith(m.group(2))), None)
        if hit:
            sid, n = hit[0], int(e.get("turn", "turn0")[4:])
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
def cfg_track():  # ask once; tty only, so never on hook runs; default yes
    cfg = state("config.json", {})
    if "track_sessions" not in cfg:
        cfg["track_sessions"] = (not sys.stdin.isatty() or
                                 input("sun: track sessions in git? [Y/n] ").strip().lower() != "n")
        save_state("config.json", cfg)
    return cfg["track_sessions"]
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
def install_push():  # travel: fetch refspec + fail-soft pre-push mirror of refs/sun/*
    if "origin" in git("remote", check=False).split():
        spec = "+refs/sun/*:refs/sun/*"
        if spec not in git("config", "--get-all", "remote.origin.fetch", check=False):
            git("config", "--add", "remote.origin.fetch", spec)
    hp = os.path.join(root(), ".git", "hooks", "pre-push")
    if not os.path.exists(hp):
        open(hp, "w").write('#!/bin/sh\n# sun: mirror op log + sessions, fail-soft\n'
                            'git push --no-verify "$1" "+refs/sun/*:refs/sun/*" >/dev/null 2>&1 || true\n')
        os.chmod(hp, 0o755)
def agent_instructions(harnesses, choice, flags=""):  # one prompt covering every harness file
    todo = []
    for h in harnesses:
        name, line = ("CLAUDE.md", CLAUDE_LINE) if h == "claude" else ("AGENTS.md", CODEX_LINE)
        p = os.path.join(root(), name)
        cur = open(p).read() if os.path.exists(p) else ""
        if line not in cur: todo.append((p, cur, line, name))
    if not todo: return
    if choice is None and sys.stdin.isatty():
        choice = input(f"sun: add one line to {'/'.join(t[3] for t in todo)} so agents find "
                       "team sessions? [Y/n] ").strip().lower() != "n"
    if choice:
        for p, cur, line, _ in todo:
            open(p, "a").write(("\n" if cur and not cur.endswith("\n") else "") + line + "\n")
    else:
        print(f"sun: run `sun init{flags} --instructions` later to enable team session sharing")
def cmd_init(a):
    if quiet("git", "rev-parse", "--git-dir").returncode: sh("git", "init", "-q")
    os.makedirs(os.path.join(root(), ".git", "sun"), exist_ok=True)
    explicit = [h for h, f in (("claude", a.claude), ("codex", a.codex)) if f]
    harnesses = explicit or detect_harnesses()
    cfg = state("config.json", {}); cfg.pop("harness", None)
    cfg["harnesses"] = harnesses; save_state("config.json", cfg)
    if "origin" in git("remote", check=False).split():  # fresh clone: fetch team refs
        git("fetch", "-q", "origin", "+refs/sun/*:refs/sun/*", check=False)
    p, sha = os.path.join(sun_dir(), "events.jsonl"), git(  # rebuild cache from our own ref
        "rev-parse", "-q", "--verify", f"refs/sun/log/{user()}", check=False).strip()
    if sha and not os.path.exists(p): open(p, "w").write(git("cat-file", "blob", sha))
    installed = ", ".join(install_hooks(h) for h in harnesses); install_push()
    for h in ("claude", "codex"):
        if explicit and h not in explicit: remove_hooks(h)
    if quiet("git", "rev-parse", "HEAD").returncode or changed_files():
        c = commit_files(["."], "sun: initial state", local())
        record(type="init", actor=local(), commit=c, edits=[])
    print(f"sun: initialized {root()} (hooks: {installed}); {do_import(harnesses)}")
    agent_instructions(harnesses, a.instructions, "".join(" --" + h for h in explicit))
    cmd_viz(argparse.Namespace(n=0, output=os.path.join(sun_dir(), "viz.html")))
    print(f"open file://{sun_dir()}/viz.html to see your history")
def cmd_sync(a):
    ev = sync(); print(f"sun: committed local edits as op {ev['id']}" if ev else "sun: nothing to sync")
def cmd_import(a):
    print("sun: " + do_import(configured_harnesses()))
def cmd_update(a):  # uv re-resolves the git source to the latest commit
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
    for line in git("log", f"-{a.n}", "--pretty=%H\t%h\t%ad\t%s", "--date=short").splitlines():
        H, h, date, subj = line.split("\t", 3)
        tags = "".join(f"  [{e['actor']}" + (f" {e['turn']}" if e.get("turn") else "")
                       + (f" pr#{e['pr']}" if e.get("pr") else "")
                       + (" undo" if e["type"] == "undo" else "") + "]"
                       for e in by_commit.get(H, []))
        print(f"{h} {date} {subj}{tags or '  [untracked]'}")
def cmd_show(a):
    maybe_sync(); H = git("rev-parse", a.commit).strip()
    print(git("show", "--stat", "--pretty=format:commit %h  %ad%n%s%n", "--date=short", H))
    evs = [e for e in events() if e.get("commit") == H]
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
    maybe_sync(); f = rel_to_root(a.file)
    out = git("blame", "--porcelain", "-L", f"{a.line},{a.line}", "--", f)
    H = out.split(None, 1)[0]
    if H == "0" * 40: sys.exit(f"sun: {f}:{a.line} is uncommitted")
    text = next((l[1:] for l in out.splitlines() if l.startswith("\t")), "")
    adds = lambda e: any(ed.get("file") == f and "+" + text in  # event's patch adds the line
                         (ed.get("patch") or "").splitlines() for ed in e.get("edits") or [])
    all_ev = events()
    evs = [e for e in all_ev if e.get("commit") == H]
    if not evs:  # squash-merge/rebase moved the sha: match events by patch-id instead
        pid = patch_id(H); evs = [e for e in all_ev if pid and e.get("patch_id") == pid]
    ev = next((e for e in evs if e.get("overlay_of") and adds(e)),  # local overlay owns its lines
              next((e for e in evs if any(ed.get("file") == f for ed in e.get("edits") or [])),
                   evs[0] if evs else None))
    print(f"{f}:{a.line}  {H[:8]}  " + (f"{ev['actor']}"
          + (f" {ev['turn']}" if ev.get("turn") else "") + f"  op {ev['id']}" if ev else "untracked"))
    print("> " + text)
    if not ev: return print("no sun operations recorded for this commit")
    if "/agent:" not in ev["actor"]:
        return print(f"human edit ({ev['actor']}): no conversation\n" + json.dumps(ev, indent=2))
    u, sid8, tcs = ev["actor"].split("/", 1)[0], ev["actor"].rsplit("/", 1)[1], ev.get("tool_calls") or []
    by_id = {e["id"]: e for e in all_ev}  # squashed per-call events map file -> tool call
    calls = [by_id[i] for i in ev.get("squashes") or [] if i in by_id][::-1]  # last call wins
    mine = [tc for tc in tcs if f in ((tc.get("input") or {}).get("files")
                                      or [(tc.get("input") or {}).get("file")])]
    tid = next((ed["tool_call_id"] for e in [ev] + [c for c in calls if adds(c)] + calls
                for ed in e.get("edits") or [] if ed.get("file") == f and ed.get("tool_call_id")),
               None) or next((tc["id"] for tc in mine + tcs if tc.get("id")), None)
    hit = next(((sid, ref) for sid, ru, ref in session_rows()
                if ru == u and sid.startswith(sid8)), None)
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
        H = git("rev-parse", a.commit).strip()
        merge = ["-m", "1"] if len(git("rev-list", "--parents", "-n1", H).split()) > 2 else []
        r = quiet("git", "revert", "--no-commit", "--no-edit", *merge, H)
        if r.returncode:
            quiet("git", "revert", "--abort"); sys.exit(f"sun: cannot revert {H[:8]} cleanly")
        files, pre = changed_files(), head()
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
    files, pre = [ed["file"] for ed in target["edits"]], head()
    c = commit_files(files, f"sun: undo op {target['id']}", actor)
    record(type="undo", actor=actor, commit=c, target_op=target["id"],
           edits=[{"file": f, "patch": patches(pre, c, files)[f]} for f in files])
    print(f"sun: undid op {target['id']} in {c[:8]}")
def cmd_viz(a):
    maybe_sync()
    log = git("log", "--all", *([f"-{a.n}"] if a.n else []), "--date=iso",
              "--pretty=%H\x1f%h\x1f%P\x1f%D\x1f%ad\x1f%s")
    cols = ["hash", "short", "parents", "refs", "date", "subject"]
    commits = [dict(zip(cols, l.split("\x1f"))) for l in log.splitlines()]
    data = json.dumps({"commits": commits, "events": events()}).replace("</", "<\\/")
    out = a.output or os.path.join(sun_dir(), "viz.html")
    open(out, "w").write(VIZ.replace("__DATA__", data))
    print(f"sun: wrote {out}")
VIZ = """<!doctype html><meta charset="utf-8"><title>sun</title>
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
<script>const D=__DATA__,cs=D.commits,byC={};D.events.forEach(e=>(byC[e.commit]=byC[e.commit]||[]).push(e));
const esc=t=>(t||'').replace(/&/g,'&amp;').replace(/</g,'&lt;');
const cnt={};D.events.forEach(e=>cnt[e.actor]=(cnt[e.actor]||0)+Math.max((e.edits||[]).length,1));
const tot=Object.values(cnt).reduce((a,b)=>a+b,0)||1;
st.innerHTML=Object.entries(cnt).sort((a,b)=>b[1]-a[1]).map(([a,n])=>`<b>${esc(a)}</b> ${Math.round(100*n/tot)}%`).join(' | ');
c.innerHTML=cs.map(x=>`<li>${x.short} ${x.date.slice(0,10)} ${esc(x.subject)}${(byC[x.hash]||[]).map(e=>` <b>[${esc(e.actor)}${e.turn?' '+e.turn:''}${e.pr?' pr#'+e.pr:''}${e.type=='undo'?' undo':''}]</b>`).join('')}</li>`).join('');
const rows=[...c.children];rows.forEach((li,i)=>li.onclick=()=>{rows.forEach(r=>r.classList.remove('sel'));li.classList.add('sel');detail(cs[i]);});
s.max=cs.length;s.value=cs.length;
function cut(){const n=+s.value;pos.textContent=n+'/'+cs.length;rows.forEach((li,i)=>li.style.display=cs.length-1-i<n?'':'none');}
function detail(x){let o=`commit ${x.hash}\\n${x.date}${x.refs?'  ('+x.refs+')':''}\\n${x.subject}\\n`;
for(const e of byC[x.hash]||[]){o+=`\\nop ${e.id} | ${e.type} | ${e.actor}${e.turn?' | '+e.turn:''}${e.target_op?' | undoes op '+e.target_op:''}${e.target_commit?' | undoes '+e.target_commit.slice(0,8):''}\\n`;
for(const ed of e.edits||[])o+=`  ${ed.file}${ed.tool_call_id?` (tool ${ed.tool_call_id})`:''}\\n`+(ed.patch||'').split('\\n').map(l=>'    '+l).join('\\n')+'\\n';}
if(!(byC[x.hash]||[]).length)o+='\\n(no sun operations recorded for this commit)';d.textContent=o;}
let t=null;play.onclick=()=>{if(t){clearInterval(t);t=null;return}s.value=0;cut();
t=setInterval(()=>{s.value=+s.value+Math.max(1,Math.ceil(cs.length/150));cut();if(+s.value>=cs.length){clearInterval(t);t=null}},80)};
s.oninput=cut;cut();</script>
"""
def main(argv=None):
    ap = argparse.ArgumentParser(prog="sun", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    ps = {c: sub.add_parser(c, help=h) for c, h in [
        ("init", "git repo + .git/sun + hooks + session import"), ("sync", "commit pending local edits"),
        ("hook", "agent-harness hook entrypoint (JSON on stdin)"), ("show", "show operations for a commit"),
        ("import", "re-import sessions + backfill attribution"), ("gc", "drop session refs older than N days"),
        ("sessions", "list/read/export sessions in refs/sun/sessions"), ("log", "git log with actors + turns"),
        ("undo", "undo one operation (default: latest) or a commit"), ("viz", "HTML visualization of the op log"),
        ("update", "update sun to the latest version"),
        ("export", "dump history as fine-tuning JSONL (prompt + tool_calls + edits per turn)"),
        ("blame", "the conversation behind a file:line")]}
    ps["init"].add_argument("--claude", action="store_true",
                            help="set up Claude Code only (default: every detected harness)")
    ps["init"].add_argument("--codex", action="store_true",
                            help="set up Codex only (default: every detected harness)")
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
    ps["viz"].add_argument("-o", "--output", default=None); ps["viz"].add_argument("-n", type=int, default=0)
    ps["export"].add_argument("-o", "--output", default=None)
    ps["blame"].add_argument("file"); ps["blame"].add_argument("line", type=int)
    a = ap.parse_args(argv)
    if a.cmd not in ("init", "hook", "update"):  # hook locates its repo from the payload
        os.chdir(root()); sun_dir(); a.lock = lock()
    {"init": cmd_init, "hook": cmd_hook, "sync": cmd_sync, "log": cmd_log, "show": cmd_show,
     "undo": cmd_undo, "viz": cmd_viz, "import": cmd_import, "sessions": cmd_sessions,
     "gc": cmd_gc, "update": cmd_update, "export": cmd_export, "blame": cmd_blame}[a.cmd](a)
if __name__ == "__main__":
    main()
