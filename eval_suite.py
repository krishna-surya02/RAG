"""The answer suite: every golden question plus every evals/case_*.json, live.

    python eval_suite.py --label before                     # RED: today's prompt + retriever
    python eval_suite.py --label after --compare before     # GREEN, with a per-case diff
    python eval_suite.py --label after-x3 --only w11 --repeat 3

Each case goes through rag.answer(source="eval") — the served path, with the
same prompt version and retrieval mode the app is configured with — into its
own trace file, so suite runs never land in the request logs. Each answer is
then graded by judge_v1.txt (validated against hand labels in week 6) on a
different model from the one that answered, so the judge has its own daily
quota and is not grading its own output.

A case passes when all of these hold:
  - the judge's verdict is a right call: correct_supported or right_call_wrong_support
  - every applicable evaluate_answers.check_assertions result passed
  - if the case sets "must_not_call", tracing.answer_call(answer) is not that call.
    This is the deterministic half: a "covered" answer to an excluded loss fails
    on a regex even if the judge has a bad day.

The pass count is over the whole suite, so a fix that rescues one case and
breaks another shows up as the same number, not a better one — --compare lists
every case that flipped.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("TRACE_PATH", "traces/eval_w11.jsonl")

import claims_common  # noqa: E402
import config  # noqa: E402
import rag  # noqa: E402
import tracing  # noqa: E402
from evaluate_answers import check_assertions, get_judge_llm, judge_one, load_goldenset  # noqa: E402

JUDGE_MODEL = claims_common.CLAIMS_CHAT_MODEL  # openai/gpt-oss-20b
RIGHT_CALL = {"correct_supported", "right_call_wrong_support"}
OUT_DIR = Path("evals/results")


def load_cases(goldenset, case_dir):
    cases = [dict(q, origin="goldenset") for q in load_goldenset(goldenset)]
    for path in sorted(Path(case_dir).glob("case_*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        cases.append(dict(case, origin=str(path)))
    return cases


def _context_of(record):
    match = re.search(r"Context:\n(.*)\n\nQuestion:\n", record["prompt"]["rendered"], re.S)
    return match.group(1) if match else None


def run_case(case, judge, template, gen_limiter, judge_limiter):
    gen_limiter.wait_for_budget(3000)
    claims_common.call_with_backoff(
        rag.answer, case["question"], source="eval",
        request={"case_id": case["id"]},
    )
    record = tracing.load_traces()[-1]
    usage = record["output"].get("token_usage") or {}
    gen_limiter.record(usage.get("total_tokens", 3000))

    item = {
        "id": case["id"],
        "question": case["question"],
        "context": _context_of(record),
        "answer": record["output"]["final"],
        "gold_answer": case["gold_answer"],
    }
    judge_limiter.wait_for_budget(4000)
    judged = claims_common.call_with_backoff(judge_one, judge, template, item)
    judge_limiter.record(4000)

    reasons = []
    verdict = judged.get("verdict")
    if "parse_error" in judged:
        reasons.append("judge output did not parse")
    elif verdict not in RIGHT_CALL:
        reasons.append(f"verdict {verdict}")
    assertions = {} if "parse_error" in judged else check_assertions(item, judged)
    for name, result in assertions.items():
        if result.get("applicable") and not result.get("passed"):
            reasons.append(f"assertion {name}: {result.get('detail')}")
    call = record.get("answer_call") or tracing.answer_call(item["answer"])
    if case.get("must_not_call") and call == case["must_not_call"]:
        reasons.append(f"answer_call is {call!r}, which this case forbids")

    return {
        "id": case["id"],
        "origin": case["origin"],
        "passed": not reasons,
        "reasons": reasons,
        "verdict": verdict,
        "answer_call": call,
        "trace_id": record["trace_id"],
        "prompt_version": record["prompt"]["version"],
        "retrieval_mode": record["retrieval"]["mode"],
        "context_files": [h["source_file"] for h in record["retrieval"]["hits"]],
        "answer_head": " ".join(item["answer"].split())[:240],
        "judge_rationale": judged.get("rationale") or judged.get("reasoning"),
    }


def to_markdown(label, rows, previous=None):
    passed = sum(r["passed"] for r in rows)
    lines = [
        f"### eval suite `{label}` — PASS {passed}/{len(rows)}",
        "",
        f"prompt {rows[0]['prompt_version']}, retrieval {rows[0]['retrieval_mode']}, "
        f"answers by {config.CHAT_MODEL}, judged by {JUDGE_MODEL}",
        "",
        "| case | result | verdict | call | why it failed |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['id']} | {'PASS' if r['passed'] else '**FAIL**'} | {r['verdict']} | "
            f"{r['answer_call']} | {'; '.join(r['reasons']) or ''} |"
        )
    if previous:
        before = {r["id"]: r["passed"] for r in previous["rows"]}
        flips = [
            f"- {r['id']}: {'PASS' if before[r['id']] else 'FAIL'} -> {'PASS' if r['passed'] else 'FAIL'}"
            for r in rows if r["id"] in before and before[r["id"]] != r["passed"]
        ]
        prev_passed = sum(r["passed"] for r in previous["rows"])
        lines += [
            "",
            f"**vs `{previous['label']}`: {prev_passed}/{len(previous['rows'])} -> {passed}/{len(rows)}**",
            "",
            *(flips or ["- no case changed result"]),
        ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--label", required=True)
    parser.add_argument("--goldenset", default="goldenset.json")
    parser.add_argument("--cases", default="evals")
    parser.add_argument("--judge", default="judge_v1.txt")
    parser.add_argument("--compare", help="label of an earlier run to diff against")
    parser.add_argument("--only", help="run only cases whose id contains this")
    parser.add_argument("--repeat", type=int, default=1, help="run each case N times (nondeterminism check)")
    args = parser.parse_args()

    config.preflight()
    cases = load_cases(args.goldenset, args.cases)
    if args.only:
        cases = [c for c in cases if args.only in c["id"]]
    template = Path(args.judge).read_text(encoding="utf-8")
    judge = get_judge_llm(JUDGE_MODEL)
    gen_limiter, judge_limiter = claims_common.RateLimiter(), claims_common.RateLimiter()

    rows = []
    for case in cases:
        for attempt in range(args.repeat):
            print(f"  {case['id']}" + (f" #{attempt + 1}" if args.repeat > 1 else ""), file=sys.stderr, flush=True)
            row = run_case(case, judge, template, gen_limiter, judge_limiter)
            if args.repeat > 1:
                row["id"] = f"{case['id']}#{attempt + 1}"
            rows.append(row)
            print(f"    {'PASS' if row['passed'] else 'FAIL'}  {'; '.join(row['reasons'])}", file=sys.stderr, flush=True)

    previous = None
    if args.compare:
        previous = json.loads((OUT_DIR / f"suite_{args.compare}.json").read_text(encoding="utf-8"))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"label": args.label, "passed": sum(r["passed"] for r in rows), "total": len(rows), "rows": rows}
    (OUT_DIR / f"suite_{args.label}.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    md = to_markdown(args.label, rows, previous)
    (OUT_DIR / f"suite_{args.label}.md").write_text(md + "\n", encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
