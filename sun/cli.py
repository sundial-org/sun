"""Record human and agent edits in an independent Git-backed operation history.

Each Git branch has its own Sun history. Unpublished, non-interleaved agent calls are grouped
per turn while remaining individually inspectable and undoable. Recording stays local. Resolve file
conflicts with normal Git. `sun push` publishes the selected Sun branch independently of Git commits;
it combines recorded histories without changing files or normal Git refs.
Raw transcripts are shared only when you explicitly enable session sharing."""

import argparse
import json
import os
import re
import sys

from . import branches
from . import checks
from . import git_store
from . import history
from . import hooks
from . import output
from . import sessions as session_store


def configure_session_sharing(choice):
    cfg = git_store.state("config.json", {})
    if choice is None and "share_sessions" in cfg: return cfg["share_sessions"]
    if choice is None:
        choice = (sys.stdin.isatty() and input(
            "sun: share raw agent transcripts with everyone who can read this remote? "
            "They may contain secrets and private data. [y/N] ").strip().lower() == "y")
    cfg["share_sessions"] = choice; git_store.save_state("config.json", cfg)
    return choice


def detect_harnesses():  # every harness with state on this machine (SUN_* overrides apply)
    hs = [h for h, home, d in (("claude", "~/.claude", session_store.projects()),
                               ("codex", "~/.codex", session_store.codex_sessions()))
          if os.path.isdir(os.path.expanduser(home)) or os.path.isdir(d)]
    return hs or ["claude"]


hook_file = lambda h: ".claude/settings.json" if h == "claude" else ".codex/hooks.json"


hook_cmd = lambda h: "sun hook" if h == "claude" else "sun hook --harness codex"


def install_hooks(harness="claude"):
    rel = hook_file(harness)
    path = os.path.join(git_store.root(), rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cfg = git_store.jread(path, {})
    if not isinstance(cfg.setdefault("hooks", {}), dict):
        sys.exit(f"sun: unexpected 'hooks' format in {rel}")
    command = hook_cmd(harness)
    hook_events = hooks.HOOK_EVENTS if harness == "claude" else hooks.CODEX_HOOK_EVENTS
    for event in hook_events:
        group = cfg["hooks"].setdefault(event, [])
        if not any(h.get("command") == command for g in group for h in g.get("hooks", [])):
            group.append({"hooks": [{"type": "command", "command": command}]})
    git_store.jwrite(path, cfg)
    return f"{harness} ({rel})"


def remove_hooks(harness):  # a restrictive re-init un-installs the excluded harness's hook
    path, command = os.path.join(git_store.root(), hook_file(harness)), hook_cmd(harness)
    cfg = git_store.jread(path, {})
    if not isinstance(cfg.get("hooks"), dict): return
    for event in list(cfg["hooks"]):
        for g in cfg["hooks"][event]:
            g["hooks"] = [h for h in g.get("hooks", []) if h.get("command") != command]
        cfg["hooks"][event] = [g for g in cfg["hooks"][event] if g.get("hooks")]
        if not cfg["hooks"][event]: del cfg["hooks"][event]
    git_store.jwrite(path, cfg)


def configure_sharing(share_sessions=False):
    if "origin" in git_store.git("remote", check=False).split():
        for old in ("+refs/sun/*:refs/sun/*", "+refs/sun/sessions/*:refs/sun/sessions/*",
                    "+refs/sun/heads/*:refs/sun/heads/*", "+refs/sun/log/*:refs/sun/log/*",
                    "+refs/sun/ops/*:refs/sun/ops/*",
                    "refs/sun/checkpoints/*:refs/sun/checkpoints/*",
                    "refs/sun/session-checkpoints/*:refs/sun/session-checkpoints/*"):
            git_store.git("config", "--fixed-value", "--unset-all", "remote.origin.fetch", old, check=False)
        current = git_store.git("config", "--get-all", "remote.origin.fetch", check=False).splitlines()
        for spec in git_store.refspecs(share_sessions):
            if spec not in current: git_store.git("config", "--add", "remote.origin.fetch", spec)
    # Remove only exact Sun-owned hooks from the earlier design; preserve custom hooks.
    managed = {
        "pre-push": ('#!/bin/sh\n# sun: mirror shared refs\nexec sun push "$1"\n',
                     '#!/bin/sh\n# sun: mirror shared refs, fail-soft\nexec sun push "$1"\n',
                     '#!/bin/sh\n# sun: mirror op log + sessions, fail-soft\n'
                     'git push --no-verify "$1" "+refs/sun/*:refs/sun/*" >/dev/null 2>&1 || true\n'),
        "post-commit": ("#!/bin/sh\n# sun: clean Git checkpoint\nsun git-hook commit\n",),
        "post-merge": ("#!/bin/sh\n# sun: clean Git checkpoint\nsun git-hook merge\n",),
    }
    for name, scripts in managed.items():
        path = git_store.git("rev-parse", "--git-path", "hooks/" + name).strip()
        if os.path.exists(path) and git_store.read_text(path) in scripts: os.remove(path)


def agent_instructions(harnesses, choice, flags=""):  # one prompt covering every harness file
    todo = []
    for h in harnesses:
        name, line = ("CLAUDE.md", git_store.CLAUDE_LINE) if h == "claude" else ("AGENTS.md", git_store.CODEX_LINE)
        p = os.path.join(git_store.root(), name)
        cur = git_store.read_text(p) if os.path.exists(p) else ""
        old = re.compile(r"^Past sessions for this repo, yours and other team members', are in "
                         r"\.git/sun/sessions/ .*Look there instead of .*\.$", re.M)
        cleaned = old.sub(line, cur)
        if cleaned != cur:
            todo.append((p, cleaned, None, name))
        elif line not in cur: todo.append((p, cur, line, name))
    if not todo: return
    if choice is None and sys.stdin.isatty():
        choice = input(f"sun: add one line to {'/'.join(t[3] for t in todo)} so agents find "
                       "team sessions? [Y/n] ").strip().lower() != "n"
    if choice:
        for p, cur, line, _ in todo:
            if line is None: git_store.write_text(p, cur)
            else: git_store.write_text(p, ("\n" if cur and not cur.endswith("\n") else "") + line + "\n", "a")
    else:
        print(f"sun: run `sun init{flags} --instructions` later to enable team session sharing")


def cmd_init(a):
    if git_store.quiet("git", "rev-parse", "--git-dir").returncode: git_store.sh("git", "init", "-q")
    os.makedirs(git_store.sun_dir(False), exist_ok=True)
    with git_store.lock():
        init_locked(a)


def init_locked(a):
    explicit = [h for h, f in (("claude", a.claude), ("codex", a.codex)) if f]
    harnesses = explicit or detect_harnesses()
    cfg = git_store.state("config.json", {}); cfg.pop("harness", None)
    cfg["harnesses"] = harnesses
    cfg.pop("shadow_history", None)
    git_store.save_state("config.json", cfg)
    share_sessions = configure_session_sharing(a.share_sessions)
    if "origin" in git_store.git("remote", check=False).split():  # fresh clone: fetch team refs
        git_store.git("fetch", "-q", "origin", *git_store.refspecs(share_sessions))
    installed = ", ".join(install_hooks(h) for h in harnesses); configure_sharing(share_sessions)
    branches.install_hooks()
    for h in ("claude", "codex"):
        if explicit and h not in explicit: remove_hooks(h)
    if share_sessions:
        agent_instructions(harnesses, a.instructions, "".join(" --" + h for h in explicit))
    if not git_store.history_head(False):
        c = git_store.commit_files(["."], "sun: initial state", git_store.local())
        remote, tree = git_store.ref_oid(git_store.remote_ref()), git_store.ref_oid(f"{c}^{{tree}}")
        matches = [line.split()[0] for line in git_store.git("log", remote, "--format=%H %T").splitlines()
                   if line.split()[1] == tree] if remote else []
        if matches: git_store.git("update-ref", git_store.shadow_ref(), matches[0])
        else: history.record(type="init", actor=git_store.local(), commit=c, edits=[])
    history.ensure_branch()
    history.sync()
    print(f"sun: initialized {git_store.root()} (hooks: {installed}); {session_store.do_import(harnesses)}")
    if "codex" in harnesses:
        print("sun: Codex requires separate hook approval; open `/hooks`, review "
              "`.codex/hooks.json`, and trust the Sun hooks before testing")
    print("run `sun viz` to explore your attributed history")


def installed_git_source():
    from importlib.metadata import distribution
    try:
        source = json.loads(distribution("sun").read_text("direct_url.json") or "{}")
        return source.get("url"), (source.get("vcs_info") or {}).get("commit_id")
    except (LookupError, TypeError, ValueError):
        return None, None


def cmd_update(a):  # uv re-resolves the git source to the latest commit
    url, installed = installed_git_source()
    if url and installed:
        head = git_store.quiet("git", "ls-remote", url, "HEAD")
        if not head.returncode and (head.stdout.split() or [None])[0] == installed:
            return print("sun: already up to date")
    try: p = git_store.quiet("uv", "tool", "upgrade", "sun")
    except OSError: p = None
    if not p or p.returncode:
        sys.exit("sun: could not update via uv; run "
                 "`uv tool install --force git+https://github.com/sundial-org/sun`")
    print(f"sun: {(p.stderr.strip().splitlines() or ['updated'])[-1]}")


def main(argv=None):
    git_store._u.clear()
    ap = argparse.ArgumentParser(
        prog="sun", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Start with `sun init`, then use `sun viz` to explore recorded work.")
    sub = ap.add_subparsers(dest="cmd", required=True, title="commands", metavar="COMMAND")
    ps = {c: sub.add_parser(c, help=h) for c, h in [
        ("init", "initialize Sun and install agent hooks"),
        ("sync", "record file changes since the last Sun snapshot"),
        ("log", "list Sun commits with attributed actors and turns"),
        ("show", "show a Sun commit and its recorded operations"),
        ("viz", "browse attributed history in an interactive terminal"),
        ("data", "emit attributed history and session paths as JSON"),
        ("blame", "show who changed a line and its stored conversation, when available"),
        ("undo", "reverse an operation or Sun commit and record the undo"),
        ("restore", "restore files to a Sun commit and record the restoration"),
        ("sessions", "manage explicitly shared agent transcripts"),
        ("push", "publish recorded Sun history independently of Git commits"),
        ("check", "record a verdict on a rule, citing the recorded state it read"),
        ("coverage", "show which commits were checked against each rule, and by whom"),
        ("export", "export operations as fine-tuning JSONL"),
        ("update", "upgrade the uv-installed Sun CLI")]}
    ps["hook"] = sub.add_parser("hook", help=argparse.SUPPRESS)
    ps["git-hook"] = sub.add_parser("git-hook", help=argparse.SUPPRESS)
    ps["git-hook"].add_argument("event", choices=("reference-transaction", "post-checkout"))
    ps["git-hook"].add_argument("args", nargs="*")
    sub._choices_actions = [choice for choice in sub._choices_actions if choice.dest not in ("hook", "git-hook")]
    ps["init"].add_argument("--claude", action="store_true",
                            help="set up Claude Code only (default: every detected harness)")
    ps["init"].add_argument("--codex", action="store_true",
                            help="set up Codex only (default: every detected harness)")
    ps["init"].add_argument("--share-sessions", dest="share_sessions", action="store_true",
                            default=None, help="share raw transcripts through git refs")
    ps["init"].add_argument("--no-share-sessions", dest="share_sessions", action="store_false",
                            help="keep raw transcripts only in their native harness directories")
    ps["init"].add_argument("--instructions", "--claude-md", dest="instructions",
                            action="store_true", default=None,
                            help="add agent instructions for finding shared sessions")
    ps["init"].add_argument("--no-instructions", "--no-claude-md", dest="instructions",
                            action="store_false", help="do not edit agent instruction files")
    ps["hook"].add_argument("--harness", choices=("claude", "codex"), default="claude")
    ps["push"].add_argument("remote", nargs="?", default="origin")
    ps["push"].add_argument("branch", nargs="?", help="local branch (default: checked-out branch)")
    ps["sync"].add_argument("--recover", action="store_true",
                            help="after stopping agents, release abandoned calls and record uncertain edits")
    session_sub = ps["sessions"].add_subparsers(
        dest="session_cmd", required=True, title="session commands", metavar="ACTION")
    session_ps = {c: session_sub.add_parser(c, help=h) for c, h in [
        ("list", "list stored transcripts"), ("show", "print one stored transcript"),
        ("import", "store new or changed native transcripts in Sun refs"),
        ("export", "index native paths and cache collaborators' shared transcripts"),
        ("prune", "delete your old stored transcript refs")]}
    session_ps["list"].add_argument("--grep", metavar="REGEX",
                                    help="show transcripts matching a regular expression")
    session_ps["list"].add_argument("--contains", metavar="TEXT",
                                    help="show transcripts containing literal text")
    session_ps["show"].add_argument("id", help="full session ID or unique prefix")
    session_ps["prune"].add_argument("--older-than", type=int, required=True, metavar="DAYS",
                                     help="prune sessions last stored more than DAYS ago")
    session_ps["prune"].add_argument("--remote", action="store_true",
                                     help="also delete the selected refs from origin")
    ps["log"].add_argument("-n", type=int, default=30, metavar="COUNT",
                           help="maximum commits to show (default: 30)")
    ps["show"].add_argument("commit", help="Sun commit, snapshot, or ref")
    undo_target = ps["undo"].add_mutually_exclusive_group()
    undo_target.add_argument("--op", nargs="?", const="", default=None, metavar="ID",
                             help="operation ID (default: latest operation)")
    undo_target.add_argument("--commit", nargs="?", const="HEAD", default=None, metavar="HASH",
                             help="Sun commit (default with flag: current Sun commit)")
    ps["undo"].add_argument("--dry-run", action="store_true",
                            help="check whether the reversal applies without changing files")
    ps["restore"].add_argument("commit", help="Sun commit, snapshot, or ref to restore")
    viz_format = ps["viz"].add_mutually_exclusive_group()
    viz_format.add_argument("--html", action="store_true", help="export self-contained HTML")
    viz_format.add_argument("--tui", action="store_true", help="open interactive terminal history")
    ps["data"].add_argument("-n", type=int, default=0, metavar="COUNT")
    ps["data"].set_defaults(output=None)
    ps["viz"].add_argument("-o", "--output", default=None,
                            help="HTML output path (implies --html)")
    ps["viz"].add_argument("-n", type=int, default=0, metavar="COUNT",
                           help="maximum commits to load (default: all)")
    ps["export"].add_argument("-o", "--output", default=None,
                              help="output path (default: stdout)")
    ps["check"].add_argument("args", nargs="*", metavar="RULE VERDICT [REV|CHECK]",
                             help="your own check or review; without arguments, read JSON checks from stdin")
    ps["check"].add_argument("-m", metavar="NOTE", help="why, in a sentence")
    ps["check"].add_argument("--json", action="store_true", help="print the stored checks as JSON")
    ps["coverage"].add_argument("-n", type=int, default=30, metavar="COUNT",
                                help="maximum commits (default: 30; 0 for all)")
    ps["coverage"].add_argument("--json", action="store_true", help="print one JSON object")
    ps["blame"].add_argument("file", help="path to inspect")
    ps["blame"].add_argument("line", type=int, help="1-based line number")
    a = ap.parse_args(argv)
    commands = {
        "init": cmd_init, "hook": hooks.cmd_hook, "git-hook": branches.cmd_hook, "sync": history.cmd_sync, "push": history.cmd_push,
        "log": output.cmd_log, "show": output.cmd_show, "undo": history.cmd_undo, "restore": history.cmd_restore,
        "viz": output.cmd_viz, "data": output.cmd_viz, "sessions": session_store.cmd_sessions, "update": cmd_update,
        "export": output.cmd_export, "blame": output.cmd_blame, "check": checks.cmd_check, "coverage": checks.cmd_coverage,
    }
    if a.cmd not in ("init", "hook", "git-hook", "update"):  # hook locates its repo from the payload
        if a.cmd == "blame": a.file = os.path.abspath(a.file)  # resolve before the chdir
        if a.cmd == "check" and not a.args:  # read stdin before taking the lock, so a slow producer blocks nobody
            a.raw = "" if sys.stdin.isatty() else sys.stdin.read()
        os.chdir(git_store.root())
        git_store.sun_dir()
        if a.cmd in ("viz", "data"):
            commands[a.cmd](a)
        else:
            with git_store.lock():
                history.ensure_branch()
                commands[a.cmd](a)
    else:
        commands[a.cmd](a)
