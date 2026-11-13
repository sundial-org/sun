"""Review 2 identity, source preservation and loopback boundary checks."""
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.request import urlopen, Request
from urllib.error import HTTPError

from sun import review2
from examples.review2.make_demo import example


class Review2Test(unittest.TestCase):
    def test_grouping_preserves_turns_and_deduplicates_inherited_operations(self):
        op={'id':'one','actor':'a','session_id':'s','branch':'main','turn':'1',
            'snapshot':'abc','edits':[{'file':'a.py','patch':'+one'}]}
        other=copy.deepcopy(op);other.update(id='two',turn='2')
        data={'commits':[{'operations':[other]},{'operations':[op]},{'operations':[op]}]}
        result=review2.build_snapshot(data,'repo')
        turns=result['threads'][0]['turns']
        self.assertEqual(len(turns),2)
        self.assertEqual([t['changes'][0]['operation'] for t in turns],['one','two'])
        before=turns[0]['changes'][0]['id']
        op['edits'][0]['patch']='+changed'
        changed=review2.build_snapshot(data,'repo')['threads'][0]['turns'][0]['changes'][0]['id']
        self.assertNotEqual(before,changed)

    def test_missing_transcript_never_invents_context(self):
        self.assertEqual(review2.transcript_context()({'session_path':None}),'')

    def test_snapshot_and_server_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'snapshot.json';path.write_text(json.dumps(example()))
            server,url=review2.create_server(directory)
            worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            try:
                self.assertEqual(json.load(urlopen(url.replace('index.html','data.json')))['id'],example()['id'])
                turn=example()['threads'][0]['turns'][0]
                payload=json.dumps({'snapshot':example()['id'],'turn':turn['id'],'file':turn['changes'][0]['file']}).encode()
                endpoint=url.replace('index.html','view')
                with self.assertRaises(HTTPError):
                    urlopen(Request(endpoint,data=payload,headers={'Content-Type':'application/json','Origin':'https://evil.example'}))
                origin='/'.join(url.split('/')[:3])
                result=json.load(urlopen(Request(endpoint,data=payload,headers={'Content-Type':'application/json','Origin':origin})))
                self.assertEqual(len(result['reviewed']),1)
                for target in [url.replace('index.html','../snapshot.json'),url.split('/')[0]+'//'+url.split('/')[2]+'/data.json']:
                    with self.assertRaises(HTTPError):urlopen(target)
                with self.assertRaises(HTTPError):urlopen(Request(url,headers={'Host':'evil.example'}))
            finally:
                server.shutdown();server.server_close();worker.join()
            value=example();value['repo']='changed';path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError,'changed'):review2.load(directory)


class Review2SelectionTest(unittest.TestCase):
    def setUp(self):
        from sun import review2_state
        self.state=review2_state
        self.snapshot=example()
        self.plan={'version':1,'snapshot':self.snapshot['id'],'turns':[
            {'id':t['id'],'summary':'A specific change.','focus':[{'id':t['changes'][0]['id'],'why':'Changes behavior.'}],
             'context':[c['id'] for c in t['changes'][1:]]}
            for thread in self.snapshot['threads'] for t in thread['turns']]}

    def test_selection_rejects_omissions_unknown_ids_and_stale_snapshot(self):
        self.state.validate(self.snapshot,self.plan)
        for mutate in [lambda p:p.update(snapshot='stale'),lambda p:p['turns'].pop(),
                       lambda p:p['turns'][0]['context'].append('invented'),
                       lambda p:p['turns'][0]['focus'].append(p['turns'][0]['focus'][0])]:
            plan=copy.deepcopy(self.plan);mutate(plan)
            with self.assertRaises(ValueError):self.state.validate(self.snapshot,plan)

    def test_file_view_never_marks_other_files_or_versions_viewed(self):
        with tempfile.TemporaryDirectory() as directory:
            self.state.save_selection(directory,self.snapshot,self.plan)
            turn=self.snapshot['threads'][0]['turns'][0]
            payload={'snapshot':self.snapshot['id'],'turn':turn['id'],'file':turn['changes'][0]['file']}
            result=self.state.record_view(directory,self.snapshot,payload)
            self.assertEqual(result['reviewed'],[{'id':turn['changes'][0]['id'],'scope':'viewed'}])
            self.assertEqual(self.state.state(directory,self.snapshot),result)
            self.assertNotIn({'id':'new-version','scope':'viewed'},result['reviewed'])
            self.assertEqual(self.state.record_view(directory,self.snapshot,payload),result)
            payload['file']=turn['changes'][1]['file']
            self.assertEqual(len(self.state.record_view(directory,self.snapshot,payload)['reviewed']),2)
            turn['changes'][1]['patch']=''
            with self.assertRaisesRegex(ValueError,'unavailable'):self.state.record_view(directory,self.snapshot,payload)
            payload['snapshot']='stale'
            with self.assertRaises(ValueError):self.state.record_view(directory,self.snapshot,payload)

    def test_only_complete_exact_checks_collapse_turns(self):
        snapshot=example();turn=snapshot['threads'][0]['turns'][0]
        changes=turn['changes']
        from sun import checks
        rule={'files':[], 'text':'Safe', 'hash':'rule'}
        records={}
        for i,c in enumerate(changes):
            records[str(i)]={'id':str(i),'rule':'safe','verdict':'pass','cites':[{'at':c['at'],'file':c['file']}], 'actor':'test/program:tests'}
        row={'rule':'safe','status':'pass','checks':list(records.values()),'outdated':[],'labels':{}}
        table=[{'rules':[row]}]
        review2.attach_checks(snapshot,table,{'safe':rule},records)
        self.assertTrue(turn['fully_checked'])
        records['0']['cites'][0]['lines']=[1,2]
        review2.attach_checks(snapshot,table,{'safe':rule},records)
        self.assertFalse(turn['fully_checked'])
        records['0']['cites'][0].pop('lines');row['status']='mixed'
        review2.attach_checks(snapshot,table,{'safe':rule},records)
        self.assertFalse(turn['fully_checked'])
        row['status']='pass';records['0']['cites'][0]['at']='another revision'
        review2.attach_checks(snapshot,table,{'safe':rule},records)
        self.assertFalse(turn['fully_checked'])
