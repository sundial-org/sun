"""Branch timelines, recorded events, turn squashing, and undo/restore."""

import json
import re
import sys
import time
import uuid
from typing import Any, Dict, List, Optional, TypedDict

from . import git_store


# How the edit was attributed; the responsible actor is stored on Event.
# Options are hook, sync, observed, and uncertain.
# TODO: potentially flatten this into Edit
class Attribution(TypedDict, total=False):
    method: str


# An Edit is one file's observed change, whether made by a person or an agent.
class Edit(TypedDict, total=False):
    file: str
    patch: str
    tool_call_id: Optional[str]
    attribution: Attribution


# A ToolCall is an attempted action that may produce zero or many Edits across files.
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
    commit: str  # History commit containing this event; may group a whole turn.
    snapshot: str  # Original operation commit retained when commit becomes a turn squash.
    patch_id: Optional[str]
    turn: str
    # Usually one call for a tool edit, none for a local edit; squashing keeps events separate.
    tool_calls: List[ToolCall]
    edits: List[Edit]
    target_op: str  # Operation being undone.
    target_commit: str  # Commit being undone, or the desired state for restore.
    parents: List[str]
    pr: int
    branch: str
    sequence: int
    git_action: Dict[str, Any]  # Reflog identity is separate from edit authorship.


def pull_action(before, after):
    """Only identify an immediately matching reflog transition; otherwise leave it unknown."""
    if not before or before == after: return
    rows = git_store.git("reflog", "show", "-2", "--format=%H%x00%gn%x00%ge%x00%gs",
                         "HEAD", check=False).splitlines()
    if len(rows) != 2: return
    current, previous = [row.split("\0", 3) for row in rows]
    if len(current) != 4 or current[0] != after or previous[0] != before: return
    if not current[3].startswith("pull ") and not current[3].startswith("pull:"): return
    return {"command": "git " + current[3].split(":", 1)[0], "reflog": current[3],
            "name": current[1], "email": current[2], "before": before, "after": after,
            "executor": "unknown"}


def observed_subject(action):
    return (f"sun: observed changes after {action['command']} (Git identity: {action['name']})"
            if action else "sun: observed repository state")


def ensure_branch():
    """Select a timeline; Git ancestry never determines how Sun combines file contents."""
    ref, normal = git_store.shadow_ref(), git_store.ref_oid("HEAD")
    previous = git_store.state("branch.json", {})
    tip = git_store.history_head(False)
    birth = git_store.state("branch-creation.json", {})
    if birth.get("target") == ref:
        # Also complete a committed unborn HEAD switch if a concurrent Sun writer
        # acquires the lock before the committed Git hook. Publish before any edit.
        source = git_store.ref_oid(birth["source"])
        if not tip and source:
            git_store.git("update-ref", ref, source, "0" * len(source))
            tip = source
        git_store.save_state("branch-creation.json", {})
    if not tip:
        # Branch creation hooks pin inheritance immediately. A missing pointer has no
        # reliable source: never infer it from a worktree's previous branch or equal SHAs.
        print("sun: no recorded branch creation; starting Sun history at the Git checkout", file=sys.stderr)
        tree = git_store.ref_oid(f"{normal}^{{tree}}") if normal else git_store.git("mktree", input="").strip()
        c = git_store.make_shadow_commit(tree, "sun: initial state", git_store.local())
        record(type="init", actor=git_store.local(), commit=c, edits=[])
    # A changed checkout is evidence of a new state, not evidence that this user authored it.
    observe = previous.get("observe", False) or bool(tip and not previous) or bool(previous and (
        previous.get("ref") != ref or previous.get("git") != normal))
    action = previous.get("git_action") if previous.get("observe") else None
    if previous.get("ref") != ref:
        action = None
    elif previous.get("git") != normal:
        action = pull_action(previous.get("git"), normal)
    git_store.save_state("branch.json", {"ref": ref, "git": normal, "observe": observe,
                                         "git_action": action})


def events(include_unreachable=False, scope=None) -> List[Event]:
    evs = []
    for ref, raw in git_store.ref_blobs("refs/sun/events/"):
        ev = json.loads(raw)
        if not re.fullmatch(r"[0-9a-f]{8}|[0-9a-f]{32}", ev.get("id", "")) or ref != f"refs/sun/events/{ev['id']}":
            sys.exit("sun: invalid operation ID in fetched history")
        evs.append(ev)
    if not evs: return []
    scope = git_store.history_refs() if scope is None else scope
    order = {c: i for i, c in enumerate(git_store.git("rev-list", "--topo-order", "--reverse",
                                            *scope).split())} if scope else {}
    # Git ancestry orders causes before effects. Concurrent branches have no total time order.
    return sorted((e for e in evs if e.get("commit") in order or
                   include_unreachable and e.get("branch") == git_store.shadow_ref()),
                  key=lambda e: (order.get(e["commit"], len(order)), e.get("sequence", 0), e["id"]))


def publish(commit, evs, before=None, ref=None):
    if before is None:
        parents = git_store.git("rev-list", "--parents", "-n1", commit).split()[1:]
        before = parents[0] if parents else ""
    updates = [f"update {ref or git_store.shadow_ref()} {commit} {before or '0' * len(commit)}"]
    for ev in evs:
        ref = f"refs/sun/events/{ev['id']}"
        updates.append(f"update {ref} {git_store.blob(json.dumps(ev))} {git_store.ref_oid(ref) or '0' * len(commit)}")
        snapshot = ev.get("snapshot", commit)
        updates.append(f"update refs/sun/ops/{snapshot} {snapshot}")
    git_store.git("update-ref", "--stdin", input="start\n" + "\n".join(dict.fromkeys(updates)) +
        "\nprepare\ncommit\n")


def record_batch(commit, entries, ref=None):
    evs = [{"id": uuid.uuid4().hex, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "sequence": i, "commit": commit, "branch": ref or git_store.shadow_ref(), **e} for i, e in enumerate(entries)]
    publish(commit, evs, ref=ref)
    return evs


def record(**ev: Any) -> Event:
    return record_batch(ev["commit"], [ev])[0]


edits_msg = lambda actor, files: (f"sun: {actor} edits " + ", ".join(files[:3])
                                  + (f" +{len(files) - 3} more" if len(files) > 3 else ""))


def sync(exclude=(), method="sync"):  # record unclaimed file changes, without touching Git's index
    active = git_store.state("active.json", {})
    if any(s.get("all_files") for s in active.values()): return
    exclude = set(exclude) | {f for s in active.values() for f in s["files"]}
    files = [f for f in git_store.changed_files() if f not in exclude]
    branch = git_store.state("branch.json", {})
    if method in ("sync", "hook") and branch.get("observe"): method = "observed"
    if not files:
        if not active and branch.get("observe"):
            git_store.save_state("branch.json", {**branch, "observe": False})
        return None
    pre, actor = git_store.history_head(), "unknown" if method in ("uncertain", "observed") else git_store.local()
    action = branch.get("git_action") if method == "observed" else None
    c = git_store.commit_files(files, observed_subject(action) if method == "observed"
                     else edits_msg(actor, files), actor)
    p = git_store.patches(pre, c, files)
    ev = record(type="observe" if method == "observed" else "edit", actor=actor, commit=c, patch_id=git_store.patch_id(c),
                  edits=[{"file": f, "patch": p[f],
                          "attribution": {"method": method}} for f in files],
                **({"git_action": action} if action else {}))
    if not active and branch.get("observe"):
        git_store.save_state("branch.json", {**branch, "observe": False})
    return ev


def maybe_sync(exclude=()):
    sync(exclude)  # sync itself excludes in-flight files and unknown-scope shell calls


def squash_turn(sid, harness="claude"):
    # Stop: squash the turn's agent calls and intervening local edits into one turn commit.
    # A different agent or an already-aggregated commit remains a hard boundary.
    t = git_store.state("turns.json", {}).get(git_store.session_key(sid, harness))
    tip = git_store.history_head()
    if not t or t.get("branch") != git_store.shadow_ref() or t.get("squashed") or \
            git_store.quiet("git", "merge-base", "--is-ancestor", t["start"], tip).returncode: return
    start, actor = t["start"], git_store.agent(sid, harness)
    rng = git_store.git("rev-list", f"{start}..{tip}").split()
    published = [sha for _, sha in git_store.refs("refs/sun/published/")] + [git_store.ref_oid(git_store.remote_ref())]
    published += [sha for ref, sha in git_store.refs("refs/sun/heads/") if ref != git_store.shadow_ref()]
    if any(p and not git_store.quiet("git", "merge-base", "--is-ancestor", c, p).returncode
           for p in published for c in rng): return
    ops = [e for e in events() if e.get("commit") in rng]
    mine = [e for e in ops if e["actor"] == actor]
    allowed = {actor, git_store.local()}
    raw = [e for e in ops if e.get("type") == "edit" and e["actor"] in allowed
           and not e.get("snapshot")]
    if not rng or not mine or len(raw) != len(ops) or set(rng) - {e["commit"] for e in raw}:
        return
    # Rewriting the turn removes these commits from the main shadow lineage. Keep every
    # operation snapshot, including intervening human edits, reachable and shareable.
    # commit-tree + update-ref never touch the worktree/index: edits after the last call stay dirty
    c = git_store.make_shadow_commit(git_store.git("rev-parse", f"{tip}^{{tree}}").strip(),
                           f"sun: {actor} turn {t['n']} ({len(mine)} tool calls)",
                           actor, [start])
    turn_pid = git_store.patch_id(c)
    revisions = [{**e, "commit": c, "snapshot": e["commit"], "sequence": i,
                  "patch_id": turn_pid} for i, e in enumerate(ops)]
    publish(c, revisions, tip)
    turns = git_store.state("turns.json", {})
    turns[git_store.session_key(sid, harness)]["squashed"] = True
    git_store.save_state("turns.json", turns)


def join_history(remote, ref):
    """Combine recorded ancestry, retaining the selected branch's snapshot and original operations."""
    tip = git_store.ref_oid(ref)
    if not remote or not git_store.quiet("git", "merge-base", "--is-ancestor", remote, tip).returncode:
        return tip
    tree = git_store.ref_oid(f"{tip}^{{tree}}")
    if tree == git_store.ref_oid(f"{remote}^{{tree}}") and not git_store.quiet(
            "git", "merge-base", "--is-ancestor", tip, remote).returncode:
        git_store.git("update-ref", ref, remote, tip)
        return remote
    c = git_store.make_shadow_commit(tree, "sun: combine recorded histories", git_store.local(), [tip, remote])
    record_batch(c, [dict(type="merge", actor=git_store.local(), parents=[tip, remote], edits=[])], ref=ref)
    return c


def cmd_push(a):
    """Publish recorded Sun history only; never commit, stage, merge files, or push Git branches."""
    branch = a.branch or git_store.git("symbolic-ref", "--short", "HEAD").strip()
    if git_store.quiet("git", "check-ref-format", "refs/heads/" + branch).returncode:
        sys.exit("sun: push requires a local branch name, not a revision or refspec")
    ref = "refs/sun/heads/" + branch
    if not git_store.ref_oid(ref): sys.exit("sun: branch has no recorded Sun history")
    # Fetch ancestry, not mutable session refs: publication must not overwrite our local transcripts.
    git_store.git("fetch", "-q", a.remote, *git_store.refspecs(False, a.remote))
    tip = join_history(git_store.ref_oid(f"refs/sun/remotes/{a.remote}/{branch}"), ref)
    selected = events(scope=[tip])
    snapshots = {e.get("snapshot", e["commit"]) for e in selected}
    # ponytail: one refspec per operation; batch transport if very large histories hit ARG_MAX.
    specs = [f"{tip}:{ref}"]
    specs += [f"refs/sun/events/{e['id']}:refs/sun/events/{e['id']}" for e in selected]
    specs += [f"refs/sun/ops/{sha}:refs/sun/ops/{sha}" for sha in sorted(snapshots)]
    if git_store.cfg_share_sessions():
        sessions = {e.get("session_id") for e in selected if e["actor"].startswith(git_store.user() + "/agent:")}
        specs += [f"{sha}:{r}" for r, sha in git_store.refs(f"refs/sun/sessions/{git_store.user()}/")
                  if r.rsplit("/", 1)[-1] in sessions]
    # Protect operations even when an interrupted push has an unknown outcome.
    git_store.git("update-ref", ref.replace("refs/sun/heads/", "refs/sun/published/"), tip)
    if git_store.refs("refs/sun/checks/"):  # separately, and fail-soft: checks never block history
        result = git_store.quiet("git", "push", "--no-verify", "--", a.remote, "refs/sun/checks/*:refs/sun/checks/*")
        if result.returncode:
            print(f"sun: warning: check upload to {a.remote} failed; checks remain local. "
                  "Continuing with history push; retry `sun push` after fixing the error.", file=sys.stderr)
            if result.stderr.strip(): print(result.stderr.strip(), file=sys.stderr)
    git_store.git("push", "--atomic", "--no-verify", "--", a.remote, *specs)


def cmd_sync(a):
    if a.recover:
        for claim in git_store.state("active.json", {}).values():
            if claim.get("id"): git_store.git("update-ref", "-d", "refs/sun/pending/" + claim["id"])
        git_store.save_state("active.json", {})
    ev = sync(method="uncertain" if a.recover else "sync")
    print(f"sun: recorded edits as op {ev['id']}" if ev else "sun: nothing to sync")


def apply_checked(patch, reverse, failure, dry_run=False):
    args = ["apply"] + (["-R"] if reverse else [])
    if git_store.quiet("git", *args, "--check", input=patch).returncode: sys.exit(failure)
    if not dry_run: git_store.git(*args, input=patch)


def cmd_undo(a):
    if git_store.state("active.json", {}): sys.exit("sun: wait for active tool calls before undoing")
    actor = git_store.local()
    if a.commit is not None:
        H = git_store.resolve_history_rev(a.commit)
        parents = git_store.git("rev-list", "--parents", "-n1", H).split()[1:]
        if not parents: sys.exit("sun: cannot undo the initial shadow commit")
        if len(parents) != 1: sys.exit("sun: cannot undo a merge commit; restore a parent instead")
        patch = git_store.git("diff", "--binary", parents[0], H)
        if not a.dry_run: maybe_sync()
        apply_checked(patch, True, f"sun: cannot undo commit {H[:8]} cleanly", a.dry_run)
        if a.dry_run: return print(f"sun: can undo commit {H[:8]}")
        files, pre = git_store.changed_files(), git_store.history_head()
        c = git_store.commit_files(files or ["."], f"sun: undo commit {H[:8]}", actor)
        record(type="undo", actor=actor, commit=c, target_commit=H,
               edits=[{"file": f, "patch": git_store.patches(pre, c, files)[f]} for f in files])
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
    pre = git_store.history_head()
    c = git_store.commit_files(files, f"sun: undo op {target['id']}", actor)
    record(type="undo", actor=actor, commit=c, target_op=target["id"],
           edits=[{"file": f, "patch": git_store.patches(pre, c, files)[f]} for f in files])
    print(f"sun: undid op {target['id']} in {c[:8]}")


def cmd_restore(a):
    if git_store.state("active.json", {}): sys.exit("sun: wait for active tool calls before restoring")
    target = git_store.resolve_history_rev(a.commit)
    maybe_sync(); pre = git_store.history_head()
    patch = git_store.git("diff", "--binary", pre, target)
    if not patch: return print(f"sun: already at {target[:8]}")
    apply_checked(patch, False, f"sun: cannot restore {target[:8]} cleanly")
    files = git_store.changed_files()
    c = git_store.commit_files(files or ["."], f"sun: restore {target[:8]}", git_store.local())
    record(type="restore", actor=git_store.local(), commit=c, target_commit=target,
           edits=[{"file": f, "patch": git_store.patches(pre, c, files)[f]} for f in files])
    print(f"sun: restored {target[:8]} in {c[:8]}")
