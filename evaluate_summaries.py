"""Grade frozen claim summaries: deterministic assertions plus an LLM judge.

    # One command, everything pre-frozen (no generation, no Groq cost for the
    # assertions; one Groq call per case for the judge):
    python evaluate_summaries.py --judge summary_judge_v1.txt \\
        --in summary_goldenset.json summary_regression_set.json \\
        --out eval_out/summary_judged_v1.json

evaluate_answers.py measures the coverage-Q&A feature. This measures the
claim-summary feature (summarize.py): the same 4-outcome rubric, but with
4 criteria the brief originally asked the judge to grade -- claim number
echoed, date of loss parseable, deductible numeric, exclusion cited on
denial -- pulled out into deterministic checks instead. See
summary_judge_v1.txt's own note on what it does and does not grade, and
notes.md for why "generate once, judge many times" matters here too: a
regenerated summary is not byte-identical to the frozen one even at the same
seed, so every case here is pre-frozen and never regenerated.
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import config

DENY_PREFIXES = ("deny",)

# Confirmed by directly reading docs/HO-0304_ed-*.pdf and docs/HO-0500_ed-01-23.pdf:
# every HO-0304 edition's Declarations states "$1,000 All Perils"; HO-0500's states
# "$2,500 All Perils". Same constants evaluate_answers.py uses for the Q&A feature.
KNOWN_DEDUCTIBLES = {
    "HO-0304": "$1,000",
    "HO-0500": "$2,500",
}

CLAIM_LINE_RE = re.compile(r"^Claim:\s*(.+?)\s*$", re.M)
DATE_OF_LOSS_LINE_RE = re.compile(r"^Date of Loss:\s*(.+?)\s*$", re.M)
POLICY_EDITION_LINE_RE = re.compile(r"^Policy & Edition:\s*(.+?)\s*$", re.M)
DEDUCTIBLE_LINE_RE = re.compile(r"^Deductible:\s*(.+?)\s*$", re.M)
BASIS_LINE_RE = re.compile(r"^Basis:\s*(.+?)(?=\n[A-Z][A-Za-z &]*:|\Z)", re.M | re.S)
EXCLUSION_CODE_RE = re.compile(r"\b[EF]-\d{1,2}\b")
DOLLAR_RE = re.compile(r"\$[\d,]+(?:\.\d+)?")

DATE_FORMATS = ("%B %d, %Y", "%B %-d, %Y", "%b %d, %Y")


def _parse_date(text):
    text = text.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    # %-d isn't portable (no leading-zero day) -- normalise "March 3, 2026"
    # style by hand if strptime's platform-specific flag isn't available.
    match = re.match(r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", text)
    if match:
        try:
            return datetime.strptime(f"{match.group(1)} {int(match.group(2))} {match.group(3)}", "%B %d %Y")
        except ValueError:
            return None
    return None


# --- Load ---------------------------------------------------------------


def load_items(paths):
    items = []
    for path in paths:
        payload = json.load(open(path, encoding="utf-8"))
        cases = payload.get("cases")
        if cases is None:
            raise SystemExit(f"{path} has no 'cases' array")
        for case in cases:
            case = dict(case)
            case.setdefault("taxonomy_mode", "regression")
            case["_source_file"] = path
            items.append(case)
    return items


# --- Deterministic assertions --------------------------------------------


def check_assertions(item):
    gold = item["gold_answer"]
    summary = item["summary"]
    results = {}

    claim_match = CLAIM_LINE_RE.search(summary)
    stated_claim = claim_match.group(1) if claim_match else None
    results["claim_number_echoed"] = {
        "applicable": True,
        "passed": stated_claim == item["claim_number"],
        "detail": f"expected {item['claim_number']!r}, summary states {stated_claim!r}",
    }

    date_match = DATE_OF_LOSS_LINE_RE.search(summary)
    stated_date = date_match.group(1) if date_match else None
    parsed = _parse_date(stated_date) if stated_date else None
    results["date_of_loss_parseable"] = {
        "applicable": True,
        "passed": parsed is not None,
        "detail": f"summary states {stated_date!r}" + ("" if parsed else " (not parseable)"),
    }

    ded_match = DEDUCTIBLE_LINE_RE.search(summary)
    stated_ded = ded_match.group(1).strip() if ded_match else None
    if stated_ded and DOLLAR_RE.search(stated_ded):
        edition_match = POLICY_EDITION_LINE_RE.search(summary)
        edition_field = edition_match.group(1) if edition_match else ""
        form = next((f for f in KNOWN_DEDUCTIBLES if f in edition_field or f in (gold.get("correct_policy_form_edition") or "")), None)
        expected = KNOWN_DEDUCTIBLES.get(form)
        stated_amount = DOLLAR_RE.search(stated_ded).group(0)
        results["deductible_numeric"] = {
            "applicable": True,
            "passed": expected is not None and stated_amount == expected,
            "detail": f"summary states {stated_amount!r}, expected {expected!r} for {form!r}",
        }
    else:
        results["deductible_numeric"] = {
            "applicable": False,
            "detail": "no dollar figure stated" if not stated_ded else f"stated {stated_ded!r}, not a dollar figure",
        }

    call = (gold.get("call") or "").strip().lower()
    code = gold.get("correct_exclusion_or_code")
    if call.startswith(DENY_PREFIXES) and code:
        basis_match = BASIS_LINE_RE.search(summary)
        basis_text = basis_match.group(1) if basis_match else ""
        cited_codes = EXCLUSION_CODE_RE.findall(basis_text)
        results["exclusion_id_on_denial"] = {
            "applicable": True,
            "passed": code in cited_codes,
            "detail": f"expected {code!r} in Basis, found {cited_codes or '(none)'}",
        }
    else:
        results["exclusion_id_on_denial"] = {"applicable": False}

    return results


# --- Judge ----------------------------------------------------------------


def get_judge_llm(model=None):
    from langchain_groq import ChatGroq

    return ChatGroq(
        model=model or config.CHAT_MODEL,
        api_key=config.GROQ_API_KEY,
        temperature=0,
        timeout=config.REQUEST_TIMEOUT,
        max_retries=config.MAX_RETRIES,
    )


def build_judge_prompt(template, item):
    return (
        template.replace("{notes}", item["notes"])
        .replace("{context}", item.get("context") or "(no context recorded -- see the trace)")
        .replace("{summary}", item["summary"])
        .replace("{gold_answer}", json.dumps(item["gold_answer"], indent=2))
    )


def judge_one(llm, template, item):
    import rag

    prompt = build_judge_prompt(template, item)
    message = llm.invoke(prompt)
    text = rag.strip_think(message.content)
    try:
        fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
        parsed = json.loads(fenced.group(1) if fenced else text)
    except json.JSONDecodeError as exc:
        return {"parse_error": f"{exc}", "raw": text}
    return parsed


def _load_checkpoint(checkpoint_path):
    rows = {}
    if checkpoint_path.exists():
        with checkpoint_path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    row = json.loads(line)
                    rows[row["id"]] = row
    return rows


def judge_all(items, template_path, checkpoint_path, model=None, limit=None):
    import time

    import groq

    template = Path(template_path).read_text(encoding="utf-8")
    llm = get_judge_llm(model)
    if limit:
        items = items[:limit]

    done = _load_checkpoint(checkpoint_path)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    with checkpoint_path.open("a", encoding="utf-8") as checkpoint:
        for item in items:
            if item["id"] in done:
                print(f"  {item['id']}: already judged, resuming", file=sys.stderr)
                rows.append(done[item["id"]])
                continue
            print(f"  judging {item['id']}...", file=sys.stderr)
            # Judge prompts carry the full retrieved context (often 3-4k tokens
            # each), and this account's TPM cap is 8000 -- pace every call, don't
            # just react to a 429 after the fact (same discipline traffic.py's
            # run() uses). A daily-quota error still stops the run, but every
            # case judged before that point is checkpointed, so a retry after
            # the cooldown resumes instead of re-spending those tokens.
            while True:
                try:
                    judged = judge_one(llm, template, item)
                    break
                except groq.RateLimitError as exc:
                    if re.search(r"per day|TPD|RPD", str(exc)):
                        raise SystemExit(f"daily quota reached at {item['id']}: {exc}")
                    print(f"  {item['id']}: rate limit, backing off 30s", file=sys.stderr)
                    time.sleep(30)
            time.sleep(20)
            row = {
                "id": item["id"],
                "taxonomy_mode": item["taxonomy_mode"],
                "judged": judged,
                "assertions": check_assertions(item),
            }
            checkpoint.write(json.dumps(row, ensure_ascii=False) + "\n")
            checkpoint.flush()
            rows.append(row)
    return rows


# --- Reporting --------------------------------------------------------------


def summarise(rows):
    graded = [r for r in rows if "parse_error" not in r["judged"]]
    tally = {}
    for r in graded:
        v = r["judged"].get("verdict", "unparsed")
        tally[v] = tally.get(v, 0) + 1

    by_mode = {}
    for r in graded:
        mode = r["taxonomy_mode"]
        bucket = by_mode.setdefault(mode, {"total": 0, "correct_supported": 0})
        bucket["total"] += 1
        if r["judged"].get("verdict") == "correct_supported":
            bucket["correct_supported"] += 1

    assertion_failures = {}
    assertion_counts = {"applicable": 0, "passed": 0}
    for r in graded:
        for name, result in r["assertions"].items():
            if result.get("applicable"):
                assertion_counts["applicable"] += 1
                if result.get("passed"):
                    assertion_counts["passed"] += 1
                else:
                    assertion_failures.setdefault(name, []).append(r["id"])

    pass_rate = tally.get("correct_supported", 0) / len(graded) if graded else 0.0

    return {
        "total": len(rows),
        "parsed": len(graded),
        "parse_errors": [r["id"] for r in rows if "parse_error" in r["judged"]],
        "verdict_tally": tally,
        "pass_rate": round(pass_rate, 3),
        "pass_rate_by_mode": {
            mode: {**b, "rate": round(b["correct_supported"] / b["total"], 3)}
            for mode, b in sorted(by_mode.items())
        },
        "assertion_counts": assertion_counts,
        "assertion_failures": assertion_failures,
        "judged_criteria_count": 3,  # verdict, failure_modes, cites_correct_edition -- rationale isn't a graded criterion
        "deterministic_assertion_count": 4,  # claim_number_echoed, date_of_loss_parseable, deductible_numeric, exclusion_id_on_denial
    }


def to_markdown(summary, rows):
    lines = [
        f"### claim-summary quality -- pass rate {summary['pass_rate']:.1%} "
        f"({summary['verdict_tally'].get('correct_supported', 0)}/{summary['parsed']} correct_supported)",
        "",
        f"verdicts: {summary['verdict_tally']}",
        f"deterministic assertions: {summary['assertion_counts']['passed']}/{summary['assertion_counts']['applicable']} passed "
        f"({summary['deterministic_assertion_count']} assertions vs {summary['judged_criteria_count']} judged criteria)",
        "",
        "**pass rate by taxonomy mode:**",
        "",
        "| mode | correct_supported | total | rate |",
        "|---|---|---|---|",
    ]
    for mode, b in summary["pass_rate_by_mode"].items():
        lines.append(f"| {mode} | {b['correct_supported']} | {b['total']} | {b['rate']:.1%} |")

    lines += [
        "",
        "| id | mode | verdict | tags | rationale |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        j = r["judged"]
        if "parse_error" in j:
            lines.append(f"| {r['id']} | {r['taxonomy_mode']} | PARSE ERROR | | {j['parse_error']} |")
            continue
        rationale = (j.get("rationale") or "").replace("|", "\\|")
        lines.append(
            f"| {r['id']} | {r['taxonomy_mode']} | {j.get('verdict')} | "
            f"{', '.join(j.get('failure_modes') or []) or '—'} | {rationale} |"
        )
    if summary["assertion_failures"]:
        lines.append("")
        lines.append("Assertion failures:")
        for name, ids in summary["assertion_failures"].items():
            lines.append(f"  {name}: {', '.join(ids)}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--judge", metavar="TEMPLATE", required=True)
    parser.add_argument("--judge-model", default=None)
    parser.add_argument("--in", dest="in_paths", nargs="+", required=True, help="frozen case file(s) to grade")
    parser.add_argument("--out", required=True)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    config.preflight()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    items = load_items(args.in_paths)
    checkpoint_path = out_path.with_suffix(".checkpoint.jsonl")
    rows = judge_all(items, args.judge, checkpoint_path, model=args.judge_model, limit=args.limit)
    summary = summarise(rows)

    payload = {"summary": summary, "rows": rows}
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path = out_path.with_suffix(".md")
    md_path.write_text(to_markdown(summary, rows), encoding="utf-8")

    print(to_markdown(summary, rows))
    print(f"\nWrote {out_path} and {md_path}")


if __name__ == "__main__":
    main()
