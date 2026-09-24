"""Explicit reconstruction of historical edits from Git and transcripts."""

import json
import os
import re
import sys
import time
import uuid

from . import checks
from . import git_store
from . import history
from . import sessions as session_store


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
    lines = git_store.read_text(path, errors="replace").splitlines()
    kinds = [session_store.prompt_line(l, harness) for l in lines]
    boundary = 3 if 3 in kinds else 1 if 1 in kinds else 2  # codex mirrors one prompt across records
    for line, kind in zip(lines, kinds):
        if kind and (harness == "claude" or kind == boundary): turn += 1
        try: o = json.loads(line)
        except ValueError: continue
        p = o.get("payload") or {}
        cwd = (p.get("cwd") if o.get("type") == "session_meta" else o.get("cwd")) or cwd
        t = checks.epoch(o.get("timestamp"))
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
    p = git_store.quiet("git", "cat-file", "-p", f"{tree}:{path}")
    return None if p.returncode else p.stdout


def tree_write(base, overlay):  # a base tree plus {path: text, or None to delete} -> a new tree
    ix, env = os.path.join(git_store.sun_dir(), "migrate-index"), None
    env = {**os.environ, "GIT_INDEX_FILE": ix}
    if os.path.exists(ix): os.remove(ix)
    git_store.git("read-tree", *([base] if base else ["--empty"]), env=env)
    info = "".join(f"0 {'0' * 40}\t{p}\n" if text is None else f"100644 {git_store.blob(text)}\t{p}\n"
                   for p, text in overlay.items())
    if info: git_store.git("update-index", "--index-info", input=info, env=env)
    return git_store.git("write-tree", env=env).strip()


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
        p = os.path.realpath(p if os.path.isabs(p) else os.path.join(cwd or git_store.root(), p))
        for base in sorted(session_store.repo_locations(), key=len, reverse=True) + ([os.path.realpath(cwd)] if cwd else []):
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
    ref, tip, evs = git_store.shadow_ref(), git_store.history_head(False), history.events()
    if tip and (len(evs) != 1 or evs[0].get("type") != "init"):
        sys.exit("sun: migrate right after `sun init`, before anything is recorded on this branch")
    published = [sha for _, sha in git_store.refs("refs/sun/published/")] + [git_store.ref_oid(git_store.remote_ref())]
    if tip and any(p and not git_store.quiet("git", "merge-base", "--is-ancestor", tip, p).returncode for p in published):
        sys.exit("sun: this branch's Sun history is already published; migrate on a fresh branch")
    calls = []
    for harness in ("claude", "codex"):
        for path, sid, sub in session_store.transcript_sources(harness):
            calls += call_records(path, harness, sid)
    since = checks.epoch(a.since + "T00:00:00Z") if a.since else None
    calls = sorted((c for c in calls if base_tool(c[4]["tool"]) in EDIT_TOOLS and (since is None or c[0] >= since)),
                   key=lambda c: c[0])
    if not calls: sys.exit("sun: no file-editing tool calls found in the agent sessions for this repository")
    log = [(int(ct), H, an) for H, ct, an in (l.split(" ", 2) for l in
           git_store.git("log", "--first-parent", "--reverse", "--format=%H %ct %an", "HEAD", check=False).splitlines())]
    before = [x for x in log if x[0] <= calls[0][0]]
    base = before[-1][1] if before else ""
    timeline = sorted([(t, 0, H, an) for t, H, an in log if t > calls[0][0]] +
                      [(c[0], 1, c, None) for c in calls], key=lambda x: (x[0], x[1]))
    if a.dry_run:
        sessions = {(c[1], c[2]) for c in calls}
        return print(f"sun: would replay {len(calls)} tool calls from {len(sessions)} sessions across "
                     f"{len(timeline) - len(calls)} Git commits since {iso(calls[0][0])}, starting at {base[:8] or 'an empty tree'}")
    tree = git_store.ref_oid(f"{base}^{{tree}}") if base else git_store.git("mktree", input="").strip()
    parent = git_store.make_shadow_commit(tree, "sun: initial state" + (f" at {base[:8]}" if base else ""), git_store.local(),
                                when=int(calls[0][0]))
    init = {"id": uuid.uuid4().hex, "timestamp": iso(calls[0][0]), "sequence": 0, "commit": parent, "branch": ref,
            "type": "init", "actor": git_store.local(), "edits": [], "git_commit": base}
    updates = [f"update refs/sun/ops/{parent} {parent}"]
    def put(ev): updates.append(f"update refs/sun/events/{ev['id']} {git_store.blob(json.dumps(ev))} {'0' * 40}")
    put(init)
    turn_key, turn_start, turn_evs, turn_calls, turn_when = None, parent, [], 0, [None]
    replayed = skipped = observed = 0
    def close_turn():
        nonlocal parent, turn_key, turn_start, turn_evs, turn_calls
        if not turn_evs: return
        actor, n = turn_evs[0]["actor"], turn_evs[0]["turn"][4:]
        T = git_store.make_shadow_commit(git_store.ref_oid(f"{parent}^{{tree}}"), f"sun: {actor} turn {n} ({turn_calls} tool calls)",
                               actor, [turn_start], when=turn_when[0])
        pid = git_store.patch_id(T)
        for i, ev in enumerate(turn_evs): ev.update(commit=T, sequence=i, patch_id=pid); put(ev)
        parent, turn_evs, turn_calls, turn_key = T, [], 0, None
    for t, kind, item, author in timeline:
        cur_tree = git_store.ref_oid(f"{parent}^{{tree}}")
        if kind == 0:  # a Git commit: whatever the replay did not explain is observed state
            close_turn()
            new_tree = git_store.ref_oid(f"{item}^{{tree}}")
            if new_tree == cur_tree: continue
            files = checks.changed_between(cur_tree, new_tree)
            c = git_store.make_shadow_commit(new_tree, f"sun: observed repository state at {item[:8]}", "unknown", [parent], when=int(t))
            p = git_store.patches(cur_tree, c, files)
            put({"id": uuid.uuid4().hex, "timestamp": iso(t), "sequence": 0, "commit": c, "branch": ref, "type": "observe",
                 "actor": "unknown", "patch_id": git_store.patch_id(c), "git_commit": item, "git_author": author,
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
        actor = git_store.agent(sid, harness)
        snap = git_store.make_shadow_commit(new_tree, f"sun: {actor} {call['tool']}", actor, [parent], when=int(t))
        turn_when[0] = int(t)
        p = git_store.patches(cur_tree, snap, list(overlay))
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
    git_store.git("update-ref", "--stdin", input="start\n" + "\n".join(dict.fromkeys(updates)) + "\nprepare\ncommit\n")
    git_store.save_state("branch.json", {"ref": ref, "git": git_store.ref_oid("HEAD"), "observe": True})
    history.sync(method="observed")  # what changed since the last commit or call, author unknown
    print(f"sun: replayed {replayed} tool calls into turn commits, observed {observed} Git commits, "
          f"could not replay {skipped} calls (their effects appear as observed state)")
