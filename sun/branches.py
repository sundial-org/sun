"""Git branch creation pins Sun ancestry; worktrees keep only hook bookkeeping."""

import os
import shlex
import sys

from . import git_store, history


# Delegate every standard hook to the original directory, including hooks added later.
GIT_HOOKS = """applypatch-msg pre-applypatch post-applypatch pre-commit pre-merge-commit
prepare-commit-msg commit-msg post-commit pre-rebase post-checkout post-merge pre-push
pre-receive update proc-receive post-receive post-update reference-transaction
push-to-checkout pre-auto-gc post-rewrite sendemail-validate fsmonitor-watchman
p4-changelist p4-prepare-changelist p4-post-changelist p4-pre-submit post-index-change""".split()


def install_hooks():
    """Use a repo-local dispatcher without modifying a user's existing hooks directory."""
    directory = os.path.join(git_store.common_sun_dir(), "hooks")
    current = git_store.git("config", "--get", "core.hooksPath", check=False).strip()
    if current != directory:
        original = current or git_store.git("rev-parse", "--path-format=absolute", "--git-path", "hooks").strip()
        git_store.git("config", "sun.originalHooksPath", os.path.expanduser(original))
    original = git_store.git("config", "--get", "sun.originalHooksPath").strip()
    os.makedirs(directory, exist_ok=True)
    # Bind to this installation, independent of an editor's PATH or a checkout
    # containing its own sun.py/package. -I also excludes ambient PYTHONPATH.
    launch = "import sys; sys.path.insert(0, " + repr(os.path.dirname(os.path.dirname(__file__))) + "); from sun.cli import main; main()"
    command = shlex.join([sys.executable, "-I", "-c", launch])
    for name in GIT_HOOKS:
        script = '#!/bin/sh\n# sun: Git lifecycle dispatcher\noriginal=' + shlex.quote(os.path.join(original, name)) + '\n'
        if name in ("reference-transaction", "post-checkout"):
            script += 'run_sun() { ' + command + ' "$@"; }\n'
        if name == "reference-transaction":
            # A Sun ref update recursively invokes this hook. Filter in the shell,
            # before starting Sun or taking its shared repository lock.
            script += '''input=$(cat)
status=0
if [ -x "$original" ]; then
    printf '%s\\n' "$input" | "$original" "$@" || status=$?
fi
printf '%s\\n' "$input" | while read -r old new ref; do
        case "$ref:$new" in
            HEAD:ref:refs/heads/*)
                printf '%s %s %s\\n' "$old" "$new" "$ref" | run_sun git-hook reference-transaction "$1"
                continue ;;
        esac
        [ "$1" = committed ] || continue
        case "$ref" in refs/heads/*) ;; *) continue ;; esac
        case "$old" in *[!0]*|'') continue ;; esac
        case "$new" in *[!0]*) ;; *) continue ;; esac
        printf '%s %s %s\\n' "$old" "$new" "$ref" | run_sun git-hook reference-transaction committed
done
exit "$status"
'''
        elif name == "post-checkout":
            script += '''status=0
if [ -x "$original" ]; then "$original" "$@" || status=$?; fi
run_sun git-hook post-checkout "$@"
exit "$status"
'''
        else:
            script += 'if [ -x "$original" ]; then exec "$original" "$@"; fi\n'
        path = os.path.join(directory, name)
        git_store.write_text(path, script)
        os.chmod(path, 0o755)
    git_store.git("config", "core.hooksPath", directory)


def created_branch(ref, normal):
    """Read Git's recorded start-point while HEAD still names the source checkout.

    Resolve names, never search for a branch with a matching commit. Local main
    and origin/main can share a Git commit but have different Sun histories.
    """
    message = git_store.git("reflog", "show", "-1", "--format=%gs", ref, check=False).strip()
    prefix = "branch: Created from "
    if not message.startswith(prefix): return  # Initial commits and ref rewrites are not branch births.
    start = message[len(prefix):]
    source = git_store.git("rev-parse", "--symbolic-full-name", "--verify", start, check=False).strip() if start else ""
    if source.startswith("refs/heads/"):
        sun_source = source.replace("refs/heads/", "refs/sun/heads/", 1)
    elif source.startswith("refs/remotes/"):
        sun_source = source.replace("refs/remotes/", "refs/sun/remotes/", 1)
    else:
        sun_source = ""
    tip = git_store.ref_oid(sun_source) if sun_source and git_store.ref_oid(source) == normal else ""
    if not tip:
        # An explicit commit, missing hooks/reflog, or an unrecorded source has no
        # known Sun ancestry. Keep the Git baseline, without inventing attribution.
        tree = git_store.ref_oid(normal + "^{tree}")
        tip = git_store.make_shadow_commit(tree, "sun: initial state", "unknown")
        print(f"sun: {ref.removeprefix('refs/heads/')} starts a new Sun history; "
              "no recorded Sun source was found", file=sys.stderr)
    target = ref.replace("refs/heads/", "refs/sun/heads/", 1)
    # The shared lock orders this capture against Sun writers in other worktrees.
    # Recreating a deleted Git branch starts again from its new source.
    git_store.git("update-ref", target, tip, git_store.ref_oid(target) or "0" * len(tip))


def cmd_hook(a):
    if not git_store.initialized(): return
    if a.event == "reference-transaction":
        updates = [line.split() for line in sys.stdin if len(line.split()) == 3]
        for _, new, ref in updates:
            if ref == "HEAD" and new.startswith("ref:refs/heads/"):
                # Before Git's first commit there is no branch ref/reflog. Capture
                # the source name before HEAD changes; never use Sun's last checkout.
                with git_store.lock():
                    if a.args == ["prepared"] and not git_store.ref_oid("HEAD"):
                        git_store.save_state("branch-creation.json", {
                            "source": git_store.shadow_ref(),
                            "target": new.replace("ref:refs/heads/", "refs/sun/heads/", 1)})
                    elif a.args == ["committed"] and git_store.state("branch-creation.json", {}):
                        history.ensure_branch()
                    elif a.args == ["aborted"]:
                        git_store.save_state("branch-creation.json", {})
        if a.args != ["committed"]: return
        creations = [(new, ref) for old, new, ref in updates
                     if set(old) == {"0"} and set(new) != {"0"} and ref.startswith("refs/heads/")]
        if not creations: return
        with git_store.lock():
            for new, ref in creations: created_branch(ref, new)
    elif a.event == "post-checkout" and a.args[-1:] == ["1"]:
        from .cli import install_hooks as install_agent_hooks
        with git_store.lock():
            # Configuration and history are shared; active calls, turns and the
            # shadow index are private to this worktree. Do not copy active calls.
            git_store.sun_dir()
            for harness in git_store.configured_harnesses(): install_agent_hooks(harness)
            if git_store.git("symbolic-ref", "-q", "HEAD", check=False).strip():
                history.ensure_branch()
                history.sync()
