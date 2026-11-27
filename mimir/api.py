"""The single set of operations behind every way of using Mimir: the MCP
server, the command line and the dashboard all call these methods, so they
always behave the same. Every call is written to the activity log.

Mimir never contacts an AI provider and never reads credentials. The AI
calls Mimir, not the other way round."""
from __future__ import annotations

import time
from pathlib import Path

from . import activity
from .checkpoints import Checkpoints
from .codemap import CodeMap
from .edits import EditError, replace_symbol as _replace_symbol
from .feedback import check as _check

GUIDE = """Mimir gives you a structural view of the project{where}.
Prefer it over reading whole files or searching text:
1. repo_map            see the project's shape (files, classes, methods)
2. outline FILE        a file's signatures without bodies
3. get_symbol NAME     one function/method/class with line numbers
                       NAME: 'func', 'Class.method', 'path/File.java:Class.method',
                       add '@LINE' to pick one overload ('Cart.add@27')
4. who_calls NAME      every call site, before changing behaviour or a signature
5. checkpoint LABEL    save the project before a risky change; restore ID to undo,
                       list_checkpoints to see them, diff_since ID to review changes
6. replace_symbol      rewrite a whole function/class by name; refuses edits
                       that break syntax and returns related test results
7. check [FILES]       syntax, lint and related tests after any other edit
Supported languages: Python, Java."""


class Mimir:
    def __init__(self, root: str | Path, actor: str = "ai"):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise NotADirectoryError(f"Project folder not found: {self.root}")
        self.actor = actor
        self.cm = CodeMap(self.root)
        self.cps = Checkpoints(self.root)

    def _logged(self, tool: str, args: dict, fn) -> str:
        t = time.perf_counter()
        try:
            result = fn()
        except (EditError, ValueError, FileNotFoundError, NotADirectoryError) as e:
            result = f"ERROR: {e}"
        activity.write(self.root, tool, args, result, int((time.perf_counter() - t) * 1000), by=self.actor)
        return result

    def guide(self) -> str:
        return GUIDE.format(where=f" at {self.root}")

    def repo_map(self) -> str:
        return self._logged("repo_map", {}, self.cm.repo_map)

    def outline(self, file: str) -> str:
        return self._logged("outline", {"file": file}, lambda: self.cm.outline(file))

    def get_symbol(self, name: str) -> str:
        def run():
            hits = self.cm.find(name)
            if not hits:
                return f"No symbol named '{name}'. Try repo_map or outline FILE."
            return "\n\n".join(self.cm.source(h) for h in hits)
        return self._logged("get_symbol", {"name": name}, run)

    def who_calls(self, name: str) -> str:
        def run():
            calls = self.cm.callers(name)
            if not calls:
                return f"No calls to '{name}' found."
            return "\n".join([f"{len(calls)} call(s) to '{name}' (matched by name):"] +
                             [f"  {c.file}:{c.line}  in {c.caller}  |  {c.text}" for c in calls])
        return self._logged("who_calls", {"name": name}, run)

    def replace_symbol(self, name: str, new_source: str) -> str:
        def run():
            rel = _replace_symbol(self.cm, name, new_source)
            return f"Replaced {name} in {rel}.\n" + _check(self.cm, [rel])
        return self._logged("replace_symbol", {"name": name, "new_source": new_source}, run)

    def check(self, files: list[str] | None = None) -> str:
        return self._logged("check", {"files": files} if files else {}, lambda: _check(self.cm, files or None))

    def checkpoint(self, label: str = "") -> str:
        return self._logged("checkpoint", {"label": label}, lambda: f"Checkpoint {self.cps.create(label)} saved.")

    def list_checkpoints(self) -> str:
        def run():
            items = self.cps.list()
            if not items:
                return "No checkpoints yet."
            return "\n".join(f"{c['id']}  {c['time']}  {c['files']} files  {c['label']}" for c in items)
        return self._logged("list_checkpoints", {}, run)

    def diff_since(self, checkpoint_id: str) -> str:
        return self._logged("diff_since", {"checkpoint_id": checkpoint_id}, lambda: self.cps.diff(checkpoint_id))

    def restore(self, checkpoint_id: str) -> str:
        def run():
            r = self.cps.restore(checkpoint_id)
            if r["safety_checkpoint"] is None:
                return f"Already identical to {checkpoint_id}; nothing to do."
            return (f"Restored to {checkpoint_id} (undo with restore {r['safety_checkpoint']}).\n"
                    f"modified: {r['modified']}\nre-created: {r['deleted']}\nremoved: {r['added']}")
        return self._logged("restore", {"checkpoint_id": checkpoint_id}, run)
