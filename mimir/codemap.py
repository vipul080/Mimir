"""Code map: understands a Python project as a structure (modules, classes,
functions, calls) instead of as plain text.

Everything here is built on Python's own `ast` module, so it needs no extra
dependencies. Results are cached per file and refreshed when a file changes.
"""
from __future__ import annotations

import ast
import os
from dataclasses import dataclass, field
from pathlib import Path

SKIP_DIRS = {
    ".git", ".venv", "venv", "env", "__pycache__", ".mimir", "node_modules",
    "site-packages", ".pytest_cache", ".mypy_cache", "build", "dist", ".tox",
}


@dataclass
class Symbol:
    name: str          # short name, e.g. "apply_discount"
    qualname: str      # e.g. "Cart.apply_discount"
    kind: str          # "class" | "function" | "method"
    file: str          # path relative to project root, forward slashes
    start: int         # first line (including decorators), 1-based
    end: int           # last line, 1-based
    col: int           # indentation column of the def/class line
    signature: str
    doc: str = ""      # first line of the docstring


@dataclass
class Call:
    caller: str        # qualname of the enclosing function ("<module>" at top level)
    callee: str        # short name being called
    file: str
    line: int
    text: str          # the source line, stripped


@dataclass
class FileInfo:
    mtime: float
    lines: list[str]
    symbols: list[Symbol] = field(default_factory=list)
    calls: list[Call] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    error: str | None = None


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
        self.rel = rel
        self.lines = lines
        self.stack: list[tuple[str, str]] = []  # (name, kind)
        self.symbols: list[Symbol] = []
        self.calls: list[Call] = []
        self.imports: list[str] = []

    def _qual(self, name: str) -> str:
        return ".".join([n for n, _ in self.stack] + [name])

    def _add(self, node, kind: str):
        start = min([node.lineno] + [d.lineno for d in node.decorator_list])
        self.symbols.append(Symbol(
            name=node.name, qualname=self._qual(node.name), kind=kind,
            file=self.rel, start=start, end=node.end_lineno, col=node.col_offset,
            signature=_signature(node), doc=_doc_line(node),
        ))

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
            self.calls.append(Call(caller, name, self.rel, node.lineno, text))
        self.generic_visit(node)

    def visit_Import(self, node):
        self.imports.extend(a.name for a in node.names)

    def visit_ImportFrom(self, node):
        mod = "." * node.level + (node.module or "")
        self.imports.append(mod)


class CodeMap:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self._cache: dict[str, FileInfo] = {}

    # ---------- indexing ----------
    def rel(self, path: str | Path) -> str:
        p = Path(path)
        if not p.is_absolute():
            p = self.root / p
        return p.resolve().relative_to(self.root).as_posix()

    def python_files(self) -> list[str]:
        out = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
            for f in sorted(filenames):
                if f.endswith(".py"):
                    out.append(Path(dirpath, f).relative_to(self.root).as_posix())
        return out

    def file_info(self, rel: str) -> FileInfo:
        path = self.root / rel
        mtime = path.stat().st_mtime
        cached = self._cache.get(rel)
        if cached and cached.mtime == mtime:
            return cached
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        info = FileInfo(mtime=mtime, lines=lines)
        try:
            tree = ast.parse(text, filename=rel)
            v = _Visitor(rel, lines)
            v.visit(tree)
            info.symbols, info.calls, info.imports = v.symbols, v.calls, v.imports
        except SyntaxError as e:
            info.error = f"SyntaxError line {e.lineno}: {e.msg}"
        self._cache[rel] = info
        return info

    def all_symbols(self) -> list[Symbol]:
        return [s for f in self.python_files() for s in self.file_info(f).symbols]

    def all_calls(self) -> list[Call]:
        return [c for f in self.python_files() for c in self.file_info(f).calls]

    # ---------- queries ----------
    def find(self, name: str) -> list[Symbol]:
        """Find symbols by 'name', 'Class.method', or 'path/file.py:name'."""
        file_filter = None
        if ":" in name and name.split(":", 1)[0].endswith(".py"):
            file_filter, name = name.split(":", 1)
            file_filter = file_filter.replace("\\", "/")
        hits = []
        for s in self.all_symbols():
            if file_filter and not s.file.endswith(file_filter):
                continue
            if s.qualname == name or ("." not in name and s.name == name):
                hits.append(s)
        return hits

    def repo_map(self) -> str:
        """One compact line per file: its top-level classes and functions."""
        out = [f"Project: {self.root.name}  ({len(self.python_files())} Python files)"]
        for rel in self.python_files():
            info = self.file_info(rel)
            if info.error:
                out.append(f"{rel}  !! {info.error}")
                continue
            parts = []
            for s in info.symbols:
                if s.kind == "function" and "." not in s.qualname:
                    parts.append(f"{s.name}()")
                elif s.kind == "class":
                    methods = [m.name for m in info.symbols
                               if m.kind == "method" and m.qualname.rsplit(".", 1)[0] == s.qualname]
                    parts.append(f"{s.name}[{', '.join(methods)}]" if methods else s.name)
            out.append(f"{rel} ({len(info.lines)} lines): {', '.join(parts) or '-'}")
        return "\n".join(out)

    def outline(self, file: str) -> str:
        """Signatures and docstrings of a file, bodies hidden."""
        rel = self.rel(file)
        info = self.file_info(rel)
        out = [f"{rel} ({len(info.lines)} lines)"]
        if info.error:
            out.append(f"!! {info.error}")
            return "\n".join(out)
        if info.imports:
            out.append("imports: " + ", ".join(dict.fromkeys(info.imports)))
        for s in info.symbols:
            depth = s.qualname.count(".")
            line = f"{'  ' * depth}L{s.start}-{s.end}  {s.signature}"
            if s.doc:
                line += f"   # {s.doc}"
            out.append(line)
        return "\n".join(out)

    def source(self, sym: Symbol) -> str:
        info = self.file_info(sym.file)
        width = len(str(sym.end))
        body = [f"{str(i).rjust(width)}| {info.lines[i - 1]}" for i in range(sym.start, sym.end + 1)]
        return f"# {sym.file}  L{sym.start}-{sym.end}  ({sym.kind} {sym.qualname})\n" + "\n".join(body)

    def callers(self, name: str) -> list[Call]:
        short = name.rsplit(".", 1)[-1].split(":")[-1]
        return [c for c in self.all_calls() if c.callee == short]
