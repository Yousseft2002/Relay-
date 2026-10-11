# AGENTS.md — relay-sandbox

A tiny practice project for testing Relay before using it on real products.

## Project

- Python 3.11+, standard library only. Don't add dependencies.
- Code lives in `textstats/`, tests in `tests/`.
- Run tests with: `python -m unittest discover -s tests -v`
- Every new function gets unit tests. Keep functions small and documented.

## Multi-agent team rules (Relay)

This repo is built by a team of AI coding agents (Claude Code, Codex, GitHub Copilot)
coordinated by Relay through GitHub Issues and pull requests. A different tool reviews
every change, so write code and notes another engineer can check quickly.

- One task per run: the GitHub issue you were given. Don't fix unrelated things; if you
  spot a problem elsewhere, mention it under open_questions so it becomes its own issue.
- Don't commit, push, branch, or open PRs yourself. Relay does all git and GitHub work.
- Read `.relay/handoffs/issue-<n>.md` if it exists. It's what the previous agent did and
  what's left. Add to it rather than starting over.
- Tests are the contract between agents. Every behavior change ships with a test, and
  you run the relevant tests before reporting "done".
- Keep changes small enough to review in one sitting (aim for under ~400 changed lines).
  If a task is bigger, finish a coherent slice and say what's left in next_step.
- Product decisions, new paid services, new external accounts, data deletion, auth or
  payment changes, and anything legal: stop with status "blocked" and ask.
- Never touch production data or production credentials. Never add secrets to the repo.
- New dependencies: state the license. MIT, Apache-2.0 and BSD are fine; flag anything else.
- End every run with the RELAY_RESULT block exactly as the prompt shows. Relay parses it.

When reviewing another agent's PR: judge it against the issue's acceptance criteria and
this file. Be specific (file, line, fix). Only block on real problems; put style in
suggestions. Never approve something you didn't actually read.
