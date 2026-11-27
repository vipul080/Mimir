"""Language-neutral data the code map is built from."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Symbol:
    name: str          # short name, e.g. "applyDiscount"
    qualname: str      # e.g. "Cart.total"
    kind: str          # "class" | "function" | "method"
    file: str          # path relative to project root, forward slashes
    start: int         # first line (including decorators/annotations), 1-based
    end: int           # last line, 1-based
    col: int           # indentation column of the first line
    signature: str
    doc: str = ""      # first line of the docstring / Javadoc


@dataclass
class Call:
    caller: str        # qualname of the enclosing function ("<module>" at top level)
    callee: str        # short name being called
    file: str
    line: int
    text: str          # the source line, stripped


@dataclass
class Parsed:
    symbols: list[Symbol] = field(default_factory=list)
    calls: list[Call] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    error: str | None = None   # first syntax error, if any


@dataclass
class CheckResult:
    """One section of a check report, e.g. 'LINT' or 'TESTS (maven)'."""
    name: str
    ok: bool
    detail: str = ""
    fatal: bool = False   # stop further checks (e.g. syntax errors)

    def render(self) -> str:
        head = f"{self.name}: {'ok' if self.ok else 'FAIL'}"
        if self.detail:
            sep = " - " if self.ok and "\n" not in self.detail else "\n"
            head += sep + self.detail
        return head
