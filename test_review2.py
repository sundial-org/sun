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
                for target in [url.replace('index.html','../snapshot.json'),url.split('/')[0]+'//'+url.split('/')[2]+'/data.json']:
                    with self.assertRaises(HTTPError):urlopen(target)
                with self.assertRaises(HTTPError):urlopen(Request(url,headers={'Host':'evil.example'}))
            finally:
                server.shutdown();server.server_close();worker.join()
            value=example();value['repo']='changed';path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError,'changed'):review2.load(directory)
