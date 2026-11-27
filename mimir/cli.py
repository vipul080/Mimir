"""Command line for Mimir. Any AI that can run terminal commands can use
Mimir this way, with or without MCP support. Command names match the MCP
tool names, so the same guide works for both.

  mimir repo_map
  mimir outline src/main/java/shop/Cart.java
  mimir get_symbol Cart.total
  mimir who_calls applyDiscount
  mimir replace_symbol Pricing.applyDiscount --file new_code.txt   (or pipe it on stdin)
  mimir check [FILES...]
  mimir checkpoint "before refactor" | list_checkpoints | diff_since ID | restore ID
  mimir guide                       print instructions to paste into AGENTS.md / GEMINI.md / CLAUDE.md
  mimir serve [PROJECT] [--http]    run as an MCP server
  mimir dashboard [PROJECT]         open the human dashboard

The project is --root, else MIMIR_ROOT, else the current folder.
"""
from __future__ import annotations

import argparse
import os
import sys

from .api import Mimir

CLI_NOTE = """
From a terminal, run each as `mimir <tool> [args]` in the project folder
(or add --root PATH). replace_symbol reads the new source from --file or stdin.
Exit code is 1 when a check fails or a command reports an ERROR."""


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mimir", description="Mimir: an IDE for AI agents.",
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("--root", help="project folder (default: MIMIR_ROOT or current folder)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("repo_map", help="map of the whole project")
    sub.add_parser("outline", help="signatures of one file").add_argument("file")
    sub.add_parser("get_symbol", help="source of one symbol").add_argument("name")
    sub.add_parser("who_calls", help="call sites of a symbol").add_argument("name")
    r = sub.add_parser("replace_symbol", help="rewrite a symbol by name")
    r.add_argument("name")
    r.add_argument("--file", help="read the new source from this file instead of stdin")
    sub.add_parser("check", help="syntax, lint and tests").add_argument("files", nargs="*")
    sub.add_parser("checkpoint", help="save a snapshot").add_argument("label", nargs="?", default="")
    sub.add_parser("list_checkpoints", help="list snapshots")
    sub.add_parser("diff_since", help="diff since a snapshot").add_argument("checkpoint_id")
    sub.add_parser("restore", help="roll back to a snapshot").add_argument("checkpoint_id")
    sub.add_parser("guide", help="instructions for an AI agent")

    s = sub.add_parser("serve", help="run as an MCP server (stdio by default)")
    s.add_argument("project", nargs="?")
    s.add_argument("--http", action="store_true", help="serve MCP over HTTP instead of stdio")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--allow-host", action="append", default=[],
                   help="extra Host header to accept, e.g. a tunnel domain (repeatable)")

    d = sub.add_parser("dashboard", help="open the human dashboard")
    d.add_argument("project", nargs="?")
    d.add_argument("--port", type=int, default=8765)
    d.add_argument("--no-browser", action="store_true")
    return p


def main(argv: list[str] | None = None) -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    args = _parser().parse_args(argv)
    root = getattr(args, "project", None) or args.root or os.environ.get("MIMIR_ROOT") or "."

    if args.cmd == "dashboard":
        from .dashboard import run_dashboard
        return run_dashboard(root, args.port, not args.no_browser)

    try:
        m = Mimir(root)
    except NotADirectoryError as e:
        sys.exit(f"ERROR: {e}")

    if args.cmd == "serve":
        from .server import serve_http, serve_stdio
        if args.http:
            return serve_http(m, args.host, args.port, args.allow_host)
        return serve_stdio(m)

    if args.cmd == "guide":
        print(m.guide() + CLI_NOTE)
        return
    if args.cmd == "replace_symbol":
        if args.file:
            with open(args.file, encoding="utf-8") as f:
                source = f.read()
        else:
            source = sys.stdin.read()
        out = m.replace_symbol(args.name, source)
    else:
        call = {
            "repo_map": lambda: m.repo_map(),
            "outline": lambda: m.outline(args.file),
            "get_symbol": lambda: m.get_symbol(args.name),
            "who_calls": lambda: m.who_calls(args.name),
            "check": lambda: m.check(args.files or None),
            "checkpoint": lambda: m.checkpoint(args.label),
            "list_checkpoints": lambda: m.list_checkpoints(),
            "diff_since": lambda: m.diff_since(args.checkpoint_id),
            "restore": lambda: m.restore(args.checkpoint_id),
        }[args.cmd]
        out = call()
    print(out)
    if out.startswith("ERROR") or "RESULT: FAIL" in out:
        sys.exit(1)


if __name__ == "__main__":
    main()
