"""Real CLI/Git experiments. Nothing runs on import; the CLI preserves all created repos."""
import argparse
import json
import os
from pathlib import Path
import random
import shlex
import subprocess
import sys
import threading
import time
import unittest

SUN = Path(__file__).resolve().parents[1] / "sun.py"


class Lab:
    def __init__(self, directory, seed=17):
        self.root = Path(directory).resolve()
        self.root.mkdir(parents=True, exist_ok=False)
        self.seed = seed
        self.log_lock = threading.Lock()
        self.users = []
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                        PYTHONDONTWRITEBYTECODE="1", GIT_TERMINAL_PROMPT="0")
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        launcher = bin_dir / "sun"
        launcher.write_text("#!/bin/sh\nexec " + shlex.quote(sys.executable) + " " +
                            shlex.quote(str(SUN)) + ' "$@"\n')
        launcher.chmod(0o755)
        self.env["PATH"] = str(bin_dir) + os.pathsep + self.env.get("PATH", "")
        self.remote = self.root / "remote.git"
        self.command(self.root, ["git", "init", "--bare", "--initial-branch=main", str(self.remote)])

    def log(self, record):
        with self.log_lock, (self.root / "actions.jsonl").open("a") as f:
            f.write(json.dumps(record) + "\n")

    def command(self, cwd, args, env=None, input=None, ok=True):
        p = subprocess.run(args, cwd=cwd, env=env or self.env, input=input,
                           text=True, capture_output=True, timeout=45)
        self.log(dict(cwd=str(cwd), argv=args, stdin=input, status=p.returncode,
                      stdout=p.stdout, stderr=p.stderr))
        if ok and p.returncode:
            raise AssertionError(f"{args} failed in {cwd}:\n{p.stdout}\n{p.stderr}")
        return p

    def user(self, name, identity=None):
        path = self.root / name
        if self.users:
            self.command(self.root, ["git", "clone", str(self.remote), str(path)])
        else:
            path.mkdir()
            self.command(path, ["git", "init", "--initial-branch=main"])
            self.command(path, ["git", "remote", "add", "origin", str(self.remote)])
        repo = Repo(self, path, identity or name)
        self.users.append(repo)
        repo.git("config", "user.name", repo.identity)
        repo.git("config", "user.email", repo.identity + "@example.test")
        repo.git("config", "commit.gpgsign", "false")
        repo.git("config", "merge.gpgsign", "false")
        repo.git("config", "core.autocrlf", "false")
        if len(self.users) == 1:
            repo.edit("shared.txt", "baseline\n")
            repo.git("add", ".")
            repo.git("commit", "-m", "baseline")
        repo.sun("init", "--claude", "--no-share-sessions", "--no-instructions")
        if repo.git("status", "--porcelain").stdout:
            repo.commit("track hook configuration")
        if len(self.users) == 1:
            repo.sun("push")
        return repo

    def remote_refs(self):
        return self.command(self.root, ["git", "--git-dir", str(self.remote), "show-ref"]).stdout


class Repo:
    def __init__(self, lab, path, identity):
        self.lab, self.path, self.identity = lab, path, identity
        self.env = {**lab.env, "SUN_PROJECTS": str(lab.root / (path.name + "-claude")),
                    "SUN_CODEX_SESSIONS": str(lab.root / (path.name + "-codex"))}
        Path(self.env["SUN_PROJECTS"]).mkdir()
        Path(self.env["SUN_CODEX_SESSIONS"]).mkdir()

    def git(self, *args, **kwargs):
        return self.lab.command(self.path, ["git", *args], self.env, **kwargs)

    def sun(self, *args, **kwargs):
        return self.lab.command(self.path, [sys.executable, str(SUN), *args], self.env, **kwargs)

    def oid(self, ref="HEAD"):
        return self.git("rev-parse", ref).stdout.strip()

    def refs(self, prefix):
        return self.git("for-each-ref", "--format=%(refname) %(objectname)", prefix).stdout

    def edit(self, path, content):
        target = self.path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        self.lab.log(dict(user=self.path.name, edit=path, content=content))

    def human(self, path, content):
        self.edit(path, content)
        self.sun("sync")
        return self.data()["events"][-1]

    def hook(self, event, session="agent", tool="Write", file="agent.txt", tid="call"):
        return self.sun("hook", input=json.dumps(dict(cwd=str(self.path), hook_event_name=event,
                        session_id=session, tool_name=tool, tool_use_id=tid,
                        tool_input={"file_path": str(self.path / file)})))

    def agent(self, path, content, session="agent"):
        self.hook("UserPromptSubmit", session, file=path)
        self.hook("PreToolUse", session, file=path)
        self.edit(path, content)
        self.hook("PostToolUse", session, file=path)
        self.hook("Stop", session, file=path)
        return self.data()["events"][-1]

    def commit(self, message):
        self.git("add", "--all")
        self.git("commit", "--allow-empty", "-m", message)
        return self.oid()

    def data(self):
        return json.loads(self.sun("data").stdout)

    def integrate(self, source="origin/main", resolution=None, no_ff=False):
        self.git("fetch", "origin")
        result = self.git("merge", *( ["--no-ff"] if no_ff else []), "--no-edit", source, ok=False)
        if result.returncode:
            assert resolution is not None, result.stderr + result.stdout
            assert self.git("ls-files", "-u").stdout, "expected real Git conflict"
            for path, text in resolution.items():
                self.edit(path, text)
            self.commit("resolve Git conflict once")

    def verify(self, originals=()):
        data = self.data()
        events = data["events"]
        assert len({e["id"] for e in events}) == len(events), "duplicate operations"
        for original in originals:
            assert [e for e in events if e["id"] == original["id"]] == [original], "lost/rewritten operation"
        positions = {c["hash"]: i for i, c in enumerate(data["commits"])}
        for c in data["commits"]:
            for parent in c["parents"].split():
                assert positions[parent] > positions[c["hash"]], "parent after descendant in replay"
        event_positions = [positions[e["commit"]] for e in events]
        assert event_positions == sorted(event_positions, reverse=True), "operation order disagrees with DAG"
        logged = [line.split()[0] for line in self.sun("log", "-n", "100000").stdout.splitlines()]
        assert logged == [c["short"] for c in data["commits"]], "log and viz/data disagree"
        index, head = self.git("ls-files", "--stage").stdout, self.oid()
        self.sun("sync")
        assert self.oid() == head and self.git("ls-files", "--stage").stdout == index
        return data


def two_users_main(lab, same_identity=False):
    a = lab.user("emma")
    b = lab.user("belinda", "emma" if same_identity else None)
    expected = [a.agent("a.txt", "first\n", "a")]
    a.commit("first")
    a.sun("push")
    b.integrate()
    expected.append(b.human("b.txt", "second\n"))
    b.commit("second")
    b.sun("push")
    a.integrate()
    # Different clocks and genuine same-line divergence, not manufactured Sun refs.
    a.env["GIT_COMMITTER_DATE"] = "2099-01-01T00:00:00+0000"
    b.env["GIT_COMMITTER_DATE"] = "1999-01-01T00:00:00+0000"
    expected.append(a.human("shared.txt", "emma version\n"))
    a.commit("emma conflict")
    expected.append(b.agent("shared.txt", "belinda version\n", "b"))
    b.commit("belinda conflict")
    a.sun("push")
    before = lab.remote_refs()
    assert b.sun("push", ok=False).returncode
    assert lab.remote_refs() == before, "rejected push leaked refs"
    before_tip, before_events = b.oid("refs/sun/heads/main"), b.data()["events"]
    b.git("fetch", "origin")
    b.sun("log")
    assert b.oid("refs/sun/heads/main") == before_tip, "fetch/log joined histories"
    assert b.data()["events"] == before_events
    result = b.git("merge", "--no-edit", "origin/main", ok=False)
    assert result.returncode and b.git("ls-files", "-u").stdout
    markers, index = (b.path / "shared.txt").read_text(), b.git("ls-files", "--stage").stdout
    b.sun("sync")
    assert (b.path / "shared.txt").read_text() == markers
    assert b.git("ls-files", "--stage").stdout == index
    b.git("merge", "--abort")
    assert (b.path / "shared.txt").read_text() == "belinda version\n"
    b.sun("sync")
    b.integrate(resolution={"shared.txt": "agreed result\n"})
    assert any(e["type"] == "merge" for e in b.data()["events"] if e not in before_events)
    b.sun("push")
    a.integrate()
    for repo in (a, b):
        repo.verify(expected)
        assert (repo.path / "shared.txt").read_text() == "agreed result\n"
        assert (repo.path / "a.txt").read_text() == "first\n"
        assert (repo.path / "b.txt").read_text() == "second\n"
    assert a.oid() == b.oid(), "Git did not converge"


def branches(lab):
    a = lab.user("emma")
    original = a.oid("refs/sun/heads/main")
    a.git("switch", "-c", "feature-a")
    a.sun("sync")
    assert a.oid("refs/sun/heads/feature-a") == original
    f = a.agent("feature.txt", "feature\n")
    a.commit("feature")
    parent = a.oid("refs/sun/heads/feature-a")
    a.git("switch", "-c", "feature-a-child")
    a.sun("sync")
    assert a.oid("refs/sun/heads/feature-a-child") == parent
    child = a.human("child.txt", "child\n")
    a.commit("child")
    a.git("switch", "feature-a")
    a.sun("sync")
    assert child["id"] not in {e["id"] for e in a.data()["events"]}
    a.git("merge", "--ff-only", "feature-a-child")
    a.verify([f, child])
    a.git("switch", "main")
    a.sun("sync")
    assert a.oid("refs/sun/heads/main") == original
    a.git("switch", "-c", "feature-b")
    sibling = a.human("sibling.txt", "sibling\n")
    a.commit("sibling")
    a.git("switch", "main")
    a.git("merge", "--no-ff", "feature-a", "-m", "integrate a")
    a.git("merge", "--no-ff", "feature-b", "-m", "integrate b")
    a.verify([f, child, sibling])
    a.sun("push")
    remote = lab.remote_refs()
    assert "refs/heads/feature-a" not in remote and "refs/sun/heads/feature-b" not in remote
    # Checkout without a preceding Sun command, then commit and branch again.
    a.git("switch", "-c", "empty-child")
    a.commit("empty boundary")
    a.git("switch", "-c", "empty-grandchild")
    a.sun("sync")
    assert a.oid("refs/sun/heads/empty-grandchild") == a.oid("refs/sun/heads/empty-child")


def collaborative_branches(lab):
    a, b = lab.user("emma"), lab.user("belinda")
    a.git("switch", "-c", "feature-a")
    first = a.human("parent.txt", "parent\n")
    a.commit("parent")
    a.sun("push")
    b.git("fetch", "origin")
    b.git("switch", "--track", "origin/feature-a")
    b.sun("sync")
    b.git("switch", "-c", "feature-a-child")
    child = b.agent("child.txt", "child\n")
    child_conflict = b.human("shared.txt", "child version\n")
    b.commit("child")
    later = a.agent("later.txt", "parent advanced\n", "later")
    parent_conflict = a.human("shared.txt", "parent version\n")
    a.commit("parent advanced")
    a.sun("push")
    b.integrate("origin/feature-a", resolution={"shared.txt": "parent + child\n"}, no_ff=True)
    b.sun("push")
    a.integrate("origin/feature-a-child", no_ff=True)
    a.sun("push")
    a.git("switch", "main")
    a.git("merge", "--no-ff", "feature-a", "-m", "integrate feature")
    a.sun("push")
    b.git("switch", "main")
    b.integrate()
    for repo in (a, b):
        repo.verify([first, child, later, child_conflict, parent_conflict])
        assert (repo.path / "shared.txt").read_text() == "parent + child\n"


def many_users(lab, count=5):
    users = [lab.user("user" + str(i)) for i in range(count)]
    rng = random.Random(lab.seed)
    originals = []
    # Everyone works before fetching anyone else's changes.
    for i, repo in enumerate(users):
        originals.append(repo.agent(f"user-{i}.txt", f"user {i}\n", f"agent-{i}"))
        repo.commit(f"user {i}")
    order = users[:]
    rng.shuffle(order)
    for repo in order:
        result = repo.sun("push", ok=False)
        if result.returncode:
            repo.integrate()
            repo.sun("push")
    for repo in users:
        repo.integrate()
        repo.verify(originals)
    # Each collaborator now forks a branch and a branch-of-a-branch.
    branch_ops = []
    for i, repo in enumerate(users):
        repo.git("switch", "-c", f"topic-{i}")
        branch_ops.append(repo.human(f"topic-{i}.txt", "topic\n"))
        repo.commit("topic")
        repo.git("switch", "-c", f"topic-{i}-child")
        branch_ops.append(repo.agent(f"child-{i}.txt", "child\n", "child"))
        repo.commit("child")
        repo.sun("push")
    lead = users[0]
    lead.git("switch", "main")
    rng.shuffle(order)
    for repo in order:
        i = users.index(repo)
        lead.integrate(f"origin/topic-{i}-child", no_ff=True)
    lead.sun("push")
    for repo in users:
        repo.git("switch", "main")
        repo.integrate()
        repo.verify(originals + branch_ops)
        assert repo.oid() == lead.oid()
    # Every collaborator also makes a conflicting edit before fetching.
    conflicts = []
    for i, repo in enumerate(users):
        conflicts.append(repo.human("shared.txt", f"resolution from user {i}\n"))
        repo.commit("concurrent conflicting edit")
    rng.shuffle(order)
    accepted = []
    for repo in order:
        accepted.append(f"resolution from user {users.index(repo)}\n")
        if repo.sun("push", ok=False).returncode:
            repo.integrate(resolution={"shared.txt": "".join(accepted)})
            repo.sun("push")
    for repo in users:
        repo.integrate()
        repo.verify(originals + branch_ops + conflicts)
        assert (repo.path / "shared.txt").read_text() == "".join(accepted)


def partial_and_later_edits(lab):
    a = lab.user("emma")
    baseline = lab.remote_refs()
    a.human("first.txt", "first\n")
    a.human("second.txt", "second\n")
    a.git("add", "first.txt")
    a.git("commit", "-m", "partial files")
    partial = a.oid()
    assert not a.refs(f"refs/sun/checkpoints/{partial}/")
    assert a.sun("push", ok=False).returncode
    assert lab.remote_refs() == baseline
    a.commit("finish files")
    # Stage an earlier file version, then leave a different hunk unstaged.
    a.edit("first.txt", "staged change\n")
    a.git("add", "first.txt")
    a.edit("first.txt", "staged change\nunstaged hunk\n")
    a.sun("sync")
    a.git("commit", "-m", "partial hunk")
    assert not a.refs(f"refs/sun/checkpoints/{a.oid()}/")
    assert a.sun("push", ok=False).returncode
    clean = a.commit("finish hunks")
    a.sun("push")
    published = lab.remote_refs()
    later = a.agent("later.txt", "private later work\n", "later")
    a.sun("push")
    assert lab.remote_refs() == published
    assert later["id"] not in lab.remote_refs()
    assert a.oid() == clean and (a.path / "later.txt").exists()
    # Untracked files also make a new commit boundary ineligible.
    a.edit("untracked.txt", "untracked\n")
    a.git("commit", "--allow-empty", "-m", "unclean boundary")
    assert a.sun("push", ok=False).returncode


def atomic_rejections(lab):
    a, b = lab.user("emma"), lab.user("belinda")
    a.human("a.txt", "a\n")
    a.commit("a")
    # Publish only normal Git from b, leaving Sun refs at the shared baseline.
    b.human("b.txt", "b\n")
    b.commit("b")
    b.git("push", "origin", "main")
    before = lab.remote_refs()
    assert a.sun("push", ok=False).returncode
    assert lab.remote_refs() == before, "Git rejection must also reject Sun refs"
    # Independent case: a server rejects Sun, and the normal branch must not advance either.
    b.edit("b.txt", "next\n")
    b.sun("sync")
    b.commit("next")
    hook = lab.remote / "hooks" / "pre-receive"
    hook.write_text('#!/bin/sh\nwhile read old new ref; do\ncase "$ref" in refs/sun/*) exit 1;; esac\ndone\n')
    hook.chmod(0o755)
    before = lab.remote_refs()
    assert b.sun("push", ok=False).returncode
    assert lab.remote_refs() == before
    hook.unlink()
    lab.command(lab.root, ["git", "--git-dir", str(lab.remote), "config", "receive.advertiseAtomic", "false"])
    assert b.sun("push", ok=False).returncode
    assert lab.remote_refs() == before, "no non-atomic fallback allowed"


def selected_branch(lab):
    a, b = lab.user("emma"), lab.user("belinda")
    a.git("switch", "-c", "feature")
    a.agent("feature.txt", "feature\n")
    feature_git = a.commit("feature")
    a.git("switch", "-c", "private")
    private = a.agent("private.txt", "private\n", "private")
    a.commit("private")
    b.human("main.txt", "main advanced\n")
    b.commit("main advanced")
    b.sun("push")
    # Publish feature while checked out on private, despite an unrelated stale local main.
    a.git("remote", "add", "team", str(lab.remote))
    index, head = a.git("ls-files", "--stage").stdout, a.oid()
    a.sun("push", "team", "feature")
    refs = lab.remote_refs()
    assert feature_git + " refs/heads/feature" in refs
    assert "refs/heads/private" not in refs and private["id"] not in refs
    assert a.oid() == head and a.git("ls-files", "--stage").stdout == index
    assert (a.path / "private.txt").read_text() == "private\n"


def parallel_agents(lab):
    from concurrent.futures import ThreadPoolExecutor
    a = lab.user("emma")
    with ThreadPoolExecutor(3) as pool:
        list(pool.map(lambda i: a.hook("PreToolUse", f"agent-{i}", file=f"{i}.txt"), range(3)))
        for i in range(3): a.edit(f"{i}.txt", str(i))
        list(pool.map(lambda i: a.hook("PostToolUse", f"agent-{i}", file=f"{i}.txt"), range(3)))
    edits = {ed["file"]: e["actor"] for e in a.data()["events"] for ed in e.get("edits", [])}
    for i in range(3): assert edits[f"{i}.txt"] == f"emma/agent:claude/agent-{i}"
    for sid in ("overlap-a", "overlap-b"):
        a.hook("PreToolUse", sid, file="overlap.txt")
    a.edit("overlap.txt", "ambiguous combined write\n")
    for sid in ("overlap-a", "overlap-b"):
        a.hook("PostToolUse", sid, file="overlap.txt")
    assert a.data()["events"][-1]["actor"] == "unknown"
    a.commit("parallel writes")
    a.sun("push")


def duplicate_hooks_and_active_boundary(lab):
    a = lab.user("emma")
    a.hook("PreToolUse", "active")
    a.edit("agent.txt", "agent\n")
    a.commit("commit inside active call")
    assert not a.refs(f"refs/sun/checkpoints/{a.oid()}/")
    assert a.sun("push", ok=False).returncode
    a.hook("PostToolUse", "active")
    a.hook("Stop", "active")
    a.commit("clean boundary after call")
    before = a.git("show-ref").stdout
    a.sun("git-hook", "commit")
    a.sun("git-hook", "merge")
    assert a.git("show-ref").stdout == before
    a.sun("push")
    a.git("switch", "-c", "child")
    a.agent("child.txt", "child\n")
    a.commit("child")
    a.git("switch", "main")
    a.git("merge", "--no-ff", "child", "-m", "merge child")
    before = a.git("show-ref").stdout
    a.sun("git-hook", "merge")
    a.sun("git-hook", "commit")
    assert a.git("show-ref").stdout == before


def editing_during_push(lab):
    a = lab.user("emma")
    a.human("published.txt", "published\n")
    normal = a.commit("published")
    a.hook("PreToolUse", "during", file="during.txt")
    ready, release = lab.root / "ready", lab.root / "release"
    hook = lab.remote / "hooks" / "pre-receive"
    hook.write_text("#!" + sys.executable + "\nimport pathlib, sys, time\nsys.stdin.read()\n" +
                    f"pathlib.Path({str(ready)!r}).touch()\n" +
                    "deadline = time.monotonic() + 15\n" +
                    f"while not pathlib.Path({str(release)!r}).exists():\n" +
                    "    if time.monotonic() > deadline: sys.exit(1)\n    time.sleep(0.02)\n")
    hook.chmod(0o755)
    p = subprocess.Popen([sys.executable, str(SUN), "push"], cwd=a.path, env=a.env,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 20
        while not ready.exists():
            assert p.poll() is None and time.monotonic() < deadline, "push never reached receiver"
            time.sleep(0.02)
        a.edit("during.txt", "written while publication is in flight\n")
        release.touch()
        out, err = p.communicate(timeout=25)
        lab.log(dict(argv=["sun", "push"], stdout=out, stderr=err, status=p.returncode))
        assert p.returncode == 0, err
    finally:
        release.touch()
        if p.poll() is None: p.kill()
        p.communicate()
    a.hook("PostToolUse", "during", file="during.txt")
    a.hook("Stop", "during", file="during.txt")
    later = a.data()["events"][-1]
    assert later["id"] not in lab.remote_refs()
    assert normal + " refs/heads/main" in lab.remote_refs()
    assert (a.path / "during.txt").exists()


def checkpoints_and_transcripts(lab):
    a = lab.user("emma")
    a.sun("init", "--claude", "--share-sessions", "--no-instructions")
    a.git("switch", "-c", "private-session")
    private = Path(a.env["SUN_PROJECTS"]) / "private.jsonl"
    private.write_text('{"type":"user","message":{"content":"unrelated branch"}}\n')
    a.sun("hook", input=json.dumps(dict(cwd=str(a.path), hook_event_name="UserPromptSubmit",
                   session_id="private", transcript_path=str(private))))
    a.hook("PreToolUse", "private", file="private.txt")
    a.edit("private.txt", "private\n")
    a.hook("PostToolUse", "private", file="private.txt")
    a.sun("hook", input=json.dumps(dict(cwd=str(a.path), hook_event_name="Stop",
                   session_id="private", transcript_path=str(private))))
    a.commit("private branch transcript")
    a.git("switch", "main")
    transcript = Path(a.env["SUN_PROJECTS"]) / "native.jsonl"
    transcript.write_text('{"type":"user","message":{"content":"old prompt"}}\n')
    payload = dict(cwd=str(a.path), hook_event_name="UserPromptSubmit", session_id="shared",
                   transcript_path=str(transcript))
    a.sun("hook", input=json.dumps(payload))
    a.hook("PreToolUse", "shared", file="shared.txt")
    a.edit("shared.txt", "shared result\n")
    a.hook("PostToolUse", "shared", file="shared.txt")
    payload["hook_event_name"] = "Stop"
    a.sun("hook", input=json.dumps(payload))
    a.commit("checkpoint transcript")
    source = "refs/sun/sessions/emma/shared"
    pinned = a.oid(source)
    # Append a later transcript chunk through a later turn, before publishing the earlier checkpoint.
    payload["hook_event_name"] = "UserPromptSubmit"
    a.sun("hook", input=json.dumps(payload))
    with transcript.open("a") as f: f.write('{"type":"user","message":{"content":"private later"}}\n')
    payload["hook_event_name"] = "Stop"
    a.sun("hook", input=json.dumps(payload))
    a.sun("push")
    remote_sha = lab.command(lab.root, ["git", "--git-dir", str(lab.remote), "rev-parse", source]).stdout.strip()
    assert remote_sha == pinned, "later transcript leaked past checkpoint"
    assert "refs/sun/sessions/emma/private" not in lab.remote_refs()


def checks_and_reviews(lab):
    a, b = lab.user("emma"), lab.user("belinda")
    if a.sun("check", "--help", ok=False).returncode:
        raise unittest.SkipTest("PR #26 checks/reviews are not part of this stack's base")
    a.human("RULES", "honest: Reports match the evidence.\n")
    a.commit("rules")
    a.sun("push")
    b.integrate()
    state = a.oid("refs/sun/heads/main")
    def check(repo, verdict, cites):
        p = repo.sun("check", "--json", input=json.dumps(dict(rule="honest", verdict=verdict,
                     actor="agent:reviewer", cites=cites)))
        return json.loads(p.stdout)["checks"][0]
    first = check(a, "pass", [{"at": state}])
    a.commit("publish check")
    a.sun("push")
    b.integrate()
    # Independent collaborators review the same check before seeing one another.
    second = check(b, "fail", [{"check": first["id"]}])
    third = check(a, "pass", [{"check": first["id"]}])
    a.commit("publish independent review")
    a.sun("push")
    b.commit("publish review")
    if b.sun("push", ok=False).returncode:
        b.integrate()
    b.sun("push")
    a.integrate()
    for repo in (a, b):
        rows = json.loads(repo.sun("coverage", "--json", "-n", "0").stdout)["commits"]
        rules = [rule for row in rows for rule in row["rules"] if rule["rule"] == "honest"]
        all_checks = {c["id"]: c for rule in rules for c in rule["checks"]}
        for original in (first, second, third):
            assert all_checks[original["id"]] == original, "review overwrote another check"
        assert any(rule["status"] == "mixed" for rule in rules)


def tool_turns_and_branch_pins(lab):
    a = lab.user("emma")
    human = a.human("human.txt", "before agent\n")
    a.hook("UserPromptSubmit", "turn")
    a.hook("PreToolUse", "turn", file="one.txt", tid="one")
    a.edit("one.txt", "one\n")
    a.hook("PostToolUse", "turn", file="one.txt", tid="one")
    a.human("human.txt", "human during turn\n")
    a.hook("PreToolUse", "turn", file="two.txt", tid="two")
    a.edit("two.txt", "two\n")
    a.hook("PostToolUse", "turn", file="two.txt", tid="two")
    before = a.data()["events"]
    a.hook("Stop", "turn")
    after = a.data()["events"]
    assert {e["id"] for e in before} == {e["id"] for e in after}
    assert next(e for e in after if e["id"] == human["id"]) == human
    tail = after[after.index(human) + 1:]
    assert len(tail) == 3 and len({e["commit"] for e in tail}) == 1
    assert sum(e["actor"] == "emma/local" for e in tail) == 1
    for original in before[before.index(human) + 1:]:
        current = next(e for e in tail if e["id"] == original["id"])
        assert current["snapshot"] == original["commit"]
        assert current["edits"] == original["edits"]
        assert a.oid("refs/sun/ops/" + current["snapshot"]) == current["snapshot"]
    a.commit("squashed turn")
    a.sun("push")
    # Forking a branch pins inherited operations even before Stop arrives.
    a.hook("UserPromptSubmit", "fork")
    a.hook("PreToolUse", "fork", file="fork.txt", tid="fork")
    a.edit("fork.txt", "fork\n")
    a.hook("PostToolUse", "fork", file="fork.txt", tid="fork")
    inherited = a.data()["events"][-1]
    a.git("switch", "-c", "inherited")
    a.sun("sync")
    a.git("switch", "main")
    a.hook("Stop", "fork")
    a.verify([inherited])
    assert a.oid("refs/sun/heads/inherited") == inherited["commit"]
    assert not a.refs("refs/sun/sessions/"), "opt-out unexpectedly copied transcripts"


def git_state_observation(lab):
    a = lab.user("emma")
    baseline = a.oid()
    original = a.agent("agent.txt", "recorded attribution\n")
    a.commit("normal commit")
    a.commit("empty commit")
    assert a.data()["events"][-1] == original, "ordinary commit manufactured an operation"
    old_tip = a.oid("refs/sun/heads/main")
    # Reset only this throwaway fixture, never the development checkout.
    a.git("reset", "--hard", baseline)
    a.sun("sync")
    observed = a.data()["events"][-1]
    assert observed["type"] == "observe" and observed["actor"] == "unknown"
    a.git("merge-base", "--is-ancestor", old_tip, a.oid("refs/sun/heads/main"))
    a.verify([original])


SCENARIOS = {
    "two-users-main": two_users_main,
    "same-identity-two-clones": lambda lab: two_users_main(lab, same_identity=True),
    "nested-branches": branches,
    "collaborative-branches": collaborative_branches,
    "many-users": many_users,
    "partial-and-later-edits": partial_and_later_edits,
    "atomic-rejections": atomic_rejections,
    "selected-branch": selected_branch,
    "parallel-agents": parallel_agents,
    "duplicate-hooks-active-boundary": duplicate_hooks_and_active_boundary,
    "editing-during-push": editing_during_push,
    "checkpoint-transcripts": checkpoints_and_transcripts,
    "checks-and-reviews": checks_and_reviews,
    "tool-turns-branch-pins": tool_turns_and_branch_pins,
    "git-state-observation": git_state_observation,
}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", required=True, type=Path, help="new directory; never reuses or deletes a repo")
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--users", type=int, default=5)
    ap.add_argument("--scenario", choices=SCENARIOS, action="append")
    args = ap.parse_args()
    if args.output.exists(): ap.error("output must not exist; existing repos are never overwritten")
    if args.users < 2: ap.error("users must be at least two")
    args.output.mkdir(parents=True)
    report = []
    for name in args.scenario or SCENARIOS:
        lab = Lab(args.output / name, args.seed)
        item = dict(scenario=name, seed=args.seed, directory=str(lab.root))
        try:
            if name == "many-users": many_users(lab, args.users)
            else: SCENARIOS[name](lab)
            item["status"] = "PASS"
        except unittest.SkipTest as exc:
            item.update(status="SKIP", reason=str(exc))
        except Exception as exc:
            item.update(status="FAIL", reason=repr(exc))
        report.append(item)
        (args.output / "report.json").write_text(json.dumps(report, indent=2))
        print(item["status"], name, item.get("reason", ""), flush=True)
    print("Repos and action logs preserved at", args.output.resolve())
    return int(any(item["status"] == "FAIL" for item in report))


if __name__ == "__main__":
    sys.exit(main())
