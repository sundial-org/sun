"""A deterministic, read-only browser of commit ancestry and recorded checks."""
import sys

from . import checks, git_store, history


# Verdicts are free text in Sun. Only explicit negative verdicts get this action label.
NEGATIVE = {"fail", "failed", "contradicted", "needs revision", "needs-revision"}


def current_checks(row):
    replaced = {x['check'] for c in row['checks'] for x in c['cites'] if 'check' in x}
    return [c for c in row['checks'] if c['id'] not in replaced and c['id'] not in row['outdated']]


def needs_revision(commit):
    return any(c['verdict'].lower() in NEGATIVE for r in commit['rules'] for c in current_checks(r))


class Browser:
    def __init__(self, table, graph):
        self.commits = {c['commit']: c for c in table}
        self.graph = graph
        self.stack = []
        self.page, self.selected = ('summary', None), 0
        self.diffs = {}

    def rows(self):
        """(label, destination) rows; destinations are absent for informational lines."""
        kind, value = self.page
        commits = list(self.commits.values())
        if kind == 'summary':
            gaps = sum(any(r['status'] in ('unchecked', 'outdated') for r in c['rules']) for c in commits)
            revisions = sum(needs_revision(c) for c in commits)
            recorded = sum(any(current_checks(r) for r in c['rules']) for c in commits)
            return [(f'{gaps} commits with missing or outdated checks', ('list', 'gaps')),
                    (f'{revisions} commits need revision', ('list', 'revision')),
                    (f'{recorded} commits with checks recorded', ('list', 'recorded')),
                    (f'Commit map ({len(commits)} loaded)', ('map', None)),
                    ('Checks recorded does not mean every changed line is checked.', None),
                    ('No rules configured. Add RULES.md to define checks.' if not any(c['rules'] for c in commits)
                     else 'Coverage applies to cited revisions, not their descendants.', None)]
        if kind == 'map':
            rows = [('Ancestry only; joins are not checks or PR merge requirements.', None)]
            for line in self.graph.splitlines():
                parts = line.split()
                H = next((p for p in parts if p in self.commits), None)
                rows.append((line.replace(H, self.label(self.commits[H])) if H else line,
                             ('commit', H) if H else None))
            return rows
        if kind == 'list':
            matches = {'gaps': lambda c: any(r['status'] in ('unchecked', 'outdated') for r in c['rules']),
                       'revision': needs_revision,
                       'recorded': lambda c: any(current_checks(r) for r in c['rules'])}
            return [(self.label(c), ('commit', c['commit'])) for c in commits if matches[value](c)] or [('None in loaded history.', None)]
        if kind == 'commit':
            c = self.commits[value]
            rows = [(c['subject'], None), (f"session: {c['session'] or 'no session attribution'}", None)]
            for parent in c['parents']:
                rows.append((f'parent: {parent[:8]}' + ('' if parent in self.commits else ' (outside loaded window)'),
                             ('commit', parent) if parent in self.commits else None))
            rows += [(f"{r['rule']}: {r['status']}" + ('  human-reviewed' if r['eyes'] == 'terminal' else ''),
                      ('rule', (value, i))) for i, r in enumerate(c['rules'])]
            rows.append(('Show diff against first parent' if c['parents'] else 'Show initial snapshot diff', ('diff', value)))
            return rows
        if kind == 'rule':
            H, index = value
            row = self.commits[H]['rules'][index]
            rows = [(f"{row['rule']}: {row['status']}", None)]
            live = {c['id'] for c in current_checks(row)}
            for c in row['checks']:
                state = 'current' if c['id'] in live else 'outdated' if c['id'] in row['outdated'] else 'superseded'
                rows.append((f"{c['verdict']} by {row['labels'][c['id']]} [{state}]", None))
                if c.get('note'): rows.append((c['note'], None))
                for cite in c['cites']:
                    scope = cite.get('file', 'commit scope (no file/line detail)')
                    if cite.get('lines'): scope += ':' + '-'.join(map(str, cite['lines']))
                    rows.append((f"  {cite.get('at', cite.get('check', ''))[:8]}  {scope}", None))
            if not row['checks']: rows.append(('No check recorded for this rule and commit.', None))
            rows.append(('Show commit diff', ('diff', H)))
            return rows
        if kind == 'diff':
            if value not in self.diffs:
                c = self.commits[value]
                if c['parents']:
                    patch = git_store.git('diff', '--no-ext-diff', '--no-textconv', '--no-color', c['parents'][0], value, '--')
                else:
                    patch = git_store.git('show', '--root', '--format=', '--no-ext-diff', '--no-textconv', '--no-color', value, '--')
                self.diffs[value] = patch.splitlines() or ['No tree changes against first parent.']
            return [(line, None) for line in self.diffs[value]]
        return []

    def label(self, c):
        gaps = sum(r['status'] in ('unchecked', 'outdated') for r in c['rules'])
        suffix = '  needs revision' if needs_revision(c) else f'  {gaps} rule gaps' if gaps else ''
        return f"{c['short']} {c['subject']}{suffix}"

    def open(self):
        rows = self.rows()
        if rows and rows[self.selected][1]:
            self.stack.append((self.page, self.selected))
            self.page, self.selected = rows[self.selected][1], 0

    def back(self):
        if self.stack: self.page, self.selected = self.stack.pop()


def tui(screen, browser):
    import curses
    from .output import _tui_put
    try: curses.curs_set(0)
    except curses.error: pass
    screen.keypad(True)
    while True:
        screen.erase()
        height, width = screen.getmaxyx()
        rows = browser.rows()
        browser.selected = min(browser.selected, max(0, len(rows) - 1))
        size = max(1, height - 4)
        start = max(0, min(browser.selected - size // 2, len(rows) - size))
        _tui_put(screen, 0, 0, f'sun coverage / {browser.page[0]}  ({len(browser.commits)} commits loaded)', width - 1, curses.A_BOLD)
        for y, (label, target) in enumerate(rows[start:start + size], 2):
            selected = start + y - 2 == browser.selected
            # Shared records may contain terminal controls; never emit them verbatim.
            label = ''.join(c if c.isprintable() else ' ' for c in label)
            _tui_put(screen, y, 0, ('> ' if target else '  ') + label, width - 1,
                     curses.A_REVERSE if selected else 0)
        _tui_put(screen, height - 1, 0, 'j/k move  Enter open  h/Esc back  q quit', width - 1)
        screen.refresh()
        key = screen.getch()
        if key == ord('q'): return
        if key in (ord('j'), curses.KEY_DOWN): browser.selected = min(max(0, len(rows) - 1), browser.selected + 1)
        elif key in (ord('k'), curses.KEY_UP): browser.selected = max(0, browser.selected - 1)
        elif key in (10, 13, curses.KEY_ENTER, curses.KEY_RIGHT, ord('l')): browser.open()
        elif key in (27, curses.KEY_LEFT, ord('h')): browser.back()
        elif key == curses.KEY_NPAGE: browser.selected = min(max(0, len(rows) - 1), browser.selected + size)
        elif key == curses.KEY_PPAGE: browser.selected = max(0, browser.selected - size)


def run(n):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        sys.exit('sun: coverage --tui needs an interactive terminal; use sun coverage --json')
    import curses
    with git_store.lock():
        history.ensure_branch()
        history.maybe_sync()
        table = checks.coverage(n)
        graph = git_store.git('log', '--graph', '--topo-order', '--no-color', '--format=%H',
                              f'-{len(table)}', *[c['commit'] for c in table]) if table else ''
    # Hooks can keep recording while the user browses this fixed snapshot.
    curses.wrapper(tui, Browser(table, graph))
