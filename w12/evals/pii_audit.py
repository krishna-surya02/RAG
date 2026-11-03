"""PII audit: is any generated name, address, phone, email or injury anywhere
it must not be?

    python -m w12.evals.pii_audit

Two sweeps, both against the generator's full ground truth (store.pii_values,
~2,700 values -- production would not have this list; a synthetic corpus is
what makes an exact count possible):

  1. every file the system wrote: traces/w12_*.jsonl, traces/referrals/,
     and every eval run under evals/w12/runs/ (spans, MCP-server spans, run
     records, referrals, judge cache). labels.json / labels_worksheet.md are
     included: they hold judge inputs, which must be redacted too.
  2. what the claims-files MCP server returns, for ALL 500 claims, by calling
     its tool functions in-process -- the exact bytes another squad's agent
     would receive on Thursday.

Exit status 1 on any leak.
"""

import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def _matcher(values):
    # One alternation, longest first, so "Amara Sorensen" is reported rather than "Amara".
    vals = sorted({v for v in values if len(v) >= 3}, key=len, reverse=True)
    return re.compile(r"(?<![\w'’-])(?:" + "|".join(re.escape(v) for v in vals) + r")(?![\w-])")


def scan_files(pattern):
    files = list((ROOT / "traces").glob("w12_*.jsonl")) + list((ROOT / "traces" / "referrals").glob("*"))
    files += [p for p in (ROOT / "evals" / "w12" / "runs").rglob("*") if p.is_file()]
    leaks = []
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        for m in pattern.finditer(text):
            leaks.append((str(f.relative_to(ROOT)), m.group(0)))
    return files, leaks


def scan_mcp(pattern):
    os.environ["W12_TRACE_DIR"] = tempfile.mkdtemp(prefix="pii_audit_")
    from w12 import mcp_claims_server, store

    leaks, n = [], 0
    for cid in store.claim_ids():
        for fn in (mcp_claims_server.get_fnol, mcp_claims_server.get_adjuster_notes):
            out = fn(cid)
            n += 1
            for m in pattern.finditer(out):
                leaks.append((f"{fn.__name__}({cid})", m.group(0)))
    return n, leaks


def main():
    from w12 import store

    values = store.pii_values()
    pattern = _matcher(values)
    files, file_leaks = scan_files(pattern)
    n_calls, mcp_leaks = scan_mcp(pattern)
    print(f"PII values known: {len(values)}")
    print(f"files scanned: {len(files)} -> leaks: {len(file_leaks)}")
    print(f"MCP responses scanned: {n_calls} (get_fnol + get_adjuster_notes x {n_calls // 2} claims) -> leaks: {len(mcp_leaks)}")
    for where, value in (file_leaks + mcp_leaks)[:20]:
        print(f"  LEAK {where}: {value!r}")
    result = {"values_known": len(values), "files_scanned": len(files), "file_leaks": len(file_leaks),
              "mcp_responses_scanned": n_calls, "mcp_leaks": len(mcp_leaks),
              "examples": [list(x) for x in (file_leaks + mcp_leaks)[:20]]}
    print(json.dumps(result))
    sys.exit(1 if file_leaks or mcp_leaks else 0)


if __name__ == "__main__":
    main()
