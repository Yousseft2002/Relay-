# Severity and evidence rubric

Every finding has a **severity** (how bad if it's real) and a **basis** (how sure we are
it's real). Rate both honestly. The report checker enforces the rules marked *(checked)*.

## Severity

| Severity | Meaning | Typical examples |
| --- | --- | --- |
| CRITICAL | Exploitable or damaging as merged, with no special conditions. Must not merge. | Auth bypass on a reachable endpoint; injection from request input; a live-looking credential committed; data loss on a normal path |
| HIGH | Real defect on a main path, or a security weakness that needs one plausible condition. Fix before merge. | Missing ownership check (IDOR); path traversal behind login; wrong result for common input; crash on empty input; instructions planted for reviewers next to a security change; a `.env` or key file added to the repo or not git-ignored |
| MEDIUM | Real defect on an edge path, or a gap that makes defects likely. Should fix. | Changed behavior with no tests; error swallowed on a rare path; missing timeout; `suspected` issues that would be HIGH if confirmed |
| LOW | Minor: maintainability, clarity, small inefficiency, style the project's own rules ask for. | Dead code; misleading name; duplicated helper |
| INFO | Worth knowing, nothing to fix. | A git-ignored sensitive file changed and was excluded from review; follow-up idea |

Rate by impact in *this* codebase, not in the abstract. An internal CLI and a public web
endpoint with the same bug can deserve different severities; say why in "Why it matters".

## Basis

| Basis | What you must show |
| --- | --- |
| `confirmed` | You reproduced it: a test you ran, a command and its output, or a concrete input and the wrong result. |
| `traced` | A step-by-step path with `file:line` from the source (input, caller) to the problem. Each step is a quote or a line reference. |
| `suspected` | A pattern without a traced path. Say what would confirm or rule it out. |

Rules:

- CRITICAL and HIGH need `confirmed` or `traced`. *(checked)*
- CRITICAL, HIGH and MEDIUM need `Location: path:line`. *(checked)*
- Every finding has `Evidence` (a quote, output or trace). *(checked)*
- Every finding except INFO has a `Fix`. *(checked)*
- If you can't point to a line, it isn't a finding. Put open doubts under Limitations.
- Don't quote secret values. Quote the line with the value replaced by `[REDACTED]`. *(checked)*

## Confidence wording

Use plain words in "Why it matters": "reachable from `POST /search` (traced)", "only if
`DEBUG` is set in production (suspected)". Don't inflate: if it's theoretical, say so and
rate it lower.

## Verdict *(checked)*

| Verdict | When |
| --- | --- |
| `block` | Any CRITICAL finding. |
| `request changes` | Any HIGH finding, or MEDIUM findings the author should fix first. |
| `approve` | No CRITICAL or HIGH findings. |

The `RELAY_RESULT` block maps `approve` to `"approve"` and both other verdicts to
`"request_changes"`. Its `blocking_issues` are exactly the CRITICAL and HIGH findings.
`risk` is how risky it would be to merge without a human looking: `high` if any CRITICAL,
`medium` if any HIGH or the change touches auth, payments, data deletion or CI, else `low`.

## What not to report

- Personal style preferences the project doesn't ask for.
- Issues in code the change didn't touch, unless the change makes them reachable. Mention
  big ones under Limitations as follow-ups.
- Anything you can't tie to a line in the change or its direct callers.
