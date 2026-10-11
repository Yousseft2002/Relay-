"""Test doubles: an in-memory GitHub and a real local git repo with a bare origin."""
from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

from relay.agents import RunOutput
from relay.config import load_config


class FakeGitHub:
    def __init__(self):
        self.items: dict[int, dict] = {}   # issues and PRs share numbering, like GitHub
        self.comments: list[tuple[int, str]] = []
        self.merged: list[int] = []
        self.copilot_assigned: list[int] = []
        self.next = 1

    def _new(self, **fields) -> int:
        n = self.next
        self.next += 1
        self.items[n] = {"number": n, "state": "OPEN", "assignees": [], "labels": [], **fields}
        return n

    def ensure_labels(self, extra=None):
        pass

    def list_issues(self, label, state="open", limit=50):
        return [dict(i) for i in self.items.values() if not i.get("is_pr")
                and i["state"] == state.upper() and label in i["labels"]]

    def issue(self, number):
        return dict(self.items[number])

    def create_issue(self, title, body, labels):
        return self._new(title=title, body=body, labels=list(labels))

    def edit_labels(self, number, add=(), remove=(), kind="issue"):
        labels = self.items[number]["labels"]
        for label in remove:
            if label in labels:
                labels.remove(label)
        for label in add:
            if label not in labels:
                labels.append(label)

    def comment(self, number, body, kind="issue"):
        self.comments.append((number, body))

    def assign_copilot(self, number, base_branch, instructions=""):
        self.copilot_assigned.append(number)
        self.items[number]["assignees"] = [{"login": "Copilot"}]

    def list_prs(self, label=None, limit=50):
        return [dict(p) for p in self.items.values() if p.get("is_pr") and p["state"] == "OPEN"
                and (label is None or label in p["labels"])]

    def pr(self, number):
        return dict(self.items[number])

    def pr_diff(self, number):
        return "diff --git a/x b/x\n+hello\n"

    def create_pr(self, head, base, title, body, labels):
        return self._new(title=title, body=body, labels=list(labels), headRefName=head,
                         is_pr=True, isDraft=False, statusCheckRollup=[])

    def merge_pr(self, number):
        self.items[number]["state"] = "MERGED"
        self.merged.append(number)

    def labels(self, number):
        return self.items[number]["labels"]


def git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def make_repo(tmp: Path) -> Path:
    """A clone with an 'origin' bare remote and one commit on main."""
    origin = tmp / "origin.git"
    git(["init", "--bare", "-b", "main", str(origin)], tmp)
    seed = tmp / "seed"
    git(["clone", str(origin), str(seed)], tmp)
    git(["config", "user.email", "t@example.com"], seed)
    git(["config", "user.name", "Test"], seed)
    (seed / "README.md").write_text("# demo\n")
    (seed / "AGENTS.md").write_text("# rules\n")
    git(["add", "-A"], seed)
    git(["commit", "-m", "init"], seed)
    git(["push", "origin", "main"], seed)
    repo = tmp / "repo"
    git(["clone", str(origin), str(repo)], tmp)
    git(["config", "user.email", "t@example.com"], repo)
    git(["config", "user.name", "Test"], repo)
    return repo


CONFIG = textwrap.dedent("""
    [project]
    repo = "me/demo"
    worktree_root = "../wt"
    auto_merge_sizes = ["S"]
    require_ci = true
    max_jobs_per_tick = 2

    [routing]
    planner = "claude"
    by_size = { S = "codex", M = "codex", L = "claude" }
    fallback = ["codex", "claude"]
    reviewers = { claude = "codex", codex = "claude", copilot-cloud = "claude" }

    [agents.claude]
    kind = "claude"
    max_runs_per_day = 10
    [agents.codex]
    kind = "codex"
    max_runs_per_day = 10
    [agents.copilot-cloud]
    kind = "copilot-cloud"
""")


def make_config(repo: Path, extra: str = "", text: str = CONFIG):
    path = repo / "relay.toml"
    path.write_text(text + extra)
    return load_config(path)


class FakeRunner:
    """Stands in for run_agent. Build runs write a file; reviews return a scripted verdict."""

    def __init__(self, verdicts=("approve",), risk="low", build_status="done"):
        self.verdicts = list(verdicts)
        self.risk = risk
        self.build_status = build_status
        self.calls: list[tuple[str, str]] = []

    def __call__(self, agent, mode, prompt, cwd):
        self.calls.append((agent.name, mode))
        if mode == "build":
            (Path(cwd) / f"feature-{len(self.calls)}.txt").write_text("work\n")
            text = ('RELAY_RESULT\n{"status": "%s", "summary": "did it", "files_changed": '
                    '["feature.txt"], "tests_run": ["pytest"], "tests_passed": true, '
                    '"risk": "low"}\nEND_RELAY_RESULT' % self.build_status)
        elif mode == "review":
            verdict = self.verdicts.pop(0) if self.verdicts else "approve"
            blocking = '[{"file": "a.py", "line": "3", "issue": "bug", "fix": "fix it"}]' \
                if verdict == "request_changes" else "[]"
            text = ('RELAY_RESULT\n{"verdict": "%s", "summary": "looked", "blocking_issues": %s, '
                    '"risk": "%s"}\nEND_RELAY_RESULT' % (verdict, blocking, self.risk))
        else:  # plan
            text = ('RELAY_RESULT\n{"title": "Login", "spec_markdown": "## Goal", "tasks": ['
                    '{"title": "Set up CI", "size": "S", "body": "ci", "depends_on": []},'
                    '{"title": "Login page", "size": "M", "body": "page", "depends_on": [0]}'
                    ']}\nEND_RELAY_RESULT')
        return RunOutput(True, text, 0.5 if agent.kind == "claude" else None,
                         1000 if agent.kind == "codex" else None, 1.0, 0)
