"""The three ways an AI can reach Mimir: CLI, MCP over stdio, MCP over HTTP."""
import asyncio
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

DEMO = Path(__file__).parent.parent / "demo_shop"
EXPECTED_TOOLS = {"repo_map", "outline", "get_symbol", "who_calls", "replace_symbol", "check",
                  "checkpoint", "list_checkpoints", "diff_since", "restore"}


@pytest.fixture
def proj(tmp_path):
    dst = tmp_path / "demo_shop"
    shutil.copytree(DEMO, dst)
    return dst


def cli(*args, stdin=None):
    return subprocess.run([sys.executable, "-m", "mimir.cli", *args], input=stdin,
                          capture_output=True, text=True, encoding="utf-8")


def test_cli_read_commands(proj):
    r = cli("--root", str(proj), "get_symbol", "apply_discount")
    assert r.returncode == 0 and "def apply_discount" in r.stdout


def test_cli_exit_codes_and_stdin_edit(proj):
    assert cli("--root", str(proj), "check").returncode == 1  # demo has a bug
    r = cli("--root", str(proj), "replace_symbol", "apply_discount",
            stdin="def apply_discount(price, percent):\n    return price - price * percent / 100\n")
    assert r.returncode == 0 and "RESULT: ok" in r.stdout
    assert cli("--root", str(proj), "get_symbol", "nope").returncode == 0  # not found is not an error


def test_cli_guide_mentions_every_tool(proj):
    out = cli("--root", str(proj), "guide").stdout
    assert all(t in out for t in EXPECTED_TOOLS)


def test_mcp_stdio(proj):
    async def run():
        params = StdioServerParameters(command=sys.executable, args=["-m", "mimir.cli", "serve", str(proj)])
        async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            names = {t.name for t in (await s.list_tools()).tools}
            res = await s.call_tool("who_calls", {"name": "apply_discount"})
            return names, res.content[0].text
    names, text = asyncio.run(run())
    assert names == EXPECTED_TOOLS
    assert "2 call(s)" in text


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(port: int, proc, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        if proc.poll() is not None:
            raise RuntimeError(proc.stdout.read())
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.2)
    raise TimeoutError("server did not start")


def test_mcp_http_requires_token(proj):
    port = _free_port()
    env = {**os.environ, "MIMIR_TOKEN": "s3cret-test-token"}
    proc = subprocess.Popen([sys.executable, "-m", "mimir.cli", "serve", str(proj), "--http", "--port", str(port)],
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        _wait_for_port(port, proc)
        url = f"http://127.0.0.1:{port}/mcp"

        async def run():
            async with create_mcp_http_client() as anon:
                denied = (await anon.post(url, json={})).status_code
            client = create_mcp_http_client(headers={"Authorization": "Bearer s3cret-test-token"})
            async with client, streamable_http_client(url, http_client=client) as (r, w), ClientSession(r, w) as s:
                await s.initialize()
                return denied, {t.name for t in (await s.list_tools()).tools}
        denied, names = asyncio.run(run())
        assert denied == 401
        assert names == EXPECTED_TOOLS
    finally:
        proc.kill()


def test_http_refuses_public_address_without_token(proj):
    env = {k: v for k, v in os.environ.items() if k != "MIMIR_TOKEN"}
    r = subprocess.run([sys.executable, "-m", "mimir.cli", "serve", str(proj), "--http", "--host", "0.0.0.0"],
                       env=env, capture_output=True, text=True, timeout=30)
    assert r.returncode != 0 and "MIMIR_TOKEN" in r.stderr
