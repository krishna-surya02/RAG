"""Freeze answers once, then grade the frozen text — never the live model twice.

    # Mode 1 — generate once, freeze forever. Point TRACE_PATH somewhere of its
    # own first, so these don't mix into traces/claims_traces.jsonl (notes.md
    # §0/§2 records that file's exact line count and sha256):
    TRACE_PATH=traces/eval_traces.jsonl python evaluate_answers.py --generate \\
        --goldenset goldenset.json --out eval_out/answers_v1.json

    # Mode 2 — grade a frozen snapshot. Re-runnable with judge_v2.txt later
    # without ever calling rag.answer() again:
    python evaluate_answers.py --judge judge_v1.txt \\
        --in eval_out/answers_v1.json --out eval_out/judged_v1.json

    # The judge's own self-check, before it's trusted on anything else — both
    # entries in regression_set.json are hand-graded 'wrong_call' in notes.md
    # §3, at zero generation cost (frozen straight from an existing trace):
    python evaluate_answers.py --judge judge_v1.txt \\
        --in regression_set.json --out eval_out/judged_regression_v1.json

evaluate.py measures retrieval only — whether the right chunk ranks in the
top k. This measures the answer itself: the same 4-outcome rubric notes.md
§3 validated by hand (correct_supported / right_call_wrong_support / no_call
/ wrong_call), plus the taxonomy.md failure-mode tags, graded by an LLM judge
that is handed each question's gold_answer — the correct call, form/edition
and code — rather than just checking the answer against whatever got
retrieved. See judge_v1.txt for why that distinction matters here.
"""

import argparse
import json
import re
import sys
from pathlib import Path

import config
import rag
import redact
import tracing

DENY_PREFIXES = ("deny", "denied", "excluded", "not covered")

# HO-0304's deductible is $1,000 All Perils in every edition; HO-0500's is
# $2,500 All Perils (see docs/*.pdf declarations). Used only by the
# deductible_conditional assertion, and only when the frozen answer states a
# dollar figure next to the word "deductible" — most questions never mention
# one, and absence never fails the assertion.
KNOWN_DEDUCTIBLES = {
    "HO-0304": "$1,000",
    "HO-0500": "$2,500",
}

DEDUCTIBLE_RE = re.compile(r"\$[\d,]+(?:\.\d+)?\s*(?=[^.]{0,30}deductible)|deductible[^.]{0,40}?\$[\d,]+(?:\.\d+)?", re.I)


# --- Mode 1: generate and freeze --------------------------------------------


def load_goldenset(path):
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload["questions"]


def generate(questions, limit=None):
    """Call rag.answer() exactly once per question, then read the trace back
    to capture the exact context and answer byte-for-byte, the same text a
    human grader or a judge will see later — never the live model again."""
    if limit:
        questions = questions[:limit]

    for entry in questions:
        print(f"  generating {entry['id']}...", file=sys.stderr)
        rag.answer(entry["question"], source="eval", request={"goldenset_id": entry["id"]})

    traces = tracing.load_traces()
    by_question = {}
    for record in traces:
        by_question[record["input"]["question"]] = record  # last write wins

    answers = []
    for entry in questions:
        record = by_question.get(entry["question"])
        if record is None:
            print(f"  WARNING: no trace found for {entry['id']}, skipping", file=sys.stderr)
            continue
        rendered = record["prompt"]["rendered"]
        match = re.search(r"Context:\n(.*)\n\nQuestion:\n", rendered, re.S)
        answers.append(
            {
                "id": entry["id"],
                "trace_id": record["trace_id"],
                "kind": entry["kind"],
                "question": entry["question"],
                "context": match.group(1) if match else None,
                "answer": record["output"]["final"],
                "gold_answer": entry["gold_answer"],
            }
        )
    return answers


# --- Mode 2: judge a frozen snapshot ----------------------------------------


def load_items(path):
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    items = payload.get("answers") or payload.get("cases")
    if items is None:
        raise SystemExit(f"{path} has neither an 'answers' nor a 'cases' array")
    return items


def build_judge_prompt(template, item):
    return (
        template.replace("{question}", item["question"])
        .replace("{context}", item["context"] or "(no context recorded)")
        .replace("{answer}", item["answer"])
        .replace("{gold_answer}", json.dumps(item["gold_answer"], indent=2))
    )


def get_judge_llm(model=None):
    # A separate client from config.get_llm(), at temperature 0: the app's own
    # generation intentionally samples at 0.4 for natural answers, but a judge
    # should be as repeatable as the same-trace-different-answer problem in
    # notes.md §1 allows (Groq doesn't honour `seed` across backends either,
    # so 0 only narrows the variance, it doesn't eliminate it).
    from langchain_groq import ChatGroq

    return ChatGroq(
        model=model or config.CHAT_MODEL,
        api_key=config.GROQ_API_KEY,
        temperature=0,
        timeout=config.REQUEST_TIMEOUT,
        max_retries=config.MAX_RETRIES,
    )


def judge_one(llm, template, item):
    prompt = build_judge_prompt(template, item)
    message = llm.invoke(prompt)
    text = rag.strip_think(message.content)
    try:
        # Judges occasionally wrap JSON in a fenced code block despite the
        # instruction not to; strip one if present before parsing.
        fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
        parsed = json.loads(fenced.group(1) if fenced else text)
    except json.JSONDecodeError as exc:
        return {"parse_error": f"{exc}", "raw": text}
    return parsed


def check_assertions(item, judged):
    """Deterministic, zero-cost checks applied after the judge returns its
    structured fields. See judge_v1.txt / the Week-5 write-up for why the
    brief's own examples (claim number, date of loss) don't apply here."""
    gold = item["gold_answer"]
    results = {}

    call = (gold.get("call") or "").strip().lower()
    code = gold.get("correct_exclusion_or_code")
    if call.startswith(DENY_PREFIXES) and code:
        cited = judged.get("exclusion_code_cited")
        results["exclusion_id_on_denial"] = {
            "applicable": True,
            "passed": cited == code,
            "detail": f"expected {code!r}, judge saw {cited!r}",
        }
    else:
        results["exclusion_id_on_denial"] = {"applicable": False}

    leaked = redact._find_claim_numbers(item["answer"])
    results["claim_number_na"] = {
        "applicable": True,
        "passed": not leaked,
        "detail": "not applicable by design (claim numbers are redacted before the model "
        "ever sees the question) — this only re-checks that none leaked into the answer text"
        if not leaked
        else f"claim-number-shaped text in the answer: {leaked}",
    }

    results["date_of_loss_na"] = {
        "applicable": False,
        "detail": "no question in this corpus includes a date of loss",
    }

    match = DEDUCTIBLE_RE.search(item["answer"])
    if match:
        form = next((f for f in KNOWN_DEDUCTIBLES if f in (gold.get("correct_policy_form_edition") or "")), None)
        expected = KNOWN_DEDUCTIBLES.get(form)
        results["deductible_conditional"] = {
            "applicable": True,
            "passed": expected is not None and expected in match.group(0),
            "detail": f"answer states {match.group(0)!r}, expected {expected!r}" if expected else match.group(0),
        }
    else:
        results["deductible_conditional"] = {"applicable": False, "detail": "no deductible figure stated"}

    return results


def judge_all(items, template_path, model=None, limit=None):
    template = Path(template_path).read_text(encoding="utf-8")
    llm = get_judge_llm(model)
    if limit:
        items = items[:limit]

    rows = []
    for item in items:
        print(f"  judging {item['id']}...", file=sys.stderr)
        judged = judge_one(llm, template, item)
        row = {"id": item["id"], "question": item["question"], "judged": judged}
        if "parse_error" not in judged:
            row["assertions"] = check_assertions(item, judged)
        if "expected_verdict" in item:
            row["expected_verdict"] = item["expected_verdict"]
            row["expected_failure_modes"] = item.get("expected_failure_modes", [])
            row["matches_expected"] = judged.get("verdict") == item["expected_verdict"]
        rows.append(row)
    return rows


def summarise(rows):
    graded = [r for r in rows if "parse_error" not in r["judged"]]
    tally = {}
    for r in graded:
        v = r["judged"].get("verdict", "unparsed")
        tally[v] = tally.get(v, 0) + 1

    tags = {}
    for r in graded:
        for tag in r["judged"].get("failure_modes") or []:
            tags[tag] = tags.get(tag, 0) + 1

    assertion_failures = {}
    for r in graded:
        for name, result in r.get("assertions", {}).items():
            if result.get("applicable") and not result.get("passed"):
                assertion_failures.setdefault(name, []).append(r["id"])

    pass_rate = tally.get("correct_supported", 0) / len(graded) if graded else 0.0

    return {
        "total": len(rows),
        "parsed": len(graded),
        "parse_errors": [r["id"] for r in rows if "parse_error" in r["judged"]],
        "verdict_tally": tally,
        "pass_rate": round(pass_rate, 3),
        "failure_mode_tally": tags,
        "assertion_failures": assertion_failures,
    }


def to_markdown(summary, rows):
    lines = [
        f"### answer quality — pass rate {summary['pass_rate']:.1%} "
        f"({summary['verdict_tally'].get('correct_supported', 0)}/{summary['parsed']} correct_supported)",
        "",
        f"verdicts: {summary['verdict_tally']}",
        f"failure modes: {summary['failure_mode_tally'] or 'none'}",
        "",
        "| id | verdict | tags | exclusion code | matches expected | rationale |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        j = r["judged"]
        if "parse_error" in j:
            lines.append(f"| {r['id']} | PARSE ERROR | | | | {j['parse_error']} |")
            continue
        matches = r.get("matches_expected")
        matches_str = "yes" if matches else ("NO" if matches is False else "—")
        rationale = (j.get("rationale") or "").replace("|", "\\|")
        lines.append(
            f"| {r['id']} | {j.get('verdict')} | {', '.join(j.get('failure_modes') or []) or '—'} | "
            f"{j.get('exclusion_code_cited')} | {matches_str} | {rationale} |"
        )
    if summary["parse_errors"]:
        lines.append("")
        lines.append(f"UNPARSED: {', '.join(summary['parse_errors'])}")
    if summary["assertion_failures"]:
        lines.append("")
        lines.append("Assertion failures:")
        for name, ids in summary["assertion_failures"].items():
            lines.append(f"  {name}: {', '.join(ids)}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--generate", action="store_true", help="call rag.answer() once per goldenset question")
    parser.add_argument("--goldenset", default="goldenset.json")
    parser.add_argument("--judge", metavar="TEMPLATE", help="judge prompt file, e.g. judge_v1.txt")
    parser.add_argument("--judge-model", default=None, help="override config.CHAT_MODEL for grading only")
    parser.add_argument("--in", dest="in_path", help="frozen answers/cases file to grade")
    parser.add_argument("--out", required=True)
    parser.add_argument("--limit", type=int, default=None, help="cap items processed, for a cheap dry run")
    args = parser.parse_args()

    if not args.generate and not args.judge:
        parser.error("pass --generate or --judge")

    config.preflight()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if args.generate:
        questions = load_goldenset(args.goldenset)
        answers = generate(questions, limit=args.limit)
        out_path.write_text(json.dumps({"answers": answers}, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Wrote {len(answers)} frozen answers to {out_path}")
        return

    if not args.in_path:
        parser.error("--judge requires --in")
    items = load_items(args.in_path)
    rows = judge_all(items, args.judge, model=args.judge_model, limit=args.limit)
    summary = summarise(rows)

    payload = {"summary": summary, "rows": rows}
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path = out_path.with_suffix(".md")
    md_path.write_text(to_markdown(summary, rows), encoding="utf-8")

    print(to_markdown(summary, rows))
    print(f"\nWrote {out_path} and {md_path}")


if __name__ == "__main__":
    main()
