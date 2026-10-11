"""Thin wrapper around the GitHub CLI (gh). All GitHub access goes through here."""
from __future__ import annotations

import json
import shutil
import subprocess
from typing import Callable

Runner = Callable[[list[str], str | None], str]

COPILOT_BOT = "copilot-swe-agent[bot]"

LABELS = {
    "relay:ready": ("0E8A16", "Ready for an agent to pick up"),
    "relay:needs-approval": ("FBCA04", "Waiting for a human to approve the task or spec"),
    "relay:in-progress": ("1D76DB", "An agent is working on it"),
    "relay:review": ("5319E7", "PR waiting for a cross-vendor review"),
    "relay:changes-requested": ("D93F0B", "Reviewer asked for changes"),
    "relay:approved": ("0E8A16", "Reviewer approved"),
    "relay:blocked": ("B60205", "Agent got stuck; see the handoff comment"),
    "relay:needs-human": ("B60205", "Needs your decision"),
    "relay:spec": ("C5DEF5", "Spec / epic issue"),
    "size:S": ("EDEDED", "Under ~1 hour of agent work"),
    "size:M": ("EDEDED", "A few hours of agent work"),
    "size:L": ("EDEDED", "Large or cross-cutting"),
}


class GhError(RuntimeError):
    pass


def default_runner(args: list[str], stdin: str | None = None) -> str:
    exe = shutil.which("gh")
    if exe is None:
        raise GhError("GitHub CLI 'gh' isn't installed or isn't on PATH")
    proc = subprocess.run([exe, *args], input=stdin, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise GhError(f"gh {' '.join(args[:3])} failed: {proc.stderr.strip()[-400:]}")
    return proc.stdout


class GitHub:
    def __init__(self, repo: str, runner: Runner = default_runner):
        self.repo = repo
        self.run = runner

    def _json(self, args: list[str]):
        out = self.run(args, None)
        return json.loads(out) if out.strip() else None

    # ---- labels -------------------------------------------------------------
    def ensure_labels(self, extra: dict[str, tuple[str, str]] | None = None) -> None:
        for name, (color, desc) in {**LABELS, **(extra or {})}.items():
            self.run(["label", "create", name, "-R", self.repo, "--color", color,
                      "--description", desc, "--force"], None)

    # ---- issues -------------------------------------------------------------
    def list_issues(self, label: str, state: str = "open", limit: int = 50) -> list[dict]:
        return self._json(["issue", "list", "-R", self.repo, "--label", label, "--state", state,
                           "--limit", str(limit), "--json",
                           "number,title,body,labels,assignees,state"]) or []

    def issue(self, number: int) -> dict:
        return self._json(["issue", "view", str(number), "-R", self.repo, "--json",
                           "number,title,body,labels,state,assignees"])

    def create_issue(self, title: str, body: str, labels: list[str]) -> int:
        args = ["issue", "create", "-R", self.repo, "--title", title, "--body-file", "-"]
        for label in labels:
            args += ["--label", label]
        url = self.run(args, body).strip().splitlines()[-1]
        return int(url.rstrip("/").rsplit("/", 1)[-1])

    def edit_labels(self, number: int, add: list[str] = (), remove: list[str] = (),
                    kind: str = "issue") -> None:
        args = [kind, "edit", str(number), "-R", self.repo]
        for label in add:
            args += ["--add-label", label]
        for label in remove:
            args += ["--remove-label", label]
        if add or remove:
            self.run(args, None)

    def comment(self, number: int, body: str, kind: str = "issue") -> None:
        self.run([kind, "comment", str(number), "-R", self.repo, "--body-file", "-"], body)

    def assign_copilot(self, number: int, base_branch: str, instructions: str = "") -> None:
        """Hand an issue to GitHub's Copilot cloud agent (runs in GitHub, opens a PR)."""
        payload = {
            "assignees": [COPILOT_BOT],
            "agent_assignment": {"target_repo": self.repo, "base_branch": base_branch,
                                 "custom_instructions": instructions, "custom_agent": "",
                                 "model": ""},
        }
        self.run(["api", "--method", "POST", "-H", "Accept: application/vnd.github+json",
                  f"/repos/{self.repo}/issues/{number}/assignees", "--input", "-"],
                 json.dumps(payload))

    # ---- pull requests --------------------------------------------------------
    def list_prs(self, label: str | None = None, limit: int = 50) -> list[dict]:
        args = ["pr", "list", "-R", self.repo, "--state", "open", "--limit", str(limit),
                "--json", "number,title,body,labels,headRefName,author,isDraft"]
        if label:
            args += ["--label", label]
        return self._json(args) or []

    def pr(self, number: int) -> dict:
        return self._json(["pr", "view", str(number), "-R", self.repo, "--json",
                           "number,title,body,labels,headRefName,isDraft,mergeable,"
                           "statusCheckRollup,author"])

    def pr_diff(self, number: int) -> str:
        return self.run(["pr", "diff", str(number), "-R", self.repo], None)

    def create_pr(self, head: str, base: str, title: str, body: str, labels: list[str]) -> int:
        args = ["pr", "create", "-R", self.repo, "--head", head, "--base", base,
                "--title", title, "--body-file", "-"]
        for label in labels:
            args += ["--label", label]
        url = self.run(args, body).strip().splitlines()[-1]
        return int(url.rstrip("/").rsplit("/", 1)[-1])

    def ready_pr(self, number: int) -> None:
        self.run(["pr", "ready", str(number), "-R", self.repo], None)

    def merge_pr(self, number: int) -> None:
        self.run(["pr", "merge", str(number), "-R", self.repo, "--squash", "--delete-branch"],
                 None)


PASSED = {"SUCCESS", "NEUTRAL", "SKIPPED"}
FAILED = {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"}


def checks_state(rollup: list[dict] | None) -> str:
    """Summarize CI: 'none', 'pending', 'failed' or 'green'."""
    if not rollup:
        return "none"
    pending = False
    for check in rollup:
        conclusion = (check.get("conclusion") or "").upper()
        state = (check.get("state") or "").upper()
        if conclusion in FAILED or state in FAILED:
            return "failed"
        if conclusion in PASSED or state == "SUCCESS":
            continue
        pending = True
    return "pending" if pending else "green"


def checks_green(rollup: list[dict] | None, require_ci: bool) -> bool:
    """True when every reported check passed. No checks counts as red if CI is required."""
    state = checks_state(rollup)
    return state == "green" or (state == "none" and not require_ci)


def failed_checks(rollup: list[dict] | None) -> list[str]:
    names = []
    for check in rollup or []:
        conclusion = (check.get("conclusion") or "").upper()
        state = (check.get("state") or "").upper()
        if conclusion in FAILED or state in FAILED:
            names.append(str(check.get("name") or check.get("context") or "unnamed check"))
    return names


def label_names(item: dict) -> list[str]:
    return [label["name"] if isinstance(label, dict) else str(label)
            for label in item.get("labels") or []]
