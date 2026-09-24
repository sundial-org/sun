"""Git objects, refs, file snapshots, and local repository state."""

import fcntl
import json
import os
import subprocess
import sys


CLAUDE_LINE = CODEX_LINE = (
    "Use `sun data` for attributed history and session paths. Your sessions stay in their "
    "native harness directories; only collaborators' shared sessions are cached in "
    ".git/sun/sessions/. Read the returned session path instead of guessing a location.")


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


def make_shadow_commit(tree, message, author, parents=(), when=None):
    ident = {**os.environ, "GIT_AUTHOR_NAME": author, "GIT_AUTHOR_EMAIL": "sun@sun",
             "GIT_COMMITTER_NAME": author, "GIT_COMMITTER_EMAIL": "sun@sun"}
    if when: ident.update(GIT_AUTHOR_DATE=str(when), GIT_COMMITTER_DATE=str(when))  # migrated: the original time
    args = ["-c", "commit.gpgsign=false", "commit-tree", tree]
    for parent in parents: args += ["-p", parent]
    return git(*args, "-m", message, env=ident).strip()


def commit_files(files, message, author):
    """Snapshot files into an independent commit graph without touching HEAD or the real index."""
    parent = history_head(False)
    tree = snapshot_tree(files)
    commit = make_shadow_commit(tree, message, author, [parent] if parent else [])
    # record() publishes this commit and its attribution in one Git ref transaction.
    return commit


def snapshot_tree(files=(".",), source=None):
    parent, ix = history_head(False), shadow_index()
    if os.path.exists(ix): os.remove(ix)
    env = {**os.environ, "GIT_INDEX_FILE": ix}
    if parent: git("read-tree", parent, env=env)
    else: git("read-tree", "--empty", env=env)
    if source:
        git("--literal-pathspecs", "restore", "--source=" + source, "--staged", "--", *files, env=env)
    else:
        git("--literal-pathspecs", "add", "-A", "--", *files, env=env)
    return git("write-tree", env=env).strip()


def tree_changes(before, after):
    return [f for f in git("diff", "--no-renames", "--name-only", "-z", before, after).split("\0") if f]


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


def lock():
    common = git("rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    lk = open(os.path.join(common, "sun.lock"), "a")
    fcntl.flock(lk, fcntl.LOCK_EX)
    return lk  # closing the file releases the lock


_u = {}


def user():  # the git user on whose machine the change happened; owns every event
    _u or _u.setdefault("u", (git("config", "user.name", check=False).strip()
                              or os.environ.get("USER", "unknown")).replace(" ", "-").lower())
    return _u["u"]


local = lambda u=None: f"{u or user()}/local"


agent = lambda sid, harness="claude", u=None: f"{u or user()}/agent:{harness}/{sid}"


session_key = lambda sid, harness="claude": sid if harness == "claude" else f"{harness}/{sid}"


rel_to_root = lambda path: os.path.relpath(os.path.abspath(path), root())


def cfg_share_sessions(): return state("config.json", {}).get("share_sessions", False)


def configured_harnesses():
    cfg = state("config.json", {})
    return cfg.get("harnesses") or [cfg.get("harness", "claude")]


def refspecs(share_sessions=False, remote="origin"):
    specs = ["refs/sun/events/*:refs/sun/events/*", "refs/sun/ops/*:refs/sun/ops/*",
             "refs/sun/checks/*:refs/sun/checks/*", f"+refs/sun/heads/*:refs/sun/remotes/{remote}/*"]
    return specs + (["+refs/sun/sessions/*:refs/sun/sessions/*"] if share_sessions else [])


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
