"""`relay smoke`: check that each agent CLI runs headless with relay's flags.

Runs every local agent twice (read-only review flags and build flags) in a throwaway
git folder with a prompt that asks for no file changes. Nothing touches GitHub or
your repo, and these runs don't count toward daily budgets.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from . import gitops
from .agents import AgentUnavailable, run_agent
from .config import Config
from .result import parse_build

PROMPT = """This is a connectivity test from a tool called Relay.
Do not read, create or change any files, and do not run any commands.
Reply with exactly these three lines and nothing else:
RELAY_RESULT
{"status": "done", "summary": "pong"}
END_RELAY_RESULT
"""

HINTS = {
    "claude": "Run `claude` once to sign in. If the error mentions the permission mode, your "
              "plan may not offer auto mode: use the acceptEdits build_args shown in "
              "relay.example.toml.",
    "codex": "Run `codex` once to sign in. If it complains about the sandbox on Windows, see "
             "the Codex Windows docs or run relay from WSL.",
    "copilot": "Run `copilot` once to sign in. If it rejects a flag, adjust build_args to "
               "match `copilot --help` on your version.",
}


def _usage(out) -> str:
    bits = [f"{out.duration_s:.0f}s"]
    if out.usd is not None:
        bits.append(f"${out.usd:.3f}")
    if out.tokens is not None:
        bits.append(f"{out.tokens:,} tokens")
    return ", ".join(bits)


def smoke(cfg: Config, only: list[str] | None = None, runner=run_agent) -> str:
    lines: list[str] = []
    failures = 0
    for name, agent in cfg.agents.items():
        if only and name not in only:
            continue
        if agent.is_cloud:
            lines.append(f"skip     {name}: runs on GitHub; it's tested by your first cloud dispatch")
            continue
        if not agent.enabled:
            lines.append(f"skip     {name}: disabled in relay.toml")
            continue
        for mode in ("review", "build"):
            with tempfile.TemporaryDirectory(prefix="relay-smoke-", ignore_cleanup_errors=True) as tmp:
                folder = Path(tmp)
                gitops.git(["init", "-q"], folder)  # Codex refuses to run outside a git repo
                try:
                    out = runner(agent, mode, PROMPT, folder)
                except AgentUnavailable as exc:
                    lines.append(f"FAIL     {name} ({mode}): {exc}")
                    failures += 1
                    break
            parsed = parse_build(out.text) if out.ok else None
            if out.ok and parsed and "pong" in parsed["summary"].lower():
                lines.append(f"ok       {name} ({mode} flags): {_usage(out)}")
                continue
            failures += 1
            why = out.error if not out.ok else (
                "ran, but the reply had no RELAY_RESULT block: " + repr(out.text[:160]))
            lines.append(f"FAIL     {name} ({mode} flags): {why}")
            lines.append(f"         hint: {HINTS.get(agent.kind, '')}")
    lines.append("")
    lines.append("All agents ready." if failures == 0 else
                 f"{failures} check(s) failed. Fix those before `relay plan` or `relay tick`.")
    return "\n".join(lines)
