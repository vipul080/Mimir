"""Feedback loop: after a change, tell the AI in a few lines whether the code
still parses, whether the linter found real problems, and whether the
relevant tests pass."""
from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

from .codemap import CodeMap

MAX_TEST_OUTPUT = 3000  # characters of pytest failure detail to return


def project_python(root: Path) -> str:
    """The interpreter that should run the project's tests: AIDE_PYTHON if set,
    else the project's own .venv, else the one running aide."""
    env = os.environ.get("AIDE_PYTHON")
    if env:
        return env
    for cand in (root / ".venv" / "Scripts" / "python.exe", root / ".venv" / "bin" / "python",
                 root / "venv" / "Scripts" / "python.exe", root / "venv" / "bin" / "python"):
        if cand.exists():
            return str(cand)
    return sys.executable


def _run(cmd: list[str], cwd: Path, timeout: int = 120) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        return p.returncode, (p.stdout + p.stderr).strip()
    except subprocess.TimeoutExpired:
        return -1, f"timed out after {timeout}s"


def syntax_errors(cm: CodeMap, files: list[str]) -> list[str]:
    errs = []
    for rel in files:
        try:
            ast.parse((cm.root / rel).read_text(encoding="utf-8", errors="replace"), filename=rel)
        except SyntaxError as e:
            errs.append(f"{rel}:{e.lineno}: {e.msg}")
    return errs


def lint(cm: CodeMap, files: list[str]) -> list[str]:
    """pyflakes finds real mistakes (undefined names, unused imports), not style."""
    if not files:
        return []
    _, out = _run([sys.executable, "-m", "pyflakes", *files], cm.root)
    return [ln.replace("\\", "/") for ln in out.splitlines() if ln.strip()]


def related_tests(cm: CodeMap, changed: list[str]) -> list[str]:
    """Test files that import any of the changed modules (or are themselves changed)."""
    tests = [f for f in cm.python_files()
             if Path(f).name.startswith("test_") or Path(f).name.endswith("_test.py")]
    changed_mods = {Path(f).stem for f in changed}
    picked = []
    for t in tests:
        if t in changed:
            picked.append(t)
            continue
        imported = {part for imp in cm.file_info(t).imports for part in imp.strip(".").split(".")}
        if imported & changed_mods:
            picked.append(t)
    return picked


def _summarise_pytest(out: str) -> str:
    lines = out.splitlines()
    summary = next((ln for ln in reversed(lines) if re.search(r"\d+ (passed|failed|error)", ln)), "")
    if " failed" not in summary and " error" not in summary:
        return summary.strip("= ").strip()
    # keep only the failure details, not the progress dots or headers
    start = next((i for i, ln in enumerate(lines) if re.match(r"=+ (FAILURES|ERRORS) =+", ln)), 0)
    detail = "\n".join(lines[start:])
    if len(detail) > MAX_TEST_OUTPUT:
        detail = detail[:MAX_TEST_OUTPUT] + "\n... (truncated)"
    return detail


def check(cm: CodeMap, files: list[str] | None = None, run_tests: bool = True) -> str:
    """Run syntax, lint and tests. `files` limits the check to what changed;
    omit it to check the whole project."""
    all_files = cm.python_files()
    targets = [cm.rel(f) for f in files] if files else all_files
    report = []
    ok = True

    errs = syntax_errors(cm, targets)
    if errs:
        ok = False
        report.append("SYNTAX: FAIL\n  " + "\n  ".join(errs))
        return "\n".join(["RESULT: FAIL"] + report)  # nothing else is meaningful yet
    report.append("SYNTAX: ok")

    problems = lint(cm, targets)
    if problems:
        ok = False
        report.append(f"LINT: {len(problems)} problem(s)\n  " + "\n  ".join(problems[:30]))
    else:
        report.append("LINT: ok")

    if run_tests:
        tests = related_tests(cm, targets) if files else []
        if files and not tests:
            report.append("TESTS: no tests import the changed files (run check() with no files for the full suite)")
        else:
            cmd = [project_python(cm.root), "-m", "pytest", "-q", "--tb=short", "-p", "no:cacheprovider", *tests]
            code, out = _run(cmd, cm.root)
            scope = f"{len(tests)} related file(s)" if tests else "full suite"
            if code == 0:
                report.append(f"TESTS ({scope}): ok - {_summarise_pytest(out)}")
            elif code == 5:
                report.append(f"TESTS ({scope}): no tests collected")
            else:
                ok = False
                report.append(f"TESTS ({scope}): FAIL\n{_summarise_pytest(out)}")

    return "\n".join([f"RESULT: {'ok' if ok else 'FAIL'}"] + report)
