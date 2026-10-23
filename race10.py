"""Week 10: single agent vs orchestrator on the same 10 claims, same judge.

    python race10.py                       # run both arms, write the race files
    python race10.py --limit 1             # smoke test on the first claim
    python race10.py --inject-failure CLM-2026-010007   # coverage worker 500

Same 10 claims (claims_data.json) and same judge (race._passed: claim_status,
exclusion_code, payout and cap must all match `expected`) for both arms.

Writes:
  race10.csv       one row per system x claim; also the resume checkpoint
                   (Groq's daily token limit can stop a run midway -- re-run
                   and finished rows are skipped)
  handoffs.log     per-hand-off token counts, orchestrator arm (JSONL)
  race_table.md    4 metrics x 2 arms, the re-send multiplier, the biggest hand-off
  failure_case.md  (--inject-failure) what the orchestrator did when the
                   coverage worker returned a 500

The injected-failure run is kept out of race10.csv and handoffs.log so it
cannot contaminate the 10-case numbers.
"""

import argparse
import csv
import json
import re
from pathlib import Path

import numpy as np

import claim_agent
import claims_common
import config
import orchestrator
from race import AGENT_TOKEN_ESTIMATE, CLAIMS_PATH, _passed

CSV_PATH = Path("race10.csv")
TABLE_PATH = Path("race_table.md")
FAILURE_PATH = Path("failure_case.md")
FAILURE_HANDOFF_LOG = "handoffs_failure.log"
FIELDS = ["system", "claim_id", "pass", "latency_ms", "tokens", "cost", "status"]
SYSTEMS = ("single", "orchestrator")


def load_claims():
    return json.loads(CLAIMS_PATH.read_text(encoding="utf-8"))["claims"]


def read_rows():
    if not CSV_PATH.exists():
        return []
    with CSV_PATH.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for r in rows:
        r["pass"] = r["pass"] == "True"
        r["latency_ms"] = float(r["latency_ms"])
        r["tokens"] = int(r["tokens"])
        r["cost"] = float(r["cost"])
    return rows


def append_row(row):
    new = not CSV_PATH.exists()
    with CSV_PATH.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if new:
            writer.writeheader()
        writer.writerow(row)


def _row(system, claim_id, run, passed):
    return {
        "system": system,
        "claim_id": claim_id,
        "pass": passed,
        "latency_ms": round(run["latency_ms"], 1),
        "tokens": run["tokens"],
        "cost": round(run["cost"], 6),
        "status": run["status"],
    }


def run_race(claims):
    done = {(r["system"], r["claim_id"]) for r in read_rows()}
    limiter = claims_common.RateLimiter(tpm=8000, margin=0.8)

    for claim in claims:
        cid, expected = claim["claim_id"], claim["expected"]
        print(f"--- {cid} ({claim['source_goldenset_id']}) ---")

        if ("single", cid) not in done:
            limiter.wait_for_budget(AGENT_TOKEN_ESTIMATE)
            run = claims_common.call_with_backoff(claim_agent.run_claim, cid, verbose=False)
            limiter.record(run["tokens"])
            row = _row("single", cid, run, _passed(run["output"], expected))
            append_row(row)
            print(f"  single:       pass={row['pass']} {row['status']} {row['latency_ms']:.0f}ms {row['tokens']} tok")

        if ("orchestrator", cid) not in done:
            run = orchestrator.run_claim(cid, limiter=limiter)
            row = _row("orchestrator", cid, run, _passed(run["output"], expected))
            append_row(row)
            print(f"  orchestrator: pass={row['pass']} {row['status']} {row['latency_ms']:.0f}ms {row['tokens']} tok")


def read_handoffs(claim_ids, path=orchestrator.HANDOFF_LOG):
    path = Path(path)
    if not path.exists():
        return []
    out = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [h for h in out if h["claim_id"] in claim_ids]


def write_table(claims):
    ids = {c["claim_id"] for c in claims}
    rows = [r for r in read_rows() if r["claim_id"] in ids]
    stats = {}
    for system in SYSTEMS:
        rs = [r for r in rows if r["system"] == system]
        n = len(rs)
        if n < len(ids):
            print(f"{system}: only {n}/{len(ids)} claims done -- table not written yet; re-run to resume")
            return False
        lat = [r["latency_ms"] for r in rs]
        stats[system] = {
            "n": n,
            "passed": sum(r["pass"] for r in rs),
            "p50": float(np.percentile(lat, 50)),
            "p99": float(np.percentile(lat, 99)),
            "tokens": sum(r["tokens"] for r in rs),
            "cost": sum(r["cost"] for r in rs) / n,
        }

    s, o = stats["single"], stats["orchestrator"]
    multiplier = o["tokens"] / s["tokens"]

    handoffs = read_handoffs(ids)
    by_edge = {}
    for h in handoffs:
        e = by_edge.setdefault(f"{h['from']} -> {h['to']}", {"total": 0, "prompt": 0})
        e["total"] += h["total_tokens"]
        e["prompt"] += h["prompt_tokens"]
    log_total = sum(e["total"] for e in by_edge.values())
    top_edge, top = max(by_edge.items(), key=lambda kv: kv[1]["total"])

    def fmt(a):
        return [
            f"{a['passed']}/{a['n']} ({a['passed'] / a['n'] * 100:.0f}%)",
            f"{a['p50']:,.0f} ms",
            f"{a['p99']:,.0f} ms",
            f"{a['tokens']:,}",
            f"${a['cost']:.6f}",
        ]

    labels = ["Pass rate", "p50 latency", "p99 latency", "Total tokens", "Cost per claim"]
    lines = [
        f"# Week 10 race: single agent vs orchestrator ({s['n']} claims, same judge)",
        "",
        "| Metric | Single agent | Orchestrator |",
        "|---|---|---|",
    ]
    for label, a, b in zip(labels, fmt(s), fmt(o)):
        lines.append(f"| {label} | {a} | {b} |")
    lines += [
        "",
        f"Latency percentiles are over n={s['n']} claims, so p99 is effectively the slowest claim. "
        "Latency excludes pacing waits for the shared 8k TPM limit.",
        "",
        f"**Context re-send multiplier: {multiplier:.1f}x** "
        f"({o['tokens']:,} orchestrator tokens / {s['tokens']:,} single-agent tokens).",
        "",
        f"**Largest hand-off: {top_edge}, {top['total'] / log_total * 100:.0f}% of all orchestrator tokens** "
        f"({top['total']:,} of {log_total:,}; {top['prompt'] / top['total'] * 100:.0f}% of it re-sent prompt).",
        "",
        "Token share by hand-off (from handoffs.log):",
        "",
        "| Hand-off | Tokens | Share |",
        "|---|---|---|",
    ]
    for edge, e in sorted(by_edge.items(), key=lambda kv: -kv[1]["total"]):
        lines.append(f"| {edge} | {e['total']:,} | {e['total'] / log_total * 100:.0f}% |")
    if log_total != o["tokens"]:
        lines += ["", f"WARNING: handoffs.log total ({log_total:,}) != race10.csv orchestrator tokens ({o['tokens']:,})."]
    TABLE_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return True


_ACK = re.compile(r"unavailable|failed|failure|could not|couldn't|unable|error|not (?:verified|checked|available)|unverified|500|without", re.I)


def classify_failure(run):
    """Retried / degraded / lied, judged from what the orchestrator did and what
    the final answer admits -- not from whether it matched `expected`."""
    coverage_ok = isinstance(run["coverage"], dict) and "error" not in run["coverage"]
    if coverage_ok:
        return "retried", "the retry succeeded, so the coverage check actually ran"
    out = run["output"]
    if run["status"] != "ok":
        return "errored", f"no answer produced (status={run['status']})"
    acknowledged = out.get("coverage_checked") is False or bool(_ACK.search(str(out.get("rationale", ""))))
    if acknowledged:
        return "degraded", "answered, but flagged that the exclusions check did not run"
    return "lied", (
        f"declared claim_status={out.get('claim_status')!r} with no exclusions check and no admission of that"
    )


def run_failure(claim):
    cid = claim["claim_id"]
    Path(FAILURE_HANDOFF_LOG).unlink(missing_ok=True)
    limiter = claims_common.RateLimiter(tpm=8000, margin=0.8)
    run = orchestrator.run_claim(cid, fail_worker="coverage", limiter=limiter, handoff_log=FAILURE_HANDOFF_LOG)
    kind, why = classify_failure(run)
    passed = _passed(run["output"], claim["expected"])
    handoff_lines = Path(FAILURE_HANDOFF_LOG).read_text(encoding="utf-8").strip() if Path(FAILURE_HANDOFF_LOG).exists() else ""

    lines = [
        f"# Failure injection: coverage/exclusions worker returns 500 on {cid}",
        "",
        f"**Result: {kind.upper()}.** {why[0].upper() + why[1:]}.",
        "",
        "## What the orchestrator did",
        "",
        *[f"- {e}" for e in run["events"]],
        "",
        f"Coverage result handed to the synthesiser: `{json.dumps(run['coverage'])}`",
        "",
        "## Final answer",
        "",
        "```json",
        json.dumps(run["output"], indent=2),
        "```",
        "",
        f"Expected: `{json.dumps(claim['expected'])}`",
        f"Matches expected (race judge): {passed}",
        "",
        f"Tokens {run['tokens']:,}, latency {run['latency_ms']:.0f} ms, status {run['status']}.",
        "",
        "## Hand-offs (handoffs_failure.log)",
        "",
        "```",
        handoff_lines,
        "```",
        "",
        "Classification is automatic (retried / degraded / errored / lied); read the final answer above to confirm it.",
    ]
    FAILURE_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="only the first N claims (smoke test)")
    parser.add_argument("--inject-failure", metavar="CLAIM_ID", help="run one claim with the coverage worker failing")
    args = parser.parse_args()

    config.preflight()
    claims = load_claims()

    if args.inject_failure:
        match = [c for c in claims if c["claim_id"] == args.inject_failure]
        if not match:
            raise SystemExit(f"{args.inject_failure} is not one of the {len(claims)} race claims")
        run_failure(match[0])
        return

    if args.limit:
        claims = claims[: args.limit]
    try:
        run_race(claims)
    except Exception as exc:
        if exc.__class__.__name__ == "RateLimitError" and re.search(r"per day|TPD|RPD", str(exc)):
            raise SystemExit(f"Daily Groq limit hit on {claims_common.CLAIMS_CHAT_MODEL}; rows so far are in {CSV_PATH}. Re-run after reset.\n{exc}")
        raise
    write_table(claims)


if __name__ == "__main__":
    main()
