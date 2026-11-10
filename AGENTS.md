# AGENTS.md — developing Relay

Rules for AI coding agents (Claude Code, Codex, Copilot) working on Relay itself.
Note: `kit/AGENTS.team.md` is different. It's the template Relay users paste into *their*
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

## Repo map

```
relay/                 the engine (Python package; the only code the CLI ships)
  templates/           prompts: plan, build, review, handoff
skills/relay-review/   standalone review skill; ships as-is (see its SKILL.md)
tests/                 all tests; fixtures/ holds planted-bug repos for the review skill
docs/                  guides/ (users), product/, dev/ (maintainers), audits/ (dated)  -> docs/README.md
kit/                   files users copy into THEIR repos/machines; no code reads them -> kit/README.md
examples/relay-sandbox practice repo for live tests
relay.example.toml     annotated config template (code and tests point here; keep it at the root)
bridge_server.py       launcher for the private research bridge (external MCP configs point here)
```

## Where things live

| Module | Responsibility | Tests |
| --- | --- | --- |
| `relay/cli.py` | `relay` commands: doctor, smoke, init, plan, approve, dispatch, review, rework, merge, tick, status, pause, resume, mcp | none directly; commands call `workflows.Relay` |
| `relay/config.py` | Load + validate `relay.toml`; default CLI args per agent kind | `test_units.py` (ConfigTests) |
| `relay/routing.py` | Pure decisions: who builds, who reviews, can it auto-merge. No I/O | `test_units.py` (RoutingTests) |
| `relay/agents.py` | Run an agent CLI headless, normalize output and usage | `test_agents.py` |
| `relay/result.py` | Parse the `RELAY_RESULT` block agents end with | `test_units.py` (ResultParsingTests) |
| `relay/gh.py` | Every GitHub call (through the `gh` CLI) | `test_units.py` (check parsing); elsewhere faked by `tests/helpers.py` FakeGitHub. No test against real `gh` |
| `relay/gitops.py` | Worktrees, commits, pushes | indirectly, `test_workflow.py` (real local git repo) |
| `relay/workflows.py` | The loop: plan, dispatch, review, rework, merge, tick, status | `test_workflow.py` |
| `relay/ledger.py` | Append-only usage ledger for daily budgets | `test_workflow.py` |
| `relay/prompts.py` | Load templates; per-repo overrides from `.relay/prompts/` | indirectly, `test_workflow.py` |
| `relay/smoke.py` | `relay smoke`: check each agent CLI runs with relay's flags | `test_agents.py` (SmokeTests) |
| `relay/mcp_server.py` | Dev-team stdio MCP server for StarNet or any MCP client | `test_units.py` (McpTests) |
| `relay/bridge.py` | Private research bridge: separate stdio MCP server, no build/shell/merge tools | `test_bridge.py` |
| `relay/jobs.py` | SQLite job store for the bridge; expired work fails closed | `test_jobs.py` |
| `relay/rewrite.py` | Tool-free prompt rewrite through an official CLI (API key only) | `test_rewrite.py` |
| `skills/relay-review/` | Standalone review skill. No imports from `relay/`, no network, no fixtures inside | `test_review_skill.py` |

## Where to look

| You need to... | Start here |
| --- | --- |
| Change who builds or reviews | `relay/routing.py`, then `relay/config.py` for new settings |
| Change what agents are told | `relay/templates/*.md` |
| Add a CLI command | `relay/cli.py` -> `relay/workflows.py`, and update `docs/guides/first-run.md` |
| Work on the review skill | `docs/product/relay-review.md`, then `skills/relay-review/SKILL.md` |
| Know the review product's promises | `docs/product/independent-code-review.md` |
| Know what was live-tested | `docs/dev/test-log.md` |
| Pick the next piece of work | `docs/dev/claude-code-playbook.md` |
| Change the shared rules users paste | `kit/AGENTS.team.md` (not this file) |

## Design rules

- GitHub labels are the state machine. Any step must be safe to re-run, and a crash
  mid-step must leave labels in a state the next tick can recover from.
- Unparseable agent output never counts as success or approval.
- Keep routing pure and tested. New decision logic goes in `routing.py`, not workflows.
- Prompts live in templates so users can override them per repo in `.relay/prompts/`.
