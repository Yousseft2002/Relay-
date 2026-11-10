# Independent and multi-agent review

## What "independent" means here

| Header value | Who reviewed | Counts as independent? |
| --- | --- | --- |
| `independent` | A different agent, from a different vendor than the author | Yes |
| `not independent (same vendor)` | A different agent or subagent from the author's vendor | No |
| `not independent (self-review)` | The same agent that wrote the change | No |

A second pass, a fresh session or a subagent of the same product is still `not independent`.
Those reviews are useful, but they can share the author's blind spots, so the report must not
claim otherwise. If both agents run the same underlying model family (for example, a
Copilot model picker set to the author's model family), say so under Limitations: the
agents are independent, the model isn't.

## Roles are configuration, not code

Nobody is the permanent lead. Roles come from `relay-review.toml` in the repo root (copy
[../assets/roles.example.toml](../assets/roles.example.toml)):

```toml
[agents.<id>]
vendor = "<company>"                      # required; independence is judged by vendor
capabilities = ["lead", "implement", "review", "security-review"]
available = true                          # false = skip until changed
available_from = 2026-10-31               # optional TOML date: skip before this day
model_family = "<family>"                 # optional; flags same-model pairs
invoke = "manual"                         # how the reviewer is started (see below)

[assign]
lead = "<id>"                             # or a list, in order of preference
implement = "<id>"
review = ["<id>", "<id>"]                 # first eligible one wins
```

`python scripts/relay_review.py roles --author <id>` resolves this for today: who holds
`lead` and `implement`, and which reviewer is eligible for that author (has `review`,
isn't the author, has another vendor, is available). To reassign a role, edit the file;
the skill never assumes a particular agent.

## Lead side: handing the review off

Only after the user said yes to the authorization question in SKILL.md step 2:

1. Build the bundle: `python scripts/relay_review.py bundle --base <ref>`.
2. Copy [../assets/handoff-template.md](../assets/handoff-template.md) to
   `.relay-review/handoff-<YYYY-MM-DD>-<short-scope>.md` and fill it in. Under
   "Sharing authorization", record what the user said and the date. Don't paraphrase a
   "maybe" into a "yes".
3. Tell the user how to start the reviewer:
   - `invoke = "manual"` (the default): open the reviewer agent in this same repository
     (for example GitHub Copilot in VS Code or the Copilot CLI, or Codex) with the skill
     installed, and say: *"Use the relay-review skill. You are the reviewer described in
     `.relay-review/handoff-....md`."*
   - `invoke = "command"` with `command = [...]` set in the roles file: show the user the
     exact command and run it only after a second, explicit yes. Use only the command the
     user configured; don't add flags.
4. **Stop.** Never write, edit or "pre-fill" the reviewer's report, and never put another
   agent's name in a report you wrote.
5. When the reviewer's report exists, you may run `check-report --repo .` on it and summarize it for
   the user, keeping each finding attributed to the reviewer. If you disagree with a finding,
   add an "Author response" note in your own message. Don't change the reviewer's findings or verdict.

## Reviewer side: when you are handed a review

1. Read the handoff file. Check that you are the agent it names. If you are the author, or
   from the author's vendor, say so and write the report as `not independent`.
2. Your scope is the bundle named in the handoff. You may read other files in the
   repository for context, except the sensitive files listed in the bundle's header.
3. Follow SKILL.md steps 4 to 7. In the header: `Author agent` from the handoff,
   `Reviewer agent` is you with your vendor, `Independence: independent`, and
   `Sharing authorization` copied from the handoff.
4. Copy `Base SHA`, `Head SHA` and `Diff fingerprint` from the handoff into the report. Write
   the report to the path the handoff gives, run `check-report --repo .`, and stop. A `stale`
   result means the code changed after the handoff: say so and ask for a new handoff.

## Multi-agent review

When several agents are available:

- **Specialist passes** (security, correctness, tests) can run as parallel subagents of the
  same agent. They improve coverage, but the result is still `not independent` unless an
  agent from another vendor wrote it.
- **Several independent reviewers:** each writes its own report. A combined summary lists
  every finding with the reviewer that found it, takes the most severe verdict, and keeps
  the original reports unchanged.
- If reviewers disagree, show both views. Don't average them or drop the minority.

## Fallback when no one else is available

Write a self-review (SKILL.md step 2, self-review path). In Limitations, say which agents were
skipped and why (the `skipped` list from `roles`), and recommend an independent review
before merging anything rated `medium` risk or above. A self-review never becomes
independent later. Run a new review instead.

## With the Relay CLI

Relay's own loop (`relay review`) already starts a reviewer from another vendor and parses
the `RELAY_RESULT` block. Reports from this skill end with the same block, so Relay can read
them too.

## Known limits

- The reviewer identity in a report is what the reviewing agent declares. A report can't
  prove which model wrote it. Keep handoffs and reports under `.relay-review/` and run reviews
  yourself, or through Relay, so you know who ran them.
- Rules 2 and 3 in SKILL.md are instructions. A reviewer agent working in the same checkout
  could still open excluded files if it ignores them. For sensitive repos, review from a
  clone that doesn't contain those files.
