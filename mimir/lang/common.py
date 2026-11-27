"""Helpers shared by language backends."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

MAX_TEST_OUTPUT = 3000  # characters of failure detail returned to the AI


def run(cmd: list[str], cwd: Path, timeout: int = 120) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace",
                           shell=os.name == "nt" and cmd[0].lower().endswith((".cmd", ".bat")))
        return p.returncode, (p.stdout + p.stderr).strip()
    except subprocess.TimeoutExpired:
        return -1, f"timed out after {timeout}s"
    except FileNotFoundError as e:
        return -2, f"command not found: {e}"


def truncate(text: str, limit: int = MAX_TEST_OUTPUT) -> str:
    return text if len(text) <= limit else text[:limit] + "\n... (truncated)"
