# Docs index

One line per document. Pick the folder by who the document is for.

## guides/ — for people running Relay

| Doc | Read it when |
| --- | --- |
| [guides/first-run.md](guides/first-run.md) | Installing Relay and testing it on the practice repo, step by step, with troubleshooting |
| [guides/local-bridge.md](guides/local-bridge.md) | Setting up the private research bridge (`bridge_server.py`) and its stdio MCP tools |

## product/ — what Relay sells and promises

| Doc | Read it when |
| --- | --- |
| [product/independent-code-review.md](product/independent-code-review.md) | You need the review product's buyer experience, report contract and release criteria |
| [product/relay-review.md](product/relay-review.md) | Maintaining `skills/relay-review/`: layout, tests, live evaluation, packaging checklist |

## dev/ — for whoever is building Relay

| Doc | Read it when |
| --- | --- |
| [dev/claude-code-playbook.md](dev/claude-code-playbook.md) | Picking the next phase of work; the prompts to paste, in order |
| [dev/test-log.md](dev/test-log.md) | Recording or checking a live test result (append a row; don't rewrite history) |
| [dev/chatgpt-claude-copilot.md](dev/chatgpt-claude-copilot.md) | Working on the ChatGPT -> Claude -> Copilot connection design and its security gates |

## audits/ — dated snapshots

Reviews of the repo at a point in time. They are not updated after they're written, so
paths in them reflect the layout on their date.

| Doc | Scope |
| --- | --- |
| [audits/2026-10-28-relay-review-copilot-audit.md](audits/2026-10-28-relay-review-copilot-audit.md) | Brief for a Copilot audit of the relay-review skill |

## Adding a doc

Put it in the folder for its reader, add a row here, and link it from `AGENTS.md` if agents
need it to do their work. Dated reviews go in `audits/` as `YYYY-MM-DD-<topic>.md`.
