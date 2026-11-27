"""Human dashboard: a small local web page to watch what the AI is doing in a
project and step in (run checks, view diffs, roll back to a checkpoint).

Uses only Python's standard library, so it adds no dependencies and little RAM.

Run:  python -m mimir.dashboard <project-folder> [--port 8765]
Then open http://127.0.0.1:8765
"""
from __future__ import annotations

import argparse
import json
import re
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import activity
from .checkpoints import Checkpoints
from .codemap import CodeMap
from .feedback import check

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
    def __init__(self, root: Path):
        self.root = root
        self.cm = CodeMap(root)
        self.cps = Checkpoints(root)

    def state(self, since: int) -> dict:
        everything = activity.read(self.root)
        cps = self.cps.list()
        latest = cps[-1]["id"] if cps else None
        return {
            "project": self.root.name,
            "path": str(self.root),
            "entries": [e for e in everything if e["n"] >= since][-500:],
            "total": len(everything),
            "stats": {
                "calls": sum(1 for e in everything if e.get("by", "ai") == "ai"),
                "edits": sum(1 for e in everything if e["tool"] in EDIT_TOOLS
                             and not e.get("result_head", "").startswith("ERROR")),
                "refused": sum(1 for e in everything if e.get("result_head", "").startswith("ERROR")),
                "files": len(self.cm.python_files()),
            },
            "last_check": last_check(everything),
            "checkpoints": cps,
            "changes": self.cps.changes(latest) if latest else None,
            "changes_since": latest,
        }

    def run_check(self) -> str:
        t = time.perf_counter()
        result = check(self.cm)
        activity.write(self.root, "check", {}, result, int((time.perf_counter() - t) * 1000), by="human")
        return result

    def restore(self, cp_id: str) -> str:
        r = self.cps.restore(cp_id)
        msg = (f"Already identical to {cp_id}." if r["safety_checkpoint"] is None else
               f"Restored to {cp_id} (undo: {r['safety_checkpoint']}). "
               f"modified {r['modified']}, re-created {r['deleted']}, removed {r['added']}")
        activity.write(self.root, "restore", {"checkpoint_id": cp_id}, msg, 0, by="human")
        return msg

    def checkpoint(self, label: str) -> str:
        cp_id = self.cps.create(label)
        msg = f"Checkpoint {cp_id} saved."
        activity.write(self.root, "checkpoint", {"label": label}, msg, 0, by="human")
        return msg


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


def main():
    ap = argparse.ArgumentParser(description="Mimir dashboard")
    ap.add_argument("project", nargs="?", default=".")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    app = App(Path(args.project).resolve())
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(app, args.port))
    url = f"http://127.0.0.1:{args.port}"
    print(f"Mimir dashboard for {app.root}\n  {url}   (Ctrl+C to stop)")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
