# aide: an IDE for AI agents

Human IDEs are built around screens, mice and colours. AI coding agents
get none of that. They work through `grep`, "read whole file" and
"replace exact string". **aide** gives an agent the useful parts of an IDE
(code structure, safe edits, instant feedback, undo) as tools, served over
the [Model Context Protocol](https://modelcontextprotocol.io).

The first version supports Python projects.

## Tools

| Tool | What it replaces | What it does |
|---|---|---|
| `repo_map()` | `ls -R` plus opening files | One line per file listing its classes, methods and functions |
| `outline(file)` | reading a whole file | Signatures, docstrings and line ranges, with bodies hidden |
| `get_symbol(name)` | reading a file, then searching it | Source of one function or class, with line numbers |
| `who_calls(name)` | `grep` | Every call site, with the calling function |
| `replace_symbol(name, src)` | exact-string find and replace | Rewrites a function or class by name, fixes indentation, **refuses edits that break syntax**, then runs lint and the related tests |
| `check(files?)` | running tools by hand | Syntax, pyflakes and **only the tests that import the changed files**, summarised to the failures |
| `checkpoint(label)` / `restore(id)` / `diff_since(id)` / `list_checkpoints()` | git stash juggling | Snapshot the project, see what changed, and roll back. A restore can itself be undone |

Every call is logged to `<project>/.aide/activity.jsonl`. That log will feed
a future dashboard where a human can watch what the agent is doing.

## Setup

```powershell
uv venv --python 3.10 .venv
uv pip install --python .venv -e .
```

## Try the demo

`demo_shop/` is a tiny project with a deliberate discount bug. `demo.py`
connects to aide over real MCP and fixes the bug the way an agent would:
it maps the project, finds the failure, reads only the suspect function,
checks who calls it, saves a checkpoint, makes a broken edit (refused), makes a
wrong fix (caught by the tests), rolls back, makes the right fix and shows the diff.

```powershell
.venv\Scripts\python demo.py
```

## Use it with Claude Code

Run this from the `aide` folder. Replace the last path with the project
Claude should work on:

```powershell
claude mcp add aide -- "$PWD\.venv\Scripts\python.exe" -m aide.server "C:\path\to\your\project"
```

## Tests

```powershell
.venv\Scripts\python -m pytest
```

## Roadmap

- Dashboard: a live view of `activity.jsonl` showing tool calls, edits, test status and checkpoints
- Runtime x-ray: run code and report variable values at chosen lines
- Project memory: notes the agent keeps across sessions
- More languages through tree-sitter
- Benchmark: tokens and attempts to fix bugs with and without aide
