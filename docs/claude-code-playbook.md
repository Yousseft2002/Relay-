# Claude Code playbook: test Relay, then make it production-ready

How to use this: open the Relay repo in Claude Code on your Windows machine and paste one
prompt at a time, in order. Each phase ends with passing tests and a pull request you
read and merge. Don't skip ahead: phase 1 tells you what's actually broken on your machine,
which changes what phase 2 needs.

```powershell
cd C:\code\Relay-
git pull
claude
```

Claude Code reads `AGENTS.md` (the rules for working on Relay) automatically, through
`CLAUDE.md`.

Every prompt below ends the same way on purpose: plan first, wait for your OK, build with
tests, run the full suite, open a PR. Keep that habit; it's what makes the agents' work
reviewable.

---

## Phase 0 — Fix the known security gap (do this first)

> Read AGENTS.md, then relay/workflows.py and relay/gh.py.
>
> Security fix: `sync_cloud_prs` labels any open PR whose body says "Fixes #N" for a
> cloud-agent task, without checking who opened it. On a public repo a stranger could open
> such a PR and it could be auto-merged after review. Also, issue bodies are passed to
> agents as instructions, so an issue edited by an outside user after a maintainer labeled
> it could inject instructions.
>
> Fix both:
> 1. Only adopt cloud PRs whose author is GitHub's Copilot agent. Don't guess the login:
>    find out what `gh pr list --json author` returns for a Copilot-authored PR (check
>    GitHub's docs, and note in the code that this was verified and how). Make the
>    accepted logins a config value with that verified default.
> 2. Add `allowed_authors` to `[project]` in relay.toml (default: the repo owner from
>    `project.repo`). `dispatch`, `rework` and `plan` must skip issues and PRs whose author
>    isn't on the list, and skip issues edited by someone not on the list after labeling.
>    Use `gh` JSON fields that actually exist; verify them with `gh issue view --help`.
> 3. Tests for both, using FakeGitHub.
>
> Plan first and wait for my OK. Then implement, run
> `python -m unittest discover -s tests -t .`, update README and relay.example.toml, and
> open a PR.

## Phase 1 — Live test on my machine

> Walk me through docs/first-run.md one step at a time on this Windows machine. Run the
> commands yourself where you can; tell me when I need to do something (sign-ins, GitHub
> settings). Stop after each step, show me the output, and tell me whether it matches what
> the runbook expects.
>
> Keep a log in docs/test-log.md: date, step, command, expected, actual, pass/fail, and
> the fix if any. Use my GitHub username Yousseft2002 and create the practice repo as
> Yousseft2002/relay-sandbox.
>
> When something fails, don't patch around it. Find the root cause in relay/, write a
> failing test that reproduces it, fix it, run the full test suite, and add a row to the
> log. Batch the fixes into one PR on the Relay repo at the end of the session.
>
> Don't run night-shift.ps1 or connect StarNet yet. Stop after step 10 of the runbook.

If you run out of time, say "stop here and summarize where we are in docs/test-log.md".
Next session: "Read docs/test-log.md and continue the live test from where we stopped."

## Phase 2 — Harden it for unattended use

Do these as separate prompts, one PR each, in this order.

### 2.1 Crash recovery

> Read AGENTS.md and relay/workflows.py. Make every step safe to crash and re-run:
> - An issue stuck in `relay:in-progress` with no open PR and no running tick for longer
>   than the agent's timeout plus 30 minutes is requeued once (back to `relay:ready`,
>   with a comment), and goes to `relay:needs-human` the second time.
> - If a branch already has an open PR, reuse it instead of failing on `gh pr create`.
> - Retry gh and git network errors twice with backoff; never retry agent runs
>   automatically (they cost money).
> Plan first and wait for my OK, then implement with tests, run the full suite, open a PR.

### 2.2 Logs I can actually read

> Add structured run logs: every agent run writes a JSON record (issue/PR, agent, mode,
> start, duration, exit code, usage, result status) and the full agent output to
> `.relay/state/runs/<timestamp>-<agent>-<ref>.log`. Add `relay logs [--last N]` to list
> recent runs and `relay logs --show <id>` to print one. Redact anything that looks like
> a token or key before writing. Prune logs older than 30 days.
> Plan first and wait for my OK, then implement with tests, run the full suite, open a PR.

### 2.3 Run agents in parallel safely

> Right now a tick runs one job at a time. Add `max_parallel` to `[project]` (default 1)
> and `max_parallel` per agent (default 1). When higher, run builds for different issues
> concurrently in their own worktrees using a thread pool. Never run two jobs on the same
> issue or PR. Keep the GitHub label updates race-free. Keep ledger writes safe across
> threads.
> Plan first and wait for my OK, then implement with tests (including one that proves two
> builds overlap and one that proves the same issue never runs twice), run the full suite,
> open a PR.

### 2.4 Config and preflight checks

> Make `relay doctor` a real preflight: check gh auth scopes, that the repo exists and I
> can push, that the labels exist, that CI is configured on the base branch, that branch
> protection status is known (warn if off, don't fail), that every agent passes `relay
> smoke` within the last 24 hours (cache the result), and that relay.toml has no unknown
> keys (catch typos). Exit non-zero on any failure so the night-shift script can skip
> broken nights.
> Plan first and wait for my OK, then implement with tests, run the full suite, open a PR.

## Phase 3 — See what it's doing

### 3.1 Notifications

> Add notifications without needing StarNet: a `[notify]` section with webhook URLs read
> from environment variables (never stored in relay.toml), supporting Discord and Slack
> incoming webhooks and Telegram bot messages. Send one message when something gets
> `relay:needs-human`, when a tick errors, and a daily summary (merged, in review, blocked
> with the exact question, usage per agent). Add a `.env.example`. Standard library only
> (urllib). Check each service's webhook format in its docs; don't guess.
> Plan first and wait for my OK, then implement with tests that don't hit the network,
> run the full suite, open a PR.

### 3.2 Local dashboard

> Add `relay dashboard`: a local web page served with the standard library on
> 127.0.0.1 only, showing the task board by label, recent runs from the logs, today's and
> this week's usage per agent (runs, dollars, tokens), and buttons for pause/resume. It
> reads the same state the CLI does; it never calls agents itself. One HTML page, no
> frontend build step, works in light and dark mode.
> Plan first and wait for my OK, then implement with tests for the data endpoints, run
> the full suite, open a PR.

## Phase 4 — Many projects, easy install

### 4.1 Fleet mode

> Add a fleet file (`relay-fleet.toml`) listing several repos, each with its local path
> and relay.toml. `relay fleet tick` runs one tick per repo in turn with a shared daily
> budget per agent across all repos, and `relay fleet status` summarizes all of them. The
> night-shift script should accept the fleet file instead of one repo.
> Plan first and wait for my OK, then implement with tests, run the full suite, open a PR.

### 4.2 Packaging and releases

> Make Relay easy to install on a fresh Windows machine: support `pipx install
> git+https://github.com/Yousseft2002/Relay-.git`, add a version command, a CHANGELOG, and
> a GitHub Actions release workflow that builds and attaches a wheel when I push a tag.
> If you suggest a single-file .exe, name the tool and check its license terms for
> commercial use before recommending it.
> Plan first and wait for my OK, then implement, run the full suite, open a PR.

## Phase 5 — Before calling it a product

> Act as my technical cofounder. Review Relay as a product: who would pay for it and why
> they wouldn't just use GitHub Agent HQ, Vibe Kanban or Emdash; what the moat is (routing
> by budget, cross-vendor review, auto-merge policy, fleet mode); whether MIT is the right
> license if I want to sell it; whether "Relay" is too generic a name to own; and what the
> smallest paid version would be. Write it up in docs/product.md. Don't change code.

---

## Prompts for any time

- **A run failed:** "Here's the output of `py -m relay tick`: <paste>. Find the root cause
  in relay/, add a failing test, fix it, run the suite, and open a PR."
- **Bad agent output:** "Look at the latest run log for <issue/PR>. Did the agent follow the
  prompt? If the prompt is the problem, propose a change to relay/templates/ and explain
  it before editing."
- **Before you merge an agent PR:** "Review PR #<n> on this repo against AGENTS.md. Run
  the tests on its branch. List blocking issues only."
- **Check the docs match the code:** "Compare README.md and docs/first-run.md to the
  current CLI (`py -m relay --help` and each subcommand). Fix anything out of date."
