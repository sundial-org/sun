"""Run with the review2-plugin extra: exercises a real stdio MCP client/server."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.request import urlopen

from examples.review2.make_demo import example
from sun.review2_mcp import package


class PluginPackageTest(unittest.TestCase):
    def test_package_is_bound_to_one_workspace_and_preserves_existing_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace=Path(tmp)/'review';workspace.mkdir()
            (workspace/'snapshot.json').write_text(json.dumps(example()))
            destination=Path(tmp)/'plugin'
            package(workspace,destination)
            config=json.loads((destination/'.mcp.json').read_text())
            self.assertEqual(config['mcpServers']['sun-review2']['args'][-1],str(workspace.resolve()))
            self.assertTrue((destination/'skills/sun-review2/SKILL.md').exists())
            with self.assertRaises(FileExistsError):package(workspace,destination)


@unittest.skipUnless(importlib.util.find_spec('mcp'), 'optional MCP SDK not installed')
class MCPIntegrationTest(unittest.TestCase):
    def test_stdio_workflow(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        async def check(workspace):
            params=StdioServerParameters(command=sys.executable,args=['-m','sun.review2_mcp',workspace],
                env={**os.environ,'PYTHONPATH':str(Path(__file__).parent)})
            async with stdio_client(params) as (read,write):
                async with ClientSession(read,write) as session:
                    await session.initialize()
                    names={t.name for t in (await session.list_tools()).tools}
                    self.assertEqual(names,{'read_snapshot','save_highlights','open_review'})
                    result=await session.call_tool('read_snapshot',{})
                    snapshot=result.structuredContent['snapshot']
                    self.assertEqual(snapshot['id'],example()['id'])
                    bad=await session.call_tool('save_highlights',{'plan':{}})
                    self.assertTrue(bad.isError)
                    plan={'version':1,'snapshot':snapshot['id'],'turns':[
                        {'id':t['id'],'summary':'Check the change.','focus':[{'id':c['id'],'why':'Review behavior.'} for c in t['changes']],'context':[]}
                        for th in snapshot['threads'] for t in th['turns']]}
                    saved=await session.call_tool('save_highlights',{'plan':plan})
                    self.assertFalse(saved.isError)
                    pane=(await session.call_tool('open_review',{})).structuredContent
                    with urlopen(pane['url'].replace('index.html','data.json')) as response:
                        self.assertEqual(json.load(response)['selection'],plan)
                    again=(await session.call_tool('open_review',{})).structuredContent
                    self.assertEqual(again['url'],pane['url'])
        with tempfile.TemporaryDirectory() as workspace:
            (Path(workspace)/'snapshot.json').write_text(json.dumps(example()))
            asyncio.run(check(workspace))
