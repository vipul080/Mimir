"""Mimir is a tool the AI calls; it must never act like a 'harness' that
reuses someone's AI login. These tests fail if the code ever starts to
contact AI providers or read credential folders."""
import re
from pathlib import Path

from mimir.checkpoints import Checkpoints
from mimir.codemap import CodeMap

PKG = Path(__file__).parent.parent / "mimir"
SOURCES = {p: p.read_text(encoding="utf-8") for p in PKG.rglob("*.py")}

# outbound network clients Mimir must not use (it only *serves* on localhost)
FORBIDDEN_IMPORTS = re.compile(r"^\s*(import|from)\s+(requests|httpx|httpx2|aiohttp|urllib\.request|http\.client"
                               r"|socket|openai|anthropic|google\.generativeai|google\.genai)\b", re.M)
FORBIDDEN_TEXT = re.compile(r"googleapis\.com|generativelanguage|openai\.com|anthropic\.com|"
                            r"\.gemini[/\\]|\.codex[/\\]|\.claude[/\\]|oauth_creds|GEMINI_API_KEY|"
                            r"OPENAI_API_KEY|ANTHROPIC_API_KEY|GOOGLE_API_KEY", re.I)


def test_no_outbound_network_clients():
    bad = {p.name: m.group(0).strip() for p, src in SOURCES.items() if (m := FORBIDDEN_IMPORTS.search(src))}
    assert not bad, f"Mimir must not make outbound connections: {bad}"


def test_no_ai_provider_endpoints_or_credentials():
    bad = {p.name: m.group(0) for p, src in SOURCES.items() if (m := FORBIDDEN_TEXT.search(src))}
    assert not bad, f"Mimir must not reference AI provider APIs or credentials: {bad}"


def test_hidden_folders_are_never_read_or_copied(tmp_path):
    for d in (".gemini", ".codex", ".claude", ".env_secrets"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "oauth.py").write_text("TOKEN = 'secret'\n")
    (tmp_path / "app.py").write_text("def f():\n    return 1\n")
    assert CodeMap(tmp_path).source_files() == ["app.py"]
    cp = Checkpoints(tmp_path).create("t")
    copied = {p.relative_to(tmp_path / ".mimir" / "checkpoints" / cp / "files").as_posix()
              for p in (tmp_path / ".mimir" / "checkpoints" / cp / "files").rglob("*") if p.is_file()}
    assert copied == {"app.py"}
