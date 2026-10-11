"""Load and validate relay.toml."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

KINDS = ("claude", "codex", "copilot", "copilot-cloud")
SIZES = ("S", "M", "L")
RISKS = ("low", "medium", "high")

# Default CLI arguments per agent kind. The prompt is always sent on stdin,
# which avoids Windows quoting problems and command-line length limits.
# "{last_message_file}" is replaced with a temp file path at run time.
DEFAULT_ARGS: dict[str, dict[str, list[str]]] = {
    "claude": {
        "build": ["-p", "--output-format", "json",
                  "--permission-mode", "auto", "--permission-prompts", "none"],
        "review": ["-p", "--output-format", "json",
                   "--permission-mode", "dontAsk", "--allowedTools", "Read,Grep,Glob"],
        "plan": ["-p", "--output-format", "json",
                 "--permission-mode", "dontAsk", "--allowedTools", "Read,Grep,Glob"],
    },
    "codex": {
        "build": ["exec", "--sandbox", "workspace-write", "--json",
                  "-o", "{last_message_file}", "-"],
        "review": ["exec", "--sandbox", "read-only", "--json",
                   "-o", "{last_message_file}", "-"],
        "plan": ["exec", "--sandbox", "read-only", "--json",
                 "-o", "{last_message_file}", "-"],
    },
    "copilot": {
        "build": ["-s", "--no-ask-user", "--allow-tool", "write",
                  "--allow-tool", "shell(npm:*)", "--allow-tool", "shell(npx:*)",
                  "--allow-tool", "shell(pnpm:*)", "--allow-tool", "shell(python:*)",
                  "--allow-tool", "shell(pytest:*)"],
        "review": ["-s", "--no-ask-user"],
        "plan": ["-s", "--no-ask-user"],
    },
    "copilot-cloud": {"build": [], "review": [], "plan": []},
}

DEFAULT_COMMANDS = {"claude": "claude", "codex": "codex", "copilot": "copilot",
                    "copilot-cloud": ""}


class ConfigError(ValueError):
    """Raised when relay.toml is missing or invalid."""


@dataclass
class AgentConfig:
    name: str
    kind: str
    command: list[str]
    args: dict[str, list[str]]
    timeout_min: int = 45
    max_runs_per_day: int = 20
    max_usd_per_day: float | None = None
    enabled: bool = True

    @property
    def vendor(self) -> str:
        """The company behind the agent; reviewers must use a different vendor."""
        return "copilot" if self.kind.startswith("copilot") else self.kind

    @property
    def is_cloud(self) -> bool:
        return self.kind == "copilot-cloud"


@dataclass
class Config:
    repo: str
    base_branch: str
    repo_dir: Path
    worktree_root: Path
    autonomy: str
    spec_approval: bool
    require_ci: bool
    auto_merge_sizes: list[str]
    auto_merge_max_risk: str
    max_rework_rounds: int
    max_jobs_per_tick: int
    planner: str
    by_size: dict[str, str]
    fallback: list[str]
    reviewers: dict[str, str]
    agents: dict[str, AgentConfig] = field(default_factory=dict)
    config_path: Path | None = None

    @property
    def state_dir(self) -> Path:
        return self.repo_dir / ".relay" / "state"

    @property
    def prompts_dir(self) -> Path:
        return self.repo_dir / ".relay" / "prompts"


def _as_command(value: object, kind: str) -> list[str]:
    if value is None or value == "":
        default = DEFAULT_COMMANDS[kind]
        return [default] if default else []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return list(value)
    raise ConfigError(f"agents.*.command must be a string or list of strings, got {value!r}")


def _parse_agent(name: str, raw: dict) -> AgentConfig:
    kind = raw.get("kind", name)
    if kind not in KINDS:
        raise ConfigError(f"agents.{name}.kind must be one of {KINDS}, got {kind!r}")
    args = {mode: list(raw.get(f"{mode}_args", DEFAULT_ARGS[kind][mode]))
            for mode in ("build", "review", "plan")}
    usd = raw.get("max_usd_per_day")
    return AgentConfig(
        name=name,
        kind=kind,
        command=_as_command(raw.get("command"), kind),
        args=args,
        timeout_min=int(raw.get("timeout_min", 45)),
        max_runs_per_day=int(raw.get("max_runs_per_day", 20)),
        max_usd_per_day=float(usd) if usd is not None else None,
        enabled=bool(raw.get("enabled", True)),
    )


def load_config(path: str | Path, repo_dir: str | Path | None = None) -> Config:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}. Copy relay.example.toml to relay.toml.")
    with path.open("rb") as fh:
        raw = tomllib.load(fh)

    project = raw.get("project", {})
    routing = raw.get("routing", {})
    agents_raw = raw.get("agents", {})

    repo = project.get("repo", "")
    if "/" not in repo:
        raise ConfigError("project.repo must look like 'owner/name'")

    base_dir = Path(repo_dir) if repo_dir else path.parent
    base_dir = base_dir.resolve()
    worktree_root = Path(project.get("worktree_root", "../relay-worktrees"))
    if not worktree_root.is_absolute():
        worktree_root = (base_dir / worktree_root).resolve()

    agents = {name: _parse_agent(name, a) for name, a in agents_raw.items()}
    if not agents:
        raise ConfigError("Define at least one [agents.<name>] section")

    cfg = Config(
        repo=repo,
        base_branch=project.get("base_branch", "main"),
        repo_dir=base_dir,
        worktree_root=worktree_root,
        autonomy=project.get("autonomy", "auto"),
        spec_approval=bool(project.get("spec_approval", False)),
        require_ci=bool(project.get("require_ci", True)),
        auto_merge_sizes=list(project.get("auto_merge_sizes", ["S"])),
        auto_merge_max_risk=project.get("auto_merge_max_risk", "low"),
        max_rework_rounds=int(project.get("max_rework_rounds", 2)),
        max_jobs_per_tick=int(project.get("max_jobs_per_tick", 2)),
        planner=routing.get("planner", "claude"),
        by_size=dict(routing.get("by_size", {"S": "copilot-cloud", "M": "codex", "L": "claude"})),
        fallback=list(routing.get("fallback", list(agents))),
        reviewers=dict(routing.get("reviewers", {})),
        agents=agents,
        config_path=path.resolve(),
    )
    _validate(cfg)
    return cfg


def _validate(cfg: Config) -> None:
    if cfg.autonomy not in ("auto", "gated"):
        raise ConfigError("project.autonomy must be 'auto' or 'gated'")
    if cfg.auto_merge_max_risk not in RISKS:
        raise ConfigError(f"project.auto_merge_max_risk must be one of {RISKS}")
    for size in cfg.auto_merge_sizes:
        if size not in SIZES:
            raise ConfigError(f"project.auto_merge_sizes has unknown size {size!r}")

    names = set(cfg.agents)
    referenced = [("routing.planner", cfg.planner)]
    referenced += [(f"routing.by_size.{s}", a) for s, a in cfg.by_size.items()]
    referenced += [("routing.fallback", a) for a in cfg.fallback]
    referenced += [(f"routing.reviewers.{k}", v) for k, v in cfg.reviewers.items()]
    for where, agent in referenced:
        if agent not in names:
            raise ConfigError(f"{where} names agent {agent!r}, which isn't defined in [agents]")

    planner = cfg.agents[cfg.planner]
    if planner.is_cloud:
        raise ConfigError("routing.planner must be a local agent, not copilot-cloud")
    for author, reviewer in cfg.reviewers.items():
        if cfg.agents[reviewer].is_cloud:
            raise ConfigError(f"routing.reviewers.{author}: a cloud agent can't be a reviewer")
        if cfg.agents[reviewer].vendor == cfg.agents[author].vendor:
            raise ConfigError(
                f"routing.reviewers.{author} = {reviewer!r}: reviewer must be a different "
                "vendor than the author, or it's not a real second opinion")
