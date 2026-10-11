# First run: make Relay real

This walks you from zero to a working loop on a throwaway practice repo, then to a real
project. Plan on about an hour the first time. All commands are for Windows PowerShell.

Use `py -m relay ...` everywhere. It works even if pip didn't put `relay.exe` on your PATH.

The whole loop has already been run once with the real Claude Code CLI (plan, build,
review) against a real git repo, with GitHub simulated. What's left to prove is your
machine, your sign-ins, Codex, and real GitHub.

---

## Step 1 — Install the tools (10 min)

```powershell
winget install Python.Python.3.12
winget install Git.Git
winget install GitHub.cli
# open a NEW PowerShell window so PATH picks these up
gh auth login                      # choose GitHub.com, HTTPS, log in with browser
git config --global user.name  "Your Name"
git config --global user.email "you@example.com"
```

Then sign in once to each agent, interactively, so headless runs work later:

- Codex: `npm install -g @openai/codex`, then run `codex`, sign in, `/exit`.
- Claude Code: install it (see https://code.claude.com/docs/en/overview), then run `claude`
  once and sign in.
- Copilot CLI is optional. The Copilot cloud agent needs nothing installed locally.

## Step 2 — Install Relay (2 min)

```powershell
cd C:\code
git clone https://github.com/Yousseft2002/Relay-.git
cd Relay-
py -m pip install -e .
py -m relay --help
py -m unittest discover -s tests -t .     # should end with OK
```

## Step 3 — Create the practice repo (5 min)

The practice project lives in `examples/relay-sandbox`: one function, three tests, and
GitHub Actions CI. Copy it out into its own repo:

```powershell
Copy-Item -Recurse C:\code\Relay-\examples\relay-sandbox C:\code\relay-sandbox
cd C:\code\relay-sandbox
notepad relay.toml          # change YOUR-GITHUB-USERNAME to your username, save
git init -b main
git add -A
git commit -m "Practice project for Relay"
gh repo create relay-sandbox --private --source . --push
```

Open the repo on GitHub and check the **Actions** tab: the CI workflow should run and
pass on `main`. Relay never auto-merges without green CI, so this matters.

Optional: in the repo's Settings > Branches, protect `main` (require a pull request and
passing checks) if GitHub offers it for your plan. Relay doesn't push to `main` either way.

## Step 4 — Smoke test the agents (3 min, ~$0.30)

From `C:\code\relay-sandbox`:

```powershell
py -m relay doctor
py -m relay smoke
```

`smoke` runs each agent CLI headless twice (read-only flags, then build flags) in a
throwaway folder and asks it to reply "pong". Nothing touches GitHub. Expected output
(the Claude lines are from a real run; your times and costs will differ):

```
ok       claude (review flags): 3s, $0.073
ok       claude (build flags): 3s, $0.062
ok       codex (review flags): <seconds>, <n> tokens
ok       codex (build flags): <seconds>, <n> tokens
skip     copilot: disabled in relay.toml
skip     copilot-cloud: runs on GitHub; it's tested by your first cloud dispatch

All agents ready.
```

Don't continue until both agents say `ok`. Fixes for common failures are under
"Troubleshooting" at the end.

## Step 5 — Set up the repo for Relay (1 min)

```powershell
py -m relay init
git add .gitignore
git commit -m "Ignore relay state" ; git push
```

`init` creates the `relay:*`, `size:*`, `built-by:*` and `risk:*` labels on GitHub. Check
the repo's Issues > Labels page to see them.

## Step 6 — Test `relay plan` (2–4 min, ~$0.30)

```powershell
py -m relay plan "Add a command-line tool: python -m textstats FILE prints the file's word, line and character counts. At most 2 tasks."
```

Expected: `Spec #1 with 2 tasks (#2, #3), ready to build.`

Check on GitHub:
- Issue #1 "Spec: ..." with the `relay:spec` label holds the spec.
- Issues #2 and #3 each have a goal, acceptance criteria, `relay:ready` and a `size:` label.
- If #3 needs #2's code, its body ends with `Depends on: #2`. Relay won't start #3 until
  #2 is merged.

Not happy with the split? Close the issues and run `plan` again with clearer words.

## Step 7 — Run the loop one step at a time (15–25 min)

Doing each step by hand first shows you exactly what `tick` will do later.

```powershell
py -m relay dispatch        # builds the next ready task
```
Expected after 2–10 minutes: `#2 built by codex; PR #4 is waiting for review.` Open
PR #4 on GitHub. It contains the change, a `.relay/handoffs/issue-2.md` handoff, and
labels `relay:review`, `built-by:codex`, `size:S`. CI starts running on it.

```powershell
py -m relay review          # the other vendor reviews it
```
Expected: `PR #4 approved by claude (risk low).` or `... requested changes`. The review
is posted as a PR comment.

If changes were requested:
```powershell
py -m relay rework          # the builder fixes the same PR
py -m relay review
```

Once the PR is approved and CI is green on the PR (check its Checks tab):
```powershell
py -m relay merge
```
Expected: `Merged PR #4 (approved, small, low risk, CI green).` Issue #2 closes itself.
If CI is still running, `merge` does nothing; run it again in a minute.

```powershell
py -m relay status          # queues, today's usage, last tick
```

## Step 8 — Test `relay tick` (10–20 min)

Now let one command do all of that:

```powershell
py -m relay tick
```

A tick runs in order: pick up finished cloud PRs, merge what qualifies, review, rework,
then start new builds. With `max_jobs_per_tick = 1` it does at most one of each.
Run it a few times, a few minutes apart, until #3 is merged:

```powershell
py -m relay tick ; py -m relay status
```

At that point `python -m textstats README.md` should work in a fresh pull of `main`. That's
a feature planned, built, reviewed and merged by agents.

## Step 9 — Test the safety rails (10 min)

Blocked task (should come back to you, not guess):
```powershell
gh issue create --title "Choose a database for textstats" --body "Pick the best database for storing stats." --label relay:ready --label size:M
py -m relay dispatch
```
Expected (usually): the agent stops with `blocked`, the issue gets `relay:needs-human`, and a
comment lists its questions. If it just picks a database instead, tighten the "stop and
ask" rule in AGENTS.md; that's exactly the kind of thing this step is for.

Pause:
```powershell
py -m relay pause
py -m relay tick            # -> "Relay is paused ... Nothing done."
py -m relay resume
```

Your morning inbox: on GitHub, filter issues and PRs by the label `relay:needs-human`.

## Step 10 — Test the cloud lane (15–30 min)

1. Make sure the Copilot cloud agent is enabled for `relay-sandbox` in your GitHub Copilot
   settings.
2. In `relay.toml`, change `S = "codex"` to `S = "copilot-cloud"`.
3. Create a small task and dispatch it:
   ```powershell
   gh issue create --title "Add a --version flag" --body "python -m textstats --version prints 0.1.0. Add a test." --label relay:ready --label size:S
   py -m relay dispatch     # -> "handed to GitHub's cloud agent"
   ```
4. Copilot opens a draft PR on GitHub and works on it. When it marks the PR ready, run
   `py -m relay tick`. Relay labels it, Codex reviews it, and it merges if it qualifies.

If the PR doesn't get picked up, check that its description says `Fixes #<issue>`. If not,
add the labels `relay:review` and `built-by:copilot-cloud` to the PR yourself.

## Step 11 — One night on the practice repo

```powershell
cd C:\code\Relay-
powershell -ExecutionPolicy Bypass -File .\night-shift.ps1 -RepoDir "C:\code\relay-sandbox"
```

Give it a few ready issues (or one `relay plan`) before bed. In the morning, read
`C:\code\relay-sandbox\.relay\state\night-shift.log` and check `relay:needs-human`.

Leave the computer on and signed in: the scheduled task runs as you, using your agent
sign-ins.

## Step 12 — Move to a real project (MaterialOS)

1. Copy `relay.example.toml` into the MaterialOS repo as `relay.toml` and set `repo`.
2. Paste `AGENTS.relay.md` into MaterialOS's `AGENTS.md` (under the existing rules).
3. Make sure MaterialOS has CI that runs its tests on pull requests.
4. Start with `autonomy = "gated"` for the first week, so nothing merges without you.
5. `py -m relay smoke`, `py -m relay init`, then plan one small feature and run ticks by hand.
6. Switch to `"auto"` once a week of PRs has looked right.

---

## Troubleshooting

| What you see | Fix |
| --- | --- |
| `'claude' isn't installed or isn't on PATH` | Open a new PowerShell window after installing. Check with `where.exe claude`. |
| `smoke` claude FAIL mentioning permission mode | Your plan may not offer auto mode. In `relay.toml` under `[agents.claude]`, add the `build_args` line shown in `relay.example.toml` (acceptEdits). |
| `smoke` codex FAIL about sign-in | Run `codex` interactively once and sign in. |
| `smoke` codex FAIL about the sandbox on Windows | Check Codex's Windows setup docs, or run Codex and Relay inside WSL. |
| `gh ... failed: ... authentication` | `gh auth login`, then `gh auth status`. |
| `label ... not found` when planning | You skipped `py -m relay init`. |
| `git push failed` | Check `git remote -v` points at GitHub and that `gh auth login` used HTTPS. |
| `#N waits: every agent is disabled or over today's budget` | Raise `max_runs_per_day` in `relay.toml`, or wait until tomorrow. |
| Agent reported done but changed no files | Make the issue more specific: what file, what behavior, what test. |
| Review keeps requesting changes | After 2 rounds it goes to `relay:needs-human`. Read the review comments and edit the issue, or fix it yourself. |
| `Another tick is still running` | A tick is still working (they can take 30+ minutes). If none is, delete `.relay\state\tick.lock`. |
| `merge` does nothing | CI is still running or failed, or the PR is bigger than size S. `py -m relay status` explains. |

When something breaks, open the Relay repo in Claude Code and paste the full error. The
code is small enough to read end to end.
