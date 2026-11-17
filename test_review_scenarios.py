"""Multi-session review tests and disposable demo generator.

Run tests: python3 -m unittest test_review_scenarios
Create demos: python3 test_review_scenarios.py NEW_DIRECTORY
"""
import json
from pathlib import Path
import shlex
import shutil
import sys
import unittest

from sun import checks, history
import test_review as fixtures
import test_sun

SCENARIOS = {
    'latest': {12},
    'scattered': {2, 5, 9},
    'every': set(range(1, 13)),
    'none': set(),
}


def populate(case, checked_turns):
    """Twelve synthetic turns, four sessions, two tool calls per turn."""
    turns = []
    for number in range(1, 13):
        sid = f'demo-session-{(number - 1) % 4 + 1:02}'
        case.agent_turn(sid, [
            (f'src/feature_{number:02}.py',
             f'"""Feature {number}, synthetic session {sid}."""\n'
             f'\ndef feature_{number:02}(value):\n    return value + {number}\n'),
            ('src/progress.py',
             '"""Shared file updated by every synthetic agent turn."""\n'
             f'COMPLETED_FEATURES = {list(range(1, number + 1))!r}\n'),
        ])
        at = case.sun_head()
        if number in checked_turns:
            case.check(rule='honest', verdict='pass', actor='program:demo',
                       note=f'SYNTHETIC fixture verdict for turn {number}; no checker was run.',
                       cites=[{'at': at}], meta={'synthetic': True})
        turns.append({'turn': number, 'session': sid, 'commit': at,
                      'checked': number in checked_turns})
    return turns


class ReviewScenariosTest(unittest.TestCase):
    # Reuse the existing isolated fixture without inheriting its tests.
    setUp, tearDown = fixtures.ReviewTest.setUp, fixtures.ReviewTest.tearDown
    git, sun_head, check = fixtures.ReviewTest.git, fixtures.ReviewTest.sun_head, fixtures.ReviewTest.check
    tool_call, agent_turn = fixtures.ReviewTest.tool_call, test_sun.SunTest.agent_turn
    data, change, passed = fixtures.ReviewTest.data, fixtures.ReviewTest.change, fixtures.ReviewTest.passed

    def scenario(self, name):
        turns = populate(self, SCENARIOS[name])
        data = self.data()
        edits = [e for e in history.events() if e.get('session_id', '').startswith('demo-session-')]
        self.assertEqual({e['session_id'] for e in edits}, {t['session'] for t in turns})
        self.assertEqual(len({e['commit'] for e in edits}), 12)
        self.assertEqual(len(checks.checks()), len(SCENARIOS[name]))
        self.assertEqual(data['files'], 13)
        visible = {i['file'] for i in data['items']}
        hidden = {i['file'] for i in data['hidden_files']}
        self.assertFalse(visible & hidden)
        self.assertEqual(len(visible | hidden), 13)
        return data, visible, hidden

    def test_latest_turn_check_covers_current_files_from_all_sessions(self):
        data, visible, hidden = self.scenario('latest')
        self.assertEqual(visible, set())
        self.assertEqual(len(hidden), 13)
        self.assertTrue(all(len(i['checks']) == 1 for i in data['hidden_files']))

    def test_scattered_checks_leave_last_three_turns_and_shared_file_visible(self):
        data, visible, hidden = self.scenario('scattered')
        self.assertEqual(visible, {'src/feature_10.py', 'src/feature_11.py',
                                   'src/feature_12.py', 'src/progress.py'})
        self.assertEqual(len(hidden), 9)
        shared = next(i for i in data['items'] if i['file'] == 'src/progress.py')
        self.assertIn('changed since', shared['reason'])
        self.assertIn('12]', shared['patch'])

    def test_every_turn_checked_leaves_no_review_items(self):
        _, visible, hidden = self.scenario('every')
        self.assertEqual(visible, set())
        self.assertEqual(len(hidden), 13)

    def test_no_turns_checked_keeps_all_current_diffs(self):
        data, visible, hidden = self.scenario('none')
        self.assertEqual(len(visible), 13)
        self.assertEqual(hidden, set())
        self.assertTrue(all('No check' in i['reason'] for i in data['items']))
        self.assertTrue(all(i['patch'] for i in data['items']))

    def test_new_session_edit_invalidates_only_the_edited_file(self):
        populate(self, SCENARIOS['latest'])
        self.agent_turn('demo-session-new', [('src/feature_01.py', 'VALUE = "changed"\n')])
        data = self.data()
        self.assertEqual([i['file'] for i in data['items']], ['src/feature_01.py'])
        self.assertIn('changed since', data['items'][0]['reason'])
        self.assertEqual(len(data['hidden_files']), 12)

    def test_latest_failure_blocks_earlier_passing_checks(self):
        populate(self, SCENARIOS['every'])
        self.check(rule='honest', verdict='fail', actor='program:demo-failure',
                   cites=[{'at': self.sun_head(), 'file': 'src/feature_01.py'}],
                   meta={'synthetic': True})
        data = self.data()
        self.assertEqual([i['file'] for i in data['items']], ['src/feature_01.py'])
        self.assertIn('nonpassing', data['items'][0]['reason'])
        self.assertEqual(len(data['hidden_files']), 12)

    def test_latest_file_scoped_check_does_not_cover_other_sessions_files(self):
        populate(self, SCENARIOS['none'])
        self.passed(self.sun_head(), 'src/feature_12.py')
        data = self.data()
        self.assertEqual([i['file'] for i in data['hidden_files']], ['src/feature_12.py'])
        self.assertEqual(len(data['items']), 12)


def create_demos(destination):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=False)  # never replace someone's repo
    manifest = {}
    for name, checked in SCENARIOS.items():
        case = ReviewScenariosTest()
        try:
            case.setUp()
            # Put rules in Git's baseline so review's default base works too.
            case.git('add', '-A')
            case.git('commit', '-m', 'Synthetic review demo baseline')
            turns = populate(case, checked)
            data = case.data()
            target = destination / name
            shutil.copytree(case.dir, target)
            manifest[name] = {
                'repo': str(target), 'base': case.base, 'turns': turns,
                'visible': [i['file'] for i in data['items']],
                'hidden': [i['file'] for i in data['hidden_files']],
            }
        finally:
            case.tearDown()
            case.doCleanups()
    (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    source = Path(__file__).resolve().parent
    lines = ['# Synthetic Sun review scenarios', '',
             'Each repository has 12 simulated turns across 4 agent sessions.',
             'Passing checks are synthetic fixtures, not real test results. No remote is configured.',
             'Each turn creates a feature file and edits the shared progress file.', '',
             '| Scenario | Checked turns | Needs review | Hidden |',
             '| --- | --- | --- | --- |']
    for name, info in manifest.items():
        turns = ', '.join(str(t['turn']) for t in info['turns'] if t['checked']) or 'none'
        lines.append(f"| {name} | {turns} | {len(info['visible'])} | {len(info['hidden'])} |")
    lines += ['', 'Open any scenario with this checkout of Sun:', '']
    for name, info in manifest.items():
        lines += [f'## {name}', '', f"    cd {shlex.quote(info['repo'])}",
                  f'    PYTHONPATH={shlex.quote(str(source))} python3 -m sun review --web', '']
    (destination / 'README.md').write_text('\n'.join(lines))
    print(destination / 'README.md')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Usage: python3 test_review_scenarios.py NEW_DIRECTORY')
    create_demos(sys.argv[1])
