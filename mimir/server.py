"""Mimir as an MCP server, the open standard most AI coding tools speak
(Claude Code, Gemini CLI, Codex CLI, Cursor, VS Code Copilot, ...).

Two transports:
  stdio  the AI tool starts Mimir itself (most tools; the default)
  http   Mimir runs as a local web service the AI connects to by URL

Run with the CLI:  mimir serve <project>   or   mimir serve <project> --http
"""
from __future__ import annotations

import hmac
import ipaddress
import os

from mcp.server.mcpserver import MCPServer

from .api import Mimir


def build(m: Mimir) -> MCPServer:
    mcp = MCPServer("mimir", instructions=m.guide())

    @mcp.tool()
    def repo_map() -> str:
        """Compact map of the whole project: every source file with its classes
        (and their methods) and top-level functions. Start here."""
        return m.repo_map()

    @mcp.tool()
    def outline(file: str) -> str:
        """Signatures, doc lines and line ranges for every class/function in one
        file, with bodies hidden. Much cheaper than reading the file."""
        return m.outline(file)

    @mcp.tool()
    def get_symbol(name: str) -> str:
        """Source of one function, method or class, with line numbers.
        name: 'func', 'Class', 'Class.method', 'path/File.java:Class.method';
        add '@LINE' to pick one overload, e.g. 'Cart.add@27'."""
        return m.get_symbol(name)

    @mcp.tool()
    def who_calls(name: str) -> str:
        """Every call site of a function/method across the project, with the
        calling function and the line. Matched by name, so same-named methods
        on different classes are listed together."""
        return m.who_calls(name)

    @mcp.tool()
    def replace_symbol(name: str, new_source: str) -> str:
        """Replace a whole function/method/class definition with new_source
        (include the signature line and any decorators/annotations; indentation
        is fixed for you). Refused if it would break syntax. Returns check
        results for the file and its related tests."""
        return m.replace_symbol(name, new_source)

    @mcp.tool()
    def check(files: list[str] | None = None) -> str:
        """Syntax, lint and tests. With files: only those files and the tests
        related to them. Without: the whole project and full test suite."""
        return m.check(files)

    @mcp.tool()
    def checkpoint(label: str = "") -> str:
        """Save a snapshot of the whole project. Returns its id for restore()."""
        return m.checkpoint(label)

    @mcp.tool()
    def list_checkpoints() -> str:
        """All saved checkpoints, oldest first."""
        return m.list_checkpoints()

    @mcp.tool()
    def diff_since(checkpoint_id: str) -> str:
        """Unified diff of everything that changed since a checkpoint."""
        return m.diff_since(checkpoint_id)

    @mcp.tool()
    def restore(checkpoint_id: str) -> str:
        """Roll the project back to a checkpoint. Files added since are removed.
        A safety checkpoint is taken first, so a restore can itself be undone."""
        return m.restore(checkpoint_id)

    return mcp


class _BearerAuth:
    """Tiny ASGI wrapper: every HTTP request must carry 'Authorization: Bearer <token>'."""

    def __init__(self, app, token: str):
        self.app, self.token = app, token.encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers") or [])
            given = headers.get(b"authorization", b"")
            if not hmac.compare_digest(given, b"Bearer " + self.token):
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"text/plain"), (b"www-authenticate", b"Bearer")]})
                await send({"type": "http.response.body", "body": b"Missing or wrong Mimir token"})
                return
        await self.app(scope, receive, send)


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def serve_stdio(m: Mimir) -> None:
    build(m).run("stdio")


def serve_http(m: Mimir, host: str = "127.0.0.1", port: int = 8000,
               allow_hosts: list[str] | None = None) -> None:
    """Serve MCP over HTTP at http://host:port/mcp.
    MIMIR_TOKEN, if set, is required as a Bearer token. It is mandatory when
    listening beyond this computer, since Mimir can edit files and run tests."""
    import uvicorn
    from mcp.server.transport_security import TransportSecuritySettings

    token = os.environ.get("MIMIR_TOKEN", "")
    if not _is_loopback(host) and not token:
        raise SystemExit("Refusing to listen on a non-local address without MIMIR_TOKEN set.")

    allowed = [f"127.0.0.1:{port}", f"localhost:{port}", *(allow_hosts or [])]
    security = TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=allowed,
                                         allowed_origins=[f"http://{h}" for h in allowed] +
                                                         [f"https://{h}" for h in allowed])
    app = build(m).streamable_http_app(host=host, transport_security=security)
    if token:
        app = _BearerAuth(app, token)
    print(f"Mimir MCP over HTTP: http://{host}:{port}/mcp  (token {'required' if token else 'off'})")
    uvicorn.run(app, host=host, port=port, log_level="warning")


def main():
    """Backward-compatible entry: python -m mimir.server <project>"""
    from .cli import main as cli_main
    import sys
    cli_main(["serve", *sys.argv[1:]])


if __name__ == "__main__":
    main()
