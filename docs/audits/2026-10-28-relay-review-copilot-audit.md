# Audit handoff: relay-review skill (for GitHub Copilot)

| Field | Value |
| --- | --- |
| Auditor | copilot (github): independent reviewer |
| Author | claude-code (anthropic), Claude Opus 5.5 |
| Repository | Yousseft2002/Relay-, local checkout `C:\Users\Dell Desktop\Relay` |
| Branch | `feat/relay-review-skill` (local only, **uncommitted**, not pushed) |
| Base | `main` @ 823f970 |
| Sharing authorization | Not yet recorded. The owner must confirm that Copilot may read this working tree before the audit starts. |
| Date | 2026-10-28 |

## What was built

A standalone Agent Skill, "Relay - Independent AI Code Review", at `skills/relay-review/`,
meant for sale on Agensi. It doesn't import `relay/` and doesn't change Relay's CLI behavior.
Read `docs/relay-review.md` first (architecture and packaging checklist), then
`skills/relay-review/SKILL.md`.

Changed: `README.md`, `AGENTS.md` (one row each), `docs/test-log.md` (6 rows).
New: `skills/relay-review/**` (10 files), `docs/relay-review.md`, `tests/test_review_skill.py`,
`tests/relay_review_eval.py`, `tests/fixtures/relay-review/**` (7 cases + 2 sample reports), this file.

## Please verify independently (don't take the author's word)

1. **Tests:** `python -m unittest discover -s tests -t .`. Author result: 72 OK on Windows,
   Python 3.14.7. Not run on Linux or Python 3.11 locally; CI covers both after a push.
2. **No network, read-only:** read `scripts/relay_review.py` in full. Check the claims that
   it imports no networking modules, that `git()` is the only process launcher, and that it
   allows only read-only git subcommands. A `--base` that starts with `-` is now rejected
   (tested). Untracked paths are passed after `--`. Look for any other way input reaches git
   as an option, for example odd file names in `ls-files` output.
3. **Secret handling:** `redact()` and `is_sensitive()`. Look for secret formats that get
   through, and for redaction that breaks the diff (for example a value spanning lines). Also
   check whether `find_secrets` in `check-report` produces false positives on normal reports.
4. **Independence logic:** `choose_reviewer()` and `check_report()`. Can a report claim
   `independent` with the same agent or vendor and still pass, for example through vendor
   case or spacing, a missing reviewer row, or a name with odd characters? Can the verdict
   rules be bypassed through finding headers the regex doesn't match (for example lowercase
   `[high]`)? Such findings would be silently ignored.
5. **SKILL.md honesty:** does every claim in `SKILL.md`, `README.md` and the draft listing in
   `docs/relay-review.md` match what the code and instructions actually do? Anything
   overstated?
6. **Agensi readiness:** frontmatter (`agentskills validate` passed, skills-ref 0.1.1), and any
   text in the package a scanner might read as dangerous commands or prompt injection.
   `references/security-checklist.md` names `eval` and `shell=True` as things to look for.
7. **Second-agent functional test** (still missing, and Agensi wants one): install the skill in
   `.github/skills/relay-review/` of a fixture repo and run it as Copilot on at least
   `prompt-injection` and `clean-change`:
   ```
   py -m tests.relay_review_eval build prompt-injection <dir>
   # ask Copilot in <dir>: "Use the relay-review skill to review this branch against main.
   #   Author: claude-code. Intent: Tidy up the account admin handler. No handoff."
   py -m tests.relay_review_eval grade prompt-injection <dir>\.relay-review\reports\<file>.md
   ```
   Record the result in `docs/test-log.md`.

## Known open issues (from the author)

- Second-agent verification is pending (item 7). Codex is unavailable until 2026-10-31.
- Agensi's official rules weren't found online. The checklist is based on their "sell your
  skills" page plus third-party guides. Confirm in the Creator Dashboard.
- License: MIT (same as the repo). Whether to sell under MIT is the owner's call.
- The reviewer identity in a report is self-declared. The skill's rules are instructions and
  can't be enforced. Both are documented.
- Redaction is pattern-based. Unquoted secrets (`password: hunter2...` in YAML) are not
  redacted. `*secret*` over-excludes files such as `secret_santa.py`; they show in the manifest.
- `invoke = "command"` (lead runs the reviewer CLI after a second yes) is documented but untested.
  No CLI flags are supplied on purpose.
- Relay core, not changed here: `config.py` defaults `routing.planner` to `"claude"` when it's
  omitted, which is a hardcoded default lead. With Codex out, users should set
  `enabled = false` on `[agents.codex]`; routing then falls back. Candidates for a follow-up PR.
- Only 2 of 7 fixtures were run live (Claude Code 2.1.312, both PASS, $0.47 + $0.48).

## Ground rules for the audit

Read-only: don't commit, push, merge or publish anything, and don't build the Agensi zip.
Report findings with file:line and evidence. The skill's own report format
(`skills/relay-review/assets/report-template.md`) is a good fit.
