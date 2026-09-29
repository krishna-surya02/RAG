# Week 7 — agent vs. workflow for claims triage

## What this measures

A hand-built claims-triage loop (`claim_agent.py`) races against a fixed,
hard-coded pipeline (`claim_workflow.py`) over the same 10 claims, same three
tools, same output contract, to answer one question with numbers instead of
intuition: does this task need an agent?

No claims-triage loop existed in this repo before this week — see the
Setup note below for how the "existing two tools" the assignment assumes
were built fresh, and why the model differs from `config.CHAT_MODEL`.

## The third tool

`claims_tools.py` has three tools: `get_claim` (reads one claim's record,
redacting the claimant's name), `check_policy_exclusions` (decides whether a
loss cause is excluded under a form/edition, with a real PDF citation via
`retrieval.py`), and **`compute_payout`**, added this week as the tracked
third tool — pure arithmetic (`denied`→0, `approved`→claimed − deductible,
`partial`→capped then minus deductible), gated by a 3-value
`claim_status` enum, overlapping neither of the other two. The real
before/after diff is in `tool3_diff.patch` (generated with `diff -u` against
a snapshot of the file before this tool existed).

## Race: 8 numbers

10 claims, reused from `summary_goldenset.json` (week 6's PDF-verified
adjuster-notes cases — see `claims_data.json`'s `_about` for exactly how).
6 of the 10 need the notes' cause correctly read to pick the right exclusion
lookup (flood/appliance discharge, sewer backup, earthquake, wear-and-tear,
theft-during-construction, and an edition-sensitive ice/snow collapse pair
that pays under one edition and denies under another on the same facts).

| system   | pass rate | p50 latency | total tokens | cost/claim |
|----------|----------:|------------:|--------------:|-----------:|
| agent    |      100% |      3,033ms |        52,961 |  $0.000523 |
| workflow |      100% |       840ms  |         4,547 |  $0.000093 |

Full per-claim rows: `race.csv`. Raw per-call traces:
`traces/claims_agent_traces.jsonl`, `traces/claims_workflow_traces.jsonl`.

The agent used **11.6x** the tokens, **5.6x** the cost, and **3.6x** the p50
latency of the workflow, for an identical pass rate.

## Budget enforcement

`claim_agent.py` checks four budgets (`max_iterations`, `max_tokens`,
`max_cost`, `max_seconds`) before every model call, not just at the end.
`budget_termination_log.txt` is the full log of one deliberately-capped run
(`--max-iterations 1` on the flood claim, which normally needs 4 turns): the
agent makes its one allowed tool call, the next loop iteration's budget check
catches that turn 2 would exceed the cap, and `run_claim` returns
`{"status": "budget_exceeded", "budget": "max_iterations", ...}` — no
exception, no retry, no spin. The same check path (`claim_agent.py`'s
`breach()`) guards all four budgets identically.

## Verdict

Across all 10 claims, the agent — free to skip tools — called `get_claim`,
`check_policy_exclusions`, and `compute_payout` in that exact order every
time, never diverging from `claim_workflow.py`'s hard-coded sequence. Both
systems reached 100% pass rate. The decision rule is whether the tool-call
path varies by input in a way that changes the *outcome*, not whether an
LLM could technically handle it — and on this evidence, it doesn't: none of
these 10 claims forces an agent. The agent cost 11.6x the tokens, 5.6x the
dollars, and 3.6x the p50 latency for an identical result. If a claim class
exists that would force dynamic branching, it wasn't among these 10 —
likely because "read the notes, look up one exclusion, compute one payout"
is a bounded, three-step decision regardless of cause. A workflow suffices
here.

## Setup notes (read before reusing any of this)

- **No prior claims-triage agent existed.** A full repo/branch/history
  search turned up none — this week built `get_claim` and
  `check_policy_exclusions` (treated as "existing") plus `compute_payout`
  (the tracked addition) from scratch. See `tool3_diff.patch` for the real
  diff this produced.
- **Model: `openai/gpt-oss-20b`, not `config.CHAT_MODEL`.**
  `openai/gpt-oss-120b` (the project default) hit its Groq daily token quota
  mid-build (`RateLimitError`: "tokens per day (TPD): Limit 200000, Used
  199137"). Groq's TPD limit is per model, so `claims_common.py` pins
  `openai/gpt-oss-20b` for both systems via `config.get_llm(model=...)`,
  confirmed to support `bind_tools()`. `config.py`,`rag.py` and
  `summarize.py` are untouched. Pricing ($0.075/$0.30 per 1M input/output
  tokens) is from Groq's own docs, checked 2026-09-28 — re-check if the
  pinned model changes.
- **Groq's 8,000 TPM (tokens/minute) limit, not just the daily one, is
  real at this account's scale.** The first race attempt crashed outright on
  claim 10 with a per-minute `RateLimitError`, and every claim before that
  showed 20-30s latencies from Groq's client silently retrying through 429s
  — which was inflating `claim_agent.py`'s own wall-clock budget and
  causing spurious `budget_exceeded` results unrelated to the agent's actual
  behavior. Fixed by pacing `race.py` itself against a rolling 60s token
  window (`claims_common.RateLimiter`, the same idea `traffic.py` already
  used for week 5's traffic runs) — deliberately kept *outside*
  `claim_agent.py`/`claim_workflow.py` so a claim's own `latency_ms` reflects
  only its real model+tool time, not shared-quota waiting.
- **3 of the 10 claimed amounts are supplemented**, not from the goldenset
  (`s06`, `s16`, `s20` — their original notes stated no dollar estimate).
  Flagged per-claim in `claims_data.json`'s `claimed_amount_source`.

## Deliverables

| File | What it is |
|---|---|
| `claims_tools.py` | the three tools, shared by both systems |
| `tool3_diff.patch` | real `diff -u` adding `compute_payout` |
| `claims_data.json` | the 10 claims + held-back `expected` ground truth |
| `claim_agent.py` | the tool-calling loop, with 4 budgets enforced |
| `claim_workflow.py` | the fixed 4-step pipeline, same tools/model/contract |
| `claims_common.py` | shared output contract, pricing, trace writer, rate limiter |
| `race.py` | runs both systems over all 10 claims, scores, writes the race table |
| `race.csv` / `race_summary.json` | per-claim rows / the 8-number summary |
| `budget_termination_log.txt` | one run hitting a budget and stopping cleanly |
| `traces/claims_agent_traces.jsonl` / `traces/claims_workflow_traces.jsonl` | full per-call traces for both systems |
