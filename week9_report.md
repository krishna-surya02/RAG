# Week 9 — MCP: a second server by config only

## Setup note
The assignment assumed a Week-9 agent already discovering tools from our policy server. The repo had no MCP code at all (no client, config, or server; `mcp` not installed), so server one was built first (`policy_server.py`, `mcp_agent.py`, `mcp_config.json`) and staged as the baseline. Also: the "claims platform team" server isn't reachable, so server two is **a mock** (`claims_server.py`, over `claims_data.json`; status is a fixed placeholder, "history" is the single intake note). Claim numbers in this repo have 6 digits (`CLM-2026-010007`), not the 5 in the brief. `mcp` 2.3 installed (`MCPServer`, not the 1.x `FastMCP`).

## Tool counts (from `tools/list`, via `mcp_agent.py --list`)
| | count | tools |
|---|---|---|
| before (`tools_before.json`) | **1** | `search_policy` |
| after (`tools_after.json`) | **3** | `search_policy`, `get_claim_status`, `get_adjuster_notes` |

## Zero agent change
`config_diff.txt` is the only change: a 4-line `claims-system` block in `mcp_config.json`. `agent_diff.txt` is empty (0 bytes; `git diff --stat -- mcp_agent.py` prints nothing). The baseline is the git **index** (files staged, not committed), so the diff is working tree vs. staged baseline.

## Provable call to server two
Query *"What is the status of claim CLM-2026-010007 and what do the adjuster notes say?"* → trace `891cf4a178684aaeb0e19710605a62c7` in `traces/mcp_agent_traces.jsonl` shows `claims-system.get_claim_status` then `claims-system.get_adjuster_notes`.

## Wire
`wire.json` (hand-annotated, every top-level field), `wire_raw.json` (verbatim), `capture_wire.py` (SDK-free client). Model call: it happens in `mcp_agent.py` (the host, Groq) between tool results and the next turn — never in the MCP server or on the wire.

## Docstring-as-prompt
See `error_before_after.md`: 4 futile retries and no answer → recovery on the first retry. n=1; caveats listed there.

## Risk note
`risk_note.md` — verdict: don't ship the real server until scoped read-only tokens, rate limits and log terms exist.

## Deliverables
| file | purpose |
|---|---|
| `policy_server.py`, `mcp_agent.py`, `mcp_config.json` | server one + config-driven agent |
| `claims_server.py` | mock server two |
| `agent_diff.txt`, `config_diff.txt` | zero-agent-change proof |
| `tools_before.json`, `tools_after.json` | discovery counts/names |
| `wire.json`, `wire_raw.json`, `capture_wire.py` | wire exchange |
| `error_before_after.md` | docstring/error rewrite transcript |
| `risk_note.md` | 5-line supply-chain note |
