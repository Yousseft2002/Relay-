# Private local research bridge

This is the first implemented connection milestone: save research, track a job,
and retrieve a Claude rewrite through a separate stdio MCP server. It exposes no
implementation, merge, GitHub-write, or arbitrary-command tools.

## Current verification

Local automated checks exercise real stdio processes, persistent storage across
restarts, concurrent job claims, and a simulated Claude response. Provider adapter
checks use mocks. A live ChatGPT/tunnel/Claude round trip still requires account
setup and a live test; a local health response alone does not establish that.

## Start locally

Use Python 3.11+ in a checkout. No runtime dependencies or pip installation required:

```powershell
python .\bridge_server.py health
python .\bridge_server.py
```

The second command serves newline-delimited MCP over stdin/stdout. It waits for a
client, so a quiet terminal is expected. The absolute bridge_server.py path works
from another directory. State defaults to .relay/state/bridge under the checkout;
pass --state-dir before the command to choose another location.

An installed package also provides relay-bridge, or python -m relay.bridge. For
those entrypoints, set an absolute --state-dir when a tunnel launches the server.

## Tools

| Tool | Effect |
| --- | --- |
| relay_health | Connection health and local provider prerequisites; no provider request |
| relay_submit_research | Save objective, research, rough_prompt, sources and acceptance_criteria |
| relay_job_status | Return status, input hash, timestamps and a sanitized error |
| relay_job_result | Return completed report plus original input/citations |
| relay_start_rewrite | Available only with --allow-rewrite; starts a paid provider job |

Inputs are text and lists of text, capped at 200,000 serialized characters total.
Use a stable request_id on submission to make a retry return the same job. Reusing
that request_id with changed input is rejected. A saved job is immutable; submit a
new job for a revised draft. Obvious credential patterns are rejected, but this is
not a comprehensive secret scanner. Keep credentials out of research and prompts.

## Enable real rewriting

Install the official Claude CLI separately and configure ANTHROPIC_API_KEY in the
local environment that launches the bridge/tunnel client. Keep the key out of
source files, MCP tool arguments and chat. For the intended commercial integration,
this adapter uses API authentication instead of borrowing a browser subscription.

Optional local settings:

- RELAY_CLAUDE_COMMAND: one trusted executable path, otherwise claude on PATH.
- RELAY_CLAUDE_MODEL: a supported model identifier. The report records the requested
  model, not a verified identity of the model actually used.

```powershell
python .\bridge_server.py --allow-rewrite
```

Run relay_health before spending budget. Its ready flag checks configuration and
executable discovery, not credential validity, credit balance or CLI compatibility.
Only a successful live call verifies those. The worker uses bare mode, an empty
temporary workspace/configuration, no tools or MCP servers, and a restricted
environment. It sends the saved handoff on stdin and requires structured output.

Rewrites run in a separate process so an MCP request returns promptly. Poll status,
then retrieve the result. A database transaction permits only one worker to claim
each job. Timeout or interrupted work fails after its deadline and is not retried
automatically. A failure after a provider request may still incur a charge; new
submissions can incur another charge. No cancellation or automatic recovery of
paid work is offered in this first bridge.

## Connect ChatGPT after local health works

Use OpenAI's current Secure MCP Tunnel setup with an absolute stdio command pointing
to your Python executable and bridge_server.py. Keep the tunnel client running.
Create/associate the tunnel with the intended account/workspace and verify health
through the client before creating the ChatGPT connection.

In Create MCP App, use Name Relay and Connection Tunnel. This stdio server does not
implement OAuth. For a private tunnel-only prototype, use the supported no-server-
authentication option, with access restricted by the tunnel/account permissions.
If your workspace requires server OAuth, stop: an authenticated gateway is needed.
Do not publish an unauthenticated HTTP proxy to this server.

This is a single-user service. Any caller allowed through its local process or
private tunnel can access the same jobs. A random job ID is not an authorization
boundary. Multi-user deployment, OAuth, owner isolation, and public distribution
remain separate work. Store the database in a private OS-account directory.

## First real round-trip check

1. Select Relay in ChatGPT and request relay_health.
2. Ask ChatGPT to produce a short sourced brief and rough prompt.
3. Submit the brief with objective, research, rough_prompt, sources and
   acceptance_criteria. Record the returned job_id.
4. With rewriting enabled and configured, request relay_start_rewrite for that ID.
5. Request status; once completed, retrieve relay_job_result.
6. Compare the returned original sources/input with the submission, and inspect
   Claude's critique, revised prompt, unresolved questions and limitations.

## Sources

- [OpenAI Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
- [ChatGPT custom MCP setup](https://developers.openai.com/api/docs/guides/custom-mcp-server)
- [Claude programmatic interface](https://code.claude.com/docs/en/headless)
- [Claude CLI options](https://code.claude.com/docs/en/cli-reference)
