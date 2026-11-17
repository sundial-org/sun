import asyncio
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from sun.repository_review import current,finish,load,review_turn,save_explanation,tone,summarize
from sun.repository_review_tui import Browser,plain,sessions
ROOT=Path(__file__).parent


class PrototypeTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)
        from examples.review2.make_repository_demo import make_example
        make_example(self.path,[{'name':'tests','text':'Run tests.'},{'name':'ponytail','text':'Keep it simple.'}])
        self.model=load(self.path)
    def test_reference_totals_and_failure_precedence(self):
        self.assertEqual(self.model['summary'],{'edits':395,'checked':151,'unchecked':244,'percent':38})
        for n in [1,2,3]:self.assertEqual(tone({'failed':n,'passed':20}),('red',n))
        for n,level in [(1,1),(4,1),(5,2),(8,2),(9,3)]:self.assertEqual(tone({'failed':0,'passed':n}),('green',level))
        self.assertEqual(tone({'failed':0,'passed':0}),('gray',0))
    def test_review_state_does_not_change_check_counts_and_survives_reload(self):
        t=self.model['turns'][0];before=copy.deepcopy(self.model['summary'])
        review_turn(self.path,self.model,t['id']);again=load(self.path)
        self.assertEqual(again['summary'],before)
        self.assertTrue(all(c['id'] in again['reviewed'] for c in t['changes']))
        self.assertNotIn(t['id'],[t['id'] for g in sessions(again) for t in g])
        self.assertIn(t['id'],[t['id'] for g in sessions(again,'all') for t in g])
        with self.assertRaises(ValueError):review_turn(self.path,again,'unknown')
    def test_agent_explanation_never_enters_terminal_and_needs_citations(self):
        t=self.model['turns'][0]
        save_explanation(self.path,t['id'],'A model explanation sentinel',[t['checks'][0]['id']])
        b=Browser(self.path);b.page=('turn',t['id'])
        self.assertNotIn('sentinel','\n'.join(r[0] for r in b.rows()))
        self.assertNotIn('sentinel',plain(load(self.path)))
        self.assertIn('sentinel',load(self.path)['explanations'][t['id']]['text'])
        with self.assertRaises(ValueError):save_explanation(self.path,t['id'],'Anything',['invented'])
    def test_superseded_and_outdated_checks_are_not_counted(self):
        rs={'tests':{'hash':'new'}}
        records={'a':{'id':'a','rule':'tests','rule_text':'new','cites':[]},'b':{'id':'b','rule':'tests','rule_text':'new','cites':[{'check':'a'}]},'c':{'id':'c','rule':'tests','rule_text':'old','cites':[]}}
        self.assertEqual(set(current(records,rs)),{'b'})
    def test_terminal_drilldown_contains_complete_patch(self):
        b=Browser(self.path);b.open();self.assertEqual(b.page[0],'session');b.open();self.assertEqual(b.page[0],'turn')
        self.assertTrue(any('--- a/' in row[0] for row in b.rows()));b.back();self.assertEqual(b.page[0],'session')
    def test_empty_repository(self):
        self.assertEqual(summarize([]),{'edits':0,'checked':0,'unchecked':0,'percent':0})
    @unittest.skipUnless(__import__("importlib.util").util.find_spec("mcp"), "optional MCP SDK not installed")
    def test_mcp_inline_resource_and_ui_only_review(self):
        from mcp import ClientSession,StdioServerParameters
        from mcp.client.stdio import stdio_client
        async def check():
            from sun.review2_mcp import package
            destination=self.path/'plugin';package(self.path,destination)
            config=json.loads((destination/'.mcp.json').read_text())['mcpServers']['sun-review2']
            params=StdioServerParameters(command=config['command'],args=config['args'])
            async with stdio_client(params) as (read,write):
                async with ClientSession(read,write) as session:
                    await session.initialize()
                    tools={t.name:t for t in (await session.list_tools()).tools}
                    self.assertEqual(tools['open_review'].meta['ui']['resourceUri'],'ui://sun/repository-review-v1.html')
                    self.assertEqual(tools['review_turn'].meta['ui']['visibility'],['app'])
                    r=await session.read_resource('ui://sun/repository-review-v1.html')
                    self.assertEqual(r.contents[0].mimeType,'text/html;profile=mcp-app')
                    self.assertIn("const transport = 'plugin'",r.contents[0].text)
                    result=await session.call_tool('open_review',{})
                    self.assertFalse(result.isError);self.assertEqual(result.structuredContent['summary']['edits'],395)
                    cid=self.model['turns'][0]['changes'][0]['id']
                    first=await session.call_tool('read_patch',{'change_id':cid,'offset':0,'limit':10})
                    self.assertEqual(len(first.structuredContent['patch']),10);self.assertEqual(first.structuredContent['next_offset'],10)
                    bad=await session.call_tool('read_patch',{'change_id':'../snapshot.json'})
                    self.assertTrue(bad.isError)
        asyncio.run(check())

if __name__=='__main__':unittest.main()
