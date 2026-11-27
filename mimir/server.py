"""Mimir: an IDE whose only user is an AI. Exposed as an MCP server.

Run:  python -m mimir.server <project-folder>
(or set MIMIR_ROOT). Defaults to the current folder.
"""
from __future__ import annotations

import functools
import os
import sys
import time
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from . import activity
from .checkpoints import Checkpoints
from .codemap import CodeMap
from .edits import EditError, replace_symbol as _replace_symbol
from .feedback import check as _check

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("MIMIR_ROOT", ".")).resolve()
cm = CodeMap(ROOT)
cps = Checkpoints(ROOT)

INSTRUCTIONS = f"""Mimir gives you a structural view of the Python project at {ROOT}.
Prefer these tools over reading whole files or grepping:
1. repo_map() first to see the project's shape.
2. outline(file) to see a file's signatures without bodies.
3. get_symbol(name) to read just one function/class (with line numbers).
4. who_calls(name) before changing a function's behaviour or signature.
5. checkpoint(label) before a risky change; restore(id) if it goes wrong.
6. replace_symbol(name, new_source) to rewrite a function/class; it refuses
   edits that break syntax and returns lint + related test results.
7. check() after any other edit for syntax, lint and test results."""

mcp = MCPServer("mimir", instructions=INSTRUCTIONS)


def logged(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        t = time.perf_counter()
        try:
            result = fn(*args, **kwargs)
        except (EditError, ValueError, FileNotFoundError) as e:
            result = f"ERROR: {e}"
        activity.write(ROOT, fn.__name__, kwargs, result, int((time.perf_counter() - t) * 1000))
        return result
    return wrapper


@mcp.tool()
@logged
def repo_map() -> str:
    """Compact map of the whole project: every Python file with its classes
    (and their methods) and top-level functions. Start here."""
    return cm.repo_map()


@mcp.tool()
@logged
def outline(file: str) -> str:
    """Signatures, docstrings and line ranges for every class/function in one
    file, with bodies hidden. Much cheaper than reading the file."""
    return cm.outline(file)


@mcp.tool()
@logged
def get_symbol(name: str) -> str:
    """Source of one function, method or class, with line numbers.
    name: 'func', 'Class', 'Class.method', or 'path/file.py:Class.method'."""
    hits = cm.find(name)
    if not hits:
        return f"No symbol named '{name}'. Try repo_map() or outline(file)."
    return "\n\n".join(cm.source(h) for h in hits)


@mcp.tool()
@logged
def who_calls(name: str) -> str:
    """Every call site of a function/method across the project, with the
    calling function and the line. Matched by name, so same-named methods on
    different classes are listed together."""
    calls = cm.callers(name)
    if not calls:
        return f"No calls to '{name}' found."
    lines = [f"{len(calls)} call(s) to '{name}':"]
    lines += [f"  {c.file}:{c.line}  in {c.caller}  |  {c.text}" for c in calls]
    return "\n".join(lines)


@mcp.tool()
@logged
def replace_symbol(name: str, new_source: str) -> str:
    """Replace a whole function/method/class definition with new_source
    (include the def/class line and any decorators; indentation is fixed for
    you). Refused if it would break syntax. Returns check results for the file."""
    rel = _replace_symbol(cm, name, new_source)
    return f"Replaced {name} in {rel}.\n" + _check(cm, [rel])


@mcp.tool()
@logged
def check(files: list[str] | None = None) -> str:
    """Syntax check, lint (pyflakes) and tests. With files: only those files
    and the tests that import them. Without: the whole project and full suite."""
    return _check(cm, files)


@mcp.tool()
@logged
def checkpoint(label: str = "") -> str:
    """Save a snapshot of the whole project. Returns its id for restore()."""
    cp_id = cps.create(label)
    return f"Checkpoint {cp_id} saved."


@mcp.tool()
@logged
def list_checkpoints() -> str:
    """All saved checkpoints, oldest first."""
    items = cps.list()
    if not items:
        return "No checkpoints yet."
    return "\n".join(f"{c['id']}  {c['time']}  {c['files']} files  {c['label']}" for c in items)


@mcp.tool()
@logged
def diff_since(checkpoint_id: str) -> str:
    """Unified diff of everything that changed since a checkpoint."""
    return cps.diff(checkpoint_id)


@mcp.tool()
@logged
def restore(checkpoint_id: str) -> str:
    """Roll the project back to a checkpoint. Files added since are removed.
    A safety checkpoint is taken first, so a restore can itself be undone."""
    r = cps.restore(checkpoint_id)
    if r["safety_checkpoint"] is None:
        return f"Already identical to {checkpoint_id}; nothing to do."
    return (f"Restored to {checkpoint_id} (undo with restore('{r['safety_checkpoint']}')).\n"
            f"modified: {r['modified']}\nre-created: {r['deleted']}\nremoved: {r['added']}")


def main():
    mcp.run("stdio")


if __name__ == "__main__":
    main()
