"""Structural edits: change code by naming the function/class to replace,
not by matching exact text. An edit that would break the file's syntax is
refused before anything is written."""
from __future__ import annotations

import ast
import textwrap

from .codemap import CodeMap


class EditError(Exception):
    pass


def replace_symbol(cm: CodeMap, name: str, new_source: str) -> str:
    """Replace the full definition of `name` (decorators included) with
    `new_source`. Indentation is adjusted automatically. Returns the file path."""
    hits = cm.find(name)
    if not hits:
        raise EditError(f"No symbol named '{name}'.")
    if len(hits) > 1:
        options = ", ".join(f"{h.file}:{h.qualname}" for h in hits)
        raise EditError(f"'{name}' is ambiguous: {options}. Use 'file.py:Qual.name'.")
    sym = hits[0]

    info = cm.file_info(sym.file)
    new_block = textwrap.indent(textwrap.dedent(new_source).strip("\n"), " " * sym.col).splitlines()
    new_lines = info.lines[: sym.start - 1] + new_block + info.lines[sym.end:]
    new_text = "\n".join(new_lines) + "\n"
    try:
        ast.parse(new_text)
    except SyntaxError as e:
        raise EditError(f"Rejected: the edit would cause a SyntaxError at line {e.lineno}: {e.msg}. "
                        f"Nothing was written.") from None

    path = cm.root / sym.file
    eol = "\r\n" if b"\r\n" in path.read_bytes() else "\n"  # keep the file's line endings
    with open(path, "w", encoding="utf-8", newline=eol) as f:
        f.write(new_text)
    return sym.file
