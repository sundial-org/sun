"""Optional shell integration around the real Git executable."""

import contextlib
import os
import re
import shlex
import subprocess
import sys

from . import git_store, history


def shell_init():
    print('git() { command sun git "$@"; }')


def git_command(args):
    """Locate the subcommand, preserving Git's global options verbatim."""
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env"):
            i += 2
        elif arg.startswith("-"):
            i += 1
        else:
            return args[:i], arg, args[i + 1:]
    return args, "", []


def run_git(args):
    prefix, command, rest = git_command(args)
    env = os.environ.copy()
    dry = any(a in ("--dry-run", "-n") for a in rest)
    if dry:
        env["SUN_SKIP_PUSH"] = "1"
    enabled = command in ("push", "pull") and not dry
    # A Git shell alias runs at the repository root and inherits -C, -c and
    # --git-dir correctly. Python and internal Git calls bypass the shell function.
    launch = "import sys; sys.path.insert(0, " + repr(os.path.dirname(os.path.dirname(__file__))) + "); from sun.cli import main; main()"
    alias = "!" + shlex.join([sys.executable, "-I", "-c", launch, "git-integrate"])
    helper = ["git", *prefix, "-c", "alias.sun-integrate=" + alias, "sun-integrate"]
    if enabled:
        ready = subprocess.run([*helper, "prepare"], env=env).returncode == 0
    else:
        ready = False
    result = subprocess.run(["git", *args], env=env)
    if ready and command == "pull" and result.returncode == 0:
        subprocess.run([*helper, "finish"], env=env)
    return result.returncode


def integrate(phase):
    from . import cli

    try:
        if git_store.git("rev-parse", "--is-inside-work-tree", check=False).strip() != "true":
            return 1
        if not git_store.git("symbolic-ref", "-q", "HEAD", check=False).strip():
            return 1
        os.chdir(git_store.root())
        with contextlib.redirect_stdout(sys.stderr):
            if phase == "prepare":
                if not git_store.initialized():
                    # Noninteractive setup never opts into raw transcript sharing.
                    cli.main(["init", "--no-share-sessions", "--no-instructions"])
                else:
                    with git_store.lock():
                        cli.configure_sharing(git_store.cfg_share_sessions())
                return 0
            reconcile_pull()
        return 0
    except (SystemExit, Exception) as exc:
        print(f"sun: automatic Git integration failed: {exc}; Git's result is unchanged", file=sys.stderr)
        return 1


def reconcile_pull():
    """Join only the Sun lineage named by this pull's mergeable FETCH_HEAD."""
    path = git_store.git("rev-parse", "--git-path", "FETCH_HEAD").strip()
    rows = [line.split("\t", 2) for line in git_store.read_text(path).splitlines()]
    fetched = [row for row in rows if len(row) == 3 and row[1] == ""]
    sources = []
    normalize = lambda url: url.rstrip("/").removesuffix(".git")
    for oid, _, description in fetched:
        match = re.fullmatch(r"branch '(.*)' of (.*)", description)
        if not match:
            print("sun: pulled source has no named branch; Sun history was not joined", file=sys.stderr)
            continue
        branch, url = match.groups()
        remotes = [remote for remote in git_store.git("remote").splitlines()
                   if normalize(git_store.git("remote", "get-url", remote).strip()) == normalize(url)]
        if not remotes:
            print("sun: pulled source has no configured remote; Sun history was not joined", file=sys.stderr)
            continue
        remote = remotes[0]  # aliases for the same URL fetch the same source history
        git_store.git("fetch", "--no-write-fetch-head", "-q", remote,
                      *git_store.refspecs(git_store.cfg_share_sessions(), remote))
        tip = git_store.ref_oid(f"refs/sun/remotes/{remote}/{branch}")
        if tip:
            sources.append(tip)
    with git_store.lock():
        history.ensure_branch()
        history.sync()
        for tip in sources:
            history.join_history(tip, git_store.shadow_ref())
