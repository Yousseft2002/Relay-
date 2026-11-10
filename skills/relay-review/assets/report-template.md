# Relay Review: <short title of the change>

| Field | Value |
| --- | --- |
| Verdict | <approve / request changes / block> |
| Independence | <independent / not independent (self-review) / not independent (same vendor)> |
| Author agent | <agent-id (vendor)>, or <human (name)> |
| Reviewer agent | <agent-id (vendor)> |
| Reviewer model | <model name if known, else "not reported"> |
| Scope | <base-ref (merge-base sha) .. head sha + uncommitted; N files> |
| Base SHA | <full merge-base commit SHA: the bundle manifest's "merge_base"> |
| Head SHA | <full HEAD commit SHA you reviewed: the bundle manifest's "head"> |
| Diff fingerprint | <the bundle manifest's "diff_sha256" ("sha256:..."), or "not computed" without the helper> |
| Intent | <issue, PR or task this change should satisfy, or "none given"> |
| Sharing authorization | <"granted by <user> on <date>: <their words>", or "none (self-review)", or "sharing declined"> |
| Date | <YYYY-MM-DD> |

## Summary

<2 to 4 sentences: what the change does, whether it does it correctly, and the most important
problems. Say plainly if no blocking issues were found.>

## Findings

<One block per finding, most severe first. Number them F1, F2, ... If there are none, write
"No findings." and delete the example below.>

### F1 [HIGH] <one-line statement of the problem>

- Location: `<path>:<line>`
- Category: <security/injection, security/authz, correctness, tests, prompt-injection, ...>
- Basis: <confirmed / traced / suspected>
- Evidence:

  ```
  <quoted code, command and output, or a numbered file:line trace. Never a secret value.>
  ```

- Why it matters: <impact in this codebase, and any conditions it depends on>
- Fix: <specific change>

## Coverage

| Area | Checked | Notes |
| --- | --- | --- |
| Correctness | <yes/no> | |
| Security checklist | <sections 1-8 checked, or which were not applicable> | |
| Tests | <ran `<command>`: result / not run, why> | |
| Files reviewed | <N of M> | <files skipped and why: sensitive, truncated, binary> |

## Limitations

<What this review could not establish: missing intent, files not read, tests not run,
self-review caveat, same-model-family caveat, agents skipped by `roles` and why.>

## Machine-readable result

```
RELAY_RESULT
{"verdict": "request_changes", "summary": "<same as Summary, one or two sentences>",
 "blocking_issues": [{"file": "<path>", "line": "<line>", "issue": "<F1 title>", "fix": "<fix>"}],
 "suggestions": ["<MEDIUM/LOW findings, one line each>"], "risk": "<low/medium/high>"}
END_RELAY_RESULT
```
