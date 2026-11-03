"""A client that isn't ours: raw JSON-RPC against the HTTP MCP server.

    python triage.py serve-mcp --http 8765 &
    python w12/wire_check.py http://127.0.0.1:8765/mcp

No MCP SDK and no agent code, like week 9's capture_wire.py but over
streamable HTTP. It does what a fresh-eyes reviewer's client does first:
initialize, list tools, call search_wording WITHOUT a traceparent, and try to
pull 2025 wording for a 2024 loss. Prints every exchange and checks the
replies for PII from the generator's ground truth.
"""

import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _parse(resp):
    if resp.headers.get("content-type", "").startswith("text/event-stream"):
        for line in resp.text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:])
        return None
    return resp.json() if resp.content else None


def main(url):
    h = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    log = []
    with httpx.Client(timeout=120) as c:
        def rpc(method, params=None, id_=None):
            body = {"jsonrpc": "2.0", "method": method, **({"params": params} if params is not None else {}),
                    **({"id": id_} if id_ is not None else {})}
            r = c.post(url, headers=h, json=body)
            if "mcp-session-id" in r.headers:
                h["mcp-session-id"] = r.headers["mcp-session-id"]
            out = _parse(r)
            log.append({"sent": body, "status": r.status_code, "got": out})
            return out

        init = rpc("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                                  "clientInfo": {"name": "fresh-eyes-reviewer", "version": "0"}}, 1)
        print("server:", init["result"]["serverInfo"])
        rpc("notifications/initialized")
        tools = rpc("tools/list", {}, 2)["result"]["tools"]
        print("tools:", [t["name"] for t in tools])
        res = rpc("tools/call", {"name": "search_wording", "arguments": {
            "query": "surface water from heavy rain came into the kitchen", "product": "household",
            "loss_date": "2024-08-14"}}, 3)
        body = json.loads(res["result"]["content"][0]["text"])
        print("search (no endorsement_set, no traceparent):", body["resolution"]["resolved_by"],
              body["resolution"]["endorsement_set"], [x["ref"] for x in body["hits"]], "trace", body["trace_id"][:12])
        print("  warning:", body["resolution"].get("warning", "")[:90])
        res = rpc("tools/call", {"name": "get_clause", "arguments": {
            "refs": ["HFL-25 §2.1"], "product": "household", "loss_date": "2024-08-14"}}, 4)
        body = json.loads(res["result"]["content"][0]["text"])
        print("get_clause HFL-25 §2.1 for a 2024 loss:", body["clauses"][0])
        res = rpc("tools/call", {"name": "search_wording", "arguments": {
            "query": "flood", "product": "boats", "loss_date": "yesterday"}}, 5)
        print("bad input:", res["result"]["content"][0]["text"])

    from w12 import store
    from w12.evals.pii_audit import _matcher

    leaks = _matcher(store.pii_values()).findall(json.dumps(log, ensure_ascii=False))
    print(f"PII values in all replies: {len(leaks)}")
    out = Path(__file__).resolve().parent.parent / "week12" / "wire_check.json"
    out.write_text(json.dumps(log, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"exchange written to {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765/mcp")
