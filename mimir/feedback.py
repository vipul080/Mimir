"""Feedback loop: after a change, tell the AI in a few lines whether the code
still parses, whether the linter found real problems, and whether the
relevant tests pass. Each language backend does its own checks."""
from __future__ import annotations

from .codemap import CodeMap
from .lang import backend_for


def check(cm: CodeMap, files: list[str] | None = None, run_tests: bool = True) -> str:
    """Check `files` (and the tests related to them), or the whole project
    when `files` is None. Returns a short report starting with RESULT: ok|FAIL."""
    if files is not None:
        targets = [cm.rel(f) for f in files]
        unknown = [f for f in targets if not backend_for(f)]
        groups = {}
        for f in targets:
            if backend_for(f):
                groups.setdefault(backend_for(f), []).append(f)
    else:
        unknown = []
        groups = {b: None for b in cm.languages()}

    sections = []
    for backend, group in groups.items():
        sections += backend.check(cm, group, run_tests)
        if any(s.fatal for s in sections):
            break
    if not sections:
        sections_text = "nothing to check (no supported source files)"
        return f"RESULT: ok\n{sections_text}"

    ok = all(s.ok for s in sections)
    lines = [f"RESULT: {'ok' if ok else 'FAIL'}"] + [s.render() for s in sections]
    if unknown:
        lines.append(f"(not checked, unsupported file types: {', '.join(unknown)})")
    return "\n".join(lines)
