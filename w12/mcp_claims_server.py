"""MCP server: claim files (FNOL, adjuster notes, photo captions), redacted.

    python w12/mcp_claims_server.py                   # stdio
    python w12/mcp_claims_server.py --http 8766       # streamable HTTP

Replaces week 9's claims_server.py mock for the week-12 corpus. Everything it
returns has been through both PII locks in w12/pii.py; the claim's final
decision and the generator's PII ground truth are never returned. Claim ids
and policy numbers are operational identifiers and pass through -- an
adjuster can't act on a referral without them.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# stdout is the stdio transport and stderr lands in the caller's terminal;
# sentence-transformers' INFO lines and progress bars belong in neither.
import logging

logging.basicConfig(level=logging.WARNING)
for _name in ("sentence_transformers", "mcp", "httpx", "uvicorn.access"):
    logging.getLogger(_name).setLevel(logging.WARNING)

from mcp.server.mcpserver import Context, MCPServer

from w12 import pii, store, trace


def _tracer_for(ctx, tool, args):
    return trace.server_tracer(ctx, "claims-files", tool, args)


mcp = MCPServer(
    "claims-files",
    instructions="Read first-notice-of-loss claim files by claim id. Text is redacted: "
                 "names, addresses, phone numbers, emails and injuries are replaced by placeholders.",
)


def _redacted(claim_id, tracer):
    c = store.claim(claim_id)
    if c is None:
        return None, None
    red, found = pii.redact_claim(c)
    values = found + pii.holder_values(c["policy_number"])
    tracer.add_pii(values)
    return c, (red, values)


@mcp.tool()
def get_fnol(claim_id: str, ctx: Context = None) -> str:
    """FNOL for a claim (e.g. CLM-2024-000063): product, policy number, loss date,
    the claimant's account and photo captions, redacted."""
    tracer, parent, attrs = _tracer_for(ctx, "get_fnol", {"claim_id": claim_id})
    with tracer.span("get_fnol", "mcp_server", parent_id=parent, **attrs) as sp:
        c, packed = _redacted(claim_id, tracer)
        if c is None:
            sp["status"] = "not_found"
            return json.dumps({"error": f"no claim {claim_id!r}", "trace_id": tracer.trace_id})
        red, values = packed
        sp["attrs"]["redacted"] = red["redacted_counts"]
        out = {"trace_id": tracer.trace_id, "claim_id": c["claim_id"], "product": c["product"],
               "policy_number": c["policy_number"], "loss_date": c["loss_date"],
               "reported_at": c["reported_at"], "fnol_text": red["fnol_text"],
               "photo_captions": red["photo_captions"], "redacted_counts": red["redacted_counts"]}
        return json.dumps(pii.scrub(out, values), ensure_ascii=False)


@mcp.tool()
def get_adjuster_notes(claim_id: str, ctx: Context = None) -> str:
    """Adjuster notes on a claim so far, redacted."""
    tracer, parent, attrs = _tracer_for(ctx, "get_adjuster_notes", {"claim_id": claim_id})
    with tracer.span("get_adjuster_notes", "mcp_server", parent_id=parent, **attrs) as sp:
        c, packed = _redacted(claim_id, tracer)
        if c is None:
            sp["status"] = "not_found"
            return json.dumps({"error": f"no claim {claim_id!r}", "trace_id": tracer.trace_id})
        red, values = packed
        out = {"trace_id": tracer.trace_id, "claim_id": c["claim_id"], "notes": red["adjuster_notes"]}
        return json.dumps(pii.scrub(out, values), ensure_ascii=False)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--http", type=int, metavar="PORT")
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    if args.http:
        mcp.run("streamable-http", host=args.host, port=args.http)
    else:
        mcp.run("stdio")


if __name__ == "__main__":
    main()
