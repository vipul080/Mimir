"""Code map: understands a project as a structure (files, classes, functions,
calls) instead of as plain text. Each language is handled by a backend in
mimir/lang; results are cached per file and refreshed when a file changes."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .lang import BACKENDS, backend_for
from .model import Call, Symbol

SKIP_DIRS = {".git", ".mimir", "node_modules", "build", "dist"}
for _b in BACKENDS:
    SKIP_DIRS |= _b.skip_dirs


def _compact_imports(imports: list[str]) -> str:
    """Group imports that share a package: a.b.{C, D} instead of a.b.C, a.b.D."""
    groups: dict[str, list[str]] = {}
    for imp in dict.fromkeys(imports):
        pkg, _, name = imp.rpartition(".")
        groups.setdefault(pkg, []).append(name or imp)
    parts = []
    for pkg, names in groups.items():
        if not pkg:
            parts.extend(names)
        elif len(names) == 1:
            parts.append(f"{pkg}.{names[0]}")
        else:
            parts.append(f"{pkg}.{{{', '.join(names)}}}")
    return ", ".join(parts)


@dataclass
class FileInfo:
    mtime: float
    lines: list[str]
    symbols: list[Symbol] = field(default_factory=list)
    calls: list[Call] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    error: str | None = None


class CodeMap:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self._cache: dict[str, FileInfo] = {}

    # ---------- indexing ----------
    def rel(self, path: str | Path) -> str:
        p = Path(path)
        if not p.is_absolute():
            p = self.root / p
        p = p.resolve()
        try:
            return p.relative_to(self.root).as_posix()
        except ValueError:
            raise ValueError(f"{path} is outside the project folder") from None

    def source_files(self) -> list[str]:
        out = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
            for f in sorted(filenames):
                if backend_for(f):
                    out.append(Path(dirpath, f).relative_to(self.root).as_posix())
        return out

    def files(self, backend) -> list[str]:
        return [f for f in self.source_files() if backend_for(f) is backend]

    def languages(self) -> list:
        present = {backend_for(f) for f in self.source_files()}
        return [b for b in BACKENDS if b in present]

    def file_info(self, rel: str) -> FileInfo:
        path = self.root / rel
        mtime = path.stat().st_mtime
        cached = self._cache.get(rel)
        if cached and cached.mtime == mtime:
            return cached
        text = path.read_text(encoding="utf-8", errors="replace")
        info = FileInfo(mtime=mtime, lines=text.splitlines())
        backend = backend_for(rel)
        if backend:
            parsed = backend.parse(rel, text)
            info.symbols, info.calls, info.imports, info.error = \
                parsed.symbols, parsed.calls, parsed.imports, parsed.error
        self._cache[rel] = info
        return info

    def all_symbols(self) -> list[Symbol]:
        return [s for f in self.source_files() for s in self.file_info(f).symbols]

    def all_calls(self) -> list[Call]:
        return [c for f in self.source_files() for c in self.file_info(f).calls]

    # ---------- queries ----------
    def find(self, name: str) -> list[Symbol]:
        """Find symbols by 'name', 'Class.method', 'path/File.ext:name',
        optionally with '@line' to pick one overload, e.g. 'Cart.add@27'."""
        line = None
        if "@" in name and name.rsplit("@", 1)[1].isdigit():
            name, at = name.rsplit("@", 1)
            line = int(at)
        file_filter = None
        if ":" in name and backend_for(name.split(":", 1)[0]):
            file_filter, name = name.split(":", 1)
            file_filter = file_filter.replace("\\", "/")
        hits = []
        for s in self.all_symbols():
            if file_filter and not s.file.endswith(file_filter):
                continue
            if line is not None and s.start != line:
                continue
            if s.qualname == name or ("." not in name and s.name == name):
                hits.append(s)
        return hits

    def repo_map(self) -> str:
        """One compact line per file: its classes (with methods) and top-level functions."""
        files = self.source_files()
        langs = ", ".join(b.name for b in self.languages()) or "none"
        out = [f"Project: {self.root.name}  ({len(files)} source files; languages: {langs})"]
        for rel in files:
            info = self.file_info(rel)
            if info.error:
                out.append(f"{rel}  !! {info.error}")
                continue
            parts = []
            for s in info.symbols:
                if s.kind == "function" and "." not in s.qualname:
                    parts.append(f"{s.name}()")
                elif s.kind == "class":
                    methods = list(dict.fromkeys(
                        m.name for m in info.symbols
                        if m.kind == "method" and m.qualname.rsplit(".", 1)[0] == s.qualname))
                    parts.append(f"{s.qualname}[{', '.join(methods)}]" if methods else s.qualname)
            out.append(f"{rel} ({len(info.lines)} lines): {', '.join(parts) or '-'}")
        return "\n".join(out)

    def outline(self, file: str) -> str:
        """Signatures and doc lines of a file, bodies hidden."""
        rel = self.rel(file)
        if not (self.root / rel).is_file():
            raise FileNotFoundError(f"No file {rel}")
        info = self.file_info(rel)
        out = [f"{rel} ({len(info.lines)} lines)"]
        if info.error:
            out.append(f"!! {info.error}")
        if info.imports:
            out.append("imports: " + _compact_imports(info.imports))
        for s in info.symbols:
            line = f"{'  ' * s.qualname.count('.')}L{s.start}-{s.end}  {s.signature}"
            if s.doc:
                line += f"   // {s.doc}" if s.file.endswith(".java") else f"   # {s.doc}"
            out.append(line)
        return "\n".join(out)

    def source(self, sym: Symbol) -> str:
        info = self.file_info(sym.file)
        width = len(str(sym.end))
        body = [f"{str(i).rjust(width)}| {info.lines[i - 1]}" for i in range(sym.start, sym.end + 1)]
        return f"# {sym.file}  L{sym.start}-{sym.end}  ({sym.kind} {sym.qualname})\n" + "\n".join(body)

    def callers(self, name: str) -> list[Call]:
        short = name.split("@")[0].rsplit(".", 1)[-1].split(":")[-1]
        return [c for c in self.all_calls() if c.callee == short]
