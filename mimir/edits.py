"""Structural edits: change code by naming the function/class to replace,
not by matching exact text. An edit that would break the file's syntax is
refused before anything is written."""
from __future__ import annotations

import textwrap

from .codemap import CodeMap
from .lang import backend_for


class EditError(Exception):
    pass


def replace_symbol(cm: CodeMap, name: str, new_source: str) -> str:
    """Replace the full definition of `name` (decorators/annotations included)
    with `new_source`. Indentation is adjusted automatically. Returns the file path."""
    hits = cm.find(name)
    if not hits:
        raise EditError(f"No symbol named '{name}'.")
    if len(hits) > 1:
        options = ", ".join(f"{h.file}:{h.qualname}@{h.start}" for h in hits)
        raise EditError(f"'{name}' matches {len(hits)} symbols: {options}. "
                        f"Pick one with 'file:Qual.name' or 'Qual.name@line'.")
    sym = hits[0]
    backend = backend_for(sym.file)

    info = cm.file_info(sym.file)
    new_block = textwrap.indent(textwrap.dedent(new_source).strip("\n"), " " * sym.col).splitlines()
    # the symbol may start mid-line (e.g. Java annotation on the same line); keep what precedes it
    first = info.lines[sym.start - 1]
    prefix = first[:sym.col] if first[:sym.col].strip() else ""
    if prefix and new_block:
        new_block[0] = prefix + new_block[0].lstrip()
    new_lines = info.lines[: sym.start - 1] + new_block + info.lines[sym.end:]
    new_text = "\n".join(new_lines) + "\n"

    before = backend.syntax_error("\n".join(info.lines))
    after = backend.syntax_error(new_text)
    if after and not before:
        raise EditError(f"Rejected: the edit would cause a syntax error at {after}. Nothing was written.")

    path = cm.root / sym.file
    eol = "\r\n" if b"\r\n" in path.read_bytes() else "\n"  # keep the file's line endings
    with open(path, "w", encoding="utf-8", newline=eol) as f:
        f.write(new_text)
    return sym.file
