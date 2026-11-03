"""Frozen failures replayed against the guard: zero API calls.

    python -m w12.evals.regression --freeze w12-baseline   # add this run's judge-flagged summaries
    python -m w12.evals.regression                         # replay: every frozen summary must trip the guard

The failure->test loop's deterministic half. Every referral summary that the
judge said states a coverage decision is frozen here verbatim with its trace
id. The guard must withhold every one of them. A summary that once reached an
adjuster can never reach one again without this test going red.
"""

import argparse
import json
import sys
from pathlib import Path

from w12 import guard

ROOT = Path(__file__).resolve().parent.parent.parent
PATH = ROOT / "evals" / "w12" / "regression_decision_language.json"


def load():
    return json.loads(PATH.read_text(encoding="utf-8"))["items"] if PATH.exists() else []


def freeze(label):
    run_dir = ROOT / "evals" / "w12" / "runs" / label
    judged = json.loads((run_dir / "judge.json").read_text())
    runs = [json.loads(l) for l in (run_dir / "w12_runs.jsonl").read_text().splitlines() if l.strip()]
    items = {i["trace_id"]: i for i in load()}
    for rec in runs:
        j = judged.get(rec.get("trace_id"), {})
        if j.get("no_decision") is not False:
            continue
        raw = next((tc["args"].get("summary") for tc in rec["tool_calls"] if tc["name"] == "refer_to_adjuster"), None)
        if raw and rec["trace_id"] not in items:
            items[rec["trace_id"]] = {"trace_id": rec["trace_id"], "claim_id": rec["claim_id"], "run": label,
                                      "guard_at_run_time": rec["referral"]["guard"]["found"],
                                      "judge_rationale": j.get("rationale"), "summary": raw}
    PATH.write_text(json.dumps({"_about": __doc__.strip().splitlines()[0], "items": list(items.values())},
                               indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(items)} frozen summaries in {PATH.relative_to(ROOT)}")


def replay():
    items = load()
    missed = [i for i in items if not guard.violations(i["summary"])]
    for i in missed:
        print(f"LEAK  {i['trace_id'][:12]} {i['claim_id']}: judge said '{i['judge_rationale']}'")
    print(f"{len(items)} frozen decision-language summaries, {len(missed)} pass the guard")
    return not missed


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze", metavar="LABEL")
    a = ap.parse_args()
    if a.freeze:
        freeze(a.freeze)
    sys.exit(0 if replay() else 1)
