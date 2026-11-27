"""Human dashboard: a small local web page to watch what the AI is doing in a
project and step in (run checks, view diffs, roll back to a checkpoint).

Uses only Python's standard library, so it adds no dependencies and little RAM.

Run:  mimir dashboard <project-folder> [--port 8765]
Then open http://127.0.0.1:8765
"""
from __future__ import annotations

import json
import re
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import activity
from .api import Mimir

PAGE = Path(__file__).with_name("dashboard.html")
EDIT_TOOLS = {"replace_symbol", "restore"}


def last_check(entries: list[dict]) -> dict | None:
    """The most recent check result found in the log, from either side."""
    for e in reversed(entries):
        m = re.search(r"RESULT: (ok|FAIL)", e.get("result_head", ""))
        if m:
            return {"ok": m.group(1) == "ok", "time": e["time"], "by": e.get("by", "ai"), "tool": e["tool"]}
    return None


class App:
    """Dashboard actions go through the same API as the AI, logged as 'human'."""

    def __init__(self, root: Path):
        self.m = Mimir(root, actor="human")
        self.root, self.cm, self.cps = self.m.root, self.m.cm, self.m.cps

    def state(self, since: int) -> dict:
        everything = activity.read(self.root)
        cps = self.cps.list()
        latest = cps[-1]["id"] if cps else None
        return {
            "project": self.root.name,
            "path": str(self.root),
            "languages": [b.name for b in self.cm.languages()],
            "entries": [e for e in everything if e["n"] >= since][-500:],
            "total": len(everything),
            "stats": {
                "calls": sum(1 for e in everything if e.get("by", "ai") == "ai"),
                "edits": sum(1 for e in everything if e["tool"] in EDIT_TOOLS
                             and not e.get("result_head", "").startswith("ERROR")),
                "refused": sum(1 for e in everything if e.get("result_head", "").startswith("ERROR")),
                "files": len(self.cm.source_files()),
            },
            "last_check": last_check(everything),
            "checkpoints": cps,
            "changes": self.cps.changes(latest) if latest else None,
            "changes_since": latest,
        }

    def run_check(self) -> str:
        return self.m.check()

    def restore(self, cp_id: str) -> str:
        return self.m.restore(cp_id)

    def checkpoint(self, label: str) -> str:
        return self.m.checkpoint(label)


def make_handler(app: App, port: int):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep the terminal quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data, code: int = 200):
            self._send(code, json.dumps(data).encode(), "application/json")

        def _host_ok(self) -> bool:
            # blocks DNS-rebinding: other websites can't pose as localhost
            return self.headers.get("Host", "") in allowed_hosts

        def do_GET(self):
            if not self._host_ok():
                return self._send(403, b"forbidden", "text/plain")
            url = urlparse(self.path)
            q = parse_qs(url.query)
            try:
                if url.path == "/":
                    return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
                if url.path == "/api/state":
                    return self._json(app.state(int(q.get("since", ["0"])[0])))
                if url.path == "/api/diff":
                    return self._json({"diff": app.cps.diff(q["id"][0])})
            except (ValueError, KeyError) as e:
                return self._json({"error": str(e)}, 400)
            self._send(404, b"not found", "text/plain")

        def do_POST(self):
            # the custom header makes browsers block cross-site requests to this server
            if not self._host_ok() or self.headers.get("X-Mimir") != "1":
                return self._send(403, b"forbidden", "text/plain")
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                if self.path == "/api/check":
                    return self._json({"result": app.run_check()})
                if self.path == "/api/restore":
                    return self._json({"result": app.restore(body["id"])})
                if self.path == "/api/checkpoint":
                    return self._json({"result": app.checkpoint(body.get("label", "from dashboard"))})
            except (ValueError, KeyError) as e:
                return self._json({"error": str(e)}, 400)
            self._send(404, b"not found", "text/plain")

    return Handler


def run_dashboard(project: str, port: int = 8765, open_browser: bool = True) -> None:
    app = App(Path(project).resolve())
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app, port))
    url = f"http://127.0.0.1:{port}"
    print(f"Mimir dashboard for {app.root}")
    print(f"  {url}   (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


def main():
    from .cli import main as cli_main
    import sys
    cli_main(["dashboard", *sys.argv[1:]])


if __name__ == "__main__":
    main()
