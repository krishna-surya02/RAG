"""Claims triage as a fixed workflow: four hard-coded steps, same three tools
and same model as claim_agent.py, no loop -- the tool-call sequence and the
branching are Python, not a model decision.

    python claim_workflow.py CLM-2026-010007

Steps, always in this order, for every claim:
  1. get_claim(claim_id)                              -- direct call
  2. extract_cause(notes)                              -- regex table, no LLM
  3. check_policy_exclusions(form, edition, cause)      -- direct call, always
  4. decide(...)                                        -- Python rule, no LLM
  5. compute_payout(...)                                -- direct call
  6. one config.get_llm() call, no tools bound, to phrase `rationale` in the
     same output contract claim_agent.py produces -- kept so "same model" in
     the race is meaningful for cost/token comparison instead of trivially 0.
"""

import argparse
import json
import re
import time

from langchain_core.messages import HumanMessage

import claims_common
import claims_tools
import config

TRACE_PATH = "traces/claims_workflow_traces.jsonl"

# Fixed, in this order -- first match wins. Same vocabulary claim_agent.py's
# system prompt asks the model to use, so the two systems are deciding from
# the same cause taxonomy, not different ones.
_CAUSE_PATTERNS = [
    ("sewer_backup", re.compile(r"sewer|backed up through", re.I)),
    ("sump_failure", re.compile(r"sump (pump|pit)", re.I)),
    ("wear_and_tear", re.compile(r"leak(?:ing|ed)? slowly|for months|for weeks|gradual|unnoticed", re.I)),
    ("sudden_discharge", re.compile(r"hose (split|burst)|washing machine", re.I)),
    ("earthquake", re.compile(r"earthquake", re.I)),
    ("ice_snow_collapse", re.compile(r"ice and snow|caved in|collapse", re.I)),
    ("theft_construction", re.compile(r"stolen.*construction|construction.*stolen|under construction", re.I)),
    ("hail", re.compile(r"\bhail\b", re.I)),
    ("fire", re.compile(r"\bfire\b", re.I)),
]


def extract_cause(notes):
    for cause, pattern in _CAUSE_PATTERNS:
        if pattern.search(notes):
            return cause
    return "other"


def decide(claim, exclusion):
    """Deterministic claim_status + cap, from get_claim's record and
    check_policy_exclusions' verdict -- the same rule claim_agent.py's system
    prompt states in English, written here as code instead."""
    if not exclusion["excluded"]:
        if exclusion["cap"] is not None:
            return "partial", exclusion["cap"]
        return "approved", None

    if exclusion["buyback_endorsement"] and exclusion["buyback_endorsement"] == claim["endorsement"]:
        return "partial", claim["endorsement_limit"]

    return "denied", None


RATIONALE_PROMPT = """Write one or two sentences of rationale for this claims \
decision, citing the basis given. Reply with ONLY that sentence or two, no \
JSON, no preamble. State facts only from what is given below -- do not guess \
whether an endorsement is attached beyond what "Endorsement attached" says.

Claim status: {claim_status}
Exclusion code: {exclusion_code}
Basis: {basis}
Endorsement attached to this claim: {endorsement}
Payout: {payout}
Cap: {cap}"""


def run_claim(claim_id, trace_path=TRACE_PATH, verbose=False):
    def log(msg):
        if verbose:
            print(msg)

    start = time.perf_counter()
    tokens_used = 0
    cost_used = 0.0
    tool_calls_made = []

    def call(name, fn, kwargs):
        result = fn(**kwargs)
        tool_calls_made.append({"name": name, "args": kwargs, "result": result})
        log(f"[step] {name}({kwargs}) -> {result}")
        return result

    claim = call("get_claim", claims_tools.get_claim, {"claim_id": claim_id})
    if "error" in claim:
        status = "error"
        result = claim
    else:
        cause = extract_cause(claim["notes"])
        log(f"[step] extract_cause(notes) -> {cause!r}")

        exclusion = call(
            "check_policy_exclusions",
            claims_tools.check_policy_exclusions,
            {"form": claim["form"], "edition": claim["edition"], "cause": cause},
        )

        claim_status, cap = decide(claim, exclusion)
        log(f"[step] decide(...) -> claim_status={claim_status!r} cap={cap!r}")

        payout_result = call(
            "compute_payout",
            claims_tools.compute_payout,
            {
                "claimed_amount": claim["claimed_amount"],
                "deductible": claim["deductible"],
                "claim_status": claim_status,
                "cap": cap,
            },
        )

        llm = config.get_llm(model=claims_common.CLAIMS_CHAT_MODEL)
        prompt = RATIONALE_PROMPT.format(
            claim_status=claim_status,
            exclusion_code=exclusion["exclusion_code"],
            basis=exclusion["basis"],
            endorsement=claim["endorsement"] or "none",
            payout=payout_result["payout"],
            cap=cap,
        )
        response = llm.invoke([HumanMessage(content=prompt)])
        p, c = claims_common.usage_of(response)
        tokens_used += p + c
        cost_used += claims_common.estimate_cost(p, c)
        log(f"[step] rationale model call used {p}+{c} tokens")

        result = {
            "claim_id": claim_id,
            "claim_status": claim_status,
            "exclusion_code": exclusion["exclusion_code"],
            "payout": payout_result["payout"],
            "cap": cap,
            "rationale": response.content.strip(),
        }
        status = "ok"

    elapsed = time.perf_counter() - start
    record = {
        "input": {"claim_id": claim_id},
        "tokens_used": tokens_used,
        "cost_used": round(cost_used, 6),
        "latency_ms": round(elapsed * 1000, 1),
        "tool_calls": tool_calls_made,
        "status": status,
        "output": result,
    }
    claims_common.write_claim_trace(trace_path, "workflow", claim_id, record)

    return {
        "output": result,
        "status": status,
        "tokens": tokens_used,
        "cost": cost_used,
        "latency_ms": elapsed * 1000,
        "turns": 1,
        "tool_calls": tool_calls_made,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("claim_id")
    parser.add_argument("--trace-path", default=TRACE_PATH)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    config.preflight()
    result = run_claim(args.claim_id, trace_path=args.trace_path, verbose=not args.quiet)
    print(json.dumps(result["output"], indent=2))


if __name__ == "__main__":
    main()
