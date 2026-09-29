"""Shared by claim_agent.py and claim_workflow.py: the output contract both
must produce, Groq per-token pricing for the race's cost numbers, and a
trace writer built on tracing.py's helpers.

CLAIMS_CHAT_MODEL, not config.CHAT_MODEL: mid-implementation, config.CHAT_MODEL
(openai/gpt-oss-120b) hit its Groq daily token quota (TPD) on this account --
confirmed via groq.RateLimitError ("tokens per day (TPD): Limit 200000, Used
199137"). Groq's TPD limit is per model, not account-wide, so both claims
scripts pin openai/gpt-oss-20b instead via config.get_llm(model=...), rather
than waiting out config.CHAT_MODEL's quota reset. Confirmed to support
bind_tools() the same way. config.py itself, and rag.py/summarize.py, are
untouched -- this is scoped to week 7's two new scripts only.

Pricing source: https://console.groq.com/docs/model/openai/gpt-oss-20b,
checked 2026-09-28 -- $0.075 / 1M input tokens, $0.30 / 1M output tokens. If
CLAIMS_CHAT_MODEL changes, these no longer apply and should be re-checked.
"""

import json
from pathlib import Path

import tracing

CLAIMS_CHAT_MODEL = "openai/gpt-oss-20b"

PRICE_INPUT_PER_M = 0.075
PRICE_OUTPUT_PER_M = 0.30

OUTPUT_FIELDS = ("claim_id", "claim_status", "exclusion_code", "payout", "cap", "rationale")


def estimate_cost(prompt_tokens, completion_tokens):
    return (prompt_tokens / 1_000_000) * PRICE_INPUT_PER_M + (
        completion_tokens / 1_000_000
    ) * PRICE_OUTPUT_PER_M


def usage_of(message):
    """Pull (prompt_tokens, completion_tokens) out of a ChatGroq response,
    tolerating the field being absent (e.g. a budget check before any call)."""
    usage = (message.response_metadata or {}).get("token_usage") or {}
    return usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)


def validate_output(obj):
    """Missing/wrong-typed fields make a claim an automatic race failure
    instead of a KeyError, same spirit as the budget-exceeded path: a bad
    result should fail loudly and specifically, not crash the harness."""
    if not isinstance(obj, dict):
        return ["not a JSON object"]
    errors = [f"missing field {f!r}" for f in OUTPUT_FIELDS if f not in obj]
    if "claim_status" in obj and obj["claim_status"] not in ("approved", "denied", "partial"):
        errors.append(f"claim_status {obj.get('claim_status')!r} not one of approved/denied/partial")
    return errors


class RateLimiter:
    """Same idea as traffic.py's --tpm pacing, generalised to whole claim runs
    instead of single calls: track tokens spent in the trailing 60s and block
    before starting a run that would likely blow the per-minute budget,
    instead of letting Groq's own retry-on-429 silently eat into that run's
    wall-clock (which is exactly what inflated claim_agent.py's latency
    numbers, and its max_seconds budget trips, before this existed).

    Deliberately used by the *caller* (race.py), not inside claim_agent.py/
    claim_workflow.py themselves -- so a claim's own latency_ms measures only
    its real model+tool time, never a shared-quota traffic-cop's wait.
    """

    def __init__(self, tpm=8000, margin=0.8):
        self.tpm = tpm
        self.margin = margin
        self.events = []  # (monotonic_ts, tokens)

    def _prune(self):
        import time

        now = time.monotonic()
        self.events = [(t, tok) for t, tok in self.events if now - t < 60]
        return now

    def record(self, tokens):
        import time

        self.events.append((time.monotonic(), tokens))

    def wait_for_budget(self, estimate):
        import time

        while True:
            now = self._prune()
            used = sum(tok for _, tok in self.events)
            if used + estimate <= self.tpm * self.margin:
                return
            oldest = self.events[0][0]
            time.sleep(min(max(1.0, 60 - (now - oldest)), 10))


def call_with_backoff(fn, *args, **kwargs):
    """Run one claim (agent or workflow), retrying once on a per-minute Groq
    rate limit and stopping immediately on a daily one -- same distinction
    traffic.py's run() makes, since only the first is worth waiting out."""
    import re
    import time

    import groq

    for attempt in range(2):
        try:
            return fn(*args, **kwargs)
        except groq.RateLimitError as exc:
            if re.search(r"per day|TPD|RPD", str(exc)):
                raise
            print(f"  rate limited (attempt {attempt + 1}/2), backing off 60s")
            time.sleep(60)
    return fn(*args, **kwargs)


def write_claim_trace(path, system, claim_id, record):
    record = {
        "trace_id": tracing.new_trace_id(),
        "ts": tracing.now_utc(),
        "system": system,
        "claim_id": claim_id,
        "app": tracing.app_version(),
        **record,
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record
