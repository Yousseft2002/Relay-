"""Command line: `relay <command>` (or `python -m relay <command>`)."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from .config import ConfigError, load_config
from .gh import GhError
from .gitops import GitError
from .smoke import smoke
from .workflows import Relay

GITIGNORE_LINE = ".relay/state/"


def doctor(cfg) -> str:
    lines = []
    tools = {"git": ["git"], "gh": ["gh"]}
    for name, agent in cfg.agents.items():
        if agent.command:
            tools[f"{name} ({agent.kind})"] = agent.command
    for label, command in tools.items():
        found = shutil.which(command[0])
        lines.append(f"{'ok ' if found else 'MISSING'}  {label}: {found or command[0]}")
    gh = shutil.which("gh")
    if gh:
        auth = subprocess.run([gh, "auth", "status"], capture_output=True, text=True)
        lines.append(f"{'ok ' if auth.returncode == 0 else 'MISSING'}  gh login"
                     + ("" if auth.returncode == 0 else ": run `gh auth login`"))
    agents_md = cfg.repo_dir / "AGENTS.md"
    lines.append(f"{'ok ' if agents_md.exists() else 'MISSING'}  AGENTS.md in {cfg.repo_dir}")
    return "\n".join(lines)


def init(relay: Relay) -> str:
    cfg = relay.cfg
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    (cfg.repo_dir / ".relay" / "prompts").mkdir(parents=True, exist_ok=True)
    gitignore = cfg.repo_dir / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if GITIGNORE_LINE not in existing.splitlines():
        with gitignore.open("a", encoding="utf-8") as fh:
            fh.write(("" if existing.endswith("\n") or not existing else "\n") + GITIGNORE_LINE + "\n")
    return relay.ensure_labels() + "\n.relay/ folders created and .relay/state/ git-ignored."


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="relay", description=(
        "Run a GitHub-backed team of coding agents: plan, build, cross-review, merge."))
    p.add_argument("--config", default="relay.toml", help="path to relay.toml (default: ./relay.toml)")
    p.add_argument("--repo-dir", default=None, help="local clone of the repo (default: config's folder)")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="check that git, gh and the agent CLIs are installed")
    sm = sub.add_parser("smoke", help="run each agent CLI headless once to check sign-in and flags")
    sm.add_argument("--agent", action="append", default=None,
                    help="only this agent (repeatable)")
    sub.add_parser("init", help="create GitHub labels and the .relay/ folders")
    plan = sub.add_parser("plan", help="turn an idea into a spec issue plus task issues")
    plan.add_argument("idea", help="the idea, in plain words (quote it)")
    plan.add_argument("--agent", default=None, help="planner agent (default: routing.planner)")
    approve = sub.add_parser("approve", help="approve a task waiting in relay:needs-approval")
    approve.add_argument("issue", type=int)
    d = sub.add_parser("dispatch", help="build the next ready task (or a given issue)")
    d.add_argument("--issue", type=int, default=None)
    r = sub.add_parser("review", help="cross-review the next PR (or a given PR)")
    r.add_argument("--pr", type=int, default=None)
    w = sub.add_parser("rework", help="fix the next PR that had changes requested")
    w.add_argument("--pr", type=int, default=None)
    sub.add_parser("merge", help="merge approved PRs that meet the auto-merge rules")
    sub.add_parser("tick", help="one full pass of the loop (for a scheduler)")
    sub.add_parser("status", help="show queues and today's usage per agent")
    sub.add_parser("pause", help="stop all automated work until resumed")
    sub.add_parser("resume", help="undo pause")
    sub.add_parser("mcp", help="run as an MCP server (for StarNet or any MCP client)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.config, args.repo_dir)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    relay = Relay(cfg)

    if args.command == "mcp":
        from .mcp_server import serve
        serve(relay)
        return 0

    actions = {
        "doctor": lambda: doctor(cfg),
        "smoke": lambda: smoke(cfg, args.agent),
        "init": lambda: init(relay),
        "plan": lambda: relay.plan(args.idea, args.agent),
        "approve": lambda: relay.approve(args.issue),
        "dispatch": lambda: relay.dispatch(args.issue),
        "review": lambda: relay.review(args.pr),
        "rework": lambda: relay.rework(args.pr),
        "merge": lambda: "\n".join(relay.merge_ready()) or "Nothing to merge.",
        "tick": relay.tick,
        "status": relay.status,
        "pause": lambda: relay.set_stop(True),
        "resume": lambda: relay.set_stop(False),
    }
    try:
        print(actions[args.command]())
    except (GhError, GitError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0
