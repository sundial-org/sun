"""Demo a generated local plugin through a real MCP connection. No model/API key."""
import argparse
import asyncio
import json
import os
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def demo(package, selection=None):
    config=json.loads((Path(package)/'.mcp.json').read_text())['mcpServers']['sun-review2']
    params=StdioServerParameters(command=config['command'],args=config['args'],
                                env={**os.environ,**config.get('env',{})})
    async with stdio_client(params) as (read,write):
        async with ClientSession(read,write) as session:
            await session.initialize()
            tools=await session.list_tools()
            print('Connected: '+', '.join(t.name for t in tools.tools),flush=True)
            result=await session.call_tool('read_snapshot',{})
            if result.isError: raise RuntimeError(result.content)
            snapshot=result.structuredContent['snapshot']
            print(f"read_snapshot: {len(snapshot['threads'])} threads",flush=True)
            if selection:
                plan=json.loads(Path(selection).read_text())
                saved=await session.call_tool('save_highlights',{'plan':plan})
                if saved.isError: raise RuntimeError(saved.content)
                print('save_highlights: validated and saved',flush=True)
            result=await session.call_tool('open_review',{})
            if result.isError: raise RuntimeError(result.content)
            print('open_review: '+result.structuredContent['url'],flush=True)
            print('MCP connection remains open. Ctrl-C stops the demo.',flush=True)
            await asyncio.Event().wait()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package',help='Generated local plugin folder')
    parser.add_argument('--selection',help='Prepared selection.json for this snapshot')
    args=parser.parse_args()
    try: asyncio.run(demo(args.package,args.selection))
    except KeyboardInterrupt: pass
