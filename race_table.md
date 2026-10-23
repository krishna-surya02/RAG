# Week 10 race: single agent vs orchestrator (10 claims, same judge)

| Metric | Single agent | Orchestrator |
|---|---|---|
| Pass rate | 10/10 (100%) | 10/10 (100%) |
| p50 latency | 7,368 ms | 6,696 ms |
| p99 latency | 22,675 ms | 18,875 ms |
| Total tokens | 52,733 | 64,378 |
| Cost per claim | $0.000516 | $0.000919 |

Latency percentiles are over n=10 claims, so p99 is effectively the slowest claim. Latency excludes pacing waits for the shared 8k TPM limit.

**Context re-send multiplier: 1.2x** (64,378 orchestrator tokens / 52,733 single-agent tokens).

**Largest hand-off: orchestrator -> coverage_worker, 59% of all orchestrator tokens** (37,938 of 64,378; 82% of it re-sent prompt).

Token share by hand-off (from handoffs.log):

| Hand-off | Tokens | Share |
|---|---|---|
| orchestrator -> coverage_worker | 37,938 | 59% |
| workers -> synthesiser | 10,881 | 17% |
| orchestrator -> decomposer | 8,711 | 14% |
| orchestrator -> notes_worker | 6,848 | 11% |
