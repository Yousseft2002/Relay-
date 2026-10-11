# Live test log

One row per runbook step (docs/first-run.md). Claude Code fills this in during phase 1 of
docs/claude-code-playbook.md.

| Date | Step | Command | Expected | Actual | Result | Fix |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-10-11 | Dev box | Real Claude Code CLI: plan, build, review on the practice repo, GitHub simulated | Spec + tasks, a PR with passing tests, a parsed review | Spec with 2 tasks; PR with tests passing; approved, risk low; $0.29 | pass | Planner didn't set a dependency between the tasks; tightened the plan prompt |
| 2026-10-11 | CI | Unit + end-to-end tests on GitHub Actions | Pass on Windows and Linux, Python 3.11 and 3.13 | All 4 jobs passed | pass | |
