"""The integrated eval suite, one command.

    python triage.py eval --label w12-live          # run every case live, then grade
    python triage.py eval --label w12-live          # again: resumes, skipping cases already run
    python triage.py eval --rescore w12-live        # re-grade saved runs: zero generation calls
    python triage.py eval --label x --only w12-06   # one case (the failure->test loop)

Order per case, as the brief asks: the agent run, then deterministic
assertions, then the judge (gpt-oss-120b, cached per trace id), then the
taxonomy detectors and the trajectory score. A run's spans, MCP-server spans,
run records and referrals all live under evals/w12/runs/<label>/, so a run is
self-contained and `triage.py trace <id> --dir evals/w12/runs/<label>` opens
any case.

The Groq daily quota (200k tokens/day per model on this account) is smaller
than one full live run, so a daily-quota error stops the loop cleanly and the
same command resumes tomorrow. Each case records the date it ran on.
"""

import json
import os
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
RUNS = ROOT / "evals" / "w12" / "runs"


def add_args(p):
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--label", help="run (or resume) live into evals/w12/runs/<label>")
    g.add_argument("--rescore", metavar="LABEL", help="re-grade a saved run without generation calls")
    p.add_argument("--only", help="comma-separated case ids, claim ids or scenario substrings")
    p.add_argument("--cases", default=str(ROOT / "evals" / "w12" / "cases.json"))
    p.add_argument("--rejudge", action="store_true", help="ignore cached judge verdicts")
    p.add_argument("--no-judge", action="store_true", help="assertions only")
    p.add_argument("--max-new", type=int, default=None, help="stop after this many new live runs")
    p.add_argument("--quiet", action="store_true")


def _select(cases, only):
    if not only:
        return cases
    keys = [k.strip() for k in only.split(",") if k.strip()]
    return [c for c in cases if any(k == c["id"] or k == c["claim_id"] or k in c["scenario"] for k in keys)]


def _load_jsonl(path):
    if not path.exists():
        return []
    return [(json.loads(l), l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _span_latency(run_dir, trace_id):
    by = {}
    for f in ("w12_spans.jsonl", "w12_mcp.jsonl"):
        for s, _ in _load_jsonl(run_dir / f):
            if s.get("trace_id") == trace_id and s["kind"] in ("llm", "tool", "mcp_client", "mcp_server", "referral"):
                by[s["kind"]] = round(by.get(s["kind"], 0) + s["latency_ms"], 1)
    return by


def run_live(cases, run_dir, index, max_new, quiet):
    from w12 import agent

    new = 0
    for case in cases:
        if case["id"] in index:
            continue
        if max_new is not None and new >= max_new:
            print(f"stopping after {new} new runs (--max-new)")
            break
        print(f"[{case['id']}] {case['claim_id']} {case['scenario']} ...", flush=True)
        for attempt in range(2):
            rec = agent.run(case["claim_id"], verbose=not quiet)
            if rec["status"] == "rate_limited:daily":
                print(f"\nDaily Groq quota reached after {new} new runs (this claim was still referred, "
                      f"trace {rec['trace_id'][:12]}, but is not counted). Re-run the same command to resume.\n"
                      f"  {rec['model_errors'][-1]}")
                return False
            if rec["status"] != "rate_limited:minute":
                break
            print("  per-minute rate limit; backing off 60s")
            time.sleep(60)
        else:
            continue
        index[case["id"]] = {"trace_id": rec["trace_id"], "claim_id": case["claim_id"],
                             "ran_on": rec["ts"][:10], "status": rec["status"]}
        (run_dir / "index.json").write_text(json.dumps(index, indent=1) + "\n", encoding="utf-8")
        print(f"  -> {rec['status']} ${rec['cost_usd']:.5f} {rec['prompt_tokens'] + rec['completion_tokens']} tok "
              f"flags={rec['referral']['flags']} cites={[c['ref'] for c in rec['referral']['citations']]}", flush=True)
        new += 1
    return True


def grade(cases, run_dir, index, use_judge, rejudge):
    from claims_common import RateLimiter
    from w12.evals import analysis, assertions, judge

    runs = {r["trace_id"]: (r, line) for r, line in _load_jsonl(run_dir / "w12_runs.jsonl") if r.get("claim_id")}
    judge_cache_path = run_dir / "judge.json"
    cache = json.loads(judge_cache_path.read_text()) if judge_cache_path.exists() else {}
    limiter = RateLimiter(tpm=8000, margin=0.8)
    rows = []
    for case in cases:
        entry = index.get(case["id"])
        if not entry or entry["trace_id"] not in runs:
            continue
        rec, line = runs[entry["trace_id"]]
        rec["span_latency_ms"] = _span_latency(run_dir, rec["trace_id"])
        checks = assertions.check(case, rec, line)
        judged = None
        if use_judge:
            judged = None if rejudge else cache.get(rec["trace_id"])
            if judged is None:
                judged = judge.judge(case, rec, limiter=limiter)
                cache[rec["trace_id"]] = judged
                judge_cache_path.write_text(json.dumps(cache, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        a_pass = assertions.passed(checks)
        j_pass = None if judged is None else judged.get("verdict") == "pass"
        row = {"id": case["id"], "claim_id": case["claim_id"], "scenario": case["scenario"],
               "trace_id": rec["trace_id"], "ran_on": entry.get("ran_on"), "case": case, "rec": rec,
               "checks": [{"name": n, "passed": ok, "detail": d} for n, ok, d in checks],
               "assertions_passed": a_pass, "judge": judged, "judge_passed": j_pass,
               "passed": a_pass and (j_pass is not False)}
        row["modes"] = analysis.modes_for(case, rec, checks, judged)
        row["trajectory"] = analysis.trajectory(case, rec)
        rows.append(row)
    return rows


def summarise(rows, run_dir, label, use_judge):
    from w12.evals import analysis, judge_agreement

    n = len(rows)
    out = {
        "label": label,
        "cases_graded": n,
        "ran_on": sorted({r["ran_on"] for r in rows if r["ran_on"]}),
        "suite_pass": sum(r["passed"] for r in rows),
        "assertions_pass": sum(r["assertions_passed"] for r in rows),
        "judge_pass": sum(bool(r["judge_passed"]) for r in rows) if use_judge else None,
        "judge_parse_errors": sum(1 for r in rows if r["judge"] and r["judge"].get("parse_error")),
        "assertion_pass_rates": {},
        "taxonomy": analysis.taxonomy(rows),
        "trajectory": analysis.trajectory_summary(rows),
        "costs": analysis.costs(rows) if rows else None,
        "judge_agreement": judge_agreement.compute(run_dir, rows),
    }
    names = sorted({c["name"] for r in rows for c in r["checks"]})
    for name in names:
        app = [c for r in rows for c in r["checks"] if c["name"] == name and c["passed"] is not None]
        out["assertion_pass_rates"][name] = f"{sum(c['passed'] for c in app)}/{len(app)}"
    return out


def to_markdown(s, rows):
    L = [f"# Eval run `{s['label']}`", "",
         f"Ran on: {', '.join(s['ran_on'])}. Graded {s['cases_graded']} cases.", "",
         f"**Suite: PASS {s['suite_pass']}/{s['cases_graded']}** (assertions {s['assertions_pass']}/{s['cases_graded']}"
         + (f", judge {s['judge_pass']}/{s['cases_graded']}" if s["judge_pass"] is not None else ", judge not run") + ")", ""]
    ja = s["judge_agreement"]
    L.append(f"**Judge vs hand labels:** {ja['summary']}")
    L += ["", "## Assertions (run before the judge)", "", "| assertion | pass |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in s["assertion_pass_rates"].items()]
    L += ["", "## Error taxonomy (integrated system)", "",
          "| mode | origin | severity | frequency | example trace |", "|---|---|---|---|---|"]
    for m in s["taxonomy"]:
        L.append(f"| `{m['mode']}` | {m['origin']} | {m['severity']} | {m['frequency_pct']}% ({m['cases']}/{s['cases_graded']}) "
                 f"| `{m['example_trace_id'][:12]}` ({m['example_case']}) |")
    t = s["trajectory"]
    if t:
        L += ["", "## Trajectory", "",
              f"{t['cases']} cases. Tool-choice accuracy **{t['tool_choice_accuracy']:.0%}**, argument validity "
              f"{t['argument_validity']:.0%}, trajectory pass {t['trajectory_pass_rate']:.0%}, outcome pass "
              f"{t['outcome_pass_rate']:.0%}: **outcome − trajectory gap {t['gap_points']:+.1f} points**.",
              f"Outcome passed but path failed: {t['outcome_pass_trajectory_fail'] or 'none'}. "
              f"Path passed but outcome failed: {t['trajectory_pass_outcome_fail'] or 'none'}."]
    c = s["costs"]
    if c:
        L += ["", "## Cost and latency per claim triaged", "",
              f"- cost: mean ${c['cost_per_claim_usd']['mean']:.6f}, p50 ${c['cost_per_claim_usd']['p50']:.6f}, p95 ${c['cost_per_claim_usd']['p95']:.6f}",
              f"- tokens: mean {c['tokens_per_claim']['mean']:,}, p95 {c['tokens_per_claim']['p95']:,}; LLM turns mean {c['llm_turns']['mean']}",
              f"- latency excl. rate-limit waits: p50 {c['latency_ms_excl_rate_wait']['p50'] / 1000:.1f}s, p95 {c['latency_ms_excl_rate_wait']['p95'] / 1000:.1f}s; "
              f"wall incl. waits p50 {c['wall_ms_incl_rate_wait']['p50'] / 1000:.1f}s",
              f"- p50 latency by span kind (ms): {c['span_latency_ms_p50']}",
              f"- judge cost per case (eval only, not triage): ${c['judge_cost_per_case_usd'] or 0:.6f}"]
    L += ["", "## Cases", "", "| case | claim | scenario | pass | failed assertions | judge | modes | trace |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        failed = [c["name"] for c in r["checks"] if c["passed"] is False]
        jv = "-" if not r["judge"] else (r["judge"].get("verdict") or "parse_error")
        L.append(f"| {r['id']} | {r['claim_id']} | {r['scenario']} | {'PASS' if r['passed'] else 'FAIL'} | "
                 f"{', '.join(failed) or '-'} | {jv} | {', '.join(r['modes']) or '-'} | `{r['trace_id'][:12]}` |")
    return "\n".join(L) + "\n"


def write_worksheet(run_dir, rows):
    """Blind labelling sheet: what the judge saw, without the judge's verdict.
    Never overwrites labels already filled in."""
    from w12.evals import judge

    path = run_dir / "labels.json"
    existing = json.loads(path.read_text()) if path.exists() else {"items": []}
    have = {i["trace_id"] for i in existing["items"]}
    for r in rows:
        if r["trace_id"] in have:
            continue
        existing["items"].append({"case": r["id"], "trace_id": r["trace_id"],
                                  "inputs": judge.judge_inputs(r["case"], r["rec"]),
                                  "label": None, "labeller": None, "notes": ""})
    existing["_instructions"] = ("Label each item 'pass' or 'fail' using the four questions in "
                                 "evals/w12/judge_w12.txt, WITHOUT looking at judge.json. Set labeller to your "
                                 "name. Then: python triage.py eval --rescore <label>")
    path.write_text(json.dumps(existing, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    md = ["# Hand-label worksheet", "", existing["_instructions"], ""]
    for it in existing["items"]:
        inp = it["inputs"]
        md += [f"## {it['case']} · trace `{it['trace_id'][:12]}` · label: **{it['label'] or '____'}**", "",
               f"**FNOL:** {inp['fnol']}", "", f"**Facts:** `{inp['facts']}`", "", f"**Reference:** `{inp['reference']}`", "",
               "**Cited wording:**", "", "```", inp["cited_wording"], "```", "", f"**Summary:** {inp['summary']}", ""]
    (run_dir / "labels_worksheet.md").write_text("\n".join(md), encoding="utf-8")


def main(args):
    label = args.rescore or args.label
    run_dir = RUNS / label
    run_dir.mkdir(parents=True, exist_ok=True)
    os.environ["W12_TRACE_DIR"] = str(run_dir)
    from w12.evals import cases as casemod

    cases = _select(casemod.load(args.cases), args.only)
    index_path = run_dir / "index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {}
    if args.label:
        import config

        config.preflight()
        run_live(cases, run_dir, index, args.max_new, args.quiet)
    use_judge = not args.no_judge
    rows = grade(cases, run_dir, index, use_judge, args.rejudge)
    if not rows:
        print("nothing graded yet")
        return
    summary = summarise(rows, run_dir, label, use_judge)
    suffix = "" if not args.only else "_only-" + re.sub(r"[^\w-]+", "_", args.only)[:40]
    slim = [{k: v for k, v in r.items() if k not in ("rec", "case")} for r in rows]
    (run_dir / f"results{suffix}.json").write_text(
        json.dumps({"summary": summary, "rows": slim}, indent=1, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    (run_dir / f"report{suffix}.md").write_text(to_markdown(summary, rows), encoding="utf-8")
    write_worksheet(run_dir, rows)
    print(to_markdown(summary, rows))
    print(f"written: {run_dir / f'report{suffix}.md'}")
