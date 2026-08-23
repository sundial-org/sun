#!/usr/bin/env python3
"""Ingest a real repo + Claude Code sessions + GitHub PRs/issues into a sun
operation log (proposal: "Create example", steps 1-2).

Backfills .git/sun/events.jsonl for existing commits — no new commits are
created. Commits are attributed to agent sessions by matching each commit's
files against the sessions' Edit/Write tool calls in a surrounding time
window; everything else is attributed to the commit's human author. Merged
PRs become `pr` events on their merge commits; the full PR/issue dumps are
saved to .git/sun/github.json for the future `sft` exporter.

Usage: python3 example/demo_sundial.py [--limit 1000] [--no-github]
"""
import argparse, glob, json, os, subprocess, sys, uuid
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import sun

REPO = os.path.join(HERE, "sundial-md")
PROJECTS = os.path.expanduser("~/.claude/projects")
# every project dir for ~/sundial-md: the main folder plus its .claude worktrees
PROJECT_GLOB = os.path.join(PROJECTS, "-Users-bmo-sundial-md*")
EDIT_TOOLS = sun.EDIT_TOOLS
MAX_PATCH = 4000  # chars of stored patch per file
TRUNC_MARK = "\n[... patch truncated by sun ingest]"
# commit authors whose commits local transcripts can explain; other authors
# worked on other machines, so a filename+time match there is a false positive
LOCAL_AUTHORS = {"belinda mo", "belinda", "claude"}


def epoch(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def rel(path):
    """Repo-relative path from an absolute tool-call path (worktrees too)."""
    parts = path.split("/sundial-md/", 1)
    p = parts[1] if len(parts) > 1 else path.lstrip("/")
    if p.startswith(".claude/worktrees/"):
        p = p.split("/", 3)[-1]
    return p


def session_files():
    """All transcripts under the project dirs: top-level <session-ID>.jsonl
    files plus their nested subagent/workflow transcripts."""
    return sorted(f for d in glob.glob(PROJECT_GLOB)
                  for f in glob.glob(os.path.join(d, "**", "*.jsonl"),
                                     recursive=True))


def parent_sid(path):
    """Session id: the filename, or the parent session dir for nested
    subagent/workflow transcripts (<project>/<session-uuid>/subagents/...)."""
    parts = os.path.relpath(path, PROJECTS).split(os.sep)
    return parts[1] if len(parts) > 2 else parts[-1][:-6]


def scan_sessions():
    """file -> [(time, session_id, turn, tool_call_id, tool)] from transcripts."""
    index, sessions, files = {}, set(), session_files()
    for path in files:
            sid, turn, found = parent_sid(path), 0, False
            with open(path) as f:
                for line in f:
                    if '"type":"user"' not in line and '"tool_use"' not in line:
                        continue
                    try:
                        o = json.loads(line)
                    except ValueError:
                        continue
                    content = (o.get("message") or {}).get("content")
                    if (o.get("type") == "user" and not o.get("isSidechain")
                            and isinstance(content, str)):
                        turn += 1
                    if o.get("type") != "assistant" or not isinstance(content, list):
                        continue
                    for b in content:
                        if b.get("type") != "tool_use" or b.get("name") not in EDIT_TOOLS:
                            continue
                        fp = sun.tool_file(b.get("input", {}))
                        if fp and o.get("timestamp"):
                            found = True
                            index.setdefault(rel(fp), []).append(
                                (epoch(o["timestamp"]), sid, turn, b.get("id"), b["name"]))
            if found:
                sessions.add(sid)
    for recs in index.values():
        recs.sort()
    return index, len(sessions), len(files)


def read_commits(limit):
    """One `git log -p` pass -> [(hash, author, time, subject, {file: patch})]."""
    out = subprocess.run(
        ["git", "log", f"-{limit}", "--no-merges", "--unified=1", "-p",
         "--pretty=format:%x1e%H%x1f%an%x1f%at%x1f%s"],
        capture_output=True, text=True, cwd=REPO, errors="replace").stdout
    commits = []
    for rec in out.split("\x1e")[1:]:
        head, _, diff = rec.partition("\ndiff --git ")
        H, author, at, subject = head.strip("\n").split("\x1f")
        files = {}
        for chunk in ("diff --git " + diff).split("\ndiff --git ")[0 if diff else 1:]:
            if not chunk.startswith("diff --git"):
                chunk = "diff --git " + chunk
            target = chunk.split(" b/", 1)[-1].split("\n", 1)[0]
            files[target] = (chunk[:MAX_PATCH] + TRUNC_MARK
                             if len(chunk) > MAX_PATCH else chunk)
        commits.append((H, author, int(at), subject, files))
    return list(reversed(commits))  # oldest first, so tool calls match in order


def match_session(files, at, index, used):
    """Best (session, {file: (tool_id, tool, turn)}) near this commit time."""
    per_session = {}
    for f in files:
        for rec in index.get(f, ()):
            t, sid, turn, tid, tool = rec
            if at - 6 * 3600 <= t <= at + 600 and id(rec) not in used:
                per_session.setdefault(sid, {})[f] = (rec, turn)
    if not per_session:
        return None, {}
    sid = max(per_session, key=lambda s: len(per_session[s]))
    for f, (rec, _) in per_session[sid].items():
        used.add(id(rec))
    return sid, per_session[sid]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=1000)
    ap.add_argument("--no-github", action="store_true")
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, ".git", "sun"), exist_ok=True)

    index, n_sessions, n_files = scan_sessions()
    print(f"transcripts scanned: {n_files} (incl. subagents), "
          f"{n_sessions} sessions with edits, "
          f"{sum(len(v) for v in index.values())} tool calls over {len(index)} files")
    commits = read_commits(a.limit)
    print(f"commits ingested: {len(commits)}")

    used, events, stats = set(), [], {"agent": 0, "human": 0, "mixed": 0}
    for H, author, at, subject, files in commits:
        ts = datetime.fromtimestamp(at).astimezone().isoformat()
        local = author.lower() in LOCAL_AUTHORS
        sid, matched = match_session(files, at, index, used) if local else (None, {})
        by_author_agent = "claude" in author.lower()
        agent_files = set(matched) or (set(files) if by_author_agent else set())
        actor = (f"agent:claude/{sid[:8]}" if sid
                 else "agent:claude" if by_author_agent else None)
        a_edits = [{"file": f, "patch": files[f],
                    "tool_call_id": matched[f][0][3] if f in matched else None,
                    "attribution": {"method": "edit_tool" if f in matched
                                    else "commit_author"}}
                   for f in files if f in agent_files]
        h_edits = [{"file": f, "patch": files[f],
                    "char_edits": sun.char_edits(files[f])}
                   for f in files if f not in agent_files]
        if a_edits:
            turn = max(m[1] for m in matched.values()) if matched else None
            events.append({"id": uuid.uuid4().hex[:8], "type": "edit",
                           "actor": actor, "timestamp": ts, "commit": H,
                           **({"turn": f"turn{turn}"} if turn else {}),
                           "edits": a_edits,
                           "tool_calls": [{"id": m[0][3], "tool": m[0][4],
                                           "input": {"file": f}}
                                          for f, m in matched.items()]})
        if h_edits:
            human = "human:" + author.replace(" ", "-").lower()
            events.append({"id": uuid.uuid4().hex[:8], "type": "edit",
                           "actor": human, "timestamp": ts, "commit": H,
                           "edits": h_edits})
        stats["mixed" if a_edits and h_edits else "agent" if a_edits else "human"] += 1

    prs = issues = []
    if not a.no_github:
        def gh(*args):
            r = subprocess.run(["gh", *args, "--repo", "sundial-org/sundial-md",
                                "--state", "all", "--limit", "2000"],
                               capture_output=True, text=True)
            return json.loads(r.stdout) if not r.returncode else []
        prs = gh("pr", "list", "--json",
                 "number,title,author,state,mergedAt,mergeCommit")
        issues = gh("issue", "list", "--json", "number,title,author,state,createdAt")
        known = set(subprocess.run(  # incl. merge commits, which --no-merges skips
            ["git", "log", f"-{a.limit}", "--pretty=%H"],
            capture_output=True, text=True, cwd=REPO).stdout.split())
        for pr in prs:
            oid = (pr.get("mergeCommit") or {}).get("oid")
            if oid in known:
                subj = subprocess.run(["git", "log", "-1", "--pretty=%s", oid],
                                      capture_output=True, text=True, cwd=REPO
                                      ).stdout.strip()
                # stacked PRs: GitHub reports the same merge commit for both
                if "Merge pull request #" in subj and f"#{pr['number']}" not in subj:
                    continue
                events.append({"id": uuid.uuid4().hex[:8], "type": "pr",
                               "actor": "human:" + pr["author"]["login"],
                               "timestamp": pr.get("mergedAt"), "commit": oid,
                               "pr": pr["number"], "title": pr["title"], "edits": []})
        with open(os.path.join(REPO, ".git", "sun", "github.json"), "w") as f:
            json.dump({"prs": prs, "issues": issues}, f)
        print(f"github: {len(prs)} PRs, {len(issues)} issues "
              f"({sum(1 for e in events if e['type'] == 'pr')} merge events)")

    with open(os.path.join(REPO, ".git", "sun", "events.jsonl"), "w") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")
    print(f"events written: {len(events)}  (commits: {stats})")

    os.chdir(REPO)
    print("\n$ sun log -n 12")
    sun.main(["log", "-n", "12"])
    sun.main(["viz", "-n", "1000", "-o", os.path.join(HERE, "sundial.html")])


if __name__ == "__main__":
    main()
