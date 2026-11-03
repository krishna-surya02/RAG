# Cost per claim, and what breaks first at catastrophe volume

## Measured (baseline run, 7 claims, agent on `openai/gpt-oss-20b`)
From `evals/w12/runs/w12-baseline/results.json`. Every number below is derived from these.

| | mean | p50 | p95 |
|---|---|---|---|
| **cost per claim triaged** | **$0.001807** | $0.002011 | $0.002369 |
| tokens per claim | 18,224 | 20,116 | 22,560 |
| LLM turns per claim | 6.1 | | |
| latency, excluding rate-limit waits | | 15.8 s | 36.1 s |
| wall time, including rate-limit waits | | 244 s | 372 s |
| MCP connect per claim (2 stdio servers spawned, embedder loaded) | ~5.6 s | | |

- **Where the money goes:** generation is 100% of the dollars. Retrieval runs on a local embedder and MCP and the tools are code, so all are $0 at the margin.
- **Not included in triage cost:** the judge, at $0.000727 per case, which only runs in evals.
- **Sample caveat:** all 7 measured claims are household flood claims, the most clause-heavy kind. A not-in-force claim took about 5k tokens in the smoke run.

## Volumes
- **Today:** 1,800 FNOLs/month ≈ **59/day**.
- **Hailstorm week:** 18,000 FNOLs/week ≈ **2,571/day** on average. Arrivals bunch after the storm, so the first day is plausibly ~7,200 (40% of the week).

## What breaks first: the Groq daily token quota, and it is already broken
This account's tier allows **200,000 tokens/day per model**. The eval hit that limit: "Limit 200000, Used 198015".

| | tokens/day needed | vs 200k TPD |
|---|---|---|
| ceiling on this tier | 200,000 | **≈ 11 claims/day** (200,000 / 18,224) |
| today's volume, 59/day | 1.08 M | **5.4× over** |
| hailstorm average, 2,571/day | 46.9 M | **234× over** |
| hailstorm day 1, ~7,200 | 131 M | **656× over** |

The system can't serve *today's* volume on this tier, never mind 10×. That is the honest headline.

**Second wall:** even with no daily cap, **8,000 tokens/minute** is 11.5 M tokens/day if perfectly paced. That is **632 claims/day**, 4.1× short of the hailstorm average.

**Third:** the MCP stdio design spawns two server processes per claim, about 5.6 s each. Each loads the ~440 MB embedder. That's latency and RAM per concurrent claim, not a hard wall, and it goes away with one long-lived HTTP server.

**What does *not* break:** cost. A full hailstorm week is 18,000 × $0.0018 ≈ **$33** of generation.

## The 10× plan, in order
1. **Buy the throughput.**
   - **Tier:** move to a paid tier sized for peak. ~131 M tokens on day 1 is ~91k tokens/minute averaged over 24 h; plan for ~3× that in the peak hours.
   - **Fallback provider:** a second provider/model on the same prompt as overflow, with a per-model eval run before it takes traffic.
2. **Don't send every FNOL through the agent.**
   - **Deterministic fast path:** Week 7's verdict was that a fixed workflow matched the agent where the cause is unambiguous. A hailstorm week is mostly motor hail and windscreen, where the clause (MT-PW §3.2 / MHA-25, MT-PW §4.1) and limits row follow from cover level and endorsement set.
   - **Effect:** a deterministic referral for those, with the agent kept for the ambiguous ones, cuts LLM tokens roughly by the fast-path share. At 70% fast path, 46.9 M → ~14 M tokens/day.
3. **Cut tokens per agent claim.**
   - **Where they go:** the 18k is mostly re-sent context. Tool schemas plus system prompt are ~1.5–2k per turn × 6 turns.
   - **Fixes:** fewer turns (check in force at ingress in code; one combined wording-plus-limits tool) and smaller schemas.
   - **Target:** <10k per claim, which halves the quota needed.
4. **Long-lived MCP servers over HTTP** (already supported: `serve-mcp --http`), shared by all workers. Removes the 5.6 s spawn and the per-claim embedder load.
5. **Queue with backpressure and an SLA.**
   - **Ordering:** FNOLs wait in order and every one still gets a referral.
   - **When quota runs out:** the agent now refers on a quota error (`rate_limited:*`) instead of dropping the claim.
   - **Priority:** injury and not-in-force claims go first, because they need a human fastest.
