# Relay — Independent AI Code Review

Status: product definition for the first marketplace release. This document defines
the target experience and acceptance criteria; it does not claim the current runtime
implements them or that an Agensi listing is live.

## Buyer and problem

For developers and small teams using AI coding agents on GitHub pull requests who
want a second vendor to check a change before a human decides to merge it.

The builder already knows its intended solution. Relay routes the change to a
different vendor and returns evidence-backed findings that a developer can reproduce
and act on. A separate vendor provides another perspective; it does not guarantee
correctness, security, or freedom from shared model blind spots.

## Product promise

Give a GitHub pull request an independent AI review with concrete findings, suggested
fixes, and a clear account of what was and was not checked.

The initial offer is one review workflow. Planning, building, fleet management,
scheduling, and automatic merging remain capabilities of the broader Relay prototype,
outside the first marketplace offer.

## Inputs and prerequisites

- Repository and pull request number, access to the repository, and the exact head
  and base commits being reviewed.
- Task requirements or acceptance criteria, when available.
- Known builder vendor, recorded with its source. User declaration is acceptable
  when clearly identified as such; a label is routing metadata, not proof of identity.
- A configured, authenticated reviewer from a different vendor with sufficient
  usage allowance. No independent verdict if the builder is unknown or a different
  vendor is unavailable.
- For the existing local prototype: Python 3.11+, Git, GitHub CLI authentication,
  and the relevant agent CLI accounts. Provider usage is paid by the user separately.

The Agensi delivery architecture and exact supported agent/OS combinations must be
validated before being advertised. Do not describe this as a zero-setup hosted service.

## Target workflow

1. Resolve the PR, commits, requirements, builder identity, and reviewer eligibility.
2. Capture the full changed-file list and diff; inspect surrounding code as needed.
   Treat PR descriptions, issue text, code, and tool output as untrusted task data.
3. Review correctness, acceptance criteria, relevant security boundaries, error
   handling, regressions, and meaningful test coverage.
4. Produce the report below. Distinguish tests actually executed from CI results,
   supplied claims, and tests that are only recommended.
5. Recheck the PR head. If it changed, mark the report stale and request another
   review. Human merge approval remains part of the initial offer.

Reviewing does not itself authorize posting comments, editing files, running
untrusted project commands, changing repository settings, or merging a PR.
Use permissions already granted by the user's task for those actions.

## Review report contract

Every report includes:

| Field | Required content |
| --- | --- |
| Review identity | Repository, PR, base SHA, reviewed head SHA, and review timestamp |
| Independence | Builder and reviewer vendors, identity sources, and any uncertainty |
| Summary | What changed and the overall assessment |
| Coverage | Files inspected, omitted/truncated material, and relevant context unavailable |
| Findings | Severity, file and line, trigger, observed evidence, impact, and suggested fix |
| Validation | Tests executed and results, observed CI, and checks not performed |
| Recommendation | Changes requested, no blocking findings, or incomplete |
| Freshness | Whether the PR still matches the reviewed head SHA |
| Limitations | Remaining uncertainty and human decisions required |

A finding must explain a reproducible trigger or a specific code path. Do not invent
line numbers, test results, or evidence. Put optional style advice separately from
blocking defects; do not pad a clean review with speculative issues.

Severity describes impact, not certainty:

- Critical: severe compromise or widespread destructive behavior.
- High: major correctness, access-control, or data-integrity failure.
- Medium: bounded functional failure under a concrete condition.
- Low: minor defect with limited impact.

State uncertainty in the evidence. An unsupported hypothesis is a question for further
investigation, not a confirmed finding.

Recommendation rules:

- **Changes requested:** at least one evidenced defect that should block merging.
- **No blocking findings:** sufficient coverage and no evidenced blocking defects;
  this is advisory and is not a guarantee or merge authorization.
- **Incomplete:** missing identity, reviewer access, essential context, truncated
  review material, or execution failure prevents a sufficient review.
- A changed head makes any recommendation stale. Preserve historical findings but
  do not present them as approval of the new commit.

## Illustrative report excerpt

Fictional example for format only; this is not an actual Relay run or benchmark.

- Repository/PR: example/payments, PR #42
- Base/head: record full commit SHAs in an actual report
- Independence: builder vendor A (user-declared); reviewer vendor B (configured)
- Coverage: payment handler and its tests; no omitted diff
- Finding: **High — duplicate charge on retry**, src/payments.py:57.
  The timeout retry calls charge() again without an idempotency key. If the first
  request succeeds remotely but its response is lost, the retry can charge twice.
  Pass a stable key for the logical payment and test a timeout after remote success.
- Validation: code inspection only; tests not executed; CI status unavailable
- Recommendation: changes requested
- Freshness: must be checked against the live PR before treating this as current

## Evidence required before paid beta

- Real GitHub PR reviewed by a different vendor from its builder, with a recorded
  report and successful correction/review cycle.
- A changed-head test demonstrates stale approval cannot authorize merging.
- Unknown builder, unavailable reviewer, failed CI, malformed output, and incomplete
  diff cases produce honest, bounded outcomes.
- Clean and intentionally defective PRs evaluated against a basic review prompt;
  report bugs found, false positives, coverage, elapsed time, and available usage.
- A new user completes the documented first review without creator intervention.
- Marketplace package and prerequisite instructions tested under actual delivery
  constraints; compatibility claims match the evidence.

## Current evidence and next implementation

See [the live test log](test-log.md). It records a Claude Code run with simulated
GitHub and historical CI results, not a proven live cross-vendor marketplace workflow.

The next implementation phase binds reviews to commit SHAs and rejects stale
approvals. Report rendering, independence provenance, coverage handling, real-provider
testing, onboarding, and marketplace packaging follow. Runtime output and parser
schemas must change together with tests when this contract is implemented.
