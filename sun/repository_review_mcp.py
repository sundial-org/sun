"""Inline MCP App adapter for the repository review prototype."""
from pathlib import Path
from typing import Any
from . import repository_review as prototype

URI='ui://sun/repository-review-v1.html'


def create(workspace):
    from mcp.server.fastmcp import FastMCP
    from mcp.types import ToolAnnotations
    workspace=Path(workspace).resolve()
    app=FastMCP('Sun Repository Review',instructions='Review all recorded repository turns. Rules and verdicts are immutable evidence. Use read_turn and read_patch before saving an explanation. open_review renders inline when supported. Never call review_turn as the agent; it is only for a user clicking the review control.')
    @app.resource(URI,mime_type='text/html;profile=mcp-app',meta={'ui':{'prefersBorder':False,'csp':{'connectDomains':[],'resourceDomains':[]}}})
    def ui():
        return prototype.render_html(workspace).replace("const transport = 'server';", "const transport = 'plugin';")
    @app.tool(annotations=ToolAnnotations(readOnlyHint=True,openWorldHint=False))
    def read_repository() -> dict[str, Any]:
        """Get all repository turns and repo rule definitions without copying full diffs."""
        m=prototype.load(workspace)
        return {'repo':m['repo'],'scope':m['scope'],'rules':m['rules'],'summary':m['summary'],'turns':[{k:v for k,v in t.items() if k not in ('changes','request')} | {'edits':len(t['changes'])} for t in m['turns']]}
    @app.tool(annotations=ToolAnnotations(readOnlyHint=True,openWorldHint=False))
    def read_turn(turn_id:str) -> dict[str, Any]:
        """Read one turn with recorded checks and diff previews. Use read_patch for full file evidence."""
        return next(t for t in prototype.load(workspace)['turns'] if t['id']==turn_id)
    @app.tool(annotations=ToolAnnotations(readOnlyHint=True,openWorldHint=False))
    def read_patch(change_id:str,offset:int=0,limit:int=200000) -> dict[str, Any]:
        """Read a complete recorded file diff, with offset pagination for unusually large patches."""
        allowed={c['id'] for t in prototype.load(workspace)['turns'] for c in t['changes']}
        if change_id not in allowed or offset<0 or not 1<=limit<=200000:raise ValueError('Unknown change or invalid range')
        text=(workspace/'patches'/f'{change_id}.patch').read_text()
        return {'patch':text[offset:offset+limit],'next_offset':offset+limit if offset+limit<len(text) else None,'characters':len(text)}
    @app.tool(annotations=ToolAnnotations(readOnlyHint=False,destructiveHint=False,openWorldHint=False))
    def save_explanation(turn_id:str,text:str,check_ids:list[str]) -> dict[str, Any]:
        """Save the current agent's evidence-backed explanation. Does not change results or review state."""
        return prototype.save_explanation(workspace,turn_id,text,check_ids)
    @app.tool(meta={'ui':{'visibility':['app']}},annotations=ToolAnnotations(readOnlyHint=False,destructiveHint=False,openWorldHint=False))
    def review_turn(turn_id:str) -> dict[str, Any]:
        """User-interface action only: record a person's explicit mark-reviewed click."""
        return {'reviewed':prototype.review_turn(workspace,prototype.load(workspace),turn_id)}
    @app.tool(meta={'ui':{'resourceUri':URI},'openai/outputTemplate':URI,'openai/ui':{'preferredModelDisplayMode':'inline','supportedDisplayModes':['inline','fullscreen']}},annotations=ToolAnnotations(readOnlyHint=True,openWorldHint=False))
    def open_review() -> dict[str, Any]:
        """Show the repository coverage, turn grid, sessions and agent explanations inline in chat."""
        m=prototype.load(workspace)
        return {'repo':m['repo'],'summary':m['summary'],'turns_count':len(m['turns']),'presentation':'inline','example':m['example']}
    return app


