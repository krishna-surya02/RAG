"""The LLM judge for referral summaries (evals/w12/judge_w12.txt).

Runs after the assertions, on gpt-oss-120b at temperature 0 -- a different
model from the agent (20b), so the two don't share a daily token quota and
the judge isn't grading its own model's habits. Results are cached per trace
id in the run directory, so a rescore never calls the judge twice for the
same output unless asked to.
"""

import json
import re
from pathlib import Path

import claims_common
import rag
import tracing
from w12 import pii, store

ROOT = Path(__file__).resolve().parent.parent.parent
JUDGE_PATH = ROOT / "evals" / "w12" / "judge_w12.txt"
JUDGE_MODEL = "openai/gpt-oss-120b"


def judge_inputs(case, rec):
    """Everything the judge sees, also what a hand-labeller sees."""
    claim = store.claim(case["claim_id"])
    red, _ = pii.redact_claim(claim)
    r = rec["referral"]
    facts = {"loss_date": r["loss_date"], "in_force": r["in_force"], "endorsement_set": r["endorsement_set"],
             "term": r["term"]}
    cited = []
    for c in r["citations"]:
        if not c.get("valid"):
            cited.append(f"[{c['ref']}] NOT IN FORCE for this loss: {'; '.join(c.get('problems', []))}")
            continue
        clause = next((x for x in store.find_clause(c["ref"], r["product"]) if x["doc_id"] == c["doc_id"]), None)
        if clause:
            cited.append(f"[{clause['ref']} | {c['endorsement_version']}] {clause['title']}\n{clause['text']}")
    exp = case["expected"]
    reference = {"clause": exp["deciding_clause"], "in_force": exp["in_force"]}
    if exp.get("limits"):
        reference["coverage"] = exp["coverage"]
        reference.update(exp["limits"])
    limits = {"coverage": r["coverage"], **r["limits"]} if r.get("limits") else None
    return {"fnol": red["fnol_text"], "facts": json.dumps(facts), "cited_wording": "\n\n".join(cited) or "(none cited)",
            "limits": json.dumps(limits), "reference": json.dumps(reference), "summary": r["summary"] or "(empty)"}


def render(template, inputs):
    out = template
    for k, v in inputs.items():
        out = out.replace("{" + k + "}", v)
    return out


def judge(case, rec, llm=None, limiter=None):
    template = JUDGE_PATH.read_text(encoding="utf-8")
    prompt = render(template, judge_inputs(case, rec))
    if llm is None:
        import evaluate_answers

        llm = evaluate_answers.get_judge_llm(JUDGE_MODEL)  # week 6's temperature-0 client
    if limiter:
        limiter.wait_for_budget(len(prompt) // 3)
    msg = llm.invoke(prompt)
    p, c = claims_common.usage_of(msg)
    if limiter:
        limiter.record(p + c)
    text = rag.strip_think(msg.content)
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    try:
        parsed = json.loads(fenced.group(1) if fenced else text)
    except json.JSONDecodeError as exc:
        parsed = {"parse_error": str(exc), "raw": text[:500], "verdict": None}
    parsed["_usage"] = {"prompt_tokens": p, "completion_tokens": c,
                        "cost_usd": tracing.cost_usd(p, c, JUDGE_MODEL), "model": JUDGE_MODEL}
    return parsed
