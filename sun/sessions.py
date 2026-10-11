"""Native transcripts and the optional shared session store."""

import glob
import json
import os
import re
import shutil
import sys
import time
from typing import List

from . import git_store
from . import history


def projects():
    return os.environ.get("SUN_PROJECTS", os.path.expanduser("~/.claude/projects"))


def codex_sessions():
    return os.environ.get("SUN_CODEX_SESSIONS", os.path.expanduser("~/.codex/sessions"))


def parse_events(text: str) -> List[history.Event]:  # skips torn lines rather than bricking every command
    out: List[history.Event] = []
    for l in text.splitlines():
        try: out.append(json.loads(l))
        except ValueError: pass
    return out


def store_chunks(sid, files, u=None):  # {path: text} -> refs/sun/sessions/<u>/<sid> tree
    if not files: return
    ref, ix = f"refs/sun/sessions/{u or git_store.user()}/{sid}", os.path.join(git_store.sun_dir(), "tmpindex")
    env = {**os.environ, "GIT_INDEX_FILE": ix}
    if os.path.exists(ix): os.remove(ix)
    if not git_store.quiet("git", "rev-parse", "-q", "--verify", ref).returncode:
        git_store.git("read-tree", ref, env=env)
    git_store.git("update-index", "--index-info", env=env,
        input="".join(f"100644 blob {git_store.blob(c)}\t{p}\n" for p, c in files.items()))
    parent = git_store.ref_oid(ref)
    args = ["commit-tree", git_store.git("write-tree", env=env).strip(), "-m", sid]
    if parent: args += ["-p", parent]
    commit = git_store.git(*args).strip()
    git_store.git("update-ref", ref, commit, parent or "0" * len(commit))


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


enc = lambda path: re.sub(r"[/.]", "-", path)


def project_dirs():  # every ~/.claude project dir that maps to this repo (worktrees too)
    wt = [l.split(" ", 1)[1] for l in git_store.git("worktree", "list", "--porcelain", check=False)
          .splitlines() if l.startswith("worktree ")]
    names = {enc(p) for r in [git_store.root()] + wt for p in (r, os.path.realpath(r))}
    return [d for d in glob.glob(os.path.join(projects(), "*")) if os.path.basename(d) in names
            or any(os.path.basename(d).startswith(n + "--claude-worktrees-") for n in names)]


def repo_locations():
    wt = [l.split(" ", 1)[1] for l in git_store.git("worktree", "list", "--porcelain", check=False)
          .splitlines() if l.startswith("worktree ")]
    return {os.path.realpath(p) for p in [git_store.root()] + wt}


def codex_meta(path):
    try:
        for line in git_store.read_text(path, errors="replace").splitlines():
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
    for line in git_store.read_text(path, errors="replace").splitlines(keepends=True):
        if prompt_line(line):
            if seen: chunks.append("".join(cur)); cur = []
            seen = True
        cur.append(line)
    if cur: chunks.append("".join(cur))
    return chunks


def scan_codex_transcript(path):
    lines = git_store.read_text(path, errors="replace").splitlines(keepends=True)
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
    if not git_store.cfg_share_sessions():
        return "session sharing disabled; transcripts remain in their native harness directories"
    t0, seen, ns, nsub = time.time(), git_store.state("imported.json", {}), 0, 0
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
    git_store.save_state("imported.json", seen)
    return f"stored {ns} sessions, {nsub} subagents in {time.time() - t0:.1f}s"


session_rows = lambda: [(r.split("/", 4)[4], r.split("/")[3], r)  # (sid, user, ref)
                        for r, _ in git_store.refs("refs/sun/sessions/")]


def session_text(ref, sub=None):
    pre = f"subagents/{sub}/" if sub else ""
    names = sorted(n for n in git_store.git("ls-tree", "-r", "--name-only", ref).splitlines()
                   if n.startswith(pre) and n.count("/") == pre.count("/"))
    return "".join(git_store.git("cat-file", "blob", f"{ref}:{n}") for n in names)


def session_export_dir(): return os.path.join(git_store.sun_dir(), "sessions", enc(git_store.root()))


def session_data():
    base, owner = session_export_dir(), git_store.user()
    local_paths = git_store.state("session-paths.json", {})
    for harness in ("claude", "codex"):
        for path, sid, sub in transcript_sources(harness):
            entry = local_paths.setdefault(git_store.session_key(sid, harness),
                         {"id": sid, "harness": harness, "path": None, "subagents": {}})
            if sub: entry["subagents"][sub] = os.path.abspath(path)
            else: entry["path"] = os.path.abspath(path)
    # Older installs already recorded native paths in their turn state.
    for key, turn in git_store.state("turns.json", {}).items():
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
        git_store.write_text(fp, session_text(ref))
        subs = {}
        for sub in sorted({n.split("/")[1] for n in git_store.git("ls-tree", "-r", "--name-only", ref)
                           .splitlines() if n.startswith("subagents/")}):
            subdir = os.path.join(dest, sid, "subagents")
            os.makedirs(subdir, exist_ok=True)
            subs[sub] = os.path.join(subdir, sub + ".jsonl")
            git_store.write_text(subs[sub], session_text(ref, sub))
        idx.append({"id": sid, "user": u, "harness": None, "path": fp,
                    "subagents": subs, "origin": "team", "ref": ref})
    return idx


def export_sessions():
    idx = session_data()
    os.makedirs(session_export_dir(), exist_ok=True)
    git_store.jwrite(os.path.join(session_export_dir(), "sessions-index.json"), idx)
    return len(idx)


def cmd_sessions(a):
    if a.session_cmd == "import":
        if not git_store.cfg_share_sessions():
            sys.exit("sun: session sharing is disabled; run `sun init --share-sessions`")
        return print("sun: " + do_import(git_store.configured_harnesses()))
    if a.session_cmd == "export":
        return print(f"sun: exported {export_sessions()} sessions to .git/sun/sessions/")
    if a.session_cmd == "prune":
        if a.older_than < 0: sys.exit("sun: --older-than must be zero or greater")
        prefix = f"refs/sun/sessions/{git_store.user()}/"
        cutoff = time.time() - a.older_than * 86400
        old = [r for r, sha in git_store.refs(prefix)
               if int(git_store.git("show", "-s", "--format=%ct", sha).strip()) < cutoff]
        if a.remote and old:
            if "origin" not in git_store.git("remote", check=False).split():
                sys.exit("sun: cannot prune remote sessions without an origin remote")
            git_store.git("push", "--no-verify", "origin", "--delete", *old)
        for ref in old:
            git_store.git("update-ref", "-d", ref)
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
        count = len(git_store.git("ls-tree", "-r", "--name-only", ref).splitlines())
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
    info = git_store.actor_info(ev.get("actor"))
    sid = ev.get("session_id")
    if info["user"] == git_store.user():
        entry = git_store.state("session-paths.json", {}).get(git_store.session_key(sid, info["harness"]), {})
        paths = [entry.get("path")] + list(entry.get("subagents", {}).values())
        if not any(paths):
            paths = [p for p, s, _ in transcript_sources(info["harness"]) if s == sid]
        for path in paths:
            if path and os.path.isfile(path):
                for chunk in scan_transcript(path, info["harness"]):
                    if tid in chunk: return path, chunk
    for stored, owner, ref in session_rows():
        if stored == sid and owner == info["user"]:
            for name in git_store.git("ls-tree", "-r", "--name-only", ref).splitlines():
                chunk = git_store.git("cat-file", "blob", f"{ref}:{name}")
                if tid in chunk: return name, chunk
    return None
