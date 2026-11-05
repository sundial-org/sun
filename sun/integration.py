"""Optional shell integration around the real Git executable."""

import contextlib
import argparse
import datetime
import json
import os
import re
import shlex
import subprocess
import sys
from urllib.parse import urlsplit

from . import git_store, history


def shell_init(args=()):
    parser = argparse.ArgumentParser(prog="sun shell-init")
    parser.add_argument("--no-git-pr", action="store_true", help="disable automatic PR coverage on Git push")
    parser.add_argument("--no-gh-pr", action="store_true", help="disable automatic PR coverage on gh pr create")
    options = parser.parse_args(args)
    for command in ("git", "gh"):
        flag = " --no-sun-pr" if getattr(options, "no_" + command + "_pr") else ""
        print(f'{command}() {{ command sun {command}{flag} "$@"; }}')


def pr_opt_out(args):
    # The wrapper flag is consumed before invoking the underlying executable.
    before, separator, after = [], [], []
    if "--" in args:
        position = args.index("--")
        before, separator, after = args[:position], ["--"], args[position + 1:]
    else:
        before = args
    return [arg for arg in before if arg != "--no-sun-pr"] + separator + after, "--no-sun-pr" in before


def run_gh(args):
    args, skip_pr = pr_opt_out(args)
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("-R", "--repo")
    parser.add_argument("-H", "--head")
    options, rest = parser.parse_known_args(args)
    creating = rest[:2] == ["pr", "create"] and not any(arg in args for arg in ("--help", "-h", "--dry-run", "--web", "-w"))
    started = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
    # Preserve gh's terminal and interactive prompts. Find the newly created PR
    # by its branch, commit and creation time instead of capturing terminal output.
    result = subprocess.run(["gh", *args])
    if creating and not skip_pr and result.returncode == 0:
        refresh_prs(head=options.head, repo=options.repo, created_since=started)
    return result.returncode


def refresh_prs(head=None, repo=None, created_since=None):
    """Update only PRs whose head matches this checkout's recorded context."""
    from . import checks

    try:
        if git_store.git("rev-parse", "--is-inside-work-tree", check=False).strip() != "true": return
        if not git_store.initialized() or not checks.read_rules()[1]: return
        branch = git_store.git("symbolic-ref", "--short", "HEAD", check=False).strip()
        if not branch: return
        head = head or branch
        owner, _, name = head.rpartition(":")
        if created_since and name != branch:
            print("sun: PR coverage skipped: the created PR uses a different local branch", file=sys.stderr)
            return
        normal = git_store.ref_oid("HEAD")
        args = ["gh", "pr", "list", "--state", "open", "--head", name,
                "--json", "url,headRefName,headRefOid,createdAt,baseRefName,headRepositoryOwner,isCrossRepository"]
        if repo:
            repo = re.sub(r"^git@([^:]+):", r"https://\1/", repo)
            if "://" in repo:
                url = urlsplit(repo)
                repo = url.netloc.rsplit("@", 1)[-1] + url.path
            repo = repo.rstrip("/").removesuffix(".git")
            args += ["--repo", repo]
        candidates = json.loads(git_store.sh(*args))
        candidates = [pr for pr in candidates if pr["headRefName"] == name and pr["headRefOid"] == normal
                      and (not owner or pr["headRepositoryOwner"]["login"] == owner)
                      and (created_since is not None or not pr["isCrossRepository"])]
        if created_since:
            since = datetime.datetime.fromisoformat(created_since)
            candidates = [pr for pr in candidates if datetime.datetime.fromisoformat(pr["createdAt"].replace("Z", "+00:00")) >= since]
            if len(candidates) != 1:
                print("sun: could not identify the newly created PR uniquely; run `sun pr --update`", file=sys.stderr)
                return
        for pr in candidates:
            with contextlib.redirect_stdout(sys.stderr):
                checks.cmd_pr(argparse.Namespace(base=pr["baseRefName"], json=False, update=True,
                                                 pr=pr["url"], automatic=True))
    except (SystemExit, Exception) as exc:
        print(f"sun: automatic PR coverage update failed: {exc}; retry `sun pr --update`", file=sys.stderr)


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
    args, skip_pr = pr_opt_out(args)
    prefix, command, rest = git_command(args)
    env = os.environ.copy()
    if skip_pr: env["SUN_SKIP_PR"] = "1"
    dry = "--dry-run" in rest or command == "push" and "-n" in rest
    if dry or command == "push":
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
    if ready and command == "push":
        # Porcelain identifies the actual remote and every source/destination,
        # including up-to-date Git branches with newly recorded Sun operations.
        result = subprocess.run(["git", *prefix, "push", "--porcelain", *rest],
                                env=env, stdout=subprocess.PIPE, text=True)
        print(result.stdout, end="", flush=True)
        if result.returncode == 0:
            subprocess.run([*helper, "finish-push"], env=env, input=result.stdout, text=True)
    else:
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
            if phase == "finish-push":
                publish_push(sys.stdin.read())
            else:
                reconcile_pull()
        return 0
    except (SystemExit, Exception) as exc:
        print(f"sun: automatic Git integration failed: {exc}; Git's result is unchanged", file=sys.stderr)
        return 1


def remote_for_url(url, push=False):
    normalize = lambda value: value.rstrip("/").removesuffix(".git")
    for remote in git_store.git("remote").splitlines():
        args = ["remote", "get-url", "--all", *(["--push"] if push else []), remote]
        if normalize(url) in [normalize(value) for value in git_store.git(*args).splitlines()]:
            return remote
    return None


def publish_push(output):
    from argparse import Namespace

    remote = None
    for line in output.splitlines():
        if line.startswith("To "):
            destination = line[3:]
            remote = remote_for_url(destination, push=True)
            if not remote:
                print("sun: push destination has no configured remote; Sun history was not published", file=sys.stderr)
            continue
        row = line.split("\t")
        if not remote or len(row) < 3 or row[0] not in (" ", "=", "*", "+"):
            continue
        source, target = row[1].split(":", 1)
        if source == "HEAD":
            source = git_store.git("symbolic-ref", "-q", "HEAD", check=False).strip()
        if not source.startswith("refs/heads/") or not target.startswith("refs/heads/"):
            continue
        branch = source.removeprefix("refs/heads/")
        if not git_store.ref_oid("refs/sun/heads/" + branch):
            continue
        try:
            with git_store.lock():
                history.cmd_push(Namespace(remote=remote, branch=branch, transport=destination,
                                           target_branch=target.removeprefix("refs/heads/")))
        except (SystemExit, Exception) as exc:
            print(f"sun: history for {branch} was not published: {exc}", file=sys.stderr)
        else:
            if not os.environ.get("SUN_SKIP_PR"):
                current = git_store.git("symbolic-ref", "--short", "HEAD", check=False).strip()
                if branch == current:
                    refresh_prs(head=target.removeprefix("refs/heads/"), repo=destination)


def reconcile_pull():
    """Join only the Sun lineage named by this pull's mergeable FETCH_HEAD."""
    from argparse import Namespace

    path = git_store.git("rev-parse", "--git-path", "FETCH_HEAD").strip()
    rows = [line.split("\t", 2) for line in git_store.read_text(path).splitlines()]
    fetched = [row for row in rows if len(row) == 3 and row[1] == ""]
    sources = []
    for _, _, description in fetched:
        match = re.fullmatch(r"branch '(.*)' of (.*)", description)
        if not match:
            print("sun: pulled source has no named branch; Sun history was not joined", file=sys.stderr)
            continue
        branch, url = match.groups()
        remote = remote_for_url(url)
        if not remote:
            print("sun: pulled source has no configured remote; Sun history was not joined", file=sys.stderr)
            continue
        sources.append(Namespace(remote=remote, branch=branch))
    with git_store.lock():
        history.ensure_branch()
        history.sync()
        for source in sources:
            history.cmd_pull(source)
