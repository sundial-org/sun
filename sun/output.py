"""History output: log, show, blame, JSON, terminal, HTML, and training export."""

import difflib
import fcntl
import json
import os
import re
import sys

from . import checks
from . import git_store
from . import history
from . import sessions as session_store


def stdout_file():  # file backing a redirected stdout (`sun export > dump.jsonl`)
    try:
        p = (fcntl.fcntl(1, fcntl.F_GETPATH, bytes(1024)).rstrip(b"\0").decode()
             if hasattr(fcntl, "F_GETPATH") else os.readlink("/proc/self/fd/1"))
        return [git_store.rel_to_root(p)] if os.path.isfile(p) else []
    except OSError: return []


def cmd_export(a):  # JSONL fine-tuning dump: one record per turn/op, prompt paired with edits
    history.maybe_sync([git_store.rel_to_root(a.output)] if a.output else stdout_file())  # never re-ingest our dump
    evs, merged = history.events(), {}
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
        hit = sid and session_store.operation_transcript(e, tid)
        if hit: prompt = session_store.chunk_prompt(hit[1])
        out.write(json.dumps({"timestamp": e["timestamp"], "actor": e["actor"], "session": sid,
                              "turn": e.get("turn"), "prompt": prompt,
                              "tool_calls": e["tool_calls"],
                              "edits": [{"file": d["file"], "patch": d["patch"] or git_store.git(
                                  "show", "--format=", e.get("commit") or "", "--", d["file"],
                                  check=False)} for d in e["edits"]]}) + "\n")
    if a.output: out.close(); print(f"sun: exported to {a.output}")


def cmd_log(a):
    history.maybe_sync()
    by_commit = {}
    for ev in history.events(): by_commit.setdefault(ev.get("commit"), []).append(ev)
    revisions = git_store.history_refs()
    for line in git_store.git("log", "--topo-order", *revisions, f"-{a.n}", "--pretty=%H\t%h\t%ad\t%s",
                    "--date=short").splitlines():
        H, h, date, subj = line.split("\t", 3)
        tags = "".join(dict.fromkeys(
            f"  [{e['actor']}" + (f" {e['turn']}" if e.get("turn") else "")
            + (f" pr#{e['pr']}" if e.get("pr") else "")
            + (f" {e['type']}" if e["type"] in ("undo", "restore") else "") + "]"
            for e in by_commit.get(H, [])))
        print(f"{h} {date} {subj}{tags or '  [untracked]'}")


def cmd_show(a):
    history.maybe_sync()
    if re.fullmatch(r"[0-9a-f]{8,32}", a.commit) and git_store.quiet("git", "rev-parse", "-q", "--verify",
                                                             a.commit + "^{commit}").returncode:
        hits = [c for i, c in checks.checks().items() if i.startswith(a.commit)]
        if len(hits) == 1: return print(json.dumps(hits[0], indent=2))
    H = git_store.resolve_history_rev(a.commit)
    print(git_store.git("show", "--stat", "--pretty=format:commit %h  %ad%n%s%n", "--date=short", H))
    evs = [e for e in history.events(True) if H in (e.get("commit"), e.get("snapshot"))]
    if not evs:  # squash-merge/rebase moved the sha: match events by patch-id instead
        pid = git_store.patch_id(H); evs = [e for e in history.events(True) if pid and e.get("patch_id") == pid]
    if not evs: print("no sun operations recorded for this commit")
    for e in evs: print(json.dumps(e, indent=2))


def cmd_blame(a):
    history.maybe_sync()
    d, b = os.path.split(a.file)  # blame a symlink itself: resolve only its directory
    f = os.path.relpath(os.path.join(os.path.realpath(d or "."), b), git_store.root())
    out = git_store.git("--literal-pathspecs", "-c", "core.quotepath=false", "blame", "--porcelain",
              "-L", f"{a.line},{a.line}", git_store.history_head(), "--", f)
    H, orig = out.split()[:2]  # originating commit + the line's number in it
    if H == "0" * 40: sys.exit(f"sun: {f}:{a.line} is uncommitted")
    of = next((l[9:] for l in out.splitlines() if l.startswith("filename ")), f)  # pre-rename path
    touches = lambda e: any(ed.get("file") == of for ed in e.get("edits") or [])
    all_ev = history.events(True)
    evs = [e for e in all_ev if e.get("commit") == H]
    if not evs:  # squash-merge/rebase moved the sha: match events by patch-id instead
        pid = git_store.patch_id(H); evs = [e for e in all_ev if pid and e.get("patch_id") == pid]
    ev = next((e for e in evs if touches(e)), evs[0] if evs else None)
    snapshots = [e for e in evs if e.get("snapshot") and e.get("snapshot") != e.get("commit")]
    if snapshots:  # re-blame the preserved snapshots: exact call + actor by line position
        tip, turn_commit = snapshots[-1]["snapshot"], snapshots[0]["commit"]
        if turn_commit != H:  # patch-id match: translate the line into the original squash
            ws = lambda rev: ["".join(l.split()) for l in  # patch-id ignores all whitespace
                              git_store.quiet("git", "show", f"{rev}:{of}").stdout.splitlines()]
            i, sm = int(orig) - 1, difflib.SequenceMatcher(None, ws(H), ws(turn_commit))
            orig = next((j1 + i - i1 + 1 for t, i1, i2, j1, j2 in sm.get_opcodes()
                         if t == "equal" and i1 <= i < i2), None)
        o = tip and orig and git_store.quiet("git", "--literal-pathspecs", "-c", "core.quotepath=false", "blame", "--porcelain",
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
    hit = session_store.operation_transcript(ev, tid)
    if not hit: return print("no transcript stored for this edit")
    n, chunk = hit
    prompt, ctx, tool = session_store.blame_context(chunk, tid)
    print(f"session {sid} ({n}):")
    if prompt: print(f"user: {prompt.strip()}")
    if ctx: print(f"agent: {ctx.strip()}")
    print(f"[{tool or '?'} {tid}]")


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
            "actor_info": git_store.actor_info(ev.get("actor", "unknown")),
            "session_id": ev.get("session_id"), "timestamp": ev.get("timestamp"),
            "turn": ev.get("turn"), "pr": ev.get("pr"),
            "target_op": ev.get("target_op"), "target_commit": ev.get("target_commit"),
            "attribution_methods": methods, "tool_calls": ev.get("tool_calls") or [],
            "edits": ev.get("edits") or []}


def viz_data(n=0):
    limit = [f"-{n}"] if n else []
    scope = git_store.history_refs()
    log = git_store.git("log", "--topo-order", *scope, *limit, "--date=iso",
              "--pretty=%H\x1f%h\x1f%P\x1f%D\x1f%ad\x1f%s\x1f%an\x1f%ae\x1f%cn\x1f%ce")
    cols = ["hash", "short", "parents", "refs", "date", "subject", "author_name",
            "author_email", "committer_name", "committer_email"]
    commits = [dict(zip(cols, l.split("\x1f"))) for l in log.splitlines()]
    sessions = session_store.session_data()
    all_events, by_commit, by_pid = history.events(), {}, {}
    for ev in all_events:
        by_commit.setdefault(ev.get("commit"), []).append(ev)
        if ev.get("patch_id"): by_pid.setdefault(ev["patch_id"], []).append(ev)
    hash_pids = {}
    if by_pid and any(c["hash"] not in by_commit for c in commits):
        patches_log = git_store.git("log", *scope, *limit,
                          "--pretty=format:%H", "-p")
        hash_pids = {H: pid for pid, H in (line.split()[:2] for line in
                     git_store.git("patch-id", "--stable", input=patches_log).splitlines())}
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
                                 "actors": [git_store.actor_info(a) for a in actor_ids]}
        commit["operations"] = operations
        for op in operations:
            counts[op["actor"]] = counts.get(op["actor"], 0) + 1
    actors = [{**git_store.actor_info(actor), "operations": count}
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
    identity = lambda p: f"{actor_label(git_store.actor_info(p['name']))} <{p['email']}>"
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
    git_store.write_text(out, VIZ.replace("__DATA__", encoded))
    print(f"sun: wrote {out}")


def cmd_viz(a):
    with git_store.lock():
        history.ensure_branch()
        history.maybe_sync([git_store.rel_to_root(a.output)] if a.output else stdout_file())
        data = viz_data(a.n)
    if getattr(a, "html", False) or a.output:
        return write_viz_html(data, a.output or os.path.join(git_store.sun_dir(), "viz.html"))
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
