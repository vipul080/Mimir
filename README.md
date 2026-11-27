# Mimir: an IDE for AI agents

Human IDEs are built around screens, mice and colours. AI coding agents
get none of that. They work through `grep`, "read whole file" and
"replace exact string". **Mimir** gives an agent the useful parts of an IDE
(code structure, safe edits, instant feedback, undo) as tools, served over
the [Model Context Protocol](https://modelcontextprotocol.io). It also gives
the human a live dashboard to watch the agent work and step in.

In Norse myth, Mímir guards the well of wisdom and knows everything that
happens in the world. This one knows everything about a codebase and
shares it with the AI working on it.

The first version supports Python projects.

## Agent tools

| Tool | What it replaces | What it does |
|---|---|---|
| `repo_map()` | `ls -R` plus opening files | One line per file listing its classes, methods and functions |
| `outline(file)` | reading a whole file | Signatures, docstrings and line ranges, with bodies hidden |
| `get_symbol(name)` | reading a file, then searching it | Source of one function or class, with line numbers |
| `who_calls(name)` | `grep` | Every call site, with the calling function |
| `replace_symbol(name, src)` | exact-string find and replace | Rewrites a function or class by name, fixes indentation, **refuses edits that break syntax**, then runs lint and the related tests |
| `check(files?)` | running tools by hand | Syntax, pyflakes and **only the tests that import the changed files**, summarised to the failures |
| `checkpoint(label)` / `restore(id)` / `diff_since(id)` / `list_checkpoints()` | git stash juggling | Snapshot the project, see what changed, and roll back. A restore can itself be undone |

## Human dashboard

A local web page that shows, live:

- every tool call the agent makes, tagged *checks pass*, *checks fail*, *refused* or *rolled back*
- whether the project's checks are currently passing
- which files changed since the last checkpoint
- all checkpoints, with **Diff** and **Restore** buttons

You can also run checks or save a checkpoint yourself. Your actions show up
in the feed tagged **YOU**.

It uses only Python's standard library and listens on `127.0.0.1` only.
Requests from other websites are rejected.

```powershell
.venv\Scripts\mimir-dashboard "C:\path\to\your\project"
```

Every action, from the agent or from you, is logged to
`<project>/.mimir/activity.jsonl`.

## Setup

```powershell
uv venv --python 3.10 .venv
uv pip install --python .venv -e .
```

## Try the demo

`demo_shop/` is a tiny project with a deliberate discount bug. `demo.py`
connects to Mimir over real MCP and fixes the bug the way an agent would:
it maps the project, finds the failure, reads only the suspect function,
checks who calls it, saves a checkpoint, makes a broken edit (refused), makes a
wrong fix (caught by the tests), rolls back, makes the right fix and shows the diff.

```powershell
.venv\Scripts\python demo.py
```

The demo prints the folder it worked in. Point the dashboard at that folder
to see the whole session replayed.

## Use it with Claude Code

Run this from the repository folder. Replace the last path with the project
Claude should work on:

```powershell
claude mcp add mimir -- "$PWD\.venv\Scripts\python.exe" -m mimir.server "C:\path\to\your\project"
```

## Tests

```powershell
.venv\Scripts\python -m pytest
```

## Roadmap

- Rust or Go rewrite, in a separate fork, for a smaller memory footprint
- Runtime x-ray: run code and report variable values at chosen lines
- Project memory: notes the agent keeps across sessions
- More languages through tree-sitter
- Benchmark: tokens and attempts to fix bugs with and without Mimir

## License

GPL-3.0-or-later. You may use, study and change Mimir, but anything you
distribute that is built on it must also be released under the GPL with its
source code. See [LICENSE](LICENSE).
