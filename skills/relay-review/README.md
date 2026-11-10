# Relay - Independent AI Code Review

An Agent Skill that reviews code changes the way a careful senior reviewer would: every
finding has a location, quoted evidence, a severity and a fix, and the report says plainly
whether the review was independent or a self-review.

- **Structured workflow:** scope, roles, a safe diff bundle, separate correctness,
  security, test and scope passes, evidence, report, check.
- **Security checklist:** injection, authorization, secrets, crypto, supply chain and CI,
  AI-agent risks (including instructions planted for reviewers), resources and config.
- **Severity and evidence rubric:** CRITICAL to INFO, each backed by a `confirmed`,
  `traced` or `suspected` basis. Serious findings need real evidence.
- **Standard Markdown report** with a machine-readable `RELAY_RESULT` block, plus a checker
  that rejects reports that break the rubric.
- **Independent review across agents:** the code can be handed to an agent from a
  different vendor (for example Claude Code to GitHub Copilot), only after you authorize it.
- **Honest fallback:** with no other agent available, the report is labeled
  `not independent (self-review)`.

## What it does and doesn't do

| It does | It doesn't |
| --- | --- |
| Read your git diff and the files around it | Make network requests (the helper script imports no networking code) |
| Run read-only git commands and, if you allow it, your test suite | Commit, push, merge, approve PRs or post comments |
| Write files only under `.relay-review/` (which ignores itself in git). Your own test suite may leave its usual artifacts, which the report lists | Send code to another provider unless you say yes to a specific question |
| Leave out `.env`, keys and credential files, and redact secret-looking values | Copy secret values into reports (the checker rejects reports that do) |

The rules are instructions to the agent. Agents follow them, but they can't be enforced
from inside a skill. For highly sensitive repositories, review from a clone without
secrets in it.

## Requirements

- An agent that supports Agent Skills (`SKILL.md`). Built for Claude Code, Codex and
  GitHub Copilot.
- git.
- Python 3.11+ for the optional helper (`scripts/relay_review.py`, standard library only).
  Without it, the agent follows the same steps by hand.

## Install

Copy the `relay-review` folder (the one containing `SKILL.md`) into a skills folder your
agent reads.

| Agent | This project only | All your projects |
| --- | --- | --- |
| Claude Code | `.claude/skills/relay-review/` | `~/.claude/skills/relay-review/` |
| Codex | `.agents/skills/relay-review/` | `~/.agents/skills/relay-review/` |
| GitHub Copilot | `.github/skills/relay-review/` (also reads `.claude/skills/` and `.agents/skills/`) | `~/.copilot/skills/relay-review/` |

`.agents/skills/` works for both Codex and Copilot. For a project install, either commit
the folder or add it to `.git/info/exclude`. Otherwise its files count as untracked changes
and show up in the review.

PowerShell (personal install for Claude Code):

```powershell
Copy-Item -Recurse .\relay-review "$HOME\.claude\skills\relay-review"
```

macOS / Linux:

```bash
cp -r relay-review ~/.claude/skills/relay-review
```

## Use

Ask for a review in plain words, or name the skill:

- Claude Code: `/relay-review`, or "review my changes on this branch".
- Codex: `$relay-review`, or pick it from `/skills`.
- GitHub Copilot: "use the relay-review skill to review my changes".

Say what the change was meant to do, if you can. The review checks against that intent.

The report is saved to `.relay-review/reports/<date>-<scope>.md`. To check a report by hand:

```
python <skill-folder>/scripts/relay_review.py check-report .relay-review/reports/<file>.md --repo .
```

`--repo .` also rejects a stale report: one whose `Head SHA` or `Diff fingerprint` no longer
matches the code in front of you. A review covers one exact state of the change; after a new
commit or edit, review it again.

## Independent review across agents (optional)

1. Copy `assets/roles.example.toml` to `relay-review.toml` in your repo root and edit it:
   which agents you have, their vendor, what each can do (`lead`, `implement`, `review`,
   `security-review`), and when each is available. No agent is built in as the lead.
   Reorder `[assign]` to change roles.
2. Ask the agent that wrote the change for a review. It finds an eligible reviewer from
   another vendor and asks you to authorize sharing the diff with it. If you say no, you get
   a labeled self-review.
3. If you say yes, it writes a handoff file under `.relay-review/` and stops. Open the
   reviewer agent in the same repository (with this skill installed) and tell it:
   "Use the relay-review skill. You are the reviewer in `.relay-review/handoff-....md`."
4. The reviewer writes its own report. The author agent can summarize it but never writes
   or edits it.

A reviewer counts as independent only if it is a different agent from a different vendor.
A second pass or a subagent of the same product is labeled `not independent`.

## Files

| Path | Purpose |
| --- | --- |
| `SKILL.md` | The workflow the agent follows |
| `references/security-checklist.md` | What to check, per area |
| `references/severity-rubric.md` | Severity, evidence basis, verdict rules |
| `references/independent-review.md` | Roles, authorization, handoff, combining reviews |
| `assets/report-template.md` | Report format |
| `assets/handoff-template.md` | What a reviewer agent receives |
| `assets/roles.example.toml` | Agents, capabilities, availability |
| `scripts/relay_review.py` | `roles`, `bundle`, `check-report` helpers (no network) |

## Limitations

- An AI review can miss real problems and can be wrong. Treat it as a second opinion, not a
  guarantee. Merging is your decision.
- Secret redaction is pattern-based. Unusual secret formats, and unquoted values in
  config files, may not be caught. Sensitive file names are excluded by a fixed list
  (`--exclude` adds more).
- The reviewer identity in a report is what the reviewing agent declares. A report can't
  prove which model wrote it.

## License

MIT. See `LICENSE`.
