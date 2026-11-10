# AGENTS.md — developing Relay

Rules for AI coding agents (Claude Code, Codex, Copilot) working on Relay itself.
Note: `AGENTS.relay.md` is different. It's the template Relay users paste into *their*
projects; don't confuse the two.

## What this is

Relay coordinates Claude Code, Codex and GitHub Copilot as one dev team: GitHub Issues are
the task board, PRs the handoff, every change gets a cross-vendor review, and small
low-risk PRs auto-merge. It's a small CLI plus an MCP server.

## Ground rules

- Python 3.11+, **standard library only**. No runtime dependencies. This keeps installs
  trivial on Windows and lets anyone own and modify it.
- Must work on Windows and Linux (CI runs both). Use `pathlib`, pass prompts on stdin
  (never as long command-line args), resolve executables with `shutil.which`.
- Every behavior change ships with a test. Run before saying you're done:
  `python -m unittest discover -s tests -t .`
- No AI vendor names in product or package names. Agent names in config are fine.
- Don't invent CLI flags for Claude Code, Codex, Copilot or gh. Check their docs and say
  what needs verifying.

## Where things live

| Module | Responsibility |
| --- | --- |
| `relay/config.py` | Load + validate `relay.toml`; default CLI args per agent kind |
| `relay/routing.py` | Pure decisions: who builds, who reviews, can it auto-merge. No I/O |
| `relay/agents.py` | Run an agent CLI headless, normalize output and usage |
| `relay/result.py` | Parse the `RELAY_RESULT` block agents end with |
| `relay/gh.py` | Every GitHub call (through the `gh` CLI) |
| `relay/gitops.py` | Worktrees, commits, pushes |
| `relay/workflows.py` | The loop: plan, dispatch, review, rework, merge, tick, status |
| `relay/smoke.py` | `relay smoke`: check each agent CLI runs with relay's flags |
| `relay/mcp_server.py` | Minimal stdio MCP server for StarNet or any MCP client |
| `relay/templates/` | Prompts (plan, build, review, handoff) |
| `skills/relay-review/` | Standalone review skill. Ships as-is: no imports from `relay/`, no network, no fixtures inside |
| `tests/` | Unit tests + end-to-end loop with a real git repo and a fake GitHub |

## Design rules

- GitHub labels are the state machine. Any step must be safe to re-run, and a crash
  mid-step must leave labels in a state the next tick can recover from.
- Unparseable agent output never counts as success or approval.
- Keep routing pure and tested. New decision logic goes in `routing.py`, not workflows.
- Prompts live in templates so users can override them per repo in `.relay/prompts/`.
