# Relay

Relay's first marketplace release is being developed as **Relay — Independent AI
Code Review**: a second vendor reviews an AI-built GitHub pull request and returns
actionable findings, suggested fixes, and explicit coverage limits for a human merge
decision.

Read the [product definition and review report contract](docs/independent-code-review.md)
for the intended buyer experience and release criteria. This is a planned offer, not
a live marketplace release. The current prototype and its known limits are described
below.

## Existing orchestration prototype

Relay turns Claude Code, Codex and GitHub Copilot into one development team. GitHub
Issues are the task board, pull requests are the hand-off point, and every change is
built by one tool and reviewed by a tool from a different company. You approve the plan
and the risky merges; the agents do the rest, overnight if you want.

```
idea -> relay plan -> spec issue + task issues
                         |
        relay tick (every 30 min, or StarNet asks for one)
                         |
   build (routed by size + budget) -> PR -> cross-vendor review
            ^                                  |          |
            '------ rework (max 2 rounds) <----'      approved + CI green
                                                           |
                                    small & low risk: auto-merge / else: you merge
```

No dependencies beyond Python 3.11+, git and the GitHub CLI. MIT licensed.

**New here? Follow [docs/first-run.md](docs/first-run.md).** It walks you through a practice
repo (`examples/relay-sandbox`) from install to a feature planned, built, reviewed and
merged by agents, then on to a real project.

**Improving Relay with Claude Code?** Paste the prompts in
[docs/claude-code-playbook.md](docs/claude-code-playbook.md), one phase at a time.

**Just want the review?** [skills/relay-review](skills/relay-review/README.md) is a standalone
Agent Skill (Claude Code, Codex, Copilot) that runs an evidence-based code review, hands it
to an agent from another vendor if you authorize that, and labels it honestly as a
self-review otherwise. No Relay install needed. Maintainer notes:
[docs/relay-review.md](docs/relay-review.md).

## What each tool does by default

| Role | Default agent | Why |
|------|---------------|-----|
| Planner: idea -> spec + tasks | Claude Code | Reads the repo, writes structured plans |
| Small tasks (size S) | Copilot cloud agent | Runs on GitHub: one premium request per session (plus Actions minutes), not your Claude/Codex limits |
| Medium tasks (size M) | Codex | Strong on scoped implementation; reports token usage |
| Large tasks (size L) | Claude Code | Cross-cutting changes |
| Reviewer | Always a different vendor than the builder | A real second opinion, automatically |

All of this is set in `relay.toml` (`[routing]`), so you can rebalance as your limits change.

## Setup on Windows (about 30 minutes)

1. Install the basics (PowerShell):
   ```powershell
   winget install Python.Python.3.12
   winget install Git.Git
   winget install GitHub.cli
   gh auth login
   ```
2. Install the agent CLIs and sign in to each once:
   - Codex: `npm install -g @openai/codex`, then run `codex` and sign in.
   - Claude Code: follow https://code.claude.com/docs/en/overview, then run `claude` once.
   - Copilot CLI (optional; the cloud agent needs nothing local): see
     https://docs.github.com/en/copilot/how-tos/use-copilot-agents/use-copilot-cli
3. Install Relay:
   ```powershell
   git clone https://github.com/Yousseft2002/Relay-.git
   cd Relay-
   py -m pip install -e .
   ```
4. In your project repo:
   - Copy `relay.example.toml` to `relay.toml` and set `repo = "you/your-repo"`.
   - Paste `AGENTS.relay.md` into the repo's `AGENTS.md` (all three tools read it).
   - Run `py -m relay doctor`, `py -m relay smoke` (runs each agent CLI once to check
     sign-in and flags), then `py -m relay init` (creates labels, git-ignores `.relay/state/`).
5. On GitHub:
   - Protect `main`: require a pull request and require status checks to pass.
     Relay only auto-merges when CI is green, so you need CI (the planner makes "set up
     CI" the first task if it's missing).
   - Turn on the Copilot cloud agent for the repo. With Copilot Pro+ you can also enable
     the Claude and Codex agents in your Copilot settings (off by default) for "bake-offs"
     where all three attempt the same issue.

## Daily use

`py -m relay` works everywhere; plain `relay` works if pip put it on your PATH.

```powershell
relay plan "Visual HQ page: interactive map of one lab with freezers and racks"
relay status            # queues, today's usage, last tick report
relay smoke             # check every agent CLI still signs in and runs
relay tick              # one pass: merge, review, rework, build
relay approve 42        # if spec_approval = true
relay pause / resume    # kill switch for all automation
```

Anything needing you gets the `relay:needs-human` label. Filter GitHub by it each morning.

### Run it overnight

Option A, Windows Task Scheduler:
```powershell
powershell -ExecutionPolicy Bypass -File .\night-shift.ps1 -RepoDir "C:\code\materialos"
```
Runs `relay tick` every 30 minutes from 22:00 for 9 hours and logs to
`.relay\state\night-shift.log`.

Option B, StarNet as the manager: add Relay as an MCP connector and use the brief in
`starnet-manager.md`. StarNet then runs ticks during its Night Shift, plans from your
ideas, and messages you (e.g. on Telegram) when something needs a decision.

Use one option, not both.

## How it saves tokens

- Small work goes to GitHub's cloud agent, billed as premium requests (and Actions
  minutes) instead of your Claude Code or Codex limits.
- Handoff files (`.relay/handoffs/issue-<n>.md`) carry context between agents, so the
  next agent doesn't re-explore the repo from scratch.
- Reviewers get the diff and the handoff, not an open-ended "look around".
- Per-agent daily caps (`max_runs_per_day`, `max_usd_per_day`) with automatic fallback.
- Each headless run loads your project context (AGENTS.md, tool definitions), which has
  a fixed cost even for tiny jobs. Fewer, well-sized tasks beat many tiny ones.

## Safety rails

- Agents never push to `main`; every change is a branch and a PR.
- Each task gets its own git worktree, so parallel agents can't overwrite each other.
- Auto-merge needs: cross-vendor approval, CI green, size S (configurable), risk "low".
- After 2 failed reviews (configurable) a PR goes to you.
- Reviews that can't be parsed never count as approvals.
- `relay pause` stops everything; a tick lock prevents overlapping runs.
- Codex builds in its `workspace-write` sandbox; reviewers run read-only.

## Files

| Path | What it is |
|------|------------|
| `relay/` | The tool (config, routing, agent adapters, GitHub/git wrappers, workflows, MCP server) |
| `relay/templates/` | Build, review, plan and handoff prompts. Override per repo in `.relay/prompts/` |
| `relay.example.toml` | Annotated config |
| `AGENTS.relay.md` | Shared rules for all three agents |
| `starnet-manager.md` | Brief and setup for a StarNet manager agent |
| `night-shift.ps1` | Windows scheduled task for overnight ticks |
| `docs/first-run.md` | Step-by-step first run and troubleshooting |
| `examples/relay-sandbox` | Practice project with CI, for testing Relay safely |
| `skills/relay-review/` | Standalone review skill (SKILL.md package); fixtures in `tests/fixtures/relay-review/` |
| `AGENTS.md` | Rules for agents working on Relay itself (not the template) |
| `tests/` | `py -m unittest discover -s tests -t .` (CI runs Windows + Linux) |

## Known limits (check these on first run)

- Tested with fake agent CLIs and a simulated GitHub, plus one live run where the real
  Claude Code CLI planned, built and reviewed a feature in a real git repo. Codex,
  Copilot and real GitHub haven't been exercised yet: run your first ticks by hand
  (docs/first-run.md) and read the PRs before you schedule anything.
- Claude Code's default build mode is `--permission-mode auto`. If your plan doesn't
  offer auto mode, use the `acceptEdits` alternative shown in `relay.example.toml`.
- Cloud-agent PRs are matched to issues by "Fixes #n" in the PR body. Relay asks the
  agent to include it; if a PR doesn't, label it `relay:review` and `built-by:copilot-cloud`
  yourself.
- Assigning Claude or Codex as *GitHub* agents (Agent HQ) is done in GitHub's UI; Relay
  runs Claude Code and Codex locally instead, which uses your own subscriptions.
- `night-shift.ps1` hasn't been run on a real Windows machine yet.
