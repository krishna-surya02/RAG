"""Claims triage as an orchestrator: decompose -> two workers -> synthesise.

    python orchestrator.py CLM-2026-010007
    python orchestrator.py CLM-2026-010007 --fail-worker coverage   # injects a 500

Same tools (claims_tools), same model (claims_common.CLAIMS_CHAT_MODEL) and
same output contract (claims_common.OUTPUT_FIELDS) as claim_agent.py, so the
Week-10 race (race10.py) compares architectures, not models.

Stages for every claim:
  0. get_claim                    -- direct call, no LLM
  1. decomposer                   -- LLM, splits the question into two sub-tasks
  2. coverage_worker              -- LLM + check_policy_exclusions/compute_payout
  3. notes_worker                 -- LLM, summarises the adjuster notes
  4. synthesiser                  -- LLM, merges both worker outputs into the
                                     final JSON

Every LLM call is attributed to the hand-off that delivered its input
(`orchestrator->coverage_worker`, ...) and the per-hand-off token counts are
appended to handoffs.log (JSONL) when the claim finishes. The orchestrator
does not special-case a failed worker: it retries once, then hands whatever it
has (including the error) to the synthesiser. What that produces is the point
of the failure-injection test, so it is recorded, not engineered.
"""

import argparse
import json
import time
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

import claim_agent
import claims_common
import claims_tools
import config

TRACE_PATH = "traces/claims_orchestrator_traces.jsonl"
HANDOFF_LOG = "handoffs.log"

# Wider than claim_agent's (6 iterations / 8000 tokens / 30s): the
# orchestrator makes 4+ model calls per claim by design, so the agent's caps
# would trip it every time. Cost cap is the agent's.
DEFAULT_MAX_TOKENS = 20000
DEFAULT_MAX_COST = 0.02
DEFAULT_MAX_SECONDS = 90.0
WORKER_MAX_TURNS = 5

# Used only to pace Groq's 8k TPM per call; see claims_common.RateLimiter.
CALL_TOKEN_ESTIMATE = 2500

CAUSES = (
    "wear_and_tear, hail, earthquake, sump_failure, theft_construction, fire, "
    "sudden_discharge, sewer_backup, ice_snow_collapse, other"
)

DECOMPOSER_PROMPT = """You are the orchestrator of a claims-triage team. Given a \
claim record, split the triage question into exactly two sub-tasks and reply with \
ONLY this JSON object, no fences:

{"coverage_task": "<what the coverage/exclusions worker must establish>", \
"notes_task": "<what the adjuster-note worker must summarise>"}"""

COVERAGE_PROMPT = f"""You are the coverage/exclusions worker. You receive a claim \
record and a task from the orchestrator. Tools: check_policy_exclusions and \
compute_payout.

The loss cause you pass to check_policy_exclusions must be read from the claim's \
notes as exactly one of: {CAUSES}.

A claim is "denied" if its cause is excluded and no attached endorsement buys it \
back. It is "partial" if a cap applies to the payout -- either because the cause \
is payable but capped (e.g. a sudden-discharge sublimit from \
check_policy_exclusions), or because it was excluded but bought back by the \
claim's own attached endorsement (then use that claim's endorsement_limit as the \
cap). Otherwise it is "approved".

Once you have decided claim_status (and a cap, if partial), you MUST call \
compute_payout -- never compute the payout yourself. Then reply with ONLY this \
JSON object, no fences:

{{"claim_status": "approved"|"denied"|"partial", "exclusion_code": "..."|null, \
"payout": <number>, "cap": <number>|null, "basis": "<one sentence>"}}"""

NOTES_PROMPT = """You are the adjuster-note worker. Summarise the adjuster notes \
in the claim record for the task you are given. Reply with ONLY this JSON object, \
no fences:

{"loss_summary": "<two sentences>", "key_facts": ["..."], \
"endorsement_mentioned": true|false}"""

SYNTH_PROMPT = """You are the orchestrator's synthesiser. You receive the claim \
record, the decomposition, and the two workers' outputs. Produce the final triage \
decision. Reply with ONLY this JSON object, no fences:

{"claim_id": "...", "claim_status": "approved"|"denied"|"partial", \
"exclusion_code": "..."|null, "payout": <number>, "cap": <number>|null, \
"rationale": "<one or two sentences citing the basis>", \
"coverage_checked": true|false}

coverage_checked is true only if the coverage/exclusions worker's result was \
available and used."""


class WorkerError(Exception):
    """A worker returned an error (the injected failure is a 500)."""


class BudgetExceeded(Exception):
    def __init__(self, budget, limit, actual):
        super().__init__(f"{budget} limit={limit} actual={actual}")
        self.info = {"budget": budget, "limit": limit, "actual": actual}


class _Run:
    """Per-claim accounting: tokens, cost, per-hand-off tallies, budgets, and
    pacing waits (subtracted from latency, as the caller-side RateLimiter
    convention in claims_common requires)."""

    def __init__(self, limiter, max_tokens, max_cost, max_seconds):
        self.limiter = limiter
        self.max_tokens = max_tokens
        self.max_cost = max_cost
        self.max_seconds = max_seconds
        self.start = time.perf_counter()
        self.waited = 0.0
        self.tokens = 0
        self.cost = 0.0
        self.handoffs = {}
        self.events = []

    def elapsed(self):
        return time.perf_counter() - self.start - self.waited

    def invoke(self, llm, messages, handoff):
        if self.elapsed() > self.max_seconds:
            raise BudgetExceeded("max_seconds", self.max_seconds, round(self.elapsed(), 2))
        if self.tokens >= self.max_tokens:
            raise BudgetExceeded("max_tokens", self.max_tokens, self.tokens)
        if self.cost >= self.max_cost:
            raise BudgetExceeded("max_cost", self.max_cost, round(self.cost, 6))

        if self.limiter:
            t0 = time.perf_counter()
            self.limiter.wait_for_budget(CALL_TOKEN_ESTIMATE)
            self.waited += time.perf_counter() - t0

        response = claims_common.call_with_backoff(llm.invoke, messages)
        p, c = claims_common.usage_of(response)
        if self.limiter:
            self.limiter.record(p + c)
        self.tokens += p + c
        self.cost += claims_common.estimate_cost(p, c)
        h = self.handoffs.setdefault(handoff, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0})
        h["calls"] += 1
        h["prompt_tokens"] += p
        h["completion_tokens"] += c
        return response


def _llm(tools=None):
    llm = config.get_llm(model=claims_common.CLAIMS_CHAT_MODEL)
    return llm.bind_tools(tools) if tools else llm


def _json_of(response):
    parsed = claim_agent._extract_json(response.content)
    if parsed is None:
        raise WorkerError(f"worker reply had no JSON object: {response.content[:200]!r}")
    return parsed


def _decompose(run, claim):
    messages = [
        SystemMessage(content=DECOMPOSER_PROMPT),
        HumanMessage(content=f"Claim record:\n{json.dumps(claim)}"),
    ]
    return _json_of(run.invoke(_llm(), messages, "orchestrator->decomposer"))


def _coverage_worker(run, claim, brief, fail):
    if fail:
        raise WorkerError("500 Internal Server Error: coverage worker unavailable (injected)")
    tools = [claims_tools.TOOLS_BY_NAME["check_policy_exclusions"], claims_tools.TOOLS_BY_NAME["compute_payout"]]
    llm = _llm(tools)
    messages = [
        SystemMessage(content=COVERAGE_PROMPT),
        HumanMessage(content=f"Task: {brief.get('coverage_task')}\n\nClaim record:\n{json.dumps(claim)}"),
    ]
    for _ in range(WORKER_MAX_TURNS):
        response = run.invoke(llm, messages, "orchestrator->coverage_worker")
        messages.append(response)
        if not response.tool_calls:
            return _json_of(response)
        for tc in response.tool_calls:
            tool = claims_tools.TOOLS_BY_NAME.get(tc["name"])
            result = tool.invoke(tc["args"]) if tool else {"error": f"unknown tool {tc['name']!r}"}
            messages.append(ToolMessage(content=json.dumps(result), tool_call_id=tc["id"]))
    raise WorkerError("coverage worker used all its turns without answering")


def _notes_worker(run, claim, brief, fail):
    if fail:
        raise WorkerError("500 Internal Server Error: notes worker unavailable (injected)")
    messages = [
        SystemMessage(content=NOTES_PROMPT),
        HumanMessage(content=f"Task: {brief.get('notes_task')}\n\nClaim record:\n{json.dumps(claim)}"),
    ]
    return _json_of(run.invoke(_llm(), messages, "orchestrator->notes_worker"))


def _delegate(run, name, fn, *args):
    """One retry, then give up and return the error as the worker's result.
    Nothing here decides what a missing worker result means -- that is left
    to the synthesiser, and recorded."""
    for attempt in (1, 2):
        try:
            result = fn(*args)
            run.events.append(f"{name}: ok on attempt {attempt}")
            return result
        except WorkerError as exc:
            run.events.append(f"{name}: attempt {attempt} failed: {exc}")
    return {"error": run.events[-1].split("failed: ", 1)[1]}


def _write_handoffs(path, claim_id, run):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for name, h in run.handoffs.items():
            src, dst = name.split("->")
            handle.write(
                json.dumps(
                    {
                        "claim_id": claim_id,
                        "from": src,
                        "to": dst,
                        **h,
                        "total_tokens": h["prompt_tokens"] + h["completion_tokens"],
                    }
                )
                + "\n"
            )


def run_claim(
    claim_id,
    fail_worker=None,
    limiter=None,
    handoff_log=HANDOFF_LOG,
    trace_path=TRACE_PATH,
    max_tokens=DEFAULT_MAX_TOKENS,
    max_cost=DEFAULT_MAX_COST,
    max_seconds=DEFAULT_MAX_SECONDS,
    verbose=False,
):
    def log(msg):
        if verbose:
            print(msg)

    run = _Run(limiter, max_tokens, max_cost, max_seconds)
    claim = claims_tools.get_claim(claim_id=claim_id)
    coverage = notes = None

    if "error" in claim:
        status, result = "error", claim
    else:
        try:
            brief = _decompose(run, claim)
            log(f"[decompose] {brief}")
            coverage = _delegate(run, "coverage_worker", _coverage_worker, run, claim, brief, fail_worker == "coverage")
            log(f"[coverage_worker] {coverage}")
            notes = _delegate(run, "notes_worker", _notes_worker, run, claim, brief, fail_worker == "notes")
            log(f"[notes_worker] {notes}")

            messages = [
                SystemMessage(content=SYNTH_PROMPT),
                HumanMessage(
                    content=(
                        f"Claim record:\n{json.dumps(claim)}\n\nDecomposition:\n{json.dumps(brief)}\n\n"
                        f"Coverage/exclusions worker output:\n{json.dumps(coverage)}\n\n"
                        f"Adjuster-note worker output:\n{json.dumps(notes)}"
                    )
                ),
            ]
            response = run.invoke(_llm(), messages, "workers->synthesiser")
            parsed = claim_agent._extract_json(response.content)
            errors = claims_common.validate_output(parsed) if parsed is not None else ["no JSON object in final message"]
            if errors:
                status = "parse_error"
                result = {"status": "parse_error", "errors": errors, "raw": response.content}
            else:
                status, result = "ok", parsed
        except BudgetExceeded as exc:
            status = "budget_exceeded"
            result = {"status": "budget_exceeded", **exc.info}

    latency_ms = run.elapsed() * 1000
    if run.handoffs:
        _write_handoffs(handoff_log, claim_id, run)
    claims_common.write_claim_trace(
        trace_path,
        "orchestrator",
        claim_id,
        {
            "input": {"claim_id": claim_id, "fail_worker": fail_worker},
            "tokens_used": run.tokens,
            "cost_used": round(run.cost, 6),
            "latency_ms": round(latency_ms, 1),
            "handoffs": run.handoffs,
            "events": run.events,
            "status": status,
            "output": result,
        },
    )
    return {
        "output": result,
        "status": status,
        "tokens": run.tokens,
        "cost": run.cost,
        "latency_ms": latency_ms,
        "handoffs": run.handoffs,
        "events": run.events,
        "coverage": coverage,
        "notes": notes,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("claim_id")
    parser.add_argument("--fail-worker", choices=["coverage", "notes"])
    parser.add_argument("--handoff-log", default=HANDOFF_LOG)
    parser.add_argument("--trace-path", default=TRACE_PATH)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    config.preflight()
    result = run_claim(
        args.claim_id,
        fail_worker=args.fail_worker,
        handoff_log=args.handoff_log,
        trace_path=args.trace_path,
        verbose=not args.quiet,
    )
    print(json.dumps(result["output"], indent=2))


if __name__ == "__main__":
    main()
