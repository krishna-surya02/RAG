"""Score claim_agent.py's tool-call trajectories, not just its final output.

    python trajectory_eval.py --run --trials 2      # drive fresh live trials, then score them
    python trajectory_eval.py                        # score every agent trace already on disk
    python trajectory_eval.py --since 2026-09-29T00   # score only traces at/after this ISO stamp
    python trajectory_eval.py --mitigation            # also run the before/after mitigation report

race.py's `_passed()` only checks the final claim_status/exclusion_code/payout/
cap fields against claims_data.json's `expected` block -- it never looks at
`tool_calls`. An agent can reach the right payout without ever opening the
exclusions on a claim that happens to be clean, and race.py would call that a
pass. This script scores the path: which tools were called, whether their
arguments were grounded in real prior results or invented, how many steps it
took, and what it cost -- then reports the gap between "outcome pass rate" and
"trajectory pass rate" as a number.

For all 10 claims in claims_data.json, the valid tool sequence is a SINGLETON
set: (get_claim, check_policy_exclusions, compute_payout), each called exactly
once, in that order. This isn't an assumption baked into the scorer -- it's a
documented finding: (a) check_policy_exclusions needs form/edition/cause, and
cause can only be read from get_claim's notes -- there is no other source;
(b) compute_payout needs a claim_status/cap decision that is only knowable
after check_policy_exclusions returns (contract-specific facts, never
guessable); (c) claim_agent.py's system prompt makes compute_payout explicitly
mandatory ("you MUST call compute_payout... never compute or guess"). So
EXPECTED_SEQUENCES below is a genuinely generic mechanism -- a dict mapping
claim_id -> a SET of acceptable tuples -- and it happens that all 10 sets
contain exactly one tuple. A claim needing real branching would just get a
second tuple added to its set; none currently does.
"""

import argparse
import csv
import json
import statistics
import time
import typing
from collections import Counter
from pathlib import Path

import claim_agent
import claims_common
import claims_tools
import config
import race
import tracing

CLAIMS_PATH = Path(__file__).parent / "claims_data.json"

CANONICAL_SEQUENCE = ("get_claim", "check_policy_exclusions", "compute_payout")
STEPS_NEEDED = len(CANONICAL_SEQUENCE)

AGENT_TOKEN_ESTIMATE = 6000  # same estimate race.py uses for this model/prompt

FAILURE_MODES = (
    "mandatory_tool_skipped",
    "wrong_tool_order",
    "argument_hallucination",
    "ungrounded_citation",
    "redundant_tool_call",
)


def _load_claims():
    return json.loads(CLAIMS_PATH.read_text(encoding="utf-8"))["claims"]


_CLAIMS = _load_claims()
REAL_CLAIM_IDS = {c["claim_id"] for c in _CLAIMS}
CLAIMS_BY_ID = {c["claim_id"]: c for c in _CLAIMS}

VALID_CAUSES = set(typing.get_args(claims_tools.CauseCategory))
VALID_CLAIM_STATUSES = {"approved", "denied", "partial"}
VALID_EXCLUSION_CODES = {rule["code"] for rule in claims_tools._RULES.values()} | {None}

EXPECTED_SEQUENCES = {claim_id: frozenset({CANONICAL_SEQUENCE}) for claim_id in REAL_CLAIM_IDS}


# --- Loading runs ------------------------------------------------------------


def load_agent_runs(trace_path=None, since=None):
    """Every agent trace record (system == "agent") in trace_path, one dict per
    run -- every trial for every claim id, never deduplicated to last-write-
    wins, since sampling temperature=0.4 variance across trials is the point.
    `since`, if given, is an ISO8601 string (tracing.now_utc()'s own format,
    lexically comparable), filtering to ts >= since so a caller can score
    exactly one fresh batch without conflating it with older traces."""
    trace_path = trace_path or claim_agent.TRACE_PATH
    records = tracing.load_traces(trace_path)
    runs = [r for r in records if r.get("system") == "agent"]
    if since is not None:
        runs = [r for r in runs if r.get("ts", "") >= since]
    return runs


def run_trials(claims=None, trials=2, verbose=True):
    """Live-drive claim_agent.run_claim `trials` times per claim, paced the
    same way race.py paces the agent half of the race. Returns the ISO
    timestamp captured before the first call, so the caller can pass it to
    load_agent_runs(since=...) and score exactly this batch."""
    claims = claims if claims is not None else _CLAIMS
    limiter = claims_common.RateLimiter(tpm=8000, margin=0.8)
    started_at = tracing.now_utc()
    for claim in claims:
        for trial in range(1, trials + 1):
            limiter.wait_for_budget(AGENT_TOKEN_ESTIMATE)
            run = claims_common.call_with_backoff(claim_agent.run_claim, claim["claim_id"], verbose=False)
            limiter.record(run["tokens"])
            if verbose:
                print(
                    f"  {claim['claim_id']} trial {trial}/{trials}: status={run['status']} "
                    f"tokens={run['tokens']} cost=${run['cost']:.6f}"
                )
    return started_at


# --- Per-run tool-sequence scoring -------------------------------------------


def tool_sequence(run):
    return tuple(tc["name"] for tc in run.get("tool_calls", []))


def tool_choice_ok(run):
    return tool_sequence(run) in EXPECTED_SEQUENCES.get(run["claim_id"], frozenset())


def tool_choice_accuracy(runs):
    return (sum(1 for r in runs if tool_choice_ok(r)) / len(runs)) if runs else 0.0


def step_efficiency(run):
    return len(run.get("tool_calls", [])) / STEPS_NEEDED


def step_efficiency_summary(runs):
    values = [step_efficiency(r) for r in runs]
    return {"mean": statistics.mean(values) if values else 0.0, "max": max(values) if values else 0.0}


# --- Per-run argument-validity scoring ---------------------------------------


def _prior_result(run, tool_name, before_turn):
    """The most recent result for tool_name strictly before before_turn -- not
    just "called somewhere in this run". A tool call's arguments were only
    generated with an earlier result in hand if that result existed before
    this turn; checking "called anywhere in the run" would wrongly credit an
    argument as grounded in a result the model hadn't actually seen yet."""
    matches = [tc for tc in run.get("tool_calls", []) if tc["name"] == tool_name and tc["turn"] < before_turn]
    return matches[-1]["result"] if matches else None


def _check(run, tc, name, passed, detail, applicable=True):
    return {
        "trace_id": run["trace_id"],
        "claim_id": run["claim_id"],
        "turn": tc["turn"],
        "tool": tc["name"],
        "check": name,
        "applicable": applicable,
        "passed": bool(passed) if applicable else None,
        "detail": detail,
    }


def check_run_arguments(run):
    """Every deterministic argument-grounding assertion this run's tool_calls
    admit -- one row per check, per tool call, plus one row for the final
    output's exclusion_code. `applicable=False` rows are excluded from the
    rate, the same convention evaluate_answers.py's check_assertions uses."""
    claim = CLAIMS_BY_ID.get(run["claim_id"])
    rows = []
    for tc in run.get("tool_calls", []):
        name, args, result = tc["name"], tc.get("args", {}) or {}, tc.get("result", {}) or {}

        if name == "get_claim":
            rows.append(
                _check(
                    run, tc, "claim_id_is_real",
                    args.get("claim_id") in REAL_CLAIM_IDS,
                    f"claim_id={args.get('claim_id')!r}",
                )
            )

        elif name == "check_policy_exclusions":
            gc = _prior_result(run, "get_claim", tc["turn"])
            expected_cause = claim["expected"]["cause_category"] if claim else None
            rows.append(
                _check(run, tc, "cause_in_enum", args.get("cause") in VALID_CAUSES, f"cause={args.get('cause')!r}")
            )
            rows.append(
                _check(
                    run, tc, "cause_matches_expected",
                    args.get("cause") == expected_cause,
                    f"got {args.get('cause')!r}, expected.cause_category={expected_cause!r}",
                )
            )
            rows.append(
                _check(
                    run, tc, "form_grounded_in_get_claim",
                    gc is not None and args.get("form") == gc.get("form"),
                    "no prior get_claim result" if gc is None else f"{args.get('form')!r} vs {gc.get('form')!r}",
                )
            )
            rows.append(
                _check(
                    run, tc, "edition_grounded_in_get_claim",
                    gc is not None and args.get("edition") == gc.get("edition"),
                    "no prior get_claim result" if gc is None else f"{args.get('edition')!r} vs {gc.get('edition')!r}",
                )
            )

            cited_file = (result.get("citation") or {}).get("source_file")
            cited_edition = claims_tools.extract_edition(cited_file)
            if cited_edition is None:
                rows.append(
                    _check(
                        run, tc, "citation_edition_matches_claim", None,
                        f"citation {cited_file!r} carries no embedded edition (endorsement/claim-form PDF, "
                        "or no hit) -- not applicable",
                        applicable=False,
                    )
                )
            else:
                real_edition = claim["edition"] if claim else None
                rows.append(
                    _check(
                        run, tc, "citation_edition_matches_claim",
                        cited_edition == real_edition,
                        f"cited {cited_file!r} (edition {cited_edition}) vs claim's real edition {real_edition!r}",
                    )
                )

        elif name == "compute_payout":
            gc = _prior_result(run, "get_claim", tc["turn"])
            excl = _prior_result(run, "check_policy_exclusions", tc["turn"])
            rows.append(
                _check(
                    run, tc, "claimed_amount_grounded",
                    gc is not None and args.get("claimed_amount") == gc.get("claimed_amount"),
                    "no prior get_claim result" if gc is None
                    else f"{args.get('claimed_amount')!r} vs {gc.get('claimed_amount')!r}",
                )
            )
            rows.append(
                _check(
                    run, tc, "deductible_grounded",
                    gc is not None and args.get("deductible") == gc.get("deductible"),
                    "no prior get_claim result" if gc is None
                    else f"{args.get('deductible')!r} vs {gc.get('deductible')!r}",
                )
            )
            rows.append(
                _check(
                    run, tc, "claim_status_in_enum",
                    args.get("claim_status") in VALID_CLAIM_STATUSES,
                    f"claim_status={args.get('claim_status')!r}",
                )
            )
            status, cap_arg = args.get("claim_status"), args.get("cap")
            if status != "partial" and cap_arg is None:
                rows.append(_check(run, tc, "cap_grounded", None, "cap not required outside partial", applicable=False))
            else:
                if excl and excl.get("buyback_endorsement"):
                    expected_cap = gc.get("endorsement_limit") if gc else None
                else:
                    expected_cap = excl.get("cap") if excl else None
                rows.append(
                    _check(run, tc, "cap_grounded", cap_arg == expected_cap, f"cap={cap_arg!r} vs expected {expected_cap!r}")
                )
        else:
            rows.append(_check(run, tc, "tool_name_real", False, f"unknown tool {name!r} -- not one of the three"))

    output = run.get("output")
    if isinstance(output, dict):
        rows.append(
            {
                "trace_id": run["trace_id"], "claim_id": run["claim_id"], "turn": None,
                "tool": "final_output", "check": "exclusion_code_real", "applicable": True,
                "passed": output.get("exclusion_code") in VALID_EXCLUSION_CODES,
                "detail": f"output.exclusion_code={output.get('exclusion_code')!r}",
            }
        )
    return rows


def argument_validity_rate(check_rows):
    applicable = [c for c in check_rows if c["applicable"]]
    return (sum(1 for c in applicable if c["passed"]) / len(applicable)) if applicable else 0.0


# --- Cost -------------------------------------------------------------------


def cost_summary(runs):
    costs = [r["cost_used"] for r in runs]
    tokens = [r["tokens_used"] for r in runs]
    latencies = [r["latency_ms"] for r in runs]
    return {
        "cost_p50": statistics.median(costs) if costs else 0.0,
        "cost_max": max(costs) if costs else 0.0,
        "tokens_p50": statistics.median(tokens) if tokens else 0,
        "tokens_max": max(tokens) if tokens else 0,
        "latency_p50_ms": statistics.median(latencies) if latencies else 0.0,
        "latency_max_ms": max(latencies) if latencies else 0.0,
    }


# --- Outcome vs. trajectory ---------------------------------------------------


def outcome_passed(run):
    claim = CLAIMS_BY_ID.get(run["claim_id"])
    return claim is not None and race._passed(run.get("output"), claim["expected"])


def run_trajectory_passed(run, check_rows):
    applicable = [c for c in check_rows if c["applicable"]]
    return tool_choice_ok(run) and all(c["passed"] for c in applicable)


def _trajectory_pass_rate(runs, checks_by_run):
    if not runs:
        return 0.0
    return sum(1 for r in runs if run_trajectory_passed(r, checks_by_run[r["trace_id"]])) / len(runs)


def find_divergences(runs, checks_by_run):
    """Any run where the outcome passed but the trajectory didn't -- generic,
    not hardcoded to any one claim id. On the committed week-7 trace this
    returns exactly one row: CLM-2026-010003."""
    rows = []
    for run in runs:
        rows_for_run = checks_by_run[run["trace_id"]]
        if outcome_passed(run) and not run_trajectory_passed(run, rows_for_run):
            rows.append(
                {
                    "trace_id": run["trace_id"], "claim_id": run["claim_id"], "ts": run.get("ts"),
                    "failing_checks": [c for c in rows_for_run if c["applicable"] and not c["passed"]],
                }
            )
    return rows


def tally_failure_modes(runs, checks_by_run):
    tally = {tag: 0 for tag in FAILURE_MODES}
    for run in runs:
        seq = tool_sequence(run)
        rows = checks_by_run[run["trace_id"]]
        if run.get("status") == "ok" and set(CANONICAL_SEQUENCE) - set(seq):
            tally["mandatory_tool_skipped"] += 1
        if set(seq) == set(CANONICAL_SEQUENCE) and seq != CANONICAL_SEQUENCE:
            tally["wrong_tool_order"] += 1
        if any(r["applicable"] and not r["passed"] and r["check"] != "citation_edition_matches_claim" for r in rows):
            tally["argument_hallucination"] += 1
        if any(r["applicable"] and not r["passed"] and r["check"] == "citation_edition_matches_claim" for r in rows):
            tally["ungrounded_citation"] += 1
        if len(seq) > STEPS_NEEDED or max(Counter(seq).values(), default=0) > 1:
            tally["redundant_tool_call"] += 1
    return tally


def score_batch(runs):
    checks_by_run = {r["trace_id"]: check_run_arguments(r) for r in runs}
    all_checks = [c for cs in checks_by_run.values() for c in cs]
    n = len(runs)
    return {
        "n_runs": n,
        "tool_choice_accuracy": tool_choice_accuracy(runs),
        "argument_validity_rate": argument_validity_rate(all_checks),
        "step_efficiency": step_efficiency_summary(runs),
        "cost": cost_summary(runs),
        "outcome_pass_rate": (sum(1 for r in runs if outcome_passed(r)) / n) if n else 0.0,
        "trajectory_pass_rate": _trajectory_pass_rate(runs, checks_by_run),
        "failure_mode_tally": tally_failure_modes(runs, checks_by_run),
        "divergences": find_divergences(runs, checks_by_run),
        "_checks_by_run": checks_by_run,
    }


# --- Mitigation ---------------------------------------------------------------


def recompute_citation(args):
    """Tier-1 replay: call the (already-patched) tool directly with the
    recorded args -- deterministic, no LLM involved."""
    return claims_tools.check_policy_exclusions(**args)


def _patched_checks(runs, checks_by_run):
    patched = {}
    for run in runs:
        rows = [dict(row) for row in checks_by_run[run["trace_id"]]]
        claim = CLAIMS_BY_ID.get(run["claim_id"])
        real_edition = claim["edition"] if claim else None
        for tc in run.get("tool_calls", []):
            if tc["name"] != "check_policy_exclusions":
                continue
            new_result = recompute_citation(tc["args"])
            new_file = (new_result.get("citation") or {}).get("source_file")
            new_edition = claims_tools.extract_edition(new_file)
            for row in rows:
                if row["turn"] == tc["turn"] and row["check"] == "citation_edition_matches_claim" and row["applicable"]:
                    if new_edition is None:
                        # Same rule check_run_arguments applies: a citation with no
                        # embedded edition (endorsement/claim-form PDF) has nothing to
                        # mismatch, so it drops out of the rate rather than counting
                        # as a fabricated pass or fail.
                        row["applicable"] = False
                        row["passed"] = None
                        row["detail"] = f"[after patch] cited {new_file!r} carries no embedded edition -- not applicable"
                    else:
                        row["passed"] = new_edition == real_edition
                        row["detail"] = f"[after patch] cited {new_file!r} (edition {new_edition}) vs claim edition {real_edition!r}"
        patched[run["trace_id"]] = rows
    return patched


def measure_mitigation_price(sample_args):
    """Local-only timing: the patch changes retrieval.retrieve's k from 1 to 5
    plus a python-side edition filter. No Groq call is involved, so tokens and
    cost added is exactly 0/claim; latency is the only real price, and it's
    measured here rather than guessed."""
    import retrieval

    form, edition, cause = sample_args["form"], sample_args["edition"], sample_args["cause"]
    query = claims_tools._CAUSE_QUERY.get(cause, claims_tools._CAUSE_QUERY["other"])

    t0 = time.perf_counter()
    retrieval.retrieve(f"{form} edition {edition}: {query}", k=1)
    old_ms = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    claims_tools.check_policy_exclusions(form, edition, cause)
    new_ms = (time.perf_counter() - t0) * 1000

    return {"old_call_ms": round(old_ms, 2), "new_call_ms": round(new_ms, 2), "added_ms": round(new_ms - old_ms, 2)}


def mitigation_report(runs):
    before_checks = {r["trace_id"]: check_run_arguments(r) for r in runs}
    after_checks = _patched_checks(runs, before_checks)

    before = {
        "n_runs": len(runs),
        "argument_validity_rate": argument_validity_rate([c for cs in before_checks.values() for c in cs]),
        "trajectory_pass_rate": _trajectory_pass_rate(runs, before_checks),
        "failure_mode_tally": tally_failure_modes(runs, before_checks),
    }
    after = {
        "n_runs": len(runs),
        "argument_validity_rate": argument_validity_rate([c for cs in after_checks.values() for c in cs]),
        "trajectory_pass_rate": _trajectory_pass_rate(runs, after_checks),
        "failure_mode_tally": tally_failure_modes(runs, after_checks),
    }

    regression = []
    for mode in FAILURE_MODES:
        b, a = before["failure_mode_tally"][mode], after["failure_mode_tally"][mode]
        delta = a - b
        verdict = "unaffected" if delta == 0 else ("improved" if delta < 0 else "REGRESSED")
        regression.append({"mode": mode, "before": b, "after": a, "delta": delta, "verdict": verdict})

    price = None
    ce_calls = [tc["args"] for r in runs for tc in r.get("tool_calls", []) if tc["name"] == "check_policy_exclusions"]
    if ce_calls:
        price = measure_mitigation_price(ce_calls[0])

    return {"before": before, "after": after, "regression": regression, "price": price}


# --- Reporting ----------------------------------------------------------------


def print_summary(summary):
    print()
    print(f"n_runs: {summary['n_runs']}")
    print(f"tool-choice accuracy:   {summary['tool_choice_accuracy']*100:6.1f}%")
    print(f"argument validity rate: {summary['argument_validity_rate']*100:6.1f}%")
    se = summary["step_efficiency"]
    print(f"step efficiency:        mean={se['mean']:.2f}  max={se['max']:.2f}")
    c = summary["cost"]
    print(f"cost/claim:             p50=${c['cost_p50']:.6f}  max=${c['cost_max']:.6f}")
    print(f"tokens/claim:           p50={c['tokens_p50']:.0f}  max={c['tokens_max']:.0f}")
    print(f"latency/claim:          p50={c['latency_p50_ms']:.0f}ms  max={c['latency_max_ms']:.0f}ms")
    print(f"outcome pass rate:      {summary['outcome_pass_rate']*100:6.1f}%")
    print(f"trajectory pass rate:   {summary['trajectory_pass_rate']*100:6.1f}%")
    gap = summary["outcome_pass_rate"] - summary["trajectory_pass_rate"]
    print(f"gap (outcome - traj):   {gap*100:+6.1f} pts")
    print()
    print("failure mode tally:")
    for mode, count in summary["failure_mode_tally"].items():
        print(f"  {mode:<24} {count}")


def print_divergences(divergences):
    print()
    print("=== outcome passed but trajectory failed ===")
    if not divergences:
        print("  (none)")
        return
    for d in divergences:
        print(f"{d['claim_id']} (trace {d['trace_id'][:12]}..., {d['ts']})")
        for c in d["failing_checks"]:
            print(f"  failing check: {c['tool']}.{c['check']}")
            print(f"    {c['detail']}")


def print_regression(mitigation):
    print()
    print("=== mitigation: before -> after ===")
    print(f"{'mode':<24} {'before':>8} {'after':>8} {'delta':>8}  verdict")
    for row in mitigation["regression"]:
        print(f"{row['mode']:<24} {row['before']:>8} {row['after']:>8} {row['delta']:>+8}  {row['verdict']}")
    if mitigation["price"]:
        p = mitigation["price"]
        print(f"\nprice paid: latency {p['added_ms']:+.2f}ms/check_policy_exclusions call "
              f"({p['old_call_ms']}ms -> {p['new_call_ms']}ms); +0 tokens, +$0.00 cost/claim (no LLM call involved)")


# --- Output files --------------------------------------------------------------


def write_csv(path, runs, checks_by_run):
    fieldnames = [
        "trace_id", "claim_id", "ts", "outcome_pass", "tool_choice_ok",
        "argument_validity_rate", "trajectory_pass", "step_efficiency",
        "tokens_used", "cost_used", "latency_ms", "status",
    ]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for run in runs:
            rows = checks_by_run[run["trace_id"]]
            writer.writerow(
                {
                    "trace_id": run["trace_id"], "claim_id": run["claim_id"], "ts": run.get("ts"),
                    "outcome_pass": outcome_passed(run), "tool_choice_ok": tool_choice_ok(run),
                    "argument_validity_rate": round(argument_validity_rate(rows), 4),
                    "trajectory_pass": run_trajectory_passed(run, rows),
                    "step_efficiency": round(step_efficiency(run), 4),
                    "tokens_used": run["tokens_used"], "cost_used": run["cost_used"],
                    "latency_ms": run["latency_ms"], "status": run["status"],
                }
            )


def _json_ready(summary):
    return {k: v for k, v in summary.items() if not k.startswith("_")}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", action="store_true", help="drive fresh live trials before scoring")
    parser.add_argument("--trials", type=int, default=2)
    parser.add_argument("--since", default=None, help="ISO8601 timestamp; score only traces at/after this (ignored with --run)")
    parser.add_argument("--trace-path", default=None)
    parser.add_argument("--mitigation", action="store_true", help="also run the before/after mitigation report")
    parser.add_argument("--csv-path", default="trajectory.csv")
    parser.add_argument("--summary-path", default="trajectory_summary.json")
    parser.add_argument("--mitigation-path", default="trajectory_mitigation.json")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    config.preflight()

    since = args.since
    if args.run:
        since = run_trials(trials=args.trials, verbose=not args.quiet)

    runs = load_agent_runs(args.trace_path, since=since)
    if not runs:
        raise SystemExit("no agent runs found for the given window")

    summary = score_batch(runs)
    write_csv(args.csv_path, runs, summary["_checks_by_run"])
    Path(args.summary_path).write_text(json.dumps(_json_ready(summary), indent=2), encoding="utf-8")

    if not args.quiet:
        print_summary(summary)
        print_divergences(summary["divergences"])

    print(f"\nWrote {args.csv_path} and {args.summary_path}")

    if args.mitigation:
        mitigation = mitigation_report(runs)
        Path(args.mitigation_path).write_text(json.dumps(mitigation, indent=2), encoding="utf-8")
        if not args.quiet:
            print_regression(mitigation)
        print(f"Wrote {args.mitigation_path}")


if __name__ == "__main__":
    main()
