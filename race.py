"""Race the agent against the workflow over all 10 claims in claims_data.json.

    python race.py

Writes race.csv (one row per system x claim: pass/fail, latency, tokens,
cost) and race_summary.json (the 8-number table: pass rate, p50 latency,
total tokens, cost/claim, for each system), and prints the same table.

A run "passes" when its claim_status, exclusion_code, payout and cap all
match claims_data.json's `expected` block exactly -- including a
budget_exceeded or parse_error result, which never matches and so always
counts as a fail, same as a wrong answer would.
"""

import argparse
import csv
import json
import statistics
from pathlib import Path

import claim_agent
import claim_workflow
import claims_common
import config

CLAIMS_PATH = Path(__file__).parent / "claims_data.json"

# Observed worst case: a full 4-turn agent run uses ~5,500 tokens; a
# workflow run's single rationale call uses well under 1,000. Both systems
# share Groq's 8,000 TPM per-model quota, so the race paces itself around
# whichever system is running, not just within one.
AGENT_TOKEN_ESTIMATE = 6000
WORKFLOW_TOKEN_ESTIMATE = 1000


def _passed(output, expected):
    if not isinstance(output, dict):
        return False
    return all(output.get(k) == expected[k] for k in ("claim_status", "exclusion_code", "payout", "cap"))


def run_race(claims=None, verbose=True):
    claims = claims or json.loads(CLAIMS_PATH.read_text(encoding="utf-8"))["claims"]
    rows = []
    limiter = claims_common.RateLimiter(tpm=8000, margin=0.8)

    for claim in claims:
        claim_id = claim["claim_id"]
        expected = claim["expected"]

        if verbose:
            print(f"--- {claim_id} ({claim['source_goldenset_id']}) ---")

        limiter.wait_for_budget(AGENT_TOKEN_ESTIMATE)
        agent_run = claims_common.call_with_backoff(claim_agent.run_claim, claim_id, verbose=False)
        limiter.record(agent_run["tokens"])
        agent_pass = _passed(agent_run["output"], expected)
        rows.append(
            {
                "system": "agent",
                "claim_id": claim_id,
                "pass": agent_pass,
                "latency_ms": round(agent_run["latency_ms"], 1),
                "tokens": agent_run["tokens"],
                "cost": round(agent_run["cost"], 6),
                "status": agent_run["status"],
            }
        )
        if verbose:
            print(f"  agent:    pass={agent_pass} status={agent_run['status']} "
                  f"latency={agent_run['latency_ms']:.0f}ms tokens={agent_run['tokens']} "
                  f"cost=${agent_run['cost']:.6f}")

        limiter.wait_for_budget(WORKFLOW_TOKEN_ESTIMATE)
        workflow_run = claims_common.call_with_backoff(claim_workflow.run_claim, claim_id, verbose=False)
        limiter.record(workflow_run["tokens"])
        workflow_pass = _passed(workflow_run["output"], expected)
        rows.append(
            {
                "system": "workflow",
                "claim_id": claim_id,
                "pass": workflow_pass,
                "latency_ms": round(workflow_run["latency_ms"], 1),
                "tokens": workflow_run["tokens"],
                "cost": round(workflow_run["cost"], 6),
                "status": workflow_run["status"],
            }
        )
        if verbose:
            print(f"  workflow: pass={workflow_pass} status={workflow_run['status']} "
                  f"latency={workflow_run['latency_ms']:.0f}ms tokens={workflow_run['tokens']} "
                  f"cost=${workflow_run['cost']:.6f}")

    return rows


def summarize(rows):
    summary = {}
    for system in ("agent", "workflow"):
        sys_rows = [r for r in rows if r["system"] == system]
        n = len(sys_rows)
        passed = sum(1 for r in sys_rows if r["pass"])
        latencies = [r["latency_ms"] for r in sys_rows]
        total_tokens = sum(r["tokens"] for r in sys_rows)
        total_cost = sum(r["cost"] for r in sys_rows)
        summary[system] = {
            "pass_rate": passed / n if n else 0.0,
            "p50_latency_ms": statistics.median(latencies) if latencies else 0.0,
            "total_tokens": total_tokens,
            "cost_per_claim": total_cost / n if n else 0.0,
        }
    return summary


def print_summary(summary):
    print()
    print(f"{'system':<10} {'pass rate':>10} {'p50 latency':>13} {'total tokens':>13} {'cost/claim':>12}")
    for system, s in summary.items():
        print(
            f"{system:<10} {s['pass_rate']*100:>9.0f}% {s['p50_latency_ms']:>11.0f}ms "
            f"{s['total_tokens']:>13} ${s['cost_per_claim']:>10.6f}"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv-path", default="race.csv")
    parser.add_argument("--summary-path", default="race_summary.json")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    config.preflight()
    rows = run_race(verbose=not args.quiet)
    summary = summarize(rows)

    with open(args.csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["system", "claim_id", "pass", "latency_ms", "tokens", "cost", "status"])
        writer.writeheader()
        writer.writerows(rows)

    Path(args.summary_path).write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print_summary(summary)
    print(f"\nWrote {args.csv_path} and {args.summary_path}")


if __name__ == "__main__":
    main()
