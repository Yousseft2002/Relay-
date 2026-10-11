"""Pure routing decisions: which agent builds, which reviews. No I/O here."""
from __future__ import annotations

import re

from .config import Config, SIZES

Usage = dict[str, dict[str, float]]  # agent -> {"runs": n, "usd": x}

AGENT_LABEL = re.compile(r"^relay:agent:(?P<agent>[\w-]+)$")
DEPENDS = re.compile(r"depends on:?\s*((?:#\d+[\s,]*(?:and\s*)?)+)", re.IGNORECASE)


def size_from_labels(labels: list[str]) -> str:
    for label in labels:
        if label.startswith("size:") and label[5:] in SIZES:
            return label[5:]
    return "M"


def agent_override(labels: list[str]) -> str | None:
    for label in labels:
        m = AGENT_LABEL.match(label)
        if m:
            return m.group("agent")
    return None


def built_by(labels: list[str]) -> str | None:
    for label in labels:
        if label.startswith("built-by:"):
            return label[len("built-by:"):]
    return None


def rework_round(labels: list[str]) -> int:
    rounds = [int(label.split(":", 1)[1]) for label in labels
              if label.startswith("rework:") and label.split(":", 1)[1].isdigit()]
    return max(rounds, default=0)


def depends_on(body: str) -> list[int]:
    """Issue numbers listed on a 'Depends on: #12, #13' line."""
    found: list[int] = []
    for m in DEPENDS.finditer(body or ""):
        found += [int(n) for n in re.findall(r"#(\d+)", m.group(1))]
    return sorted(set(found))


def within_budget(cfg: Config, agent: str, usage: Usage) -> bool:
    a = cfg.agents[agent]
    if not a.enabled:
        return False
    used = usage.get(agent, {})
    if used.get("runs", 0) >= a.max_runs_per_day:
        return False
    if a.max_usd_per_day is not None and used.get("usd", 0.0) >= a.max_usd_per_day:
        return False
    return True


def choose_builder(cfg: Config, labels: list[str], usage: Usage) -> tuple[str | None, str]:
    """Pick the agent that builds a task. Returns (agent or None, reason)."""
    override = agent_override(labels)
    if override:
        if override not in cfg.agents:
            return None, f"label asks for unknown agent {override!r}"
        if within_budget(cfg, override, usage):
            return override, f"label relay:agent:{override}"
        return None, f"{override} is pinned by label but over today's budget"

    size = size_from_labels(labels)
    preferred = cfg.by_size.get(size)
    if preferred and within_budget(cfg, preferred, usage):
        return preferred, f"size {size} routes to {preferred}"

    for agent in cfg.fallback:
        if agent != preferred and within_budget(cfg, agent, usage):
            return agent, f"{preferred or 'preferred agent'} unavailable; fell back to {agent}"
    return None, "every agent is disabled or over today's budget"


def choose_reviewer(cfg: Config, author: str, usage: Usage) -> tuple[str | None, str]:
    """Pick a reviewer from a different vendor than the author."""
    author_vendor = cfg.agents[author].vendor if author in cfg.agents else author
    candidates: list[str] = []
    if author in cfg.reviewers:
        candidates.append(cfg.reviewers[author])
    candidates += [a for a in cfg.fallback if a not in candidates]
    candidates += [a for a in cfg.agents if a not in candidates]

    for agent in candidates:
        a = cfg.agents[agent]
        if a.is_cloud or a.vendor == author_vendor:
            continue
        if within_budget(cfg, agent, usage):
            return agent, f"{agent} reviews work by {author}"
    return None, f"no agent from another vendor than {author} has budget left today"


RISK_ORDER = {"low": 0, "medium": 1, "high": 2}


def can_auto_merge(cfg: Config, labels: list[str], risk: str, checks_green: bool) -> tuple[bool, str]:
    if cfg.autonomy != "auto":
        return False, "autonomy is 'gated': a human merges"
    if "relay:approved" not in labels:
        return False, "not approved by a reviewer yet"
    size = size_from_labels(labels)
    if size not in cfg.auto_merge_sizes:
        return False, f"size {size} needs a human merge"
    if RISK_ORDER.get(risk, 2) > RISK_ORDER[cfg.auto_merge_max_risk]:
        return False, f"reviewer rated risk {risk}"
    if not checks_green:
        return False, "CI isn't green"
    return True, "approved, small, low risk, CI green"
