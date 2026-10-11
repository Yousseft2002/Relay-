"""The relay loop: plan -> build -> cross-review -> rework -> merge.

GitHub Issues and PR labels are the shared state, so every step can be run by a
person, a scheduler or a manager agent, in any order, without stepping on each other.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from . import gitops, prompts
from .agents import AgentUnavailable, RunOutput, run_agent
from .config import Config
from .gh import GhError, GitHub, checks_state, failed_checks, label_names
from .gitops import GitError
from .ledger import Ledger
from .result import parse_build, parse_plan, parse_review
from .routing import (built_by, can_auto_merge, choose_builder, choose_reviewer, depends_on,
                      rework_round, size_from_labels)

CLOSES = r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+(?:[\w.-]+/[\w.-]+)?#{n}\b"
LOCK_STALE_S = 3 * 3600
IDLE = ("No ", "Nothing")


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items) if items else "- none"


class Relay:
    def __init__(self, cfg: Config, gh: GitHub | None = None, ledger: Ledger | None = None,
                 runner=run_agent):
        self.cfg = cfg
        self.gh = gh or GitHub(cfg.repo)
        self.ledger = ledger or Ledger(cfg.state_dir)
        self.runner = runner

    # ---- shared helpers -----------------------------------------------------------
    @property
    def stop_file(self) -> Path:
        return self.cfg.state_dir / "STOP"

    def stopped(self) -> bool:
        return self.stop_file.exists()

    def set_stop(self, on: bool) -> str:
        self.cfg.state_dir.mkdir(parents=True, exist_ok=True)
        if on:
            self.stop_file.write_text("Relay paused. Delete this file or run `relay resume`.\n")
            return "Relay paused: scheduled ticks will do nothing until you resume."
        self.stop_file.unlink(missing_ok=True)
        return "Relay resumed."

    def _run(self, agent: str, mode: str, prompt: str, cwd: Path, ref: str) -> RunOutput:
        try:
            out = self.runner(self.cfg.agents[agent], mode, prompt, cwd)
        except AgentUnavailable as exc:
            out = RunOutput(False, "", None, None, 0.0, -1, str(exc))
        self.ledger.append(agent=agent, kind=mode, ref=ref, ok=out.ok, usd=out.usd,
                           tokens=out.tokens, duration_s=round(out.duration_s, 1),
                           note=(out.error or "")[:200])
        return out

    def _issue_number_for_pr(self, pr: dict) -> int | None:
        m = re.match(r"relay/issue-(\d+)$", pr.get("headRefName") or "")
        if m:
            return int(m.group(1))
        m = re.search(r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)",
                      pr.get("body") or "")
        return int(m.group(1)) if m else None

    def ensure_labels(self) -> str:
        extra = {}
        for name in self.cfg.agents:
            extra[f"built-by:{name}"] = ("BFD4F2", f"Built by {name}")
            extra[f"relay:agent:{name}"] = ("C2E0C6", f"Route this task to {name}")
        for risk, color in (("low", "0E8A16"), ("medium", "FBCA04"), ("high", "B60205")):
            extra[f"risk:{risk}"] = (color, f"Reviewer rated merge risk {risk}")
        for n in range(1, self.cfg.max_rework_rounds + 1):
            extra[f"rework:{n}"] = ("EDEDED", f"Rework round {n}")
        self.gh.ensure_labels(extra)
        return f"Labels ready on {self.cfg.repo}."

    # ---- planning -------------------------------------------------------------------
    def plan(self, idea: str, agent: str | None = None) -> str:
        agent = agent or self.cfg.planner
        prompt = prompts.render("plan.md", self.cfg.prompts_dir, repo=self.cfg.repo, idea=idea)
        out = self._run(agent, "plan", prompt, self.cfg.repo_dir, ref="plan")
        if not out.ok:
            return f"Planning failed ({agent}): {out.error}"
        plan = parse_plan(out.text)
        if not plan["tasks"]:
            return f"{agent} didn't return any tasks. Raw output starts: {out.text[:300]!r}"

        spec_body = f"{plan['spec_markdown']}\n\n---\nOriginal idea:\n\n> {idea}\n\n" \
                    f"Planned by {agent}."
        spec_no = self.gh.create_issue(f"Spec: {plan['title']}", spec_body, ["relay:spec"])
        gate = "relay:needs-approval" if self.cfg.spec_approval else "relay:ready"
        numbers: dict[int, int] = {}
        for task in plan["tasks"]:
            deps = [numbers[d] for d in task["depends_on"] if d in numbers]
            body = task["body"] + f"\n\n---\nPart of #{spec_no}"
            if deps:
                body += "\nDepends on: " + ", ".join(f"#{d}" for d in deps)
            labels = [gate, f"size:{task['size']}"]
            if task["agent"] in self.cfg.agents:
                labels.append(f"relay:agent:{task['agent']}")
            numbers[task["index"]] = self.gh.create_issue(task["title"], body, labels)
        listed = ", ".join(f"#{n}" for n in numbers.values())
        state = "waiting for your approval" if self.cfg.spec_approval else "ready to build"
        return f"Spec #{spec_no} with {len(numbers)} tasks ({listed}), {state}."

    def approve(self, issue: int) -> str:
        self.gh.edit_labels(issue, add=["relay:ready"], remove=["relay:needs-approval"])
        return f"#{issue} approved and queued."

    # ---- building -----------------------------------------------------------------
    def next_ready_issue(self) -> dict | None:
        issues = self.gh.list_issues("relay:ready")
        closed_cache: dict[int, bool] = {}

        def is_closed(n: int) -> bool:
            if n not in closed_cache:
                closed_cache[n] = (self.gh.issue(n) or {}).get("state", "").upper() == "CLOSED"
            return closed_cache[n]

        for issue in sorted(issues, key=lambda i: i["number"]):
            labels = label_names(issue)
            if "relay:in-progress" in labels or issue.get("assignees"):
                continue
            if all(is_closed(d) for d in depends_on(issue.get("body") or "")):
                return issue
        return None

    def dispatch(self, issue_number: int | None = None) -> str:
        issue = self.gh.issue(issue_number) if issue_number else self.next_ready_issue()
        if not issue:
            return "Nothing ready to build."
        labels = label_names(issue)
        agent, reason = choose_builder(self.cfg, labels, self.ledger.usage_today())
        if agent is None:
            return f"#{issue['number']} waits: {reason}."
        if self.cfg.agents[agent].is_cloud:
            return self._dispatch_cloud(issue, agent, reason)
        return self._build(issue, agent, reason)

    def _dispatch_cloud(self, issue: dict, agent: str, reason: str) -> str:
        n = issue["number"]
        self.gh.assign_copilot(n, self.cfg.base_branch,
                               "Follow AGENTS.md. Keep the change scoped to this issue and "
                               "include tests. Reference this issue with 'Fixes #%d'." % n)
        self.gh.edit_labels(n, add=["relay:in-progress", f"built-by:{agent}"],
                            remove=["relay:ready"])
        self.ledger.append(agent=agent, kind="build", ref=f"#{n}", ok=True, note="cloud")
        return f"#{n} handed to GitHub's cloud agent ({reason}). Its PR is picked up on a later tick."

    def _build(self, issue: dict, agent: str, reason: str, branch: str | None = None,
               pr_number: int | None = None, feedback: str = "") -> str:
        n, title = issue["number"], issue["title"]
        branch = branch or gitops.branch_for(n)
        if pr_number is None:
            self.gh.edit_labels(n, add=["relay:in-progress"], remove=["relay:ready"])
        wt = gitops.prepare_worktree(self.cfg.repo_dir, self.cfg.worktree_root, branch,
                                     self.cfg.base_branch)
        handoff_path = wt / ".relay" / "handoffs" / f"issue-{n}.md"

        context = []
        if handoff_path.exists():
            context.append("## Previous handoff on this task\n\n" +
                           prompts.truncate(handoff_path.read_text(encoding="utf-8"), 6000))
        if feedback:
            context.append("## Review feedback you must address\n\n" + feedback)
        prompt = prompts.render("build.md", self.cfg.prompts_dir, repo=self.cfg.repo,
                                issue_number=n, issue_title=title,
                                issue_body=prompts.truncate(issue.get("body") or "", 20000),
                                context="\n\n".join(context))

        out = self._run(agent, "build", prompt, wt, ref=f"#{n}")
        res = parse_build(out.text) if out.ok else {
            **parse_build(""), "summary": f"Agent run failed: {out.error}"}
        handoff = prompts.render(
            "handoff.md", self.cfg.prompts_dir, issue_number=n, issue_title=title, agent=agent,
            status=res["status"], risk=res["risk"], tests_passed=res["tests_passed"],
            summary=res["summary"], files_changed=_bullets(res["files_changed"]),
            tests_run=_bullets(res["tests_run"]), decisions=_bullets(res["decisions"]),
            open_questions=_bullets(res["open_questions"]), next_step=res["next_step"] or "-")
        handoff_path.parent.mkdir(parents=True, exist_ok=True)
        handoff_path.write_text(handoff, encoding="utf-8")

        if res["status"] == "done":
            pushed = gitops.commit_and_push(wt, branch, f"relay: #{n} {title} ({agent})")
            if not pushed and not gitops.changed_files(wt, self.cfg.base_branch):
                res["status"] = "failed"
                res["summary"] = "Agent reported done but changed no files."
        else:
            gitops.commit_and_push(wt, branch, f"relay: #{n} partial work ({agent}, {res['status']})")

        size = size_from_labels(label_names(issue))
        if res["status"] == "done":
            body = f"Closes #{n}\n\n{handoff}\n\n---\nBuilt by **{agent}** ({reason})."
            if pr_number is None:
                pr_number = self.gh.create_pr(branch, self.cfg.base_branch, f"{title} (#{n})",
                                              body, ["relay:review", f"built-by:{agent}",
                                                     f"size:{size}"])
            else:
                self.gh.comment(pr_number, f"Rework by **{agent}**:\n\n{handoff}", kind="pr")
                self.gh.edit_labels(pr_number, add=["relay:review", f"built-by:{agent}"],
                                    remove=["relay:changes-requested"], kind="pr")
            return f"#{n} built by {agent}; PR #{pr_number} is waiting for review."

        self.gh.comment(n, f"**{agent}** stopped with status `{res['status']}`.\n\n{handoff}")
        self.gh.edit_labels(n, add=["relay:blocked", "relay:needs-human"],
                            remove=["relay:in-progress"])
        if pr_number is not None:
            self.gh.edit_labels(pr_number, add=["relay:needs-human"],
                                remove=["relay:changes-requested"], kind="pr")
        return f"#{n} {res['status']} ({agent}): {res['summary'][:200]}"

    # ---- cloud PR pickup ------------------------------------------------------------
    def sync_cloud_prs(self) -> list[str]:
        """Label finished PRs from GitHub's cloud agent so they enter review."""
        cloud = [a for a, c in self.cfg.agents.items() if c.is_cloud]
        if not cloud:
            return []
        notes = []
        open_prs = None
        for agent in cloud:
            for issue in self.gh.list_issues(f"built-by:{agent}"):
                if "relay:in-progress" not in label_names(issue):
                    continue
                if open_prs is None:
                    open_prs = self.gh.list_prs()
                pattern = re.compile(CLOSES.format(n=issue["number"]))
                for pr in open_prs:
                    pr_labels = label_names(pr)
                    if pr.get("isDraft") or any(l.startswith("relay:") for l in pr_labels):
                        continue
                    if pattern.search(pr.get("body") or "") or pattern.search(pr.get("title") or ""):
                        size = size_from_labels(label_names(issue))
                        self.gh.edit_labels(pr["number"], kind="pr", add=[
                            "relay:review", f"built-by:{agent}", f"size:{size}"])
                        notes.append(f"Cloud PR #{pr['number']} for #{issue['number']} queued for review.")
        return notes

    # ---- review -------------------------------------------------------------------------
    def _review_file(self, pr: int) -> Path:
        return self.cfg.state_dir / "reviews" / f"pr-{pr}.json"

    def review(self, pr_number: int | None = None) -> str:
        if pr_number is None:
            queue = [p for p in self.gh.list_prs("relay:review") if not p.get("isDraft")]
            if not queue:
                return "No pull requests waiting for review."
            pr_number = min(p["number"] for p in queue)
        pr = self.gh.pr(pr_number)
        labels = label_names(pr)
        author = built_by(labels) or "unknown"
        reviewer, reason = choose_reviewer(self.cfg, author, self.ledger.usage_today())
        if reviewer is None:
            return f"PR #{pr_number} waits: {reason}."

        issue_no = self._issue_number_for_pr(pr)
        issue = self.gh.issue(issue_no) if issue_no else {}
        rollup = pr.get("statusCheckRollup") or []
        checks = "\n".join(f"- {c.get('name') or c.get('context')}: "
                           f"{c.get('conclusion') or c.get('state') or 'pending'}"
                           for c in rollup) or "- no CI checks reported"
        wt = gitops.prepare_worktree(self.cfg.repo_dir, self.cfg.worktree_root,
                                     pr["headRefName"], self.cfg.base_branch)
        prompt = prompts.render(
            "review.md", self.cfg.prompts_dir, repo=self.cfg.repo, author=author,
            pr_number=pr_number, pr_title=pr.get("title", ""),
            issue_body=prompts.truncate((issue or {}).get("body") or "(no linked issue)", 12000),
            handoff=prompts.truncate(pr.get("body") or "", 8000), checks=checks,
            diff=prompts.truncate(self.gh.pr_diff(pr_number), 60000, "diff truncated"))

        out = self._run(reviewer, "review", prompt, wt, ref=f"PR #{pr_number}")
        if not out.ok:
            return f"Review of PR #{pr_number} by {reviewer} failed: {out.error}. Will retry."
        res = parse_review(out.text)
        self._review_file(pr_number).parent.mkdir(parents=True, exist_ok=True)
        self._review_file(pr_number).write_text(json.dumps({**res, "reviewer": reviewer}),
                                                encoding="utf-8")

        issues_md = "\n".join(
            f"- **{i['file']}{':' + i['line'] if i['line'] else ''}** {i['issue']}"
            + (f" Fix: {i['fix']}" if i["fix"] else "") for i in res["blocking_issues"]) or "- none"
        self.gh.comment(pr_number, kind="pr", body=(
            f"### Review by {reviewer}: {res['verdict'].replace('_', ' ')} "
            f"(risk: {res['risk']})\n\n{res['summary']}\n\n**Blocking issues**\n{issues_md}\n\n"
            f"**Suggestions**\n{_bullets(res['suggestions'])}"))

        remove = ["relay:review"] + [f"risk:{r}" for r in ("low", "medium", "high")]
        if res["verdict"] == "approve":
            self.gh.edit_labels(pr_number, kind="pr", add=["relay:approved", f"risk:{res['risk']}"],
                                remove=remove)
            return f"PR #{pr_number} approved by {reviewer} (risk {res['risk']})."

        rounds = rework_round(labels)
        if rounds >= self.cfg.max_rework_rounds:
            self.gh.edit_labels(pr_number, kind="pr", add=["relay:needs-human"], remove=remove)
            return f"PR #{pr_number} still has blocking issues after {rounds} reworks; needs you."
        self.gh.edit_labels(pr_number, kind="pr",
                            add=["relay:changes-requested", f"rework:{rounds + 1}"],
                            remove=remove + ([f"rework:{rounds}"] if rounds else []))
        return f"PR #{pr_number}: {reviewer} requested changes ({len(res['blocking_issues'])} blocking)."

    # ---- rework ---------------------------------------------------------------------------
    def rework(self, pr_number: int | None = None) -> str:
        if pr_number is None:
            queue = self.gh.list_prs("relay:changes-requested")
            if not queue:
                return "No pull requests waiting for rework."
            pr_number = min(p["number"] for p in queue)
        pr = self.gh.pr(pr_number)
        labels = label_names(pr)
        author = built_by(labels)
        usage = self.ledger.usage_today()

        # Cloud-built PRs are reworked by a local agent on the same branch.
        agent = author
        if not agent or agent not in self.cfg.agents or self.cfg.agents[agent].is_cloud:
            agent, _ = choose_builder(self.cfg, ["size:M"], usage)
            if agent and self.cfg.agents[agent].is_cloud:
                agent = next((a for a in self.cfg.fallback if not self.cfg.agents[a].is_cloud), None)
        if not agent:
            return f"PR #{pr_number} waits: no local agent has budget for rework."

        feedback = ""
        review_file = self._review_file(pr_number)
        if review_file.exists():
            r = json.loads(review_file.read_text(encoding="utf-8"))
            feedback = "\n".join(f"- {i['file']} {i['line']}: {i['issue']} (fix: {i['fix']})"
                                 for i in r.get("blocking_issues", [])) or r.get("summary", "")
        rollup = pr.get("statusCheckRollup") or []
        if checks_state(rollup) == "failed":
            feedback += "\n- CI failed: " + ", ".join(failed_checks(rollup))

        issue_no = self._issue_number_for_pr(pr)
        issue = self.gh.issue(issue_no) if issue_no else {
            "number": pr_number, "title": pr.get("title", ""), "body": pr.get("body", ""),
            "labels": pr.get("labels", [])}
        if author and author != agent:
            self.gh.edit_labels(pr_number, kind="pr", remove=[f"built-by:{author}"])
        return self._build(issue, agent, "rework", branch=pr["headRefName"],
                           pr_number=pr_number, feedback=feedback or "See the review comment.")

    # ---- merge ---------------------------------------------------------------------------
    def merge_ready(self) -> list[str]:
        notes = []
        for item in self.gh.list_prs("relay:approved"):
            pr = self.gh.pr(item["number"])
            labels = label_names(pr)
            risk = next((l.split(":", 1)[1] for l in labels if l.startswith("risk:")), "high")
            rollup = pr.get("statusCheckRollup") or []
            ci = checks_state(rollup)
            if ci == "pending":
                continue
            if ci == "failed":
                self._review_file(pr["number"]).parent.mkdir(parents=True, exist_ok=True)
                self._review_file(pr["number"]).write_text(json.dumps({
                    "summary": "CI failed", "blocking_issues": [
                        {"file": "", "line": "", "issue": f"Check failed: {name}",
                         "fix": "Make this check pass"} for name in failed_checks(rollup)]}),
                    encoding="utf-8")
                self.gh.edit_labels(pr["number"], kind="pr", add=["relay:changes-requested"],
                                    remove=["relay:approved"])
                notes.append(f"PR #{pr['number']}: CI failed, sent back for rework.")
                continue
            green = ci == "green" or (ci == "none" and not self.cfg.require_ci)
            ok, reason = can_auto_merge(self.cfg, labels, risk, green)
            if not ok and ci == "none" and self.cfg.require_ci:
                reason = "no CI checks run on this repo yet, so it can't auto-merge"
            if ok:
                self.gh.merge_pr(pr["number"])
                self.ledger.append(agent="relay", kind="merge", ref=f"PR #{pr['number']}", ok=True)
                gitops.remove_worktree(self.cfg.repo_dir, self.cfg.worktree_root /
                                       pr["headRefName"].replace("/", "-"))
                notes.append(f"Merged PR #{pr['number']} ({reason}).")
            elif "relay:needs-human" not in labels:
                self.gh.edit_labels(pr["number"], kind="pr", add=["relay:needs-human"])
                self.gh.comment(pr["number"], kind="pr",
                                body=f"Ready for your merge decision: {reason}.")
                notes.append(f"PR #{pr['number']} needs your merge: {reason}.")
        return notes

    # ---- the loop ----------------------------------------------------------------------
    def _lock(self) -> bool:
        lock = self.cfg.state_dir / "tick.lock"
        self.cfg.state_dir.mkdir(parents=True, exist_ok=True)
        if lock.exists() and time.time() - lock.stat().st_mtime < LOCK_STALE_S:
            return False
        lock.write_text(str(time.time()))
        return True

    def _unlock(self) -> None:
        (self.cfg.state_dir / "tick.lock").unlink(missing_ok=True)

    def tick(self) -> str:
        """One pass of the loop. Safe to run every 15-30 minutes from a scheduler."""
        if self.stopped():
            return "Relay is paused (STOP file present). Nothing done."
        if not self._lock():
            return "Another tick is still running. Nothing done."
        report: list[str] = []
        try:
            report += self.sync_cloud_prs()
            report += self.merge_ready()
            for step in (self.review, self.rework, self.dispatch):
                for _ in range(self.cfg.max_jobs_per_tick):
                    if self.stopped():
                        break
                    msg = step()
                    if msg.startswith(IDLE):
                        break  # queue empty
                    report.append(msg)
                    if " waits" in msg or "Will retry" in msg:
                        break  # out of budget or a transient failure: try next tick
        except (GhError, GitError) as exc:
            report.append(f"ERROR: tick stopped early: {exc}")
        finally:
            self._unlock()
        text = "\n".join(report) or "Nothing to do."
        stamp = time.strftime("%Y-%m-%d %H:%M")
        (self.cfg.state_dir / "last-tick.txt").write_text(f"[{stamp}]\n{text}\n", encoding="utf-8")
        return text

    def tick_running(self) -> bool:
        lock = self.cfg.state_dir / "tick.lock"
        return lock.exists() and time.time() - lock.stat().st_mtime < LOCK_STALE_S

    def last_tick(self) -> str:
        path = self.cfg.state_dir / "last-tick.txt"
        return path.read_text(encoding="utf-8").strip() if path.exists() else "No tick has run yet."

    def status(self) -> str:
        lines = [f"Relay for {self.cfg.repo} ({'PAUSED' if self.stopped() else 'running'}, "
                 f"autonomy: {self.cfg.autonomy})", ""]
        for label in ("relay:needs-approval", "relay:ready", "relay:in-progress",
                      "relay:blocked", "relay:needs-human"):
            items = self.gh.list_issues(label)
            lines.append(f"Issues {label:22} {len(items):3}  " +
                         " ".join(f"#{i['number']}" for i in items[:10]))
        for label in ("relay:review", "relay:changes-requested", "relay:approved",
                      "relay:needs-human"):
            items = self.gh.list_prs(label)
            lines.append(f"PRs    {label:22} {len(items):3}  " +
                         " ".join(f"#{i['number']}" for i in items[:10]))
        lines += ["", "Today's usage:"]
        usage = self.ledger.usage_today()
        for name, agent in self.cfg.agents.items():
            u = usage.get(name, {})
            cap = f"/{agent.max_runs_per_day} runs"
            usd = f", ${u.get('usd', 0):.2f}" + (f"/${agent.max_usd_per_day:.2f}"
                                                  if agent.max_usd_per_day else "")
            tokens = f", {int(u.get('tokens', 0)):,} tokens" if u.get("tokens") else ""
            lines.append(f"  {name:14} {int(u.get('runs', 0))}{cap}{usd}{tokens}")
        lines += ["", "A tick is running now." if self.tick_running() else "No tick running.",
                  "Last tick report:", self.last_tick()]
        return "\n".join(lines)
