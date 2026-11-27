"""Shared activity log: one JSON object per line in <project>/.mimir/activity.jsonl.
The MCP server writes what the AI does; the dashboard writes what the human does."""
from __future__ import annotations

import json
import time
from pathlib import Path


def log_path(root: Path) -> Path:
    return root / ".mimir" / "activity.jsonl"


def write(root: Path, tool: str, args: dict, result: str, ms: int, by: str = "ai") -> None:
    try:
        path = log_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "by": by, "tool": tool, "args": args,
                 "ms": ms, "result_chars": len(result), "result_head": result[:600]}
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def read(root: Path, since: int = 0) -> list[dict]:
    """Entries from line number `since` onward; each gets its line number as 'n'."""
    path = log_path(root)
    if not path.exists():
        return []
    out = []
    with path.open(encoding="utf-8") as f:
        for n, line in enumerate(f):
            if n < since:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            entry["n"] = n
            out.append(entry)
    return out
