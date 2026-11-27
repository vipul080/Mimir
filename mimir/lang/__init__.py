"""Language backends. Each backend knows how to parse one language into
symbols and calls, and how to check (lint/test) a project in that language.

To add a language: write a module with a class that has the same attributes
and methods as PythonBackend, and add it to BACKENDS."""
from __future__ import annotations

from pathlib import Path

from .java import JavaBackend
from .python import PythonBackend

BACKENDS = [PythonBackend(), JavaBackend()]
_BY_EXT = {ext: b for b in BACKENDS for ext in b.extensions}


def backend_for(path: str | Path):
    return _BY_EXT.get(Path(path).suffix.lower())


def supported_extensions() -> set[str]:
    return set(_BY_EXT)
