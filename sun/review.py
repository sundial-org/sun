"""Experimental review queue: subtract checked changes, open the remainder in Vim."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

from . import checks, coverage_tui, git_store, history

PASS = {'pass', 'passed', 'supported'}
HUNK = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')


def citations(check, stored, seen=None):
    """A review inherits scope; a new check with direct cites defines its own scope."""
    seen = set() if seen is None else seen
    if check['id'] in seen: return []
    seen.add(check['id'])
    direct = [c for c in check['cites'] if 'at' in c]
    if direct: return direct
    return [cite for c in check['cites'] if c.get('check') in stored
            for cite in citations(stored[c['check']], stored, seen)]


def file_scopes(commit, path, stored, rules):
    scopes = []
    for row in commit['rules']:
        if not checks.matches(rules[row['rule']], [path]): continue
        for c in coverage_tui.current_checks(row):
            for cite in citations(c, stored):
                # A tool-call snapshot is not the final turn, even if coverage folds it there.
                if cite.get('at') != commit['commit']: continue
                if cite.get('file', path) != path: continue
                bounds = cite.get('lines')
                passed = c['verdict'].lower() in PASS
                if bounds is not None and (not cite.get('file') or not 0 < bounds[0] <= bounds[1]):
                    if passed: continue
                    bounds = None  # ambiguous negative evidence must not allow hiding
                scopes.append((c['id'], passed, bounds))
    return scopes


def covering(scopes, line=None):
    """Return passing check IDs only when no overlapping nonpassing check exists.

    line=None represents deletion/metadata, which post-image line cites cannot cover.
    A nonpassing line check conservatively blocks hiding deletions in that file.
    """
    positive, blocked = set(), False
    for identity, passed, bounds in scopes:
        overlaps = bounds is None or line is not None and bounds[0] <= line <= bounds[1]
        if not passed and (overlaps or line is None): blocked = True
        if passed and overlaps: positive.add(identity)
    return set() if blocked else positive


def excerpt(patch, scopes):
    """Keep only unhidden changed lines; output is a review excerpt, not an applicable patch."""
    output, ids, hidden, remaining = [], set(), 0, 0
    old = new = None
    pending = None
    has_hunks = False
    last_visible = False
    metadata = []
    for line in patch.splitlines():
        match = HUNK.match(line)
        if match:
            old, new = int(match[1]), int(match[3])
            pending = match[0]  # never leak function context following the hunk coordinates
            has_hunks = True
        elif old is not None and line[:1] in ('+', '-'):
            plus = line.startswith('+')
            evidence = covering(scopes, new if plus else None)
            last_visible = not evidence
            if evidence:
                hidden += 1
                ids.update(evidence)
            else:
                if pending:
                    output.append(pending)
                    pending = None
                output.append(f"{line[0]} {new if plus else old:>6} | {line[1:]}")
                remaining += 1
            if plus: new += 1
            else: old += 1
        elif old is not None and line.startswith('\\ No newline') and last_visible:
            output.append(line)
        elif old is not None and line.startswith(' '):
            old += 1
            new += 1
        elif old is None and not line.startswith(('diff --git ', 'index ', '--- ', '+++ ')):
            metadata.append(line)
    # Binary, empty-file, mode and other structural changes have no new-line scope.
    if metadata or not has_hunks:
        evidence = covering(scopes)
        if evidence: ids.update(evidence)
        else:
            output = (metadata or ['File metadata changed.']) + output
    return {'lines': output, 'hidden': hidden, 'remaining': remaining, 'checks': sorted(ids)}


def review_data(n):
    table = checks.coverage(n)
    stored, rules = checks.checks(), checks.read_rules()[1]
    items, hidden, total_files, hidden_files = [], 0, 0, 0
    for commit in table:
        H = commit['commit']
        base = checks.parent_of(H)
        paths = git_store.git('diff', '--no-ext-diff', '--no-renames', '--name-only', '-z', base, H, '--').split('\0')
        for path in filter(None, paths):
            total_files += 1
            patch = git_store.git('--literal-pathspecs', 'diff', '--no-ext-diff', '--no-textconv', '--no-color',
                                  '--no-renames', '--unified=0', base, H, '--', path)
            result = excerpt(patch, file_scopes(commit, path, stored, rules))
            hidden += result['hidden']
            if result['lines']:
                items.append({'commit': H, 'parent': base, 'file': path, **result})
            else: hidden_files += 1
    return {'commits': len(table), 'files': total_files, 'hidden_files': hidden_files,
            'hidden_lines': hidden, 'items': items}


def clean(text):
    return ''.join(c if c.isprintable() or c in '\n\t' else '?' for c in text)


def vim_text(item):
    return ('Sun review excerpt (not an applicable patch). q returns to the queue.\n'
            f"Commit: {item['commit']}\nFile: {clean(item['file'])}\n"
            '+ numbers refer to the new file; - numbers refer to the parent.\n'
            f"{item['hidden']} checked lines omitted. Opening this does not record a review.\n\n"
            + '\n'.join(clean(line) for line in item['lines']) + '\n')


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
        _tui_put(screen, 0, 0, 'sun review / remaining changes', width - 1, curses.A_BOLD)
        _tui_put(screen, 1, 0, f"{len(items)} file revisions to inspect; {data['hidden_files']} hidden; "
                 f"{data['hidden_lines']} checked lines hidden", width - 1)
        if not items:
            _tui_put(screen, 3, 0, 'No remaining changes in the loaded history.', width - 1)
        for y, i in enumerate(range(start, min(len(items), start + count)), 3):
            item = items[i]
            label = f"{item['commit'][:8]}  {item['file']}  ({item['remaining']} lines / metadata)"
            _tui_put(screen, y, 0, clean(label).replace('\n', '?'), width - 1,
                     curses.A_REVERSE if i == selected else 0)
        _tui_put(screen, height - 2, 0, message or 'Exact revisions only. Snapshot view; exit and reopen to refresh.', width - 1)
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
        data = review_data(a.n)
    if a.json: return print(json.dumps(data))
    import curses
    curses.wrapper(tui, data)
