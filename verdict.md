# Week 10 verdict: orchestrator vs single agent
Sunk-cost bias, said out loud: I spent a week on the multi-agent design, which makes me want to keep it. I'm judging on the numbers instead.
Pass rate was 10/10 for both arms, so the orchestrator buys no accuracy.
It used 64,378 tokens against 52,733 (1.2x), and cost $0.000919 per claim against $0.000516, about 1.8x more.
Latency doesn't separate them: p50 6.7s vs 7.4s, p99 18.9s vs 22.7s. Single-agent latency includes Groq 429 retries (n=10).
When the coverage worker returned a 500, the orchestrator retried once, then fabricated a "denied" with an invented exclusion code (failure_case.md).
**KILL** the orchestrator for this claims workload: the same pass rate for ~1.8x the cost, plus an unsafe failure mode.
Revisit only if workers need different tools or models, or the synthesiser is made to refuse when a worker's result is missing.
