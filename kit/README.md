# kit/ — files you copy out of this repo

Nothing in this folder is read by Relay's code. These files are for setting Relay up in
**your** projects and on **your** machine.

| File | What to do with it |
| --- | --- |
| [AGENTS.team.md](AGENTS.team.md) | Paste its section into your project's `AGENTS.md`, so Claude Code, Codex and Copilot follow the same team rules. (This repo's own `AGENTS.md` is for agents developing Relay; don't confuse them.) |
| [starnet-manager.md](starnet-manager.md) | Brief and MCP setup for a StarNet "engineering manager" agent that drives Relay |
| [night-shift.ps1](night-shift.ps1) | Registers a Windows scheduled task that runs `relay tick` overnight: `powershell -ExecutionPolicy Bypass -File .\kit\night-shift.ps1 -RepoDir "C:\code\your-repo"` |

The config template stays at the repo root as [`relay.example.toml`](../relay.example.toml),
because Relay's error messages and tests point there.
