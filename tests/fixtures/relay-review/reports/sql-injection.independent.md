# Relay Review: user search endpoint

| Field | Value |
| --- | --- |
| Verdict | request changes |
| Independence | independent |
| Author agent | claude-code (anthropic) |
| Reviewer agent | copilot (github) |
| Reviewer model | not reported |
| Scope | main (fixture) .. feature + uncommitted; 2 files |
| Base SHA | 12f1b3d568f1b07ae318f0ee5a928dbc79a9d5f6 |
| Head SHA | 5d374f7407b4041cc956142465c274fc52be53ae |
| Diff fingerprint | sha256:8a88fd4602397730af2604d300b18393ccc8593ee83944ba4d9ce04202742466 |
| Intent | Add GET /users?q= to search users by name prefix. |
| Sharing authorization | granted by repo owner on 2026-10-28: "yes, Copilot can review this branch" |
| Date | 2026-10-28 |

## Summary

The change adds a name-prefix search and wires it to `GET /users?q=`. The query is built by
string formatting from the request parameter, which allows SQL injection. Fix that before
merging. Nothing else blocks.

## Findings

### F1 [HIGH] SQL injection in search_users via the q parameter

- Location: `app/users.py:10`
- Category: security/injection
- Basis: traced
- Evidence:

  ```
  1. app/web.py:6   search_users(conn, request.args["q"])   # q comes from the URL
  2. app/users.py:10 query = f"SELECT id, name FROM users WHERE name LIKE '{name}%'"
  3. app/users.py:11 conn.execute(query)                     # executed as SQL
  ```

- Why it matters: any caller of `/users?q=` controls the SQL text, for example
  `q = x' OR '1'='1` returns every user.
- Fix: use a bound parameter:
  `conn.execute("SELECT id, name FROM users WHERE name LIKE ?", (name + "%",))`, and
  escape `%` and `_` in `name` if literal matching is intended.

### F2 [MEDIUM] No tests for the new search

- Location: `app/users.py:8`
- Category: tests
- Basis: confirmed
- Evidence: `git diff` adds `search_users` and `handle_search`; no file under `tests/` changes.
- Why it matters: the injection fix and prefix behavior have no regression test.
- Fix: add tests for a normal prefix, a quote character in `q`, and an empty `q`.

## Coverage

| Area | Checked | Notes |
| --- | --- | --- |
| Correctness | yes | |
| Security checklist | sections 1-8; 1 and 2 relevant | |
| Tests | not run: the fixture has no test suite | |
| Files reviewed | 2 of 2 | |

## Limitations

The endpoint's authentication isn't shown in this change, so who can reach it wasn't
established. That's why F1 is HIGH, not CRITICAL.

## Machine-readable result

```
RELAY_RESULT
{"verdict": "request_changes", "summary": "Search builds SQL from the q parameter (SQL injection); no tests.",
 "blocking_issues": [{"file": "app/users.py", "line": "10", "issue": "SQL injection in search_users via the q parameter", "fix": "Use a bound parameter"}],
 "suggestions": ["Add tests for search_users (F2)"], "risk": "medium"}
END_RELAY_RESULT
```
