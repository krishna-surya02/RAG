# Week 12: Integration: one entry point, FNOL in, referral out

## Setup note
The brief's corpus doesn't exist in this repo. The repo has household PDFs with no effective dates, no motor product, no 2023/2025 endorsement sets, 10 claims, no policy numbers, no in-force ranges and no limits table. So `w12/corpus_gen.py` generates it: seeded, template-only (no LLM), committed under `data/`, and byte-reproducible (`triage.py gen-corpus --check`). Contents:
- **Wordings:** household and motor (29 and 17 A5 pages). The household exclusions schedule reuses HO-0304's clauses.
- **Endorsement sets:** 2023 and 2025 for each product.
  - **The flood rewrite:** HFL-23 gives back rainfall surface water up to a $15,000 sub-limit after a $2,500 flood deductible. HFL-25 excludes it unless Flood Plus is on the schedule, and it is written in plain English that embeds closer to claimant language.
  - **Motor:** a 2025 flood-warning exclusion and a hail deductible.
- **Records:** `versions.json`, `limits.csv`, 320 policies with terms, lapses and cancellations, and **500 claim files** with names, addresses, phones, emails and injuries in the FNOL and notes, plus the final decision and reason code.

**The human parts:** the Tuesday seam list and the Wednesday weaknesses are **drafts** written from what I hit while building, for the author to edit. Judge agreement needs **hand labels** I can't supply; the worksheet is generated and no number is reported until it's filled.

## What was built
- **`triage.py`:** the one entry point: `claim`, `ask`, `eval`, `serve-mcp`, `trace`, `check`, `demo`, `gen-corpus`.
- **Week 3–4 RAG, wired in:**
  - **`retrieval.retrieve_in_force`:** filters to the base wording plus the endorsement set **on the policy term covering the loss date** (not the calendar), before the top-k cut, and never backfills.
  - **`rag.answer_claim`:** structured citations naming clause, endorsement version and loss date, with a link to the clause anchor.
- **Week 7 loop, integrated (`w12/agent.py`):**
  - **Tools:** four local (`lookup_policy`, `check_in_force`, `get_limits`, `refer_to_adjuster`) plus whatever `w12/mcp_config.json`'s servers list at startup.
  - **Ending:** a run always ends in a referral, even on a budget trip, a malformed tool call or a quota error.
  - **Who supplies what:** facts come from records, citations are resolved and validated, and the summary goes through `w12/guard.py`. There is no coverage field.
- **Our MCP server (`w12/mcp_wording_server.py`):**
  - **Tools:** `search_wording` / `get_clause` / `list_versions`. `loss_date` is required, and a clause from wording not in force is refused, not substituted.
  - **Transport:** stdio for our agent; streamable HTTP for another squad (`serve-mcp --http 8765`).
  - **External-client check:** a raw JSON-RPC client that isn't ours exercised it: `w12/wire_check.py` → `week12/wire_check.json`, 0 PII in replies.
  - **Claim files:** `w12/mcp_claims_server.py` serves them, redacted.
- **Week 11 tracing across both hops (`w12/trace.py`):**
  - **Propagation:** one trace id minted at ingress and carried over MCP in `_meta.traceparent`. Server spans are written by the server process and joined by `triage.py trace`.
  - **Cost:** cost per span at the right model's price (`config.PRICES`; it was costing the 20b agent at 120b rates).
  - **PII lock:** a second lock on every line written.
- **PII:** `redact.py` now covers addresses, phones, emails and injuries, redacts a claim's texts as one document, and treats water bodies as places. `w12/evals/pii_audit.py` checks the generator's 2,712 ground-truth values against every file written and every claims-server response.
- **Evals (`w12/evals/`):** 31 stratified cases, deterministic assertions, `judge_w12.txt` on 120b, taxonomy detectors, trajectory scoring, cost, judge-agreement scaffolding, and frozen-failure replay.

## Results
| deliverable | result |
|---|---|
| eval suite, one command | `python triage.py eval --label …`. **7 of 31 cases ran** before the 20b daily quota (200k tokens) ran out. **Suite 1/7, assertions 2/7, judge 1/7.** All 7 are household flood. [week12/eval_report.md](week12/eval_report.md) |
| judge vs hand labels | **not measured: 0/7 labelled.** Worksheet: `evals/w12/runs/w12-baseline/labels_worksheet.md` |
| taxonomy re-scored | 7 modes. **4 new from integration:** `redaction_strips_cause` 28.6%, `scope_dropped_at_mcp_hop` 14.3%, `wrong_coverage_line` 14.3%, `limit_conflation` 14.3%. Top mode `decision_language` 85.7% (S1). Each has a trace id |
| trajectory | 3 trajectory cases ran. Tool-choice accuracy **67%**; outcome − trajectory gap **−66.7 points**: right paths, wrong referrals |
| citations | 7/7 runs, **0 citations from wording not in force**. The 2024-read-as-2025 wound didn't occur once date scoping was in place; unscoped, HFL-25 ranks #1 for a 2024 loss (`triage.py demo --offline`) |
| one trace, both hops | e.g. `2d70fae66a02`: 17 spans across `triage`, `claims-files` and `policy-wording`, with latency and cost per span |
| PII line | **0 leaks** in 16 trace/run files and 1,000 MCP responses |
| failure → test loop | w12-07: a decision ("…which does not apply here") reached the adjuster. Frozen as tests → RED (guard 1/16 failing; 2/5 frozen summaries passing the guard) → fix → GREEN (16/16, 0/5). Live v2 re-run pending quota |
| cost per claim triaged | **$0.001807** mean (18,224 tokens, 6.1 LLM turns). Generation is 100% of it |
| 10× | **The Groq daily quota breaks first, and is already broken.** 200k TPD ÷ 18,224 tokens per claim ≈ 11 claims/day, against 59/day today (5.4× over) and 2,571/day in a hailstorm week (234× over). Next wall: 8k TPM ≈ 632 claims/day. [week12/tenx.md](week12/tenx.md) |

## Weaknesses written down before the results, and what the results said
From [week12/weaknesses.md](week12/weaknesses.md), written before grading:

| # | weakness | outcome | where it showed |
|---|---|---|---|
| 1 | HFL-23 under-retrieves | confirmed | w12-04 missed §2.2 |
| 2 | redaction strips the cause | confirmed, and worse than predicted | both river floods read as burst pipes |
| 3 | the coverage line drives the limits | confirmed | w12-02 |

The one I didn't predict is the biggest: **decision language in 6 of 7**, with one leak past the guard.

## Caveats
- **Partial run:** 7 cases is not a suite result. Finishing the baseline, and then measuring v2, needs ~430k tokens of 20b quota per full run: two to three days on this tier, or a paid tier.
- **v2 unmeasured:** the post-baseline fixes are verified offline only, and their effect on suite pass rate is unknown. The endorsement quota still doesn't surface HFL-23 §2.2 for claimant-worded queries.
- **Code changed between cases:** cases 1–7 ran before the agent's error handling was added. That change only touches exception paths those runs never hit. Case 8 crashed the first attempt (harmony tokens in a tool name, Groq 400) and has not been re-run.
- **Synthetic data:** it flatters regex redaction and has no adjuster inconsistency.
- **No auth on the HTTP MCP server:** acceptable for a review session only (see Week 9 `risk_note.md`).

## Files
| file | purpose |
|---|---|
| `triage.py` | the entry point |
| `w12/corpus_gen.py`, `w12/corpus_text.py`, `data/` | synthetic corpus |
| `w12/store.py`, `w12/citations.py`, `w12/wording_index.py`, `retrieval.py` | in-force resolution, citations, clause index, date-scoped ranking |
| `w12/agent.py`, `w12/tools_local.py`, `w12/guard.py`, `w12/pii.py`, `redact.py` | agent, tools, decision guard, PII |
| `w12/mcp_wording_server.py`, `w12/mcp_claims_server.py`, `w12/mcp_config.json`, `w12/wire_check.py` | MCP servers, config, external-client check |
| `w12/trace.py`, `tracing.py`, `config.py` | spans across hops, per-model pricing |
| `w12/evals/*`, `evals/w12/` | cases, assertions, judge, taxonomy/trajectory/cost, agreement, PII audit, regression, runs |
| `week12/` | seam list (draft), architecture, eval report, weaknesses (draft), demo script, 10× |
