"""MOCK claims-system MCP server (stdio). Server two of week 9.

The platform team's real claims-system server isn't reachable from here, so this
stands in for it, backed by claims_data.json. It is NOT that server: the
tool names and shapes below are this mock's own. Status is a fixed placeholder
(the data has no workflow state) and the "history" is the one intake note per
claim. `expected` ground truth is never returned.

    python claims_server.py          # normally launched by mcp_agent.py via mcp_config.json
"""

import json
from pathlib import Path

from mcp.server.mcpserver import MCPServer

import redact

CLAIMS_PATH = Path(__file__).with_name("claims_data.json")

mcp = MCPServer("claims-system")


def _find(claim_number):
    for claim in json.loads(CLAIMS_PATH.read_text(encoding="utf-8"))["claims"]:
        if claim["claim_id"] == claim_number:
            return claim
    return None


def _not_found(claim_number):
    return (
        f"claim {claim_number} not found: claim numbers look like CLM-YYYY-nnnnnn "
        "(e.g. CLM-2026-010007)"
    )


@mcp.tool()
def get_claim_status(claim_number: str) -> str:
    """Look up the current status of one claim by claim number (CLM-YYYY-nnnnnn).
    Returns JSON with status, policy form/edition, date of loss and claimed amount."""
    claim = _find(claim_number)
    if claim is None:
        return _not_found(claim_number)
    return json.dumps(
        {
            "claim_number": claim["claim_id"],
            "status": "under_review",
            "form": claim["form"],
            "edition": claim["edition"],
            "date_of_loss": claim["date_of_loss"],
            "claimed_amount": claim["claimed_amount"],
        }
    )


@mcp.tool()
def get_adjuster_notes(claim_number: str) -> str:
    """Fetch the adjuster note history for one claim by claim number
    (CLM-YYYY-nnnnnn). Returns a JSON list of dated notes, newest first; the
    claimant's name is redacted."""
    claim = _find(claim_number)
    if claim is None:
        return _not_found(claim_number)
    notes, _ = redact.redact(claim["raw_notes"])
    return json.dumps([{"date": claim["date_of_loss"], "note": notes}])


if __name__ == "__main__":
    mcp.run("stdio")
