"""Optional MCP adapter, confined to one prepared Review 2 workspace."""
import argparse
from contextlib import asynccontextmanager
import json
from pathlib import Path
import shutil
import sys
import threading
from typing import Any

from . import review2, review2_state


def create_mcp(directory):
    try:
        from mcp.server.fastmcp import FastMCP
        from mcp.types import ToolAnnotations
    except ImportError:
        raise SystemExit('Install Sun with the review2-plugin extra using Python 3.10 or newer.')
    directory = Path(directory).expanduser().resolve()
    snapshot = review2.load(directory)
    servers = []

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield {}
        finally:
            for server, worker, _ in servers:
                server.shutdown()
                server.server_close()
                worker.join()

    app = FastMCP('Sun Review 2', instructions='Review only this captured workspace. Read the snapshot, save validated highlights, then open the review. Human acknowledgment happens in the pane.', lifespan=lifespan)

    @app.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    def read_snapshot() -> dict[str, Any]:
        """Read the bound snapshot and instructions for selecting relevant changes."""
        return {'snapshot': snapshot, 'instructions': review2_state.PROMPT}

    @app.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False, idempotentHint=True))
    def save_highlights(plan: dict) -> dict[str, Any]:
        """Validate and save a complete selection for this exact snapshot. Does not mark human review."""
        if review2.load(directory)['id'] != snapshot['id']:
            raise ValueError('Snapshot changed. Restart the plugin for the new workspace.')
        review2_state.save_selection(directory, snapshot, plan)
        return {'saved': True, 'snapshot': snapshot['id']}

    @app.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False, idempotentHint=True))
    def open_review() -> dict[str, Any]:
        """Start a loopback browser pane and return its URL. Does not open a browser or mark review."""
        if review2.load(directory)['id'] != snapshot['id']:
            raise ValueError('Snapshot changed. Restart the plugin.')
        if not servers:
            server, url = review2.create_server(directory)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            servers.append((server, worker, url))
        return {'url': servers[0][2], 'presentation': 'local-browser', 'snapshot': snapshot['id']}

    return app


def package(directory, destination):
    """Generate machine-specific wiring without changing the user's plugin settings."""
    directory = Path(directory).expanduser().resolve()
    review2.load(directory)
    destination = Path(destination).expanduser().resolve()
    shutil.copytree(Path(__file__).with_name('review2_plugin'), destination)
    manifest = {'name': 'sun-review2', 'version': '0.1.0',
                'description': 'A minimal review of your own agent work, one turn at a time.',
                'skills': './skills/', 'mcpServers': './.mcp.json'}
    (destination / '.codex-plugin').mkdir()
    (destination / '.codex-plugin' / 'plugin.json').write_text(json.dumps(manifest, indent=2) + '\n')
    config = {'mcpServers': {'sun-review2': {'command': sys.executable,
        'args': ['-m', 'sun.review2_mcp', str(directory)],
        'env': {'PYTHONPATH': str(Path(__file__).resolve().parent.parent)}}}}
    (destination / '.mcp.json').write_text(json.dumps(config, indent=2) + '\n')
    return str(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace')
    parser.add_argument('--package', metavar='DESTINATION', help='write a local plugin package instead of starting MCP')
    args = parser.parse_args()
    if args.package:
        print(package(args.workspace, args.package))
    else:
        create_mcp(args.workspace).run(transport='stdio')


if __name__ == '__main__':
    main()
