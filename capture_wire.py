"""Raw JSON-RPC capture against the claims-system server -- no SDK on the client side.

    python capture_wire.py > wire_raw.json

Spawns the server named in mcp_config.json and speaks newline-delimited
JSON-RPC over its stdin/stdout, logging every line in both directions:
initialize -> notifications/initialized -> tools/list -> tools/call.
"""

import json
import subprocess

CONFIG = json.load(open("mcp_config.json"))["servers"]["claims-system"]
CALL = {"name": "get_claim_status", "arguments": {"claim_number": "CLM-2026-010007"}}

proc = subprocess.Popen(
    [CONFIG["command"], *CONFIG["args"]],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
)
log = []


def send(msg, expect_reply=True):
    log.append({"direction": "client->server", "message": msg})
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()
    if expect_reply:
        reply = json.loads(proc.stdout.readline())
        log.append({"direction": "server->client", "message": reply})


send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
    "protocolVersion": "2025-11-25", "capabilities": {},
    "clientInfo": {"name": "capture_wire", "version": "0"}}})
send({"jsonrpc": "2.0", "method": "notifications/initialized"}, expect_reply=False)
send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
send({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": CALL})
proc.stdin.close()
proc.wait(timeout=10)
print(json.dumps(log, indent=2))
