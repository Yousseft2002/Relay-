"""Append-only usage ledger, so routing can respect each agent's daily budget."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


class Ledger:
    def __init__(self, state_dir: Path):
        self.path = state_dir / "ledger.jsonl"

    def append(self, **entry) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        entry.setdefault("ts", datetime.now().astimezone().isoformat(timespec="seconds"))
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")

    def entries(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def usage_on(self, day: str) -> dict[str, dict[str, float]]:
        """Runs, dollars and tokens per agent for a local date (YYYY-MM-DD)."""
        usage: dict[str, dict[str, float]] = {}
        for e in self.entries():
            if not str(e.get("ts", "")).startswith(day):
                continue
            u = usage.setdefault(e.get("agent", "?"), {"runs": 0, "usd": 0.0, "tokens": 0})
            u["runs"] += 1
            u["usd"] += float(e.get("usd") or 0.0)
            u["tokens"] += int(e.get("tokens") or 0)
        return usage

    def usage_today(self) -> dict[str, dict[str, float]]:
        return self.usage_on(datetime.now().astimezone().strftime("%Y-%m-%d"))
