#!/usr/bin/env python3
"""sun: an operation log for humans + agents on top of git.

Every change is committed and attributed to the human or agent that made it.
Human edits are detected jj-style (a diff check whenever any sun command or
agent hook runs; PreToolUse commits everything dirty as human). Agent edits are
captured per tool call (PreToolUse -> PostToolUse diff = one commit + event),
then squashed into one commit per turn at Stop; the per-call commits stay in
the op log under refs/sun/ops. Events live in .git/sun/events.jsonl and point
at commits; several events (agent + concurrent human) may share a commit.
Concurrency: like git's index.lock, .git/sun/lock (flock) serializes every
sun command/hook, and events.jsonl is append-only.
"""
import argparse, difflib, fcntl, json, os, subprocess, sys, time, uuid

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

# ---------------------------------------------------------------- git plumbing

def sh(*args, input=None, check=True):
    p = subprocess.run(args, capture_output=True, text=True, input=input)
    if check and p.returncode:
        sys.exit(f"sun: `{' '.join(args)}` failed: {p.stderr.strip()}")
    return p.stdout

def git(*args, **kw):
    return sh("git", *args, **kw)

def root():
    return git("rev-parse", "--show-toplevel").strip()

def head():
    return git("rev-parse", "HEAD").strip()

def changed_files():
    files = []
    for line in git("-c", "core.quotepath=false", "status", "--porcelain",
                    "-uall").splitlines():
        f = line[3:].split(" -> ")[-1]
        if f.startswith('"'):  # control chars still come quoted/escaped
            f = (f[1:-1].encode("latin1").decode("unicode_escape")
                 .encode("latin1").decode("utf-8"))
        files.append(f)
    return files

def commit_files(files, message, author):
    # check=False: a pathspec can legitimately match nothing when the change
    # (e.g. a deletion from revert/apply -R) is already staged
    git("add", "-A", "--", *files, check=False)
    git("-c", "commit.gpgsign=false", "commit", "-q", "--no-verify",
        "--allow-empty", "--author", f"{author} <sun@sun>", "-m", message)
    return head()

def patches(pre, post, files):
    return {f: git("diff", pre, post, "--", f) for f in files}

# ------------------------------------------------------------- .git/sun state

def sun_dir(must=True):
    d = os.path.join(root(), ".git", "sun")
    if must and not os.path.isdir(d):
        sys.exit("sun: not initialized here (run `sun init`)")
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

def state(name, default):
    return jread(os.path.join(sun_dir(), name), default)

def save_state(name, obj):
    jwrite(os.path.join(sun_dir(), name), obj)

def events():
    out = []
    try:
        with open(os.path.join(sun_dir(), "events.jsonl")) as f:
            for l in f:
                try:
                    out.append(json.loads(l))
                except ValueError:
                    pass  # skip torn/corrupt lines rather than brick every command
    except OSError:
        pass
    return out

def lock():
    lk = open(os.path.join(sun_dir(False), "lock"), "a")
    fcntl.flock(lk, fcntl.LOCK_EX)
    return lk  # held until process exit

def record(**ev):
    ev = {"id": uuid.uuid4().hex[:8],
          "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **ev}
    with open(os.path.join(sun_dir(), "events.jsonl"), "a") as f:
        f.write(json.dumps(ev) + "\n")
    return ev

# ---------------------------------------------------------------- attribution

def human():
    name = git("config", "user.name", check=False).strip() \
        or os.environ.get("USER", "unknown")
    return "human:" + name.replace(" ", "-").lower()

def char_edits(patch):
    """Character-level edit ranges for paired -/+ lines of a unified patch."""
    edits, old_ln, new_ln, minus = [], 0, 0, []
    for line in patch.splitlines():
        if line.startswith("@@"):
            nums = line.split("@@")[1].split()[:2]
            if len(nums) < 2:  # malformed/truncated hunk header
                break
            old_ln, new_ln = (int(n.lstrip("-+").split(",")[0]) for n in nums)
            minus = []
        elif line.startswith("-") and not line.startswith("---"):
            minus.append((old_ln, line[1:]))
            old_ln += 1
        elif line.startswith("+") and not line.startswith("+++"):
            new = line[1:]
            if minus:
                oln, old = minus.pop(0)
                sm = difflib.SequenceMatcher(None, old, new)
                for tag, a, b, c, d in sm.get_opcodes():
                    if tag != "equal":
                        edits.append({"old_line": oln, "new_line": new_ln,
                                      "old_range": [a, b], "new_range": [c, d],
                                      "old_text": old[a:b], "new_text": new[c:d]})
            new_ln += 1
        elif not line.startswith("\\") and not line.startswith("diff "):
            old_ln += 1
            new_ln += 1
            minus = []
    return edits

def sync(exclude=frozenset()):
    """Commit pending changes not claimed by an in-flight agent tool call as human."""
    active = state("active.json", {})
    exclude = set(exclude) | {f for s in active.values() for f in s["files"]}
    files = [f for f in changed_files() if f not in exclude]
    if not files:
        return None
    pre, actor = head(), human()
    c = commit_files(files, "sun: human edits", actor)
    p = patches(pre, c, files)
    return record(type="edit", actor=actor, commit=c,
                  edits=[{"file": f, "patch": p[f],
                          "char_edits": char_edits(p[f])} for f in files])

def maybe_sync():
    if not state("active.json", {}):  # skip while an agent tool call is in flight
        sync()

# ------------------------------------------------------------ hook entrypoint

def tool_file(inp):
    return inp.get("file_path") or inp.get("notebook_path")

def rel_to_root(path):
    # realpath: harness payloads may use unresolved paths (macOS /var vs /private/var)
    return os.path.relpath(os.path.realpath(path), root())

agent = lambda sid: f"agent:claude/{sid[:8]}"
# parallel subagents share a session_id, so claims are keyed per tool call
call_key = lambda sid, payload: f"{sid}/{payload.get('tool_use_id') or ''}"

def finish_call(sid, active, payload):
    """PostToolUse: the pre-tool -> post-tool diff is this agent's tool call."""
    st = (active.pop(call_key(sid, payload), None)  # fall back to an id-less claim
          or active.pop(call_key(sid, {}), None) or {"files": []})
    save_state("active.json", active)
    others = {f for s in active.values() for f in s["files"]}
    files = [f for f in changed_files() if f not in others]
    if not files: return
    tool, inp = payload.get("tool_name", "?"), payload.get("tool_input") or {}
    call = {"id": payload.get("tool_use_id"), "tool": tool,
            "input": {"file": rel_to_root(tool_file(inp))} if tool_file(inp) else inp}
    claimed = set(st["files"]) | ({call["input"]["file"]} if tool_file(inp) else set())
    # an Edit/Write can only have touched its own file: anything else in the
    # diff is a concurrent human edit (overlay, per proposal); for other tools
    # (Bash, ...) the whole diff is the agent's
    a_files = [f for f in files if f in claimed] if tool in EDIT_TOOLS else files
    h_files = [f for f in files if f not in a_files]
    actor, pre = agent(sid), head()
    turn = state("turns.json", {}).get(sid, {}).get("n", 0)
    c = commit_files(files, f"sun: {actor} {tool}" if a_files else "sun: human edits",
                     actor if a_files else human())
    p = patches(pre, c, files)
    if a_files:
        git("update-ref", f"refs/sun/ops/{c}", c)  # survives the turn squash + gc
        record(type="edit", actor=actor, turn=f"turn{turn}", commit=c, tool_calls=[call],
               edits=[{"file": f, "patch": p[f], "tool_call_id": call["id"],
                       "attribution": {"method": "edit_tool" if f in st["files"]
                                       else "hook_diff"}} for f in a_files])
    if h_files:
        record(type="edit", actor=human(), commit=c,
               edits=[{"file": f, "patch": p[f], "char_edits": char_edits(p[f])}
                      for f in h_files])

def squash_turn(sid):
    """Stop: squash this turn's tool-call commits into one commit per turn.
    Per-call commits stay in the op log (events + refs/sun/ops). Skipped when a
    foreign commit (human sync, another agent, manual commit) landed mid-turn."""
    t = state("turns.json", {}).get(sid)
    if not t: return
    start, actor = t["start"], agent(sid)
    if subprocess.run(["git", "merge-base", "--is-ancestor", start, "HEAD"],
                      capture_output=True).returncode:
        return
    rng = git("rev-list", f"{start}..HEAD").split()
    ops = [e for e in events() if e.get("commit") in rng]
    mine = [e for e in ops if e["actor"] == actor and "squashes" not in e]
    if not rng or set(rng) - {e["commit"] for e in mine}:  # foreign commit mid-turn
        return
    # commit-tree + update-ref: never touches the worktree/index, so human
    # edits made after the last tool call stay dirty (and human) instead of
    # being folded into the turn
    c = git("-c", f"user.name={actor}", "-c", "user.email=sun@sun", "commit-tree",
            git("rev-parse", "HEAD^{tree}").strip(), "-p", start,
            "-m", f"sun: {actor} turn {t['n']} ({len(rng)} tool calls)").strip()
    git("update-ref", "HEAD", c, head())
    files = git("diff", "--name-only", start, c).splitlines()
    p = patches(start, c, files)
    record(type="edit", actor=actor, turn=f"turn{t['n']}", commit=c,
           squashes=[e["id"] for e in mine],  # events() is chronological
           tool_calls=[tc for e in mine for tc in e["tool_calls"]],
           edits=[{"file": f, "patch": p[f],
                   "attribution": {"method": "squash"}} for f in files])
    for e in ops:  # human overlays inside the agent's commits follow the squash
        if e not in mine:
            record(type=e["type"], actor=e["actor"], commit=c, edits=e["edits"],
                   overlay_of=e["id"])

def cmd_hook(a):
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        payload = {}
    if payload.get("cwd"):
        try:
            os.chdir(payload["cwd"])
        except OSError:
            return
    p = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True)
    top = p.stdout.strip()
    if p.returncode or not os.path.isdir(os.path.join(top, ".git", "sun")):
        return  # not a sun repo; hooks must never break the harness
    os.chdir(top)  # session cwd may be a subdirectory; paths are root-relative
    lk = lock()  # serialize concurrent hooks (parallel sessions/subagents)
    event, sid = payload.get("hook_event_name", ""), payload.get("session_id", "?")
    active = state("active.json", {})
    if event in ("SessionStart", "UserPromptSubmit", "PreToolUse"):
        sync()  # everything dirty before an agent tool runs is human
    if event == "UserPromptSubmit":
        turns = state("turns.json", {})
        turns[sid] = {"n": turns.get(sid, {}).get("n", 0) + 1, "start": head()}
        save_state("turns.json", turns)
    elif event == "PreToolUse":
        # claim the file BEFORE the write exists, so a concurrent session's
        # sync can never misattribute it to the human
        f = tool_file(payload.get("tool_input") or {})
        active[call_key(sid, payload)] = {"files": [rel_to_root(f)] if f else []}
        save_state("active.json", active)
    elif event == "PostToolUse":
        finish_call(sid, active, payload)
    elif event == "Stop":
        squash_turn(sid)

# -------------------------------------------------------------------- init

def install_hooks():
    path = os.path.join(root(), ".claude", "settings.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cfg = jread(path, {})
    hooks = cfg.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        sys.exit("sun: unexpected 'hooks' format in .claude/settings.json")
    for event in ("SessionStart", "UserPromptSubmit", "PreToolUse",
                  "PostToolUse", "Stop"):
        group = cfg["hooks"].setdefault(event, [])
        if any(h.get("command") == "sun hook"
               for g in group for h in g.get("hooks", [])):
            continue
        group.append({"hooks": [{"type": "command", "command": "sun hook"}]})
    jwrite(path, cfg)
    return "claude (.claude/settings.json)"

def cmd_init(a):
    if subprocess.run(["git", "rev-parse", "--git-dir"],
                      capture_output=True).returncode:
        sh("git", "init", "-q")
    os.makedirs(os.path.join(root(), ".git", "sun"), exist_ok=True)
    harness = install_hooks()
    no_head = subprocess.run(["git", "rev-parse", "HEAD"],
                             capture_output=True).returncode
    if no_head or changed_files():
        c = commit_files(["."], "sun: initial state", human())
        record(type="init", actor=human(), commit=c, edits=[])
    print(f"sun: initialized {root()} (hooks: {harness})")

# ------------------------------------------------------------------ commands

def cmd_sync(a):
    ev = sync()
    print(f"sun: committed human edits as op {ev['id']}" if ev
          else "sun: nothing to sync")

def cmd_log(a):
    maybe_sync()
    by_commit = {}
    for ev in events():
        by_commit.setdefault(ev.get("commit"), []).append(ev)
    out = git("log", f"-{a.n}", "--pretty=%H\t%h\t%ad\t%s", "--date=short")
    for line in out.splitlines():
        H, h, date, subj = line.split("\t", 3)
        tags = "".join(f"  [{e['actor']}"
                       + (f" {e['turn']}" if e.get("turn") else "")
                       + (f" pr#{e['pr']}" if e.get("pr") else "")
                       + (" undo" if e["type"] == "undo" else "") + "]"
                       for e in by_commit.get(H, []))
        print(f"{h} {date} {subj}{tags or '  [untracked]'}")

def cmd_show(a):
    maybe_sync()
    H = git("rev-parse", a.commit).strip()
    print(git("show", "--stat", "--pretty=format:commit %h  %ad%n%s%n",
              "--date=short", H))
    evs = [e for e in events() if e.get("commit") == H]
    if not evs:
        print("no sun operations recorded for this commit")
    for e in evs:
        print(json.dumps(e, indent=2))

def cmd_undo(a):
    maybe_sync()
    actor = human()
    if a.commit is not None:
        H = git("rev-parse", a.commit).strip()
        merge = ["-m", "1"] if len(git("rev-list", "--parents", "-n1",
                                       H).split()) > 2 else []
        r = subprocess.run(["git", "revert", "--no-commit", "--no-edit",
                            *merge, H], capture_output=True, text=True)
        if r.returncode:
            subprocess.run(["git", "revert", "--abort"], capture_output=True)
            sys.exit(f"sun: cannot revert {H[:8]} cleanly: "
                     + (r.stderr.strip().splitlines() or ["?"])[0])
        files, pre = changed_files(), head()
        c = commit_files(files or ["."], f"sun: undo commit {H[:8]}", actor)
        p = patches(pre, c, files)
        record(type="undo", actor=actor, commit=c, target_commit=H,
               edits=[{"file": f, "patch": p[f]} for f in files])
        print(f"sun: undid commit {H[:8]} in {c[:8]}")
        return
    target = None
    for e in reversed(events()):
        if (e["id"] == a.op or not a.op) and e.get("edits"):
            target = e
            break
    if not target:
        sys.exit("sun: no such operation")
    combined = "".join(ed["patch"] for ed in target["edits"] if ed["patch"].strip())
    r = subprocess.run(["git", "apply", "-R"], input=combined,  # atomic: all or nothing
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"sun: cannot undo op {target['id']}: its patch no longer "
                 "applies cleanly (later commits touch the same lines); "
                 "try `sun undo --commit <hash>` instead")
    files, pre = [ed["file"] for ed in target["edits"]], head()
    c = commit_files(files, f"sun: undo op {target['id']}", actor)
    p = patches(pre, c, files)
    record(type="undo", actor=actor, commit=c, target_op=target["id"],
           edits=[{"file": f, "patch": p[f]} for f in files])
    print(f"sun: undid op {target['id']} in {c[:8]}")

def cmd_viz(a):
    maybe_sync()
    limit = [f"-{a.n}"] if a.n else []
    log = git("log", "--all", *limit, "--date=iso",
              "--pretty=%H\x1f%h\x1f%P\x1f%D\x1f%ad\x1f%s")
    cols = ["hash", "short", "parents", "refs", "date", "subject"]
    commits = [dict(zip(cols, l.split("\x1f"))) for l in log.splitlines()]
    data = json.dumps({"commits": commits, "events": events()}).replace("</", "<\\/")
    out = a.output or os.path.join(sun_dir(), "viz.html")
    with open(out, "w") as f:
        f.write(VIZ.replace("__DATA__", data))
    print(f"sun: wrote {out}")

VIZ = """<!doctype html><meta charset="utf-8"><title>sun — operation log</title>
<style>
body{margin:0;font:13px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace;background:#0d1117;color:#e6edf3}
header{padding:12px 20px;border-bottom:1px solid #30363d;display:flex;gap:16px;align-items:center;flex-wrap:wrap}
h1{font-size:16px;margin:0}
#bar{display:flex;height:10px;width:200px;border-radius:5px;overflow:hidden;background:#21262d}
.leg{display:flex;gap:12px;flex-wrap:wrap}
.dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:4px}
#ctl{margin-left:auto;display:flex;gap:8px;align-items:center}
main{display:grid;grid-template-columns:minmax(360px,1fr) 1.2fr;height:calc(100vh - 55px)}
#commits{list-style:none;margin:0;padding:10px;overflow:auto;border-right:1px solid #30363d}
#commits li{padding:5px 8px;border-radius:6px;cursor:pointer;display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
#commits li:hover{background:#161b22}#commits li.sel{background:#1f2733}
.h{color:#79c0ff}.d{color:#8b949e}.ref{color:#d29922;font-size:11px}
.chip{font-size:11px;padding:0 6px;border-radius:8px;color:#0d1117;font-weight:600}
#detail{overflow:auto;padding:14px 18px;white-space:pre-wrap;margin:0}
.add{color:#3fb950}.del{color:#f85149}.file{color:#d2a8ff;font-weight:700}
input[type=range]{width:170px}
button{background:#21262d;color:#e6edf3;border:1px solid #30363d;border-radius:6px;cursor:pointer;padding:2px 10px}
</style>
<header><h1>&#9728; sun</h1><div id=bar></div><div class=leg id=leg></div>
<div id=ctl><button id=play>&#9654; replay</button><input type=range id=slider min=0 value=0><span id=pos></span></div></header>
<main><ol id=commits></ol><pre id=detail>select a commit to see its operations</pre></main>
<script>
const DATA=__DATA__,evs=DATA.events,byC={};
evs.forEach(e=>(byC[e.commit]=byC[e.commit]||[]).push(e));
const commits=DATA.commits.slice().reverse();
const actors=[...new Set(evs.map(e=>e.actor))];
const color=a=>`hsl(${(actors.indexOf(a)*73+200)%360},65%,60%)`;
const esc=s=>(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;');
const counts={};evs.forEach(e=>counts[e.actor]=(counts[e.actor]||0)+Math.max(e.edits?e.edits.length:0,1));
const total=Object.values(counts).reduce((a,b)=>a+b,0)||1;
const ranked=actors.slice().sort((a,b)=>counts[b]-counts[a]);
const seg=(w,bg,tip)=>{const d=document.createElement('div');
  d.style.cssText=`width:${w}%;background:${bg}`;d.title=tip;bar.appendChild(d);};
for(const a of ranked.slice(0,8)){
  const pct=Math.round(100*counts[a]/total);
  seg(100*counts[a]/total,color(a),`${a}: ${pct}% of operations`);
  leg.insertAdjacentHTML('beforeend',`<span><i class=dot style="background:${color(a)}"></i>${a} ${pct}%</span>`);}
const rest=ranked.slice(8);
if(rest.length){
  const rt=rest.reduce((s,a)=>s+counts[a],0),pct=Math.round(100*rt/total);
  seg(100*rt/total,'#57606a',`${rest.length} other actors: ${pct}%`);
  leg.insertAdjacentHTML('beforeend',`<span><i class=dot style="background:#57606a"></i>+${rest.length} others ${pct}%</span>`);}
slider.max=commits.length;slider.value=commits.length;
function render(){
  const n=+slider.value;document.getElementById('commits').innerHTML='';
  pos.textContent=`${n}/${commits.length}`;
  commits.slice(0,n).reverse().forEach(c=>{
    const chips=(byC[c.hash]||[]).map(e=>`<span class=chip style="background:${color(e.actor)}">${esc(e.actor)}${e.turn?' '+esc(e.turn):''}${e.pr?' pr#'+e.pr:''}${e.type=='undo'?' undo':''}</span>`).join('');
    const li=document.createElement('li');
    li.innerHTML=`<span class=h>${c.short}</span><span class=d>${c.date.slice(0,10)}</span><span>${esc(c.subject)}</span>${c.refs?`<span class=ref>${esc(c.refs)}</span>`:''}${chips}`;
    li.onclick=()=>{document.querySelectorAll('#commits li').forEach(x=>x.classList.remove('sel'));li.classList.add('sel');detail(c);};
    document.getElementById('commits').appendChild(li);});}
function detail(c){
  let out=`commit ${c.hash}\\n${c.subject}\\n${c.date}\\n`;
  if(!(byC[c.hash]||[]).length)out+='\\n(no sun operations recorded for this commit)\\n';
  for(const e of byC[c.hash]||[]){
    out+=`\\nop ${e.id} \\u00b7 ${e.type} \\u00b7 ${e.actor}${e.turn?' \\u00b7 '+e.turn:''}${e.target_op?' \\u00b7 undoes op '+e.target_op:''}${e.target_commit?' \\u00b7 undoes '+e.target_commit.slice(0,8):''}\\n`;
    for(const ed of e.edits||[])out+=`  <f>${ed.file}</f>`+(ed.tool_call_id?` (tool ${ed.tool_call_id})`:'')+'\\n'+ed.patch.split('\\n').map(l=>'    '+l).join('\\n')+'\\n';}
  document.getElementById('detail').innerHTML=out.replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/&lt;f>(.*?)&lt;\\/f>/g,'<span class=file>$1</span>')
    .replace(/^( *\\+.*)$/gm,'<span class=add>$1</span>')
    .replace(/^( *-.*)$/gm,'<span class=del>$1</span>');}
let timer=null;
play.onclick=()=>{
  if(timer){clearInterval(timer);timer=null;return;}
  slider.value=0;render();
  timer=setInterval(()=>{if(+slider.value>=commits.length){clearInterval(timer);timer=null;return;}
    slider.value=+slider.value+1;render();},600);};
slider.oninput=render;render();
</script>
"""

# ----------------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(prog="sun", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="init git repo, .git/sun state, and agent hooks")
    sub.add_parser("hook", help="agent-harness hook entrypoint (JSON on stdin)")
    sub.add_parser("sync", help="detect and commit pending human edits")
    p = sub.add_parser("log", help="git log with actors, sessions and turns")
    p.add_argument("-n", type=int, default=30)
    p = sub.add_parser("show", help="show operations for a commit")
    p.add_argument("commit")
    p = sub.add_parser("undo", help="undo one operation (default: latest) or a commit")
    p.add_argument("--op", nargs="?", const="", default=None, metavar="ID")
    p.add_argument("--commit", nargs="?", const="HEAD", default=None, metavar="HASH")
    p = sub.add_parser("viz", help="write an HTML visualization of the op log")
    p.add_argument("-o", "--output", default=None)
    p.add_argument("-n", type=int, default=0, help="limit to N most recent commits")
    a = ap.parse_args(argv)
    if a.cmd not in ("init", "hook"):  # hook locates its repo from the payload
        os.chdir(root())
        sun_dir()
        a.lock = lock()
    {"init": cmd_init, "hook": cmd_hook, "sync": cmd_sync, "log": cmd_log,
     "show": cmd_show, "undo": cmd_undo, "viz": cmd_viz}[a.cmd](a)

if __name__ == "__main__":
    main()
