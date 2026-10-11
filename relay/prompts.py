"""Prompt templates. Put a file with the same name in <repo>/.relay/prompts/ to override."""
from __future__ import annotations

from importlib import resources
from pathlib import Path
from string import Template


def load(name: str, override_dir: Path | None = None) -> Template:
    if override_dir is not None:
        custom = override_dir / name
        if custom.exists():
            return Template(custom.read_text(encoding="utf-8"))
    text = resources.files("relay").joinpath("templates", name).read_text(encoding="utf-8")
    return Template(text)


def render(name: str, override_dir: Path | None = None, **values: object) -> str:
    return load(name, override_dir).safe_substitute({k: str(v) for k, v in values.items()})


def truncate(text: str, limit: int, note: str = "truncated") -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n[... {note}: {len(text) - limit} more characters not shown ...]\n"
