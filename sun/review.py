"""Review the current branch diff, omitting files checked since their last edit."""
import json
import os
import shutil
import subprocess
import sys
import tempfile

from . import checks, git_store, history

PASS = {'pass', 'passed', 'supported'}


def citations(check, stored, seen=None):
    """A review inherits scope; a new check with direct cites defines its own scope."""
    seen = set() if seen is None else seen
    if check['id'] in seen: return []
    seen.add(check['id'])
    direct = [c for c in check['cites'] if 'at' in c]
    if direct: return direct
    return [cite for c in check['cites'] if c.get('check') in stored
            for cite in citations(stored[c['check']], stored, seen)]


def default_base():
    """Compare branch work to its Git merge base; fall back to Git HEAD."""
    name = checks.default_base()
    for ref in ('refs/heads/' + name, 'refs/remotes/origin/' + name):
        if git_store.ref_oid(ref):
            base = git_store.git('merge-base', 'HEAD', ref, check=False).strip()
            if base: return base
    return git_store.git('rev-parse', '--verify', 'HEAD').strip()


def review_data(base=None):
    head = git_store.history_head()
    base = (git_store.git('rev-parse', '--verify', '--end-of-options', base + '^{commit}').strip()
            if base else default_base())
    ancestors = set(git_store.git('rev-list', head).split())
    owners = {H: H for H in ancestors}
    for event in history.events():
        if event['commit'] in ancestors and event.get('snapshot'):
            owners[event['snapshot']] = event['commit']
    stored, rules = checks.checks(), checks.read_rules()[1]
    scoped = [(c, citations(c, stored)) for c in stored.values() if c['rule'] in rules]
    # A check from an unrelated branch cannot supersede evidence on this branch.
    scoped = [(c, cites) for c, cites in scoped if any(x['at'] in owners for x in cites)]
    replaced = {x['check'] for c, _ in scoped for x in c['cites'] if 'check' in x}
    scoped = [(c, cites) for c, cites in scoped if c['id'] not in replaced]
    paths = git_store.git('diff', '--no-ext-diff', '--no-renames', '--name-only', '-z', base, head, '--').split('\0')
    versions, ancestry = {}, {}

    def version(at, path):
        key = (at, path)
        if key not in versions:
            entry = git_store.git('--literal-pathspecs', 'ls-tree', '-z', at, '--', path)
            versions[key] = entry.split('\t', 1)[0] if entry else None
        return versions[key]  # includes mode and object type, not just the content hash

    def after(last, at):
        key = (last, at)
        if key not in ancestry:
            ancestry[key] = not last or git_store.quiet('git', 'merge-base', '--is-ancestor', last, at).returncode == 0
        return ancestry[key]

    items, hidden = [], []
    for path in filter(None, paths):
        last = git_store.git('--literal-pathspecs', 'log', '-1', '--format=%H', head, '--', path).strip()
        passing, blocking, partial, stale, changed = [], [], [], [], []
        for c, cites in scoped:
            rule = rules[c['rule']]
            if not checks.matches(rule, [path]): continue
            for cite in cites:
                at = cite['at']
                if at not in owners or cite.get('file', path) != path: continue
                checked_version, current_version = version(at, path), version(head, path)
                if checked_version is None and (current_version is not None or not after(last, owners[at])):
                    continue  # a check before a file existed is not a check of that file
                if checked_version != current_version or not after(last, owners[at]):
                    changed.append(c['id'])
                elif c.get('rule_text', rule['hash']) != rule['hash']:
                    stale.append(c['id'])
                elif c['verdict'].lower() not in PASS:
                    blocking.append(c['id'])
                elif cite.get('lines') is not None:
                    partial.append(c['id'])
                else:
                    passing.append(c['id'])
        if passing and not blocking:
            hidden.append({'file': path, 'checks': sorted(set(passing)),
                           'reason': 'Passing check covers this file since its last edit.'})
            continue
        reason = ('A current check is nonpassing or conflicts with a passing check.' if blocking else
                  'Only part of this file has been checked.' if partial else
                  'The check definition changed since this file was checked.' if stale else
                  'This file changed since its recorded check.' if changed else
                  'No check covers this file since its last edit.')
        patch = git_store.git('--literal-pathspecs', 'diff', '--no-ext-diff', '--no-textconv', '--no-color',
                              '--no-renames', '--unified=3', base, head, '--', path)
        items.append({'commit': head, 'base': base, 'file': path, 'last_change': last,
                      'reason': reason, 'checks': sorted(set(blocking + partial + stale + changed)),
                      'patch': patch})
    return {'head': head, 'base': base, 'files': len(items) + len(hidden),
            'hidden_files': hidden, 'items': items}


def clean(text):
    return ''.join(c if c.isprintable() or c in '\n\t' else '?' for c in text)


def vim_text(item):
    return ('Sun review / current changes. q returns to the queue.\n'
            f"File: {clean(item['file'])}\nWhy: {item['reason']}\n"
            f"Base: {item['base']}\nCurrent Sun HEAD: {item['commit']}\n"
            'File-level review: the changed chunks below need attention.\n'
            'Opening this view does not record a human review.\n\n'
            + clean(item['patch']))


def open_vim(item):
    vim = shutil.which('vim')
    if not vim: return 'Vim was not found on PATH.'
    with tempfile.TemporaryDirectory(prefix='sun-review-') as directory:
        path = os.path.join(directory, 'remaining.diff')
        git_store.write_text(path, vim_text(item))
        # A disposable, nonmodifiable buffer. Repository text never becomes editor commands.
        result = subprocess.run([vim, '-Nu', 'NONE', '-i', 'NONE', '-n', '-M',
                                 '--cmd', 'set nomodeline noexrc',
                                 '-c', 'set filetype=diff', '-c', 'syntax on',
                                 '-c', 'nnoremap <buffer> q :q!<CR>', '--', path])
    return '' if result.returncode == 0 else f'Vim exited with status {result.returncode}.'


def tui(screen, data):
    import curses
    from .output import _tui_put
    try: curses.curs_set(0)
    except curses.error: pass
    screen.keypad(True)
    if curses.has_colors():
        curses.start_color()
        try: curses.use_default_colors()
        except curses.error: pass
    selected, message = 0, ''
    items = data['items']
    while True:
        screen.erase()
        height, width = screen.getmaxyx()
        count = max(1, height - 6)
        start = max(0, min(selected - count // 2, len(items) - count))
        _tui_put(screen, 0, 0, 'sun review / current changes', width - 1, curses.A_BOLD)
        _tui_put(screen, 1, 0, f"{len(items)} files need review; {len(data['hidden_files'])} checked files omitted; "
                 f"base {data['base'][:8]}", width - 1)
        if not items:
            _tui_put(screen, 3, 0, 'No files need review in the current diff.', width - 1)
        for y, i in enumerate(range(start, min(len(items), start + count)), 3):
            item = items[i]
            label = f"{item['file']}  | {item['reason']}"
            _tui_put(screen, y, 0, clean(label).replace('\n', '?'), width - 1,
                     curses.A_REVERSE if i == selected else 0)
        _tui_put(screen, height - 2, 0, message or (items[selected]['reason'] if items else 'Current diff only. Reopen to refresh.'), width - 1)
        _tui_put(screen, height - 1, 0, 'j/k move  Enter open remaining changes in Vim  q quit', width - 1)
        screen.refresh()
        key = screen.getch()
        if key in (ord('q'), 27): return
        if key in (ord('j'), curses.KEY_DOWN): selected = min(max(0, len(items) - 1), selected + 1)
        elif key in (ord('k'), curses.KEY_UP): selected = max(0, selected - 1)
        elif key in (10, 13, curses.KEY_ENTER) and items:
            curses.def_prog_mode()
            curses.endwin()
            try: message = open_vim(items[selected])
            finally:
                curses.reset_prog_mode()
                try: curses.curs_set(0)
                except curses.error: pass
                screen.clearok(True)


def cmd_review(a):
    if not a.json and (not sys.stdin.isatty() or not sys.stdout.isatty()):
        sys.exit('sun: review needs an interactive terminal; use sun review --json')
    with git_store.lock():
        history.ensure_branch()
        history.maybe_sync()
        data = review_data(a.base)
    if a.json: return print(json.dumps(data))
    import curses
    curses.wrapper(tui, data)
