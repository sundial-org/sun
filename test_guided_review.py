"""Agent workspace flow, with real Git snapshots and mocked GitHub transport."""
import copy
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock
from urllib.parse import urlsplit

from sun import guided_review, inbox, review_web
from test_sun import run
import test_inbox as inbox_tests


def fixture():
    return {'number': 7, 'title': '<script>unsafe title</script>', 'url': 'https://github.com/org/repo/pull/7',
            'repository': {'nameWithOwner': 'org/repo'}, 'author': {'login': 'author'},
            'review': {'head': 'a'*40, 'base': 'b'*40, 'files': 1, 'hidden_files': [],
                       'items': [{'file': 'a.py', 'patch': '+change', 'reason': 'No check'}],
                       'check_results': [{'name': 'tests', 'status': 'Outdated', 'files': [], 'checks': []}],
                       'coverage': {'warning': 'No shared Sun evidence'}}}


def complete(directory):
    path = Path(directory) / 'review.json'
    plan = json.loads(path.read_text())
    plan['complete'] = True
    for item in plan['reviews']:
        item.update(question='Does the new behavior preserve the contract?', why='The caller still uses the old field.',
                    evidence=[{'file': 'a.py', 'note': 'The return value changes.'}], required_checks=['security'])
    guided_review.write_json(path, plan)
    return plan


class GuidedReviewTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / 'workspace'

    def prepare(self, rows=None, *args):
        with mock.patch.object(inbox, 'collect', return_value=[fixture()] if rows is None else rows):
            return json.loads(run('review', '--prepare', str(self.directory), *args))

    def test_prepare_agent_render_flow_and_personal_skill(self):
        skill = Path(self.temp.name) / 'personal.md'
        skill.write_text('Review tenant isolation.')
        result = self.prepare(None, '--prompt', 'Focus on tenancy', '--skill', str(skill))
        self.assertEqual(result['workspace'], str(self.directory.resolve()))
        prompt = (self.directory/'prompt.md').read_text()
        self.assertIn('Focus on tenancy', prompt)
        self.assertIn('Review tenant isolation.', prompt)
        self.assertNotIn('Review on GitHub', prompt)
        with self.assertRaisesRegex(SystemExit, 'not completed'):
            run('review', '--open', str(self.directory), '--json')
        complete(self.directory)
        data = json.loads(run('review', '--open', str(self.directory), '--json'))
        self.assertTrue(data['guided'])
        self.assertEqual(data['prs'][0]['review']['check_results'][0]['status'], 'Outdated')
        self.assertEqual(data['skills'], ['personal'])
        self.assertEqual(data['prs'][0]['analysis']['required_checks'], ['security'])
        with mock.patch.object(review_web, 'run') as serve:
            run('review', '--open', str(self.directory), '--no-browser')
        self.assertEqual(serve.call_args.kwargs, {'open_browser': False})

    def test_changed_snapshot_stale_head_and_fabricated_facts_rejected(self):
        self.prepare()
        plan = complete(self.directory)
        snapshot_path = self.directory/'snapshot.json'
        snapshot = json.loads(snapshot_path.read_text())
        checksum = guided_review.digest(snapshot_path)
        for mutate in [lambda p:p['reviews'][0].update(head='c'*40),
                       lambda p:p['reviews'][0].update(check_results=[{'status':'Passed'}]),
                       lambda p:p['reviews'][0].update(evidence=[{'file':'missing.py','note':'fake'}]),
                       lambda p:p['reviews'][0].update(depends_on=['org/repo#999']),
                       lambda p:p['reviews'].append(copy.deepcopy(p['reviews'][0])),
                       lambda p:p.update(reviews=[]),
                       lambda p:p.update(snapshot='wrong')]:
            candidate = copy.deepcopy(plan)
            mutate(candidate)
            with self.assertRaises(ValueError): guided_review.validate(snapshot, candidate, checksum)
        snapshot_path.write_text(snapshot_path.read_text()+'\n')
        with self.assertRaisesRegex(ValueError, 'Snapshot changed'): guided_review.load(self.directory)

    def test_failures_and_empty_inbox_remain_visible(self):
        bad = dict(fixture(), number=8, error='Repository unavailable')
        del bad['review']
        self.prepare([bad])
        plan = complete(self.directory)
        self.assertEqual(plan['reviews'], [])
        self.assertEqual(guided_review.load(self.directory)['prs'][0]['error'], 'Repository unavailable')
        self.directory = Path(self.temp.name)/'empty'
        self.prepare([])
        complete(self.directory)
        self.assertEqual(guided_review.load(self.directory)['prs'], [])

    def test_existing_workspace_is_not_overwritten(self):
        self.prepare()
        before=(self.directory/'snapshot.json').read_bytes()
        with self.assertRaises(SystemExit): self.prepare()
        self.assertEqual((self.directory/'snapshot.json').read_bytes(),before)

    def test_same_number_in_different_repos_and_all_rows_preserved(self):
        rows=[]
        for index in range(102):
            row=copy.deepcopy(fixture())
            row['repository']['nameWithOwner']=f'org/repo{index}'
            rows.append(row)
        self.prepare(rows)
        plan=complete(self.directory)
        plan['reviews'].reverse()
        guided_review.write_json(self.directory/'review.json',plan)
        data=guided_review.load(self.directory)
        self.assertEqual(len(data['prs']),102)
        self.assertEqual(data['prs'][0]['id'],'org/repo101#7')

    def test_fetch_failure_can_be_retried_without_overwriting_files(self):
        with mock.patch.object(inbox, 'collect', side_effect=RuntimeError('Authenticate GitHub CLI')):
            with self.assertRaisesRegex(SystemExit, 'Authenticate'):
                run('review', '--prepare', str(self.directory))
        self.assertFalse(self.directory.exists())
        self.prepare()
        self.assertTrue((self.directory/'snapshot.json').exists())

    def test_cli_requires_prepare_for_prompt_and_skill(self):
        with self.assertRaises(SystemExit): run('review','--prompt','anything')
        with self.assertRaises(SystemExit): run('review','--prepare',str(self.directory),'--limit','0')
        self.assertIn('name: sun-review',run('review','--instructions'))

    def test_real_server_serves_only_bundled_ui_and_verified_data(self):
        self.prepare()
        complete(self.directory)
        server,url=review_web.create_server(guided_review.load(self.directory))
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            prefix=urlsplit(url).path.rsplit('/',1)[0]+'/'
            def get(path,headers=None):
                conn=http.client.HTTPConnection('127.0.0.1',server.server_port)
                conn.request('GET',path,headers=headers or {})
                response=conn.getresponse()
                result=response.status,response.read()
                conn.close()
                return result
            for file in ['index.html','style.css','app.mjs','model.mjs','data.json']:
                self.assertEqual(get(prefix+file)[0],200)
            data=json.loads(get(prefix+'data.json')[1])
            self.assertIn('<script>',data['prs'][0]['title'])  # UI treats it as text, never HTML.
            self.assertEqual(get(prefix+'../snapshot.json')[0],404)
            self.assertEqual(get(prefix+'data.json',{'Host':'evil.test'})[0],404)
            self.assertNotIn('root',data['prs'][0])
        finally:
            server.shutdown();server.server_close();thread.join()


class GuidedGitFlowTest(unittest.TestCase):
    setUp, tearDown = inbox_tests.InboxTest.setUp, inbox_tests.InboxTest.tearDown
    git, sun_head, check = inbox_tests.InboxTest.git, inbox_tests.InboxTest.sun_head, inbox_tests.InboxTest.check
    tool_call, agent_turn = inbox_tests.InboxTest.tool_call, inbox_tests.InboxTest.agent_turn
    change, passed = inbox_tests.InboxTest.change, inbox_tests.InboxTest.passed

    def test_prepare_uses_real_pinned_diff_and_rules_through_cli(self):
        self.git('add','-A');self.git('commit','-m','baseline')
        base=self.git('rev-parse','HEAD').strip()
        self.agent_turn('session-one',[('a.py','print("real diff")\n')])
        tip=self.sun_head();self.passed(tip)
        self.git('add','a.py');self.git('commit','-m','feature')
        head=self.git('rev-parse','HEAD').strip()
        self.git('update-ref','refs/sun/reviews/'+head,tip)
        import os
        repo=os.getcwd()
        original=inbox.command
        def command(*args,**kwargs):
            return original(*(repo if a.startswith('https://github.com/') else a for a in args),**kwargs)
        info={'headRefOid':head,'baseRefOid':base,'headRepository':{'name':'repo'},'headRepositoryOwner':{'login':'org'},
              'statusCheckRollup':[{'name':'build','status':'COMPLETED','conclusion':'SUCCESS'},
                                 {'name':'pending','status':'IN_PROGRESS','conclusion':None},
                                 {'name':'cancelled','status':'COMPLETED','conclusion':'CANCELLED'},
                                 {'context':'legacy','state':'ERROR'},
                                 {'name':'skipped','status':'COMPLETED','conclusion':'SKIPPED'}]}
        row=fixture();del row['review']
        def gh(*args): return [row] if args[0]=='search' else info
        before=self.git('status','--porcelain')
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(inbox,'gh',side_effect=gh), mock.patch.object(inbox,'command',side_effect=command):
            path=Path(tmp)/'review'
            run('review','--prepare',str(path),'--prompt','Check the return contract')
            complete(path)
            data=json.loads(run('review','--open',str(path),'--json'))
            source=data['prs'][0]['review']
            self.assertEqual(source['head'],head)
            self.assertIn('print("real diff")',source['hidden_files'][0]['patch'])
            self.assertEqual([c['status'] for c in source['github_checks']],['Passed','Running','Nonpassing','Nonpassing','Skipped'])
            statuses={r['name']:r['status'] for r in source['check_results']}
            self.assertEqual(statuses['honest'],'Passed')
            self.assertEqual(statuses['tidy'],'Not recorded')
        self.assertEqual(self.git('status','--porcelain'),before)
