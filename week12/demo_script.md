# Demo script: 10 minutes, to the clock

**Before you start:**
- Run `python triage.py check` and keep the terminal open.
- Warm the embedder: run `python triage.py demo --offline` once and discard the output.
- Have `evals/w12/runs/w12-baseline/report.md` open in an editor tab.
- If the Groq quota is low, use the saved trace ids in "Fallbacks" at the bottom instead of the live calls.

| clock | segment | command / what to show | what to say |
|---|---|---|---|
| 0:00–0:45 | **The brief and the rule** | `week12/architecture.md` diagram | "1,800 FNOLs a month, 20 minutes of lookup each. One compliance rule: nothing automated states a coverage decision. One live wound: a 2024 flood read against 2025 wording. One entry point: `triage.py`." |
| 0:45–2:15 | **The wound, then the fix** | `python triage.py demo --offline`, steps 1–3 | Step 1: "Unscoped, the 2025 flood endorsement ranks #1 for a 2024 loss. That is the client's incident, reproduced." Step 2: "Scoped to the policy term, the 2025 wording never enters the context, and asking for it is refused." Step 3: "The calendar is not enough: a June-2025 loss on a term that began in 2024 is governed by the 2023 set." |
| 2:15–4:15 | **One claim, FNOL in to referral out** | `python triage.py claim CLM-2024-000063` | Point at the tool list: "four local tools, five discovered over MCP at startup". Then the referral: in force, HEND-2023 v2023.1, citations naming clause, version and loss date with links, deductible $2,500 / sub-limit $15,000 / policy limit $500,000 on separate lines, and no decision. |
| 4:15–5:15 | **One trace across both hops** | `python triage.py trace <id from the last command>` | "One trace id. Our agent's spans and the MCP server's spans, written by a different process, join on it via `_meta.traceparent`. Cost and latency per span. Retrieval and tools cost $0; generation is all of it." |
| 5:15–6:00 | **PII line** | `python triage.py demo --offline` step 4; `python triage.py check` last lines | "Names, addresses, phones, emails, injuries out. The audit checks the generator's ground truth, 2,712 values, against every trace file and all 1,000 claims-server responses. Zero." |
| 6:00–7:00 | **The eval, one command** | `report.md`: suite line, assertions table, taxonomy table, trajectory line | Read the numbers off the report, not from memory: suite pass, the new integration-born modes, tool-choice accuracy and the outcome − trajectory gap. Say the judge-agreement line *as it stands*. If it reads UNLABELLED, say that. |
| 7:00–9:00 | **Failure → test loop, live** | see "Closed loop" below | The leaked sentence, the test it became, RED, the fix, GREEN. |
| 9:00–9:40 | **Cost and 10×** | `week12/tenx.md` | Read the cost per claim, then what breaks first at 18,000 FNOLs/week, with the number behind it. |
| 9:40–10:00 | **What we know is weak** | `week12/weaknesses.md` | "Written Wednesday, before anyone asked. Here is which ones the eval confirmed." |

## Closed loop (7:00–9:00): baseline case w12-07, a decision that reached the adjuster
1. **The failure.** Open `evals/w12/runs/w12-baseline/report.md`, row w12-07: assertions passed, the judge failed it for decision language. Then `python triage.py trace 25d475eb48c9 --dir evals/w12/runs/w12-baseline`. Read the sentence aloud: *"HFL-23 §2.1 excludes coverage for inundation, which does not apply here"*. The guard let it through.
2. **The test it became.** `evals/w12/regression_decision_language.json` (5 frozen summaries) and the last case in `w12/guard.py`'s self-test.
3. **RED, live.** `git stash push w12/guard.py && python -m w12.evals.regression` gives *2 pass the guard*: red. Then `git stash pop`. This works only once the fix is committed separately; otherwise show the RED output recorded in `week12/eval_report.md`.
4. **GREEN, live.** `python -m w12.evals.regression` gives *0 pass the guard*, and `python -m w12.guard` gives 16/16.
5. **At the source.** `W12_AGENT_PROMPT=triage-agent-v1 python triage.py eval --label demo-v1 --only w12-07` against the default v2: `python triage.py eval --label demo-v2 --only w12-07`. About 40k tokens of quota; rehearse it the day before, because the v2 result is not yet measured.
6. "It stays in `triage.py check`, so every future change re-runs it."

## Fallbacks if the network or quota fails
- Re-render any saved run with no API calls: `python triage.py eval --rescore w12-baseline`.
- Show any saved trace: `python triage.py trace <id> --dir evals/w12/runs/w12-baseline`. Pick ids from `report.md`.
- The external-client exchange is saved in `week12/wire_check.json`.
