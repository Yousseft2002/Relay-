"""Adapters that run each coding agent headless and normalize its output.

Every agent gets its prompt on stdin. Each adapter returns the agent's final
text plus whatever usage numbers that CLI reports.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .config import AgentConfig


@dataclass
class RunOutput:
    ok: bool
    text: str
    usd: float | None
    tokens: int | None
    duration_s: float
    returncode: int
    error: str | None = None


class AgentUnavailable(RuntimeError):
    pass


def resolve_command(command: list[str]) -> list[str]:
    """Resolve the executable so Windows .cmd shims (npm installs) are found."""
    if not command:
        raise AgentUnavailable("no command configured")
    exe = shutil.which(command[0])
    if exe is None:
        raise AgentUnavailable(f"'{command[0]}' isn't installed or isn't on PATH")
    return [exe, *command[1:]]


def _claude_output(stdout: str) -> tuple[str, float | None, bool, str | None]:
    try:
        data = json.loads(stdout.strip().splitlines()[-1]) if stdout.strip() else {}
    except (json.JSONDecodeError, IndexError):
        return stdout, None, False, "couldn't parse Claude Code JSON output"
    text = str(data.get("result") or "")
    usd = data.get("total_cost_usd")
    is_error = bool(data.get("is_error"))
    return text, float(usd) if isinstance(usd, (int, float)) else None, not is_error, \
        (text[:300] if is_error else None)


def _codex_output(stdout: str, last_message: Path) -> tuple[str, int | None]:
    tokens = 0
    seen_usage = False
    messages: list[str] = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
            usage = event["usage"]
            tokens += int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))
            seen_usage = True
        item = event.get("item") or {}
        if item.get("type") == "agent_message" and item.get("text"):
            messages.append(item["text"])
    text = ""
    if last_message.exists():
        text = last_message.read_text(encoding="utf-8", errors="replace")
    if not text and messages:
        text = messages[-1]
    return text, tokens if seen_usage else None


def run_agent(agent: AgentConfig, mode: str, prompt: str, cwd: Path,
              env: dict[str, str] | None = None) -> RunOutput:
    """Run one agent in `cwd`. mode is 'build', 'review' or 'plan'."""
    if agent.is_cloud:
        raise AgentUnavailable(f"{agent.name} runs in GitHub's cloud; dispatch it through GitHub")
    base = resolve_command(agent.command)

    with tempfile.TemporaryDirectory(prefix="relay-", ignore_cleanup_errors=True) as tmp:
        last_message = Path(tmp) / "last_message.txt"
        args = [a.replace("{last_message_file}", str(last_message)) for a in agent.args[mode]]
        start = time.monotonic()
        try:
            proc = subprocess.run(
                [*base, *args],
                input=prompt,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=agent.timeout_min * 60,
                env={**os.environ, **(env or {})},
            )
        except subprocess.TimeoutExpired:
            return RunOutput(False, "", None, None, time.monotonic() - start, -1,
                             f"timed out after {agent.timeout_min} min")
        duration = time.monotonic() - start
        stdout, stderr = proc.stdout or "", proc.stderr or ""

        usd: float | None = None
        tokens: int | None = None
        error: str | None = None
        ok = proc.returncode == 0
        if agent.kind == "claude":
            text, usd, parsed_ok, error = _claude_output(stdout)
            ok = ok and parsed_ok
        elif agent.kind == "codex":
            text, tokens = _codex_output(stdout, last_message)
        else:  # copilot (local CLI)
            text = stdout

    if not ok and not error:
        error = (stderr.strip() or text.strip() or f"exit code {proc.returncode}")[-500:]
    return RunOutput(ok, text, usd, tokens, duration, proc.returncode, error)
