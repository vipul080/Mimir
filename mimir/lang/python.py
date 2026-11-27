"""Python backend: parsing with the built-in `ast` module, lint with pyflakes,
tests with pytest."""
from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path

from ..model import Call, CheckResult, Parsed, Symbol
from .common import run, truncate


def _signature(node: ast.AST) -> str:
    if isinstance(node, ast.ClassDef):
        bases = ", ".join(ast.unparse(b) for b in node.bases)
        return f"class {node.name}({bases})" if bases else f"class {node.name}"
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    sig = f"{prefix} {node.name}({ast.unparse(node.args)})"
    if node.returns is not None:
        sig += f" -> {ast.unparse(node.returns)}"
    return sig


def _doc_line(node: ast.AST) -> str:
    doc = ast.get_docstring(node)
    return doc.strip().splitlines()[0] if doc else ""


def _callee_name(call: ast.Call) -> str | None:
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


class _Visitor(ast.NodeVisitor):
    def __init__(self, rel: str, lines: list[str]):
        self.rel, self.lines = rel, lines
        self.stack: list[tuple[str, str]] = []  # (name, kind)
        self.out = Parsed()

    def _qual(self, name: str) -> str:
        return ".".join([n for n, _ in self.stack] + [name])

    def _add(self, node, kind: str):
        start = min([node.lineno] + [d.lineno for d in node.decorator_list])
        self.out.symbols.append(Symbol(
            name=node.name, qualname=self._qual(node.name), kind=kind, file=self.rel,
            start=start, end=node.end_lineno, col=node.col_offset,
            signature=_signature(node), doc=_doc_line(node)))

    def visit_ClassDef(self, node):
        self._add(node, "class")
        self.stack.append((node.name, "class"))
        self.generic_visit(node)
        self.stack.pop()

    def _visit_func(self, node):
        in_class = bool(self.stack) and self.stack[-1][1] == "class"
        self._add(node, "method" if in_class else "function")
        self.stack.append((node.name, "function"))
        self.generic_visit(node)
        self.stack.pop()

    visit_FunctionDef = _visit_func
    visit_AsyncFunctionDef = _visit_func

    def visit_Call(self, node):
        name = _callee_name(node)
        if name:
            caller = ".".join(n for n, _ in self.stack) or "<module>"
            text = self.lines[node.lineno - 1].strip() if node.lineno <= len(self.lines) else ""
            self.out.calls.append(Call(caller, name, self.rel, node.lineno, text))
        self.generic_visit(node)

    def visit_Import(self, node):
        self.out.imports.extend(a.name for a in node.names)

    def visit_ImportFrom(self, node):
        self.out.imports.append("." * node.level + (node.module or ""))


def project_python(root: Path) -> str:
    """Interpreter for the project's tests: MIMIR_PYTHON, else the project's
    own virtualenv, else the one running Mimir."""
    env = os.environ.get("MIMIR_PYTHON")
    if env:
        return env
    for cand in (root / ".venv" / "Scripts" / "python.exe", root / ".venv" / "bin" / "python",
                 root / "venv" / "Scripts" / "python.exe", root / "venv" / "bin" / "python"):
        if cand.exists():
            return str(cand)
    return sys.executable


def _summarise_pytest(out: str) -> str:
    lines = out.splitlines()
    summary = next((ln for ln in reversed(lines) if re.search(r"\d+ (passed|failed|error)", ln)), "")
    if " failed" not in summary and " error" not in summary:
        return summary.strip("= ").strip()
    start = next((i for i, ln in enumerate(lines) if re.match(r"=+ (FAILURES|ERRORS) =+", ln)), 0)
    return truncate("\n".join(lines[start:]))


class PythonBackend:
    name = "python"
    extensions = (".py",)
    skip_dirs = {".venv", "venv", "env", "__pycache__", ".pytest_cache", ".mypy_cache", ".tox",
                 "site-packages"}

    def parse(self, rel: str, text: str) -> Parsed:
        try:
            tree = ast.parse(text, filename=rel)
        except SyntaxError as e:
            return Parsed(error=f"SyntaxError line {e.lineno}: {e.msg}")
        v = _Visitor(rel, text.splitlines())
        v.visit(tree)
        return v.out

    def syntax_error(self, text: str) -> str | None:
        try:
            ast.parse(text)
            return None
        except SyntaxError as e:
            return f"line {e.lineno}: {e.msg}"

    def is_test(self, rel: str) -> bool:
        n = Path(rel).name
        return n.startswith("test_") or n.endswith("_test.py")

    def related_tests(self, cm, changed: list[str]) -> list[str]:
        changed_mods = {Path(f).stem for f in changed}
        picked = []
        for t in (f for f in cm.files(self) if self.is_test(f)):
            imported = {p for imp in cm.file_info(t).imports for p in imp.strip(".").split(".")}
            if t in changed or imported & changed_mods:
                picked.append(t)
        return picked

    def check(self, cm, files: list[str] | None, run_tests: bool = True) -> list[CheckResult]:
        targets = files if files is not None else cm.files(self)
        if not targets:
            return []
        errs = [f"{rel}:{e}" for rel in targets
                if (e := self.syntax_error((cm.root / rel).read_text(encoding="utf-8", errors="replace")))]
        if errs:
            return [CheckResult("SYNTAX (python)", False, "  " + "\n  ".join(errs), fatal=True)]
        results = [CheckResult("SYNTAX (python)", True)]

        _, out = run([sys.executable, "-m", "pyflakes", *targets], cm.root)
        problems = [ln.replace("\\", "/") for ln in out.splitlines() if ln.strip()]
        results.append(CheckResult("LINT (pyflakes)", not problems,
                                   "  " + "\n  ".join(problems[:30]) if problems else ""))

        if run_tests:
            tests = self.related_tests(cm, targets) if files is not None else []
            if files is not None and not tests:
                results.append(CheckResult("TESTS (pytest)", True,
                                           "no tests import the changed files; run check() with no files for the full suite"))
            else:
                scope = f"{len(tests)} related file(s)" if tests else "full suite"
                cmd = [project_python(cm.root), "-m", "pytest", "-q", "--tb=short", "-p", "no:cacheprovider", *tests]
                code, out = run(cmd, cm.root)
                if code == 5:
                    results.append(CheckResult(f"TESTS (pytest, {scope})", True, "no tests collected"))
                else:
                    results.append(CheckResult(f"TESTS (pytest, {scope})", code == 0, _summarise_pytest(out)))
        return results
