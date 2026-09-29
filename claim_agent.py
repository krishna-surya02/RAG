"""Claims triage as a tool-calling agent loop.

    python claim_agent.py CLM-2026-010007
    python claim_agent.py CLM-2026-010007 --max-iterations 1   # forces a budget breach

The model decides which of the three claims_tools to call, in what order, and
when it has enough to answer -- unlike claim_workflow.py, which calls all
three in a fixed sequence with the branching written in Python. Same tools,
same model (claims_common.CLAIMS_CHAT_MODEL), same output contract
(claims_common.OUTPUT_FIELDS) as the workflow, so the race between them is a
fair one.

Four budgets are checked before every model call, not just at the end, so a
run that would blow one stops immediately with a clean "budget_exceeded"
result instead of a stack trace or a silent runaway loop.
"""

import argparse
import json
import re
import time

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

import claims_common
import claims_tools
import config

SYSTEM_PROMPT = """You are a claims-triage assistant. You have three tools: \
get_claim, check_policy_exclusions, and compute_payout -- use whichever you \
need, in whatever order makes sense, and skip a call if an earlier result \
already gives you what it would tell you.

The loss cause you pass to check_policy_exclusions must be read from the \
claim's notes as exactly one of: wear_and_tear, hail, earthquake, \
sump_failure, theft_construction, fire, sudden_discharge, sewer_backup, \
ice_snow_collapse, other.

A claim is "denied" if its cause is excluded and no attached endorsement \
buys it back. It is "partial" if a cap applies to the payout -- either \
because the cause is payable but capped (e.g. a sudden-discharge sublimit \
from check_policy_exclusions), or because it was excluded but bought back by \
the claim's own attached endorsement (in that case use that claim's \
endorsement_limit, from get_claim, as the cap -- check_policy_exclusions does \
not know claim-specific dollar amounts). Otherwise it is "approved".

Once you have decided claim_status (and a cap, if partial), you MUST call \
compute_payout to get the exact payout -- never compute or guess the payout \
number yourself, even when it looks obvious; the deductible and any cap have \
to go through that tool. Then reply with ONLY this JSON object and nothing \
else -- no markdown fences, no commentary before or after it:

{"claim_id": "...", "claim_status": "approved"|"denied"|"partial", \
"exclusion_code": "..."|null, "payout": <number>, "cap": <number>|null, \
"rationale": "<one or two sentences citing the basis>"}"""

DEFAULT_MAX_ITERATIONS = 6
DEFAULT_MAX_TOKENS = 8000
DEFAULT_MAX_COST = 0.02
DEFAULT_MAX_SECONDS = 30.0

TRACE_PATH = "traces/claims_agent_traces.jsonl"


def _extract_json(text):
    text = re.sub(r"^```(?:json)?\s*|\s*```\s*$", "", text.strip(), flags=re.MULTILINE)
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def run_claim(
    claim_id,
    max_iterations=DEFAULT_MAX_ITERATIONS,
    max_tokens=DEFAULT_MAX_TOKENS,
    max_cost=DEFAULT_MAX_COST,
    max_seconds=DEFAULT_MAX_SECONDS,
    trace_path=TRACE_PATH,
    verbose=False,
):
    def log(msg):
        if verbose:
            print(msg)

    llm = config.get_llm(model=claims_common.CLAIMS_CHAT_MODEL).bind_tools(claims_tools.TOOLS)
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=f"Triage claim {claim_id}."),
    ]

    start = time.perf_counter()
    tokens_used = 0
    cost_used = 0.0
    tool_calls_made = []

    def elapsed():
        return time.perf_counter() - start

    def breach():
        if elapsed() > max_seconds:
            return "max_seconds", max_seconds, round(elapsed(), 2)
        if tokens_used >= max_tokens:
            return "max_tokens", max_tokens, tokens_used
        if cost_used >= max_cost:
            return "max_cost", max_cost, round(cost_used, 6)
        return None

    result = None
    status = None
    turn = 0
    for turn in range(1, max_iterations + 1):
        hit = breach()
        if hit:
            budget, limit, actual = hit
            log(f"[turn {turn}] BUDGET EXCEEDED before model call: {budget} limit={limit} actual={actual}")
            status = "budget_exceeded"
            result = {"status": "budget_exceeded", "budget": budget, "limit": limit, "actual": actual}
            break

        log(f"[turn {turn}] calling model ({len(messages)} messages so far)")
        response = llm.invoke(messages)
        p, c = claims_common.usage_of(response)
        tokens_used += p + c
        cost_used += claims_common.estimate_cost(p, c)
        log(f"[turn {turn}] model call used {p}+{c} tokens (cumulative {tokens_used} tok, ${cost_used:.6f})")
        messages.append(response)

        if response.tool_calls:
            for tc in response.tool_calls:
                tool = claims_tools.TOOLS_BY_NAME.get(tc["name"])
                if tool is None:
                    tool_result = {"error": f"unknown tool {tc['name']!r}"}
                else:
                    tool_result = tool.invoke(tc["args"])
                log(f"[turn {turn}] tool call: {tc['name']}({tc['args']}) -> {tool_result}")
                tool_calls_made.append({"turn": turn, "name": tc["name"], "args": tc["args"], "result": tool_result})
                messages.append(ToolMessage(content=json.dumps(tool_result), tool_call_id=tc["id"]))
            continue

        parsed = _extract_json(response.content)
        errors = claims_common.validate_output(parsed) if parsed is not None else ["no JSON object in final message"]
        if errors:
            log(f"[turn {turn}] final message failed the output contract: {errors}")
            status = "parse_error"
            result = {"status": "parse_error", "errors": errors, "raw": response.content}
        else:
            status = "ok"
            result = parsed
        break

    if result is None:
        log(f"[turn {turn}] BUDGET EXCEEDED: ran out of iterations")
        status = "budget_exceeded"
        result = {"status": "budget_exceeded", "budget": "max_iterations", "limit": max_iterations, "actual": turn}

    record = {
        "input": {"claim_id": claim_id},
        "budgets": {
            "max_iterations": max_iterations,
            "max_tokens": max_tokens,
            "max_cost": max_cost,
            "max_seconds": max_seconds,
        },
        "turns_used": turn,
        "tokens_used": tokens_used,
        "cost_used": round(cost_used, 6),
        "latency_ms": round(elapsed() * 1000, 1),
        "tool_calls": tool_calls_made,
        "status": status,
        "output": result,
    }
    claims_common.write_claim_trace(trace_path, "agent", claim_id, record)

    return {
        "output": result,
        "status": status,
        "tokens": tokens_used,
        "cost": cost_used,
        "latency_ms": elapsed() * 1000,
        "turns": turn,
        "tool_calls": tool_calls_made,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("claim_id")
    parser.add_argument("--max-iterations", type=int, default=DEFAULT_MAX_ITERATIONS)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--max-cost", type=float, default=DEFAULT_MAX_COST)
    parser.add_argument("--max-seconds", type=float, default=DEFAULT_MAX_SECONDS)
    parser.add_argument("--trace-path", default=TRACE_PATH)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    config.preflight()
    result = run_claim(
        args.claim_id,
        max_iterations=args.max_iterations,
        max_tokens=args.max_tokens,
        max_cost=args.max_cost,
        max_seconds=args.max_seconds,
        trace_path=args.trace_path,
        verbose=not args.quiet,
    )
    print(json.dumps(result["output"], indent=2))


if __name__ == "__main__":
    main()
