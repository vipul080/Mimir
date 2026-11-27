# Mimir: an IDE for AI agents

Human IDEs are built around screens, mice and colours. AI coding agents
get none of that. They work through `grep`, "read whole file" and
"replace exact string". **Mimir** gives an agent the useful parts of an IDE
(code structure, safe edits, instant feedback, undo) as tools, and gives the
human a live dashboard to watch the agent work and step in.

In Norse myth, Mímir guards the well of wisdom and knows everything that
happens in the world. This one knows everything about a codebase and
shares it with the AI working on it.

- **Languages:** Python and Java (Maven or Gradle)
- **Works with:** Claude Code, Gemini CLI, OpenAI Codex CLI, Cursor, VS Code Copilot,
  and any other AI that supports [MCP](https://modelcontextprotocol.io) or can run terminal commands

## Agent tools

| Tool | What it replaces | What it does |
|---|---|---|
| `repo_map` | `ls -R` plus opening files | One line per file listing its classes, methods and functions |
| `outline FILE` | reading a whole file | Signatures, doc comments and line ranges, with bodies hidden |
| `get_symbol NAME` | reading a file, then searching it | Source of one function or class, with line numbers |
| `who_calls NAME` | `grep` | Every call site, with the calling function |
| `replace_symbol NAME` | exact-string find and replace | Rewrites a function or class by name, fixes indentation, **refuses edits that break syntax**, then runs the related tests |
| `check [FILES]` | running tools by hand | Syntax, lint and **only the tests related to the changed files**, summarised to the failures |
| `checkpoint` / `restore` / `diff_since` / `list_checkpoints` | git stash juggling | Snapshot the project, see what changed, and roll back. A restore can itself be undone |

Names can be `func`, `Class.method` or `path/File.java:Class.method`. Add
`@LINE` to pick one overloaded Java method, for example `Cart.add@28`.

| | Python | Java |
|---|---|---|
| Parsing | built-in `ast` | tree-sitter |
| Lint | pyflakes | compile errors, reported by the build |
| Tests | pytest | Maven or Gradle, found automatically (see below) |

For Java tests, Mimir looks for Maven or Gradle in this order:

1. `MIMIR_MAVEN`, if set
2. the project's own wrapper (`mvnw` / `gradlew`)
3. `mvn` / `gradle` on `PATH`
4. `MAVEN_HOME`, `M2_HOME` or `GRADLE_HOME`
5. the newest copy another project's wrapper already downloaded to `~/.m2/wrapper` or `~/.gradle/wrapper`

So a project without a wrapper still works if any other project on the machine has one.

## Safe to use with any AI

Mimir is a **tool the AI calls**, like a linter or a test runner. It is
**not a harness**, meaning a third-party app that takes your AI login and
uses it outside the official app. Some providers restrict accounts for
harness use.

- **No AI calls:** Mimir never contacts any AI provider and never makes outbound network connections.
- **No credentials:** it never reads API keys, login tokens or folders such as `~/.gemini`, `~/.codex` or `~/.claude`.
- **Official route only:** your AI tool stays the official client. Mimir connects through that tool's own supported MCP or terminal features.

[`tests/test_safety.py`](tests/test_safety.py) fails the build if any of
this ever changes. Always follow your AI provider's current terms; this
describes how Mimir works, not their policies.

## Setup

```powershell
git clone https://github.com/vipul080/Mimir
cd Mimir
uv venv --python 3.10 .venv
uv pip install --python .venv -e .
```

This gives you the `mimir` command at `.venv\Scripts\mimir.exe`. In the
examples below, replace `C:\path\to\Mimir` with where you cloned it and
`C:\path\to\project` with the project the AI should work on.

## Connect your AI

### Claude Code

```powershell
claude mcp add mimir -- C:\path\to\Mimir\.venv\Scripts\mimir.exe serve C:\path\to\project
```

### Gemini CLI

Add to `~/.gemini/settings.json` (or `.gemini/settings.json` in the project):

```json
{
  "mcpServers": {
    "mimir": {
      "command": "C:\\path\\to\\Mimir\\.venv\\Scripts\\mimir.exe",
      "args": ["serve", "C:\\path\\to\\project"]
    }
  }
}
```

### OpenAI Codex CLI

Add to `~/.codex/config.toml`:

```toml
[mcp_servers.mimir]
command = 'C:\path\to\Mimir\.venv\Scripts\mimir.exe'
args = ['serve', 'C:\path\to\project']
```

### Cursor

Add to `.cursor/mcp.json` in the project, using the same JSON as Gemini CLI.

### VS Code (Copilot agent mode)

Add to `.vscode/mcp.json` in the project:

```json
{
  "servers": {
    "mimir": {
      "type": "stdio",
      "command": "C:\\path\\to\\Mimir\\.venv\\Scripts\\mimir.exe",
      "args": ["serve", "C:\\path\\to\\project"]
    }
  }
}
```

### Any AI with a terminal (no MCP needed)

Every tool is also a command, with the same name:

```powershell
mimir repo_map
mimir get_symbol Pricing.applyDiscount
mimir check
```

Run `mimir guide` and paste its output into the instructions file your AI
reads (`AGENTS.md`, `GEMINI.md`, `CLAUDE.md` and so on) so it knows to use them.

### ChatGPT (web and desktop app)

The ChatGPT app can only connect to MCP servers that are reachable on the
public internet. Putting a tool that edits files and runs code on the
internet is risky, so **use OpenAI's Codex CLI instead** (above). It runs
locally and supports MCP directly.

### MCP over HTTP

For clients that connect by URL instead of starting a program:

```powershell
$env:MIMIR_TOKEN = "pick-a-long-random-secret"
mimir serve C:\path\to\project --http --port 8000
```

The server listens at `http://127.0.0.1:8000/mcp` and accepts only requests
that send `Authorization: Bearer <MIMIR_TOKEN>`. It refuses to listen
beyond this computer unless a token is set.

## Human dashboard

```powershell
mimir dashboard C:\path\to\project
```

A local web page that shows, live:

- every tool call the agent makes, tagged *checks pass*, *checks fail*, *refused* or *rolled back*
- whether the project's checks are currently passing
- which files changed since the last checkpoint
- all checkpoints, with **Diff** and **Restore** buttons

You can run checks or save a checkpoint yourself. Your actions appear in
the feed tagged **YOU**. The dashboard listens on `127.0.0.1` only and
rejects requests from other websites. Every action is logged to
`<project>/.mimir/activity.jsonl`.

## Environment variables

| Variable | Purpose |
|---|---|
| `MIMIR_ROOT` | Default project folder for CLI commands |
| `MIMIR_PYTHON` | Python interpreter for running the project's pytest tests |
| `MIMIR_MAVEN` | Path to a specific `mvn` to use, overriding automatic discovery |
| `MIMIR_TOKEN` | Bearer token required by the HTTP server |

## Demos

- `demo_shop/` (Python) and `demo_shop_java/` (Maven) contain the same deliberate discount bug.
- `python demo.py` drives the Python one over real MCP, the way an agent would. It maps the project, finds the failure, reads only the suspect function, saves a checkpoint, makes a broken edit (refused) and a wrong fix (caught by tests), rolls back, then fixes the bug.

## Tests

```powershell
.venv\Scripts\python -m pytest
```

Covers both languages, all three connection modes (CLI, MCP over stdio,
MCP over HTTP with a token) and the safety rules. The Maven test is skipped
when Maven isn't available.

## Adding a language

Write a backend in `mimir/lang/` with the same methods as
`PythonBackend` (`parse`, `syntax_error`, `is_test`, `check`) and add it to
`BACKENDS` in `mimir/lang/__init__.py`.

## Roadmap

- More languages: TypeScript, Kotlin, Go
- Runtime x-ray: run code and report variable values at chosen lines
- Project memory: notes the agent keeps across sessions
- Benchmark: tokens and attempts to fix bugs with and without Mimir
- Rust or Go rewrite, in a separate fork, for a smaller memory footprint

## License

GPL-3.0-or-later. You may use, study and change Mimir, but anything you
distribute that is built on it must also be released under the GPL with its
source code. See [LICENSE](LICENSE).
