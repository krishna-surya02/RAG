"""MCP server: policy-wording search, scoped by product and loss date.

    python w12/mcp_wording_server.py                  # stdio (our agent spawns it)
    python w12/mcp_wording_server.py --http 8765      # streamable HTTP at http://127.0.0.1:8765/mcp
    python triage.py serve-mcp --http 8765            # same thing via the entry point

This is the capability another squad's agent calls on Thursday. Its contract:
`loss_date` is required on every wording tool, and nothing from a document
that was not in force for that date is ever returned. Pass `endorsement_set`
(from a policy's in-force check) when you have it; without it the set is
chosen by calendar date and the response says so, because the two disagree
for any term that started before 2025-04-01 and had its loss after.

The wording carries no PII, so this server needs no redaction. It does trace:
a caller that sends `_meta.traceparent` gets its spans joined to its own
trace; a caller that doesn't (any external client) gets a fresh trace id back
in every response, so a reviewer can still quote one.
"""

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# stdout is the stdio transport and stderr lands in the caller's terminal;
# sentence-transformers' INFO lines and progress bars belong in neither.
import logging

logging.basicConfig(level=logging.WARNING)
for _name in ("sentence_transformers", "mcp", "httpx", "uvicorn.access"):
    logging.getLogger(_name).setLevel(logging.WARNING)
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

from mcp.server.mcpserver import Context, MCPServer

import retrieval
from w12 import citations, store, trace

mcp = MCPServer(
    "policy-wording",
    instructions=(
        "Search the household and motor policy wordings as they stood on a loss date. "
        "Every tool needs product ('household' or 'motor') and loss_date (YYYY-MM-DD). "
        "Results are wording only -- they are not coverage decisions."
    ),
)


def _tracer_for(ctx, tool, args):
    return trace.server_tracer(ctx, "policy-wording", tool, args)


def _check(product, loss_date):
    if product not in store.PRODUCTS:
        return f"product must be one of {list(store.PRODUCTS)}, got {product!r}"
    try:
        dt.date.fromisoformat(loss_date)
    except (TypeError, ValueError):
        return f"loss_date must be YYYY-MM-DD, got {loss_date!r}"
    return None


def _set_ok(product, endorsement_set):
    if endorsement_set is None:
        return None
    valid = [d["doc_id"] for d in store.versions() if d["product"] == product and d["kind"] == "endorsement_set"]
    return None if endorsement_set in valid else f"endorsement_set must be one of {valid} for {product}"


@mcp.tool()
def search_wording(query: str, product: str, loss_date: str, endorsement_set: str | None = None,
                   k: int = 4, ctx: Context = None) -> str:
    """Search policy wording in force on a loss date (product 'household'|'motor',
    loss_date YYYY-MM-DD). Pass endorsement_set from the policy's in-force check
    (e.g. 'HEND-2023'); without it the set is picked by calendar date, which is wrong
    for terms that started before 2025-04-01. Each hit carries a citation naming
    clause, endorsement version and loss date. k = 1-8 clauses."""
    tracer, parent, attrs = _tracer_for(ctx, "search_wording", {
        "query": query, "product": product, "loss_date": loss_date, "endorsement_set": endorsement_set, "k": k})
    with tracer.span("search_wording", "mcp_server", parent_id=parent, **attrs) as sp:
        err = _check(product, loss_date) or _set_ok(product, endorsement_set)
        if err:
            sp["status"] = "rejected"
            return json.dumps({"error": err, "trace_id": tracer.trace_id})
        hits, res = retrieval.retrieve_in_force(query, product, loss_date, endorsement_set, k=max(1, min(int(k), 8)))
        out = []
        for h in hits:
            cit = citations.build({**h.meta, "page": h.page, "product": product}, loss_date,
                                  res["endorsement_set"], res["resolved_by"])
            body = h.text.split("\n", 1)[1] if "\n" in h.text else h.text
            out.append({"ref": h.meta["ref"], "title": h.meta["title"], "score": round(h.score, 3),
                        "citation": citations.render({**cit, "valid": True}), "href": cit["href"],
                        "endorsement_version": cit["endorsement_version"],
                        "text": body[:500] + ("…" if len(body) > 500 else "")})
        sp["attrs"]["hits"] = [h["ref"] for h in out]
        sp["attrs"]["resolved_by"] = res["resolved_by"]
        return json.dumps({"trace_id": tracer.trace_id, "resolution": res, "hits": out}, ensure_ascii=False)


@mcp.tool()
def get_clause(refs: list[str], product: str, loss_date: str, endorsement_set: str | None = None,
               ctx: Context = None) -> str:
    """Full text of clauses (e.g. ['HFL-23 §2.2', 'HX-17']) as in force on the loss
    date; several per call. Wording not in force for that loss is refused. Same
    product / loss_date / endorsement_set rules as search_wording."""
    if isinstance(refs, str):
        refs = [refs]
    tracer, parent, attrs = _tracer_for(ctx, "get_clause", {
        "refs": refs, "product": product, "loss_date": loss_date, "endorsement_set": endorsement_set})
    with tracer.span("get_clause", "mcp_server", parent_id=parent, **attrs) as sp:
        err = _check(product, loss_date) or _set_ok(product, endorsement_set)
        if err:
            sp["status"] = "rejected"
            return json.dumps({"error": err, "trace_id": tracer.trace_id})
        resolved_by = "policy_term" if endorsement_set else "calendar_date"
        eset = endorsement_set or store.set_by_calendar(product, loss_date)
        out = []
        for ref in refs[:8]:
            cit = citations.resolve(ref, product, loss_date, eset, resolved_by)
            if not cit.get("valid"):
                out.append({"ref": ref, "in_force": False, "problems": cit.get("problems")})
                continue
            clause = next(c for c in store.find_clause(ref, product) if c["doc_id"] == cit["doc_id"])
            out.append({"ref": clause["ref"], "title": clause["title"], "in_force": True,
                        "citation": citations.render(cit), "href": cit["href"],
                        "endorsement_version": cit["endorsement_version"], "text": clause["text"]})
        sp["attrs"]["refused"] = [c["ref"] for c in out if not c["in_force"]]
        return json.dumps({"trace_id": tracer.trace_id, "endorsement_set": eset, "resolved_by": resolved_by,
                           "clauses": out}, ensure_ascii=False)


@mcp.tool()
def list_versions(product: str, ctx: Context = None) -> str:
    """Wording and endorsement-set versions for a product, with effective windows
    (which new/renewing terms received each set)."""
    tracer, parent, attrs = _tracer_for(ctx, "list_versions", {"product": product})
    with tracer.span("list_versions", "mcp_server", parent_id=parent, **attrs):
        docs = [{k: d[k] for k in ("doc_id", "kind", "version", "effective_from", "effective_to")}
                | ({"endorsements": d["endorsements"]} if "endorsements" in d else {})
                for d in store.versions() if d["product"] == product]
        return json.dumps({"trace_id": tracer.trace_id, "product": product, "documents": docs})


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--http", type=int, metavar="PORT", help="serve streamable HTTP instead of stdio")
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    if args.http:
        from w12 import wording_index
        wording_index.build(quiet=False)  # embed once before the first caller waits on it
        print(f"policy-wording MCP server on http://{args.host}:{args.http}/mcp", file=sys.stderr)
        mcp.run("streamable-http", host=args.host, port=args.http)
    else:
        mcp.run("stdio")


if __name__ == "__main__":
    main()
