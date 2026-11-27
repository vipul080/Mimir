"""Java backend: parsing with tree-sitter, tests with Maven or Gradle.

There is no separate Java linter: Maven/Gradle compile the code before
running tests, so compile errors show up in the TESTS section."""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

import tree_sitter_java
from tree_sitter import Language, Node, Parser

from ..model import Call, CheckResult, Parsed, Symbol
from .common import run, truncate

_PARSER = Parser(Language(tree_sitter_java.language()))

TYPE_DECLS = {"class_declaration", "interface_declaration", "enum_declaration",
              "record_declaration", "annotation_type_declaration"}
METHOD_DECLS = {"method_declaration", "constructor_declaration", "compact_constructor_declaration"}
BODY_TYPES = {"class_body", "interface_body", "enum_body", "annotation_type_body",
              "block", "constructor_body"}
TEST_TIMEOUT = 600


def _text(node: Node | None) -> str:
    return node.text.decode("utf-8", errors="replace") if node is not None else ""


def _javadoc(node: Node) -> str:
    prev = node.prev_named_sibling
    if prev is None or prev.type != "block_comment" or prev.end_point[0] < node.start_point[0] - 1:
        return ""
    raw = _text(prev)
    if not raw.startswith("/**"):
        return ""
    for line in raw[3:-2].splitlines():
        line = line.strip().lstrip("*").strip()
        if line and not line.startswith("@"):
            return line
    return ""


def _signature(node: Node, src: bytes) -> str:
    body = next((c for c in node.children if c.type in BODY_TYPES), None)
    end = body.start_byte if body is not None else node.end_byte
    sig = src[node.start_byte:end].decode("utf-8", errors="replace")
    return re.sub(r"\s+", " ", sig).strip().rstrip(";").strip()


def _first_error(node: Node) -> Node | None:
    if node.type == "ERROR" or node.is_missing:
        return node
    for child in node.children:
        if child.has_error or child.is_missing:
            found = _first_error(child)
            if found is not None:
                return found
    return None


class _Walker:
    def __init__(self, rel: str, src: bytes):
        self.rel, self.src = rel, src
        self.lines = src.decode("utf-8", errors="replace").splitlines()
        self.out = Parsed()

    def walk(self, node: Node, stack: list[str], in_method: bool):
        t = node.type
        if t in TYPE_DECLS or t in METHOD_DECLS:
            name = _text(node.child_by_field_name("name"))
            kind = "class" if t in TYPE_DECLS else ("method" if stack else "function")
            qual = ".".join(stack + [name])
            self.out.symbols.append(Symbol(
                name=name, qualname=qual, kind=kind, file=self.rel,
                start=node.start_point[0] + 1, end=node.end_point[0] + 1, col=node.start_point[1],
                signature=_signature(node, self.src), doc=_javadoc(node)))
            for c in node.children:
                self.walk(c, stack + [name], t in METHOD_DECLS)
            return
        if t == "method_invocation":
            self._call(node, _text(node.child_by_field_name("name")), stack)
        elif t == "object_creation_expression":
            type_name = _text(node.child_by_field_name("type"))
            self._call(node, re.sub(r"<.*", "", type_name).split(".")[-1], stack)
        elif t == "import_declaration":
            self.out.imports.append(_text(node).removeprefix("import").strip().rstrip(";").strip())
            return
        for c in node.children:
            self.walk(c, stack, in_method)

    def _call(self, node: Node, name: str, stack: list[str]):
        if not name:
            return
        line = node.start_point[0] + 1
        text = self.lines[line - 1].strip() if line <= len(self.lines) else ""
        self.out.calls.append(Call(".".join(stack) or "<module>", name, self.rel, line, text))


def _build_tool(root: Path) -> tuple[str, list[str]] | None:
    """('maven'|'gradle', base command) for the project, preferring its own wrapper."""
    win = os.name == "nt"
    if (root / "pom.xml").exists():
        env = os.environ.get("MIMIR_MAVEN")
        for cand in ([env] if env else []) + [str(root / ("mvnw.cmd" if win else "mvnw"))]:
            if cand and Path(cand).exists():
                return "maven", [cand]
        found = shutil.which("mvn")
        return ("maven", [found]) if found else None
    if (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
        wrapper = root / ("gradlew.bat" if win else "gradlew")
        if wrapper.exists():
            return "gradle", [str(wrapper)]
        found = shutil.which("gradle")
        return ("gradle", [found]) if found else None
    return None


_MAVEN_NOISE = re.compile(
    r"^\s*$|-> \[Help|\[Help \d|Re-run Maven|To see the full|For more information|Failed to execute goal"
    r"|^See |See dump files|<<< (FAILURE|ERROR)!|^Failures:\s*$|^Errors:\s*$|^COMPILATION ERROR")


def _summarise_maven(out: str) -> str:
    lines = out.splitlines()
    totals = [ln for ln in lines if "Tests run:" in ln and "Time elapsed" not in ln]
    errors = [ln[len("[ERROR] "):] for ln in lines if ln.startswith("[ERROR]")]
    errors = [ln for ln in errors if not _MAVEN_NOISE.search(ln)]
    if errors:
        # put the overall count last, like pytest does
        body = [ln for ln in errors if "Tests run:" not in ln]
        tail = [totals[-1].replace("[ERROR] ", "").strip()] if totals else []
        return truncate("\n".join(dict.fromkeys(body + tail)))
    return totals[-1].replace("[INFO] ", "").strip() if totals else "BUILD SUCCESS"


def _summarise_gradle(out: str) -> str:
    lines = out.splitlines()
    keep = [ln for ln in lines if "FAILED" in ln or ln.strip().startswith(("at ", "Caused by", "org.opentest4j"))
            or ": error:" in ln or "BUILD" in ln]
    return truncate("\n".join(keep[:60])) if keep else "BUILD SUCCESSFUL"


class JavaBackend:
    name = "java"
    extensions = (".java",)
    skip_dirs = {"target", ".gradle", ".idea", ".mvn"}

    def parse(self, rel: str, text: str) -> Parsed:
        src = text.encode("utf-8")
        tree = _PARSER.parse(src)
        w = _Walker(rel, src)
        w.walk(tree.root_node, [], False)
        err = self.syntax_error(text, tree)
        if err:
            w.out.error = f"SyntaxError {err}"
        return w.out

    def syntax_error(self, text: str, tree=None) -> str | None:
        tree = tree or _PARSER.parse(text.encode("utf-8"))
        if not tree.root_node.has_error:
            return None
        node = _first_error(tree.root_node) or tree.root_node
        what = f"missing '{node.type}'" if node.is_missing else "unexpected code"
        return f"line {node.start_point[0] + 1}: {what}"

    def is_test(self, rel: str) -> bool:
        n = Path(rel).stem
        return "src/test/" in rel or n.endswith(("Test", "Tests", "IT")) or n.startswith("Test")

    def related_tests(self, cm, changed: list[str]) -> list[str]:
        names = {Path(f).stem for f in changed if not self.is_test(f)}
        pattern = re.compile(r"\b(" + "|".join(map(re.escape, names)) + r")\b") if names else None
        picked = []
        for t in (f for f in cm.files(self) if self.is_test(f)):
            if t in changed or (pattern and pattern.search((cm.root / t).read_text(encoding="utf-8", errors="replace"))):
                picked.append(t)
        return picked

    def check(self, cm, files: list[str] | None, run_tests: bool = True) -> list[CheckResult]:
        targets = files if files is not None else cm.files(self)
        if not targets:
            return []
        errs = [f"{rel}:{e}" for rel in targets
                if (e := self.syntax_error((cm.root / rel).read_text(encoding="utf-8", errors="replace")))]
        if errs:
            return [CheckResult("SYNTAX (java)", False, "  " + "\n  ".join(errs), fatal=True)]
        results = [CheckResult("SYNTAX (java)", True)]
        if not run_tests:
            return results

        tool = _build_tool(cm.root)
        if tool is None:
            results.append(CheckResult("TESTS (java)", True,
                                       "skipped: no pom.xml/build.gradle with Maven or Gradle available "
                                       "(set MIMIR_MAVEN to a mvn executable)"))
            return results
        kind, cmd = tool
        tests = self.related_tests(cm, targets) if files is not None else []
        if files is not None and not tests:
            results.append(CheckResult(f"TESTS ({kind})", True,
                                       "no tests reference the changed classes; run check() with no files for the full suite"))
            return results
        classes = sorted({Path(t).stem for t in tests})
        scope = f"{len(classes)} related test class(es)" if classes else "full suite"
        if kind == "maven":
            cmd = cmd + ["-B", "test"]
            if classes:
                cmd += [f"-Dtest={','.join(classes)}", "-Dsurefire.failIfNoSpecifiedTests=false",
                        "-DfailIfNoTests=false"]
            code, out = run(cmd, cm.root, timeout=TEST_TIMEOUT)
            detail = _summarise_maven(out) if code >= 0 else out
        else:
            cmd = cmd + ["test", "--console=plain"]
            for c in classes:
                cmd += ["--tests", c]
            code, out = run(cmd, cm.root, timeout=TEST_TIMEOUT)
            detail = _summarise_gradle(out) if code >= 0 else out
        for prefix in ("/" + cm.root.as_posix(), cm.root.as_posix(), str(cm.root)):
            detail = detail.replace(prefix + "/", "").replace(prefix + "\\", "")
        results.append(CheckResult(f"TESTS ({kind}, {scope})", code == 0, detail))
        return results
