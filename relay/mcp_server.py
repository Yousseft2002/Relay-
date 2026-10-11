"""Minimal MCP server over stdio (JSON-RPC 2.0, one message per line).

Lets a manager agent (StarNet, Claude Code, Codex, any MCP client) drive the relay:
check status, plan work, run a tick, approve tasks, pause. Standard library only.
"""
from __future__ import annotations

import json
import subprocess
import sys
import traceback
from typing import Callable

from .workflows import Relay

PROTOCOL_VERSION = "2025-06-18"


def start_tick_in_background(relay: Relay) -> str:
    """A tick can run for an hour while agents build, longer than an MCP call should
    block. Start it as a separate process and report back right away."""
    if relay.stopped():
        return "Relay is paused. Nothing started."
    if relay.tick_running():
        return "A tick is already running. Check relay_status later for its report."
    if relay.cfg.config_path is None:
        return "Can't start a tick: config path unknown."
    relay.cfg.state_dir.mkdir(parents=True, exist_ok=True)
    log = (relay.cfg.state_dir / "tick-output.log").open("a", encoding="utf-8")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # don't flash a console on Windows
    subprocess.Popen([sys.executable, "-m", "relay", "--config", str(relay.cfg.config_path),
                      "--repo-dir", str(relay.cfg.repo_dir), "tick"],
                     cwd=str(relay.cfg.repo_dir), stdout=log, stderr=log,
                     stdin=subprocess.DEVNULL, creationflags=flags)
    return "Tick started in the background. Call relay_status in 20-60 minutes for the report."


def _tools(relay: Relay) -> dict[str, tuple[str, dict, Callable[[dict], str]]]:
    return {
        "relay_status": ("Show task and PR queues, today's usage per agent, and the last "
                         "tick's report.", {}, lambda a: relay.status()),
        "relay_plan": ("Turn an idea into a spec issue and buildable task issues. "
                       "Takes a few minutes.",
                       {"idea": {"type": "string", "description": "The idea in plain words"}},
                       lambda a: relay.plan(a["idea"])),
        "relay_approve": ("Approve a task waiting for human approval so agents can build it.",
                          {"issue": {"type": "integer"}},
                          lambda a: relay.approve(int(a["issue"]))),
        "relay_tick": ("Start one pass in the background: pick up cloud PRs, merge, review, "
                       "rework, build. Returns immediately.",
                       {}, lambda a: start_tick_in_background(relay)),
        "relay_pause": ("Pause all automated work.", {}, lambda a: relay.set_stop(True)),
        "relay_resume": ("Resume automated work.", {}, lambda a: relay.set_stop(False)),
    }


REQUIRED = {"relay_plan": ["idea"], "relay_approve": ["issue"]}


def handle(relay: Relay, msg: dict) -> dict | None:
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:  # notification, e.g. notifications/initialized
        return None
    tools = _tools(relay)
    if method == "initialize":
        requested = (msg.get("params") or {}).get("protocolVersion") or PROTOCOL_VERSION
        result = {"protocolVersion": requested, "capabilities": {"tools": {}},
                  "serverInfo": {"name": "relay", "version": "0.1.0"},
                  "instructions": "Drives a GitHub-backed team of coding agents. Call "
                                  "relay_status first. relay_tick does real work and spends "
                                  "agent budget; don't call it more than every 15 minutes."}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [{
            "name": name, "description": desc,
            "inputSchema": {"type": "object", "properties": props,
                            "required": REQUIRED.get(name, [])}}
            for name, (desc, props, _) in tools.items()]}
    elif method == "tools/call":
        params = msg.get("params") or {}
        name, args = params.get("name"), params.get("arguments") or {}
        if name not in tools:
            return {"jsonrpc": "2.0", "id": mid,
                    "error": {"code": -32602, "message": f"Unknown tool: {name}"}}
        try:
            text, is_error = tools[name][2](args), False
        except Exception as exc:  # report tool failures to the client, keep serving
            text, is_error = f"{type(exc).__name__}: {exc}", True
        result = {"content": [{"type": "text", "text": text}], "isError": is_error}
    else:
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": -32601, "message": f"Method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def serve(relay: Relay, stdin=None, stdout=None) -> None:
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            reply = {"jsonrpc": "2.0", "id": None,
                     "error": {"code": -32700, "message": "Parse error"}}
        else:
            try:
                reply = handle(relay, msg)
            except Exception:
                traceback.print_exc(file=sys.stderr)
                reply = {"jsonrpc": "2.0", "id": msg.get("id"),
                         "error": {"code": -32603, "message": "Internal error"}}
        if reply is not None:
            stdout.write(json.dumps(reply) + "\n")
            stdout.flush()
