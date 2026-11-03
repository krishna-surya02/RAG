"""Error taxonomy, trajectory scoring, and cost per claim, over one eval run.

Taxonomy: week 5's modes (taxonomy.md) re-scored on the integrated system,
plus modes that only exist because the parts are now joined. Each mode has a
deterministic detector where one is possible, falling back to the judge's
tags; only modes actually observed are reported, with frequency over all
cases, a severity, and one trace id to open.

Trajectory: week 8's idea (trajectory_eval.py) -- score the path, not the
answer -- with expectations per case type instead of one fixed sequence,
because a not-in-force claim should NOT search the wording.
"""

import statistics

import redact
from w12 import store

# mode -> (inherited from, severity, definition)
MODES = {
    "wrong_version_for_date": ("week 5 sibling_edition", "S1",
                               "cites or searches wording from an endorsement set other than the one on the term covering the loss date"),
    "scope_dropped_at_mcp_hop": ("NEW (integration)", "S2",
                                 "the in-force check returned the endorsement set, but a wording call over MCP was made without it (or with another product/date)"),
    "redaction_strips_cause": ("NEW (integration)", "S2",
                               "PII redaction removed a non-PII word that names the cause of loss (e.g. 'Calder River' -> [CLAIMANT_2]) and the case failed"),
    "wrong_coverage_line": ("NEW (integration)", "S2",
                            "limits looked up for a coverage line that does not carry the deciding clause's deductible/sub-limit"),
    "limit_conflation": ("NEW (integration)", "S2",
                         "summary attaches a dollar figure to the wrong limit name, or adds limits together"),
    "decision_language": ("week 5 leading_question_accepted (generalised)", "S1",
                          "summary states or implies a coverage decision (withheld by the guard, so not shown to the adjuster)"),
    "missed_deciding_clause": ("week 5 absence_as_exclusion / retrieval miss", "S2",
                               "the clause the adjuster relied on is not among the citations, for no reason above"),
    "not_in_force_ignored": ("NEW (integration)", "S1",
                             "the policy was not in force but the referral did not flag it"),
    "no_referral": ("week 7 budget termination", "S2",
                    "the agent stopped or ran out of budget without referring; the system referred for it"),
    "unsupported_paraphrase": ("week 6 judge tag", "S2", "judge: summary misstates what the cited wording says"),
    "pii_in_output": ("week 5 redaction", "S1", "a generated PII value appears in a run record or referral"),
}

WORDING_TOOLS = ("search_wording", "get_clause")


def _calls(rec, name):
    return [tc for tc in rec["tool_calls"] if tc["name"] == name]


def _redaction_stripped(claim, rec=None):
    """Non-PII words redaction removed from the FNOL the model saw.

    Uses the redacted FNOL recorded in the run when present. Records written
    before that field existed also predate redact.PLACE_NOUNS (the river fix),
    so they are replayed without it -- otherwise a rescore would grade old runs
    with today's redaction and hide what the model was actually given."""
    p = claim["pii"]
    people = [p["claimant_name"], *p["other_people"]]
    if rec is not None and rec.get("fnol_redacted") is None:
        saved = redact.PLACE_NOUNS
        redact.PLACE_NOUNS = set()
        try:
            _, found = redact.redact_many([claim["fnol_text"]])
        finally:
            redact.PLACE_NOUNS = saved
    else:
        _, found = redact.redact_many([claim["fnol_text"]])
    return sorted({raw for kind, raw, _ in found if kind == "claimant_name"
                   and not any(raw in person or person in raw for person in people)})


def modes_for(case, rec, checks, judged):
    exp = case["expected"]
    ok = {name: res for name, res, _ in checks}
    tags = set((judged or {}).get("failure_tags") or [])
    found = set()
    eset = exp["endorsement_set"]
    wording_calls = [tc for tc in rec["tool_calls"] if tc["name"] in WORDING_TOOLS]

    if ok.get("citations_valid_for_loss_date") is False or "wrong_version_for_date" in tags or any(
            tc["args"].get("endorsement_set") not in (None, eset) for tc in wording_calls):
        found.add("wrong_version_for_date")
    if eset and any(tc["args"].get("endorsement_set") is None or tc["args"].get("product") != case["product"]
                    or tc["args"].get("loss_date") != case["loss_date"] for tc in wording_calls):
        found.add("scope_dropped_at_mcp_hop")
    if ok.get("limits_for_right_coverage_line") is False:
        found.add("wrong_coverage_line")
    if ok.get("summary_limits_not_conflated") is False or "limit_conflation" in tags:
        found.add("limit_conflation")
    if ok.get("no_decision_language") is False or "decision_language" in tags or "leading_question_accepted" in tags:
        found.add("decision_language")
    if ok.get("not_in_force_flagged") is False:
        found.add("not_in_force_ignored")
    if ok.get("referral_by_agent") is False:
        found.add("no_referral")
    if ok.get("no_pii_in_run_or_referral") is False:
        found.add("pii_in_output")
    if "unsupported_paraphrase" in tags:
        found.add("unsupported_paraphrase")
    # A withheld summary can't point anywhere, so the judge's Q2 "missed" on it
    # is the guard's doing, already counted as decision_language.
    withheld = ok.get("no_decision_language") is False
    missed = ok.get("deciding_clause_cited") is False or ("missed_deciding_clause" in tags and not withheld)
    stripped = _redaction_stripped(store.claim(case["claim_id"]), rec)
    case_failed = any(res is False for res in ok.values()) or (judged or {}).get("verdict") == "fail"
    if stripped and (case_failed or "cause_misread" in tags):
        # w12-06/07: river floods read as burst pipes once "Calder River" became [CLAIMANT_2]
        found.add("redaction_strips_cause")
    elif missed and not found & {"wrong_version_for_date", "no_referral"}:
        found.add("missed_deciding_clause")
    return sorted(found)


def taxonomy(rows):
    n = len(rows)
    out = []
    for mode, (origin, sev, definition) in MODES.items():
        hit = [r for r in rows if mode in r["modes"]]
        if not hit:
            continue
        out.append({"mode": mode, "origin": origin, "severity": sev, "definition": definition,
                    "cases": len(hit), "frequency_pct": round(100 * len(hit) / n, 1),
                    "example_trace_id": hit[0]["trace_id"], "example_case": hit[0]["id"],
                    "case_ids": [r["id"] for r in hit]})
    return sorted(out, key=lambda m: (-m["cases"], m["severity"]))


# --- Trajectory ---------------------------------------------------------------


def expected_path(case):
    if not case["expected"]["in_force"]:
        return {"required": ["check_in_force", "refer_to_adjuster"],
                "forbidden": ["search_wording", "get_clause", "get_limits"]}
    req = ["check_in_force", "search_wording|get_clause", "refer_to_adjuster"]
    if case["expected"].get("limits"):
        req.insert(2, "get_limits")
    return {"required": req, "forbidden": []}


def trajectory(case, rec):
    names = [tc["name"] for tc in rec["tool_calls"]]
    path = expected_path(case)
    problems = []
    for req in path["required"]:
        if not any(n in req.split("|") for n in names):
            problems.append(f"missing {req}")
    for f in path["forbidden"]:
        if f in names:
            problems.append(f"called {f} on a not-in-force claim")
    if names and names[-1] != "refer_to_adjuster":
        problems.append("refer_to_adjuster not last")
    if "check_in_force" in names:
        first_wording = next((i for i, n in enumerate(names) if n in WORDING_TOOLS), None)
        if first_wording is not None and first_wording < names.index("check_in_force"):
            problems.append("searched wording before the in-force check")
    tool_choice_ok = not problems

    arg_problems = []
    eset = case["expected"]["endorsement_set"]
    for tc in rec["tool_calls"]:
        a = tc["args"]
        if tc["name"] == "check_in_force" and a.get("loss_date") != case["loss_date"]:
            arg_problems.append(f"check_in_force loss_date {a.get('loss_date')}")
        if tc["name"] in WORDING_TOOLS:
            if a.get("loss_date") != case["loss_date"] or a.get("product") != case["product"]:
                arg_problems.append(f"{tc['name']} scope {a.get('product')}/{a.get('loss_date')}")
            if eset and a.get("endorsement_set") != eset:
                arg_problems.append(f"{tc['name']} endorsement_set={a.get('endorsement_set')} (term carries {eset})")
        if tc["name"] == "get_limits" and eset and a.get("endorsement_set") != eset:
            arg_problems.append(f"get_limits endorsement_set={a.get('endorsement_set')}")
    return {"sequence": names, "tool_choice_ok": tool_choice_ok, "tool_problems": problems,
            "args_valid": not arg_problems, "arg_problems": arg_problems,
            "trajectory_pass": tool_choice_ok and not arg_problems}


def trajectory_summary(rows):
    t = [r for r in rows if r["case"].get("trajectory")]
    if not t:
        return None
    n = len(t)
    tc = sum(r["trajectory"]["tool_choice_ok"] for r in t)
    av = sum(r["trajectory"]["args_valid"] for r in t)
    tp = sum(r["trajectory"]["trajectory_pass"] for r in t)
    op = sum(r["passed"] for r in t)
    return {"cases": n, "tool_choice_accuracy": round(tc / n, 3), "argument_validity": round(av / n, 3),
            "trajectory_pass_rate": round(tp / n, 3), "outcome_pass_rate": round(op / n, 3),
            "gap_points": round(100 * (op - tp) / n, 1),
            "outcome_pass_trajectory_fail": [r["id"] for r in t if r["passed"] and not r["trajectory"]["trajectory_pass"]],
            "trajectory_pass_outcome_fail": [r["id"] for r in t if r["trajectory"]["trajectory_pass"] and not r["passed"]]}


# --- Cost ---------------------------------------------------------------------


def _pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    i = min(len(xs) - 1, max(0, round(q * (len(xs) - 1))))
    return xs[i]


def costs(rows):
    recs = [r["rec"] for r in rows]
    cost = [x["cost_usd"] for x in recs]
    tok = [x["prompt_tokens"] + x["completion_tokens"] for x in recs]
    lat = [x["latency_ms"] for x in recs]
    wall = [x["latency_ms"] + x["rate_limit_wait_ms"] for x in recs]
    judge_cost = [r["judge"]["_usage"]["cost_usd"] for r in rows if r.get("judge") and "_usage" in r["judge"]]
    by_span = {}
    for x in recs:
        for name, v in (x.get("span_latency_ms") or {}).items():
            by_span.setdefault(name, []).append(v)
    return {
        "claims": len(recs),
        "cost_per_claim_usd": {"mean": round(statistics.mean(cost), 6), "p50": _pct(cost, .5), "p95": _pct(cost, .95)},
        "tokens_per_claim": {"mean": round(statistics.mean(tok)), "p50": _pct(tok, .5), "p95": _pct(tok, .95)},
        "latency_ms_excl_rate_wait": {"p50": _pct(lat, .5), "p95": _pct(lat, .95)},
        "wall_ms_incl_rate_wait": {"p50": _pct(wall, .5), "p95": _pct(wall, .95)},
        "llm_turns": {"mean": round(statistics.mean(x["llm_calls"] for x in recs), 2)},
        "judge_cost_per_case_usd": round(statistics.mean(judge_cost), 6) if judge_cost else None,
        "span_latency_ms_p50": {k: _pct(v, .5) for k, v in sorted(by_span.items())},
    }
