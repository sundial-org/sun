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
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
CLAUDE_LINE = ("Past sessions for this repo, yours and other team members', are in "
               ".git/sun/sessions/ (same layout as ~/.claude/projects/, with a "
               "sessions-index.json). Look there instead of ~/.claude/projects/.")
projects = lambda: os.environ.get("SUN_PROJECTS", os.path.expanduser("~/.claude/projects"))
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
    git("-c", "commit.gpgsign=false", "commit", "-q", "--no-verify", "--allow-empty",
        "--author", f"{author} <sun@sun>", "-m", message)
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
local = lambda u=None: f"{u or user()}/local"; agent = lambda sid: f"{user()}/agent:claude/{sid[:8]}"
call_key = lambda sid, payload: f"{sid}/{payload.get('tool_use_id') or ''}"
tool_file = lambda inp: inp.get("file_path") or inp.get("notebook_path")
rel_to_root = lambda path: os.path.relpath(os.path.realpath(path), root())
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
def sync():  # commit unclaimed changes as <user>/local
    exclude = {f for s in state("active.json", {}).values() for f in s["files"]}
    files = [f for f in changed_files() if f not in exclude]
    if not files: return None
    pre, actor = head(), local()
    c = commit_files(files, f"sun: {actor} edits", actor)
    p = patches(pre, c, files)
    return record(type="edit", actor=actor, commit=c, patch_id=patch_id(c),
                  edits=[{"file": f, "patch": p[f], "char_edits": char_edits(p[f]),
                          "attribution": {"method": "hook"}} for f in files])
def maybe_sync():  # skipped while an agent tool call is in flight
    state("active.json", {}) or sync()
def finish_call(sid, active, payload):  # PostToolUse: pre->post diff is the agent's tool call
    st = (active.pop(call_key(sid, payload), None)  # or an id-less claim
          or active.pop(call_key(sid, {}), None) or {"files": []})
    save_state("active.json", active)
    others = {f for s in active.values() for f in s["files"]}
    files = [f for f in changed_files() if f not in others]
    if not files: return
    tool, inp = payload.get("tool_name", "?"), payload.get("tool_input") or {}
    call = {"id": payload.get("tool_use_id"), "tool": tool,
            "input": {"file": rel_to_root(tool_file(inp))} if tool_file(inp) else inp}
    claimed = set(st["files"]) | ({call["input"]["file"]} if tool_file(inp) else set())
    # Edit/Write only touch their own file -> the rest of the diff is a concurrent local
    # overlay; for other tools (Bash, ...) the whole diff is the agent's
    a_files = [f for f in files if f in claimed] if tool in EDIT_TOOLS else files
    h_files = [f for f in files if f not in a_files]
    actor, pre = agent(sid), head()
    turn = state("turns.json", {}).get(sid, {}).get("n", 0)
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
def squash_turn(sid):  # Stop: squash the turn's tool-call commits into one commit per turn;
    # skipped when a foreign commit landed mid-turn, and per-call commits stay either way
    t = state("turns.json", {}).get(sid)
    if not t or quiet("git", "merge-base", "--is-ancestor", t["start"], "HEAD").returncode: return
    start, actor = t["start"], agent(sid)
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
def stop_chunk(sid, payload):  # Stop: append this turn's transcript slice to the session ref
    turns = state("turns.json", {}); t = turns.get(sid)
    tp = payload.get("transcript_path") or (t or {}).get("transcript", "")
    if not (t and tp and os.path.exists(tp) and cfg_track()): return
    f = open(tp, errors="replace"); f.seek(t.get("toffset", 0)); data = f.read()
    if data: store_chunks(sid, {f"turn-{t['n']:04d}.jsonl": data})
    t["toffset"] = os.path.getsize(tp); save_state("turns.json", turns)
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
    event, sid = payload.get("hook_event_name", ""), payload.get("session_id", "?")
    active = state("active.json", {})
    if event in ("SessionStart", "UserPromptSubmit", "PreToolUse"):
        sync()  # everything dirty before an agent tool runs is <user>/local
    if event == "SessionStart":  # stdout lands in the agent's context
        print(f"sun: past sessions for this repo (yours + teammates') are in "
              f".git/sun/sessions/, not ~/.claude/projects; {export_sessions()} sessions")
    elif event == "UserPromptSubmit":
        turns, tp = state("turns.json", {}), payload.get("transcript_path", "")
        turns[sid] = {"n": turns.get(sid, {}).get("n", 0) + 1, "start": head(), "transcript": tp,
                      "toffset": os.path.getsize(tp) if os.path.exists(tp) else 0}
        save_state("turns.json", turns)
    elif event == "PreToolUse":  # claim the file BEFORE the write exists
        f = tool_file(payload.get("tool_input") or {})
        active[call_key(sid, payload)] = {"files": [rel_to_root(f)] if f else []}
        save_state("active.json", active)
    elif event == "PostToolUse":
        finish_call(sid, active, payload)
    elif event == "Stop":
        squash_turn(sid)
        stop_chunk(sid, payload)
enc = lambda path: re.sub(r"[/.]", "-", path)
def project_dirs():  # every ~/.claude project dir that maps to this repo (worktrees too)
    wt = [l.split(" ", 1)[1] for l in git("worktree", "list", "--porcelain", check=False)
          .splitlines() if l.startswith("worktree ")]
    names = {enc(p) for r in [root()] + wt for p in (r, os.path.realpath(r))}
    return [d for d in glob.glob(os.path.join(projects(), "*")) if os.path.basename(d) in names
            or any(os.path.basename(d).startswith(n + "--claude-worktrees-") for n in names)]
def scan_transcript(path, sid):  # one pass: turn chunks + edit-tool calls (epoch, sid, id, path)
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
def backfill(index):  # attribute pre-existing commits: transcript_backfill on a files+time
    # window match, else <author>/local with method import; commits with events are skipped
    have, att, tot, cs, cur = {e.get("commit") for e in events()}, 0, 0, [], None
    for l in git("log", "--name-only", "--pretty=#%H\t%an\t%at", check=False).splitlines():
        if l.startswith("#"): cur = l[1:].split("\t") + [[]]; cs.append(cur)
        elif l.strip() and cur: cur[3].append(l)
    for H, an, at, files in cs:
        if H in have: continue
        tot += 1
        m = {f: c for f in files for c in
             [next((c for c in index.get(f, []) if abs(c[0] - int(at)) < 1800), None)] if c}
        u = an.replace(" ", "-").lower()
        actor = f"{u}/agent:claude/{next(iter(m.values()))[1][:8]}" if m else local(u)
        record(mirror=False, type="edit", actor=actor, commit=H, edits=[
            {"file": f, "patch": "", "tool_call_id": m[f][2] if f in m else None,
             "attribution": {"method": "transcript_backfill" if f in m else "import"}}
            for f in files])
        att += bool(m)
    return att, tot
def do_import():
    t0, seen, index, ns, nsub = time.time(), state("imported.json", {}), {}, 0, 0
    for d in project_dirs():
        for path in glob.glob(os.path.join(d, "**", "*.jsonl"), recursive=True):
            rp = os.path.relpath(path, d).split(os.sep)
            sid, sub = (rp[0], rp[-1][:-6]) if len(rp) > 1 else (rp[0][:-6], None)
            st = os.stat(path)
            if seen.get(path) == [st.st_size, int(st.st_mtime)]:
                continue  # idempotent: only new/changed transcripts are re-read
            chunks, calls = scan_transcript(path, sid)
            for t, s, tid, f, cw in calls:  # strip repo root or the transcript's own cwd,
                pre = next((p + "/" for p in (root(), os.path.realpath(root()), cw)  # clones too
                            if p and f.startswith(p + "/")), "")
                fr = re.sub(r"^\.claude/worktrees/[^/]+/", "", f[len(pre):].lstrip("/"))
                index.setdefault(fr, []).append((t, s, tid))
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
def install_hooks():
    path = os.path.join(root(), ".claude", "settings.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cfg = jread(path, {})
    if not isinstance(cfg.setdefault("hooks", {}), dict):
        sys.exit("sun: unexpected 'hooks' format in .claude/settings.json")
    for event in ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"):
        group = cfg["hooks"].setdefault(event, [])
        if not any(h.get("command") == "sun hook" for g in group for h in g.get("hooks", [])):
            group.append({"hooks": [{"type": "command", "command": "sun hook"}]})
    jwrite(path, cfg)
    return "claude (.claude/settings.json)"
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
def claude_md(choice):
    p = os.path.join(root(), "CLAUDE.md")
    cur = open(p).read() if os.path.exists(p) else ""
    if CLAUDE_LINE in cur: return
    if choice is None and sys.stdin.isatty():
        choice = input("sun: add one line to CLAUDE.md so agents find team sessions? "
                       "[Y/n] ").strip().lower() != "n"
    if choice:
        open(p, "a").write(("\n" if cur and not cur.endswith("\n") else "") + CLAUDE_LINE + "\n")
    else:
        print("sun: run `sun init --claude-md` later to enable team session sharing")
def cmd_init(a):
    if quiet("git", "rev-parse", "--git-dir").returncode: sh("git", "init", "-q")
    os.makedirs(os.path.join(root(), ".git", "sun"), exist_ok=True)
    if "origin" in git("remote", check=False).split():  # fresh clone: fetch team refs
        git("fetch", "-q", "origin", "+refs/sun/*:refs/sun/*", check=False)
    p, sha = os.path.join(sun_dir(), "events.jsonl"), git(  # rebuild cache from our own ref
        "rev-parse", "-q", "--verify", f"refs/sun/log/{user()}", check=False).strip()
    if sha and not os.path.exists(p): open(p, "w").write(git("cat-file", "blob", sha))
    harness = install_hooks(); install_push()
    if quiet("git", "rev-parse", "HEAD").returncode or changed_files():
        c = commit_files(["."], "sun: initial state", local())
        record(type="init", actor=local(), commit=c, edits=[])
    print(f"sun: initialized {root()} (hooks: {harness}); {do_import()}")
    claude_md(a.claude_md)
    cmd_viz(argparse.Namespace(n=0, output=os.path.join(sun_dir(), "viz.html")))
    print(f"open file://{sun_dir()}/viz.html to see your history")
def cmd_sync(a):
    ev = sync(); print(f"sun: committed local edits as op {ev['id']}" if ev else "sun: nothing to sync")
def cmd_import(a): print("sun: " + do_import())
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
VIZ = """<!doctype html><meta charset="utf-8"><title>sun — operation log</title>
<style>body{margin:0;font:13px/1.45 ui-monospace,Menlo,monospace;background:#0d1117;color:#e6edf3}
header{padding:12px 20px;border-bottom:1px solid #30363d;display:flex;gap:16px;align-items:center;flex-wrap:wrap}h1{font-size:16px;margin:0}
#ctl{margin-left:auto;display:flex;gap:8px;align-items:center}main{display:grid;grid-template-columns:minmax(360px,1fr) 1.2fr;height:calc(100vh - 55px)}
#commits{list-style:none;margin:0;padding:10px;overflow:auto;border-right:1px solid #30363d}
#commits li{padding:5px 8px;border-radius:6px;cursor:pointer;display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
#commits li:hover{background:#161b22}#commits li.sel{background:#1f2733}.h{color:#79c0ff}.d{color:#8b949e}.ref{color:#d29922;font-size:11px}
.chip{font-size:11px;padding:0 6px;border-radius:8px;color:#0d1117;font-weight:600}#detail{overflow:auto;padding:14px 18px;white-space:pre-wrap;margin:0}
.add{color:#3fb950}.del{color:#f85149}.file{color:#d2a8ff;font-weight:700}input[type=range]{width:170px}
button{background:#21262d;color:#e6edf3;border:1px solid #30363d;border-radius:6px;cursor:pointer;padding:2px 10px}</style>
<header><h1>&#9728; sun</h1><div id=ctl><button id=play>&#9654; replay</button><input type=range id=slider min=0 value=0><span id=pos></span></div></header>
<main><ol id=commits></ol><pre id=detail>select a commit to see its operations</pre></main>
<script>const DATA=__DATA__,evs=DATA.events,byC={};evs.forEach(e=>(byC[e.commit]=byC[e.commit]||[]).push(e));
const commits=DATA.commits.slice().reverse(),actors=[...new Set(evs.map(e=>e.actor))];
const color=a=>`hsl(${(actors.indexOf(a)*73+200)%360},65%,60%)`,esc=s=>(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;');
slider.max=commits.length;slider.value=commits.length;
function render(){const n=+slider.value;document.getElementById('commits').innerHTML='';pos.textContent=`${n}/${commits.length}`;
commits.slice(0,n).reverse().forEach(c=>{const chips=(byC[c.hash]||[]).map(e=>`<span class=chip style="background:${color(e.actor)}">${esc(e.actor)}${e.turn?' '+esc(e.turn):''}${e.pr?' pr#'+e.pr:''}${e.type=='undo'?' undo':''}</span>`).join('');
const li=document.createElement('li');li.innerHTML=`<span class=h>${c.short}</span><span class=d>${c.date.slice(0,10)}</span><span>${esc(c.subject)}</span>${c.refs?`<span class=ref>${esc(c.refs)}</span>`:''}${chips}`;
li.onclick=()=>{document.querySelectorAll('#commits li').forEach(x=>x.classList.remove('sel'));li.classList.add('sel');detail(c);};
document.getElementById('commits').appendChild(li);});}
function detail(c){let out=`commit ${c.hash}\\n${c.subject}\\n${c.date}\\n`;
if(!(byC[c.hash]||[]).length)out+='\\n(no sun operations recorded for this commit)\\n';
for(const e of byC[c.hash]||[]){out+=`\\nop ${e.id} \\u00b7 ${e.type} \\u00b7 ${e.actor}${e.turn?' \\u00b7 '+e.turn:''}${e.target_op?' \\u00b7 undoes op '+e.target_op:''}\\n`;
for(const ed of e.edits||[])out+=`  <f>${ed.file}</f>`+(ed.tool_call_id?` (tool ${ed.tool_call_id})`:'')+'\\n'+(ed.patch||'').split('\\n').map(l=>'    '+l).join('\\n')+'\\n';}
document.getElementById('detail').innerHTML=out.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/&lt;f>(.*?)&lt;\\/f>/g,'<span class=file>$1</span>')
.replace(/^( *\\+.*)$/gm,'<span class=add>$1</span>').replace(/^( *-.*)$/gm,'<span class=del>$1</span>');}
let timer=null;play.onclick=()=>{if(timer){clearInterval(timer);timer=null;return;}slider.value=0;render();
timer=setInterval(()=>{if(+slider.value>=commits.length){clearInterval(timer);timer=null;return;}slider.value=+slider.value+1;render();},600);};
slider.oninput=render;render();</script>
"""
def main(argv=None):
    ap = argparse.ArgumentParser(prog="sun", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    ps = {c: sub.add_parser(c, help=h) for c, h in [
        ("init", "git repo + .git/sun + hooks + session import"), ("sync", "commit pending local edits"),
        ("hook", "agent-harness hook entrypoint (JSON on stdin)"), ("show", "show operations for a commit"),
        ("import", "re-import sessions + backfill attribution"), ("gc", "drop session refs older than N days"),
        ("sessions", "list/read/export sessions in refs/sun/sessions"), ("log", "git log with actors + turns"),
        ("undo", "undo one operation (default: latest) or a commit"), ("viz", "HTML visualization of the op log")]}
    ps["init"].add_argument("--claude-md", dest="claude_md", action="store_true", default=None)
    ps["init"].add_argument("--no-claude-md", dest="claude_md", action="store_false")
    ps["sessions"].add_argument("id", nargs="?"); ps["sessions"].add_argument("--grep")
    ps["sessions"].add_argument("--file"); ps["gc"].add_argument("--older-than", type=int, required=True)
    ps["log"].add_argument("-n", type=int, default=30); ps["show"].add_argument("commit")
    ps["undo"].add_argument("--op", nargs="?", const="", default=None, metavar="ID")
    ps["undo"].add_argument("--commit", nargs="?", const="HEAD", default=None, metavar="HASH")
    ps["viz"].add_argument("-o", "--output", default=None); ps["viz"].add_argument("-n", type=int, default=0)
    a = ap.parse_args(argv)
    if a.cmd not in ("init", "hook"):  # hook locates its repo from the payload
        os.chdir(root()); sun_dir(); a.lock = lock()
    {"init": cmd_init, "hook": cmd_hook, "sync": cmd_sync, "log": cmd_log, "show": cmd_show,
     "undo": cmd_undo, "viz": cmd_viz, "import": cmd_import, "sessions": cmd_sessions,
     "gc": cmd_gc}[a.cmd](a)
if __name__ == "__main__":
    main()
