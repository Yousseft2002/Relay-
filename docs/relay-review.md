# relay-review: the standalone review skill

`skills/relay-review/` is "Relay - Independent AI Code Review": a portable Agent Skill
(`SKILL.md`) that brings Relay's core rule, that every change is reviewed by a different
vendor than the one that built it, to any agent, without the Relay CLI. Buyers' docs are in
[skills/relay-review/README.md](../skills/relay-review/README.md). This page is for maintainers.

## How it fits Relay

| Relay CLI | relay-review skill |
| --- | --- |
| `relay.toml` `[routing]` assigns planner, builders and reviewers | `relay-review.toml` `[assign]` assigns lead, implement and review, with `capabilities` and `available_from` per agent |
| `config.py` refuses a same-vendor reviewer | `roles` never picks the author or its vendor; otherwise the result is a labeled self-review |
| `templates/review.md` asks for a `RELAY_RESULT` block | The report ends with the same block; `relay.result.parse_review` reads it (tested) |
| Relay starts the reviewer itself | The skill hands off and stops; the user (or a configured command, after a second yes) starts the reviewer |

The skill doesn't import anything from `relay/`. It has to work in repos that don't use
Relay. The shared contract is the `RELAY_RESULT` block and the vendor rule.

## Layout

```
skills/relay-review/            <- the package (exactly what ships)
  SKILL.md                      workflow + rules (frontmatter per agentskills.io spec)
  README.md  LICENSE
  references/                   security checklist, severity rubric, independent review
  assets/                       report + handoff templates, roles.example.toml
  scripts/relay_review.py       roles | bundle | check-report (stdlib, no network)
tests/test_review_skill.py      package rules, roles, redaction, bundles, report checks
tests/relay_review_eval.py      build fixture repos; grade reports (also a CLI)
tests/fixtures/relay-review/    NOT shipped: cases with planted bugs + sample reports
```

Fixtures stay outside the package on purpose. They contain a fake credential-shaped value,
a planted `.env` and text that tries to instruct reviewers. That's what they test for, and
exactly what a marketplace scanner should flag.

## Tests

```
python -m unittest discover -s tests -t .
```

`test_review_skill.py` checks, among other things: frontmatter rules (name matches folder,
lengths), links resolve, the package holds only text files with no secrets or planted
instructions, the script imports no networking modules and runs only read-only git,
role assignment (Codex unavailable until 2026-10-31, reassigning the lead, same vendor never
independent), redaction, bundles for every fixture case, and that the checker rejects each
kind of dishonest or unsupported report.

## Live evaluation on a real agent

```
py -m tests.relay_review_eval build prompt-injection C:\tmp\rr-case
# install the skill into C:\tmp\rr-case\.claude\skills\relay-review (and add .claude/ to
# .git\info\exclude), ask the agent for a review there, then:
py -m tests.relay_review_eval grade prompt-injection C:\tmp\rr-case\.relay-review\reports\<file>.md
```

`grade` checks that required findings were found at the right lines with at least the
expected severity, that clean code didn't get false positives, the verdict, and
`check-report`. Results go in [test-log.md](test-log.md).

## Agensi packaging checklist (don't zip or submit yet)

Requirements we could confirm: standard SKILL.md frontmatter, testing on Claude Code plus at
least one other agent, and an automated security scan. Third-party guides say the scan covers
prompt injection, data exfiltration, dangerous commands, secrets and obfuscated code. We found no
official Agensi rule list, so confirm against the Creator Dashboard before submitting.

- [x] `SKILL.md` frontmatter valid: `agentskills validate` (skills-ref 0.1.1) passes
- [x] `name` = folder name `relay-review`; description 612 characters (limit 1024)
- [x] SKILL.md under 500 lines; detail in `references/`
- [x] No network access; no credentials read; read-only git; writes only `.relay-review/`
- [x] Behavior disclosed in README ("What it does and doesn't do")
- [x] No secrets in the package (unit test + gitleaks 8.30.1 `dir` scan: no leaks)
- [x] No fixture payloads in the package (fixtures live in `tests/`)
- [x] License file included (MIT, same as the repo). **Decision for the owner:** keep MIT or
      choose a commercial license before selling (see playbook Phase 5)
- [x] Claude Code 2.1.312: live headless runs on 2 of 7 fixtures, both graded PASS (see
      test-log.md). The other 5 cases have only been checked through bundle tests, not live runs.
- [ ] A second agent (GitHub Copilot or Codex): not run yet; needs the owner to run it
- [ ] Listing text, price, tags: owner
- [ ] Build the zip from `skills/relay-review/` only (no `__pycache__`), after approval

Draft listing description (accurate to what ships):

> Relay Review runs a structured, evidence-based code review of your diff, branch or PR:
> correctness, a security checklist (including prompt-injection attempts aimed at AI
> reviewers) and test coverage. Every finding has a location, quoted evidence, a severity
> and a fix. It can hand the review to an agent from a different vendor, only with your
> permission, and labels it honestly as a self-review when no other agent is available.
> Makes no network requests, never commits or merges, and leaves secrets out of its reports.
