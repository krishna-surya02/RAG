# Cost per query, by stage

## The found request (`c4559f34`, adj-06, 2026-10-29 11:25 UTC, claims-v1, dense)
From [trace.json](trace.json) `spans`. Pricing: `openai/gpt-oss-120b` on Groq, $0.15 / 1M input and $0.60 / 1M output (console.groq.com, checked 2026-10-27; `config.PRICE_*_PER_M`).

| stage | latency | tokens (in / out) | cost | share of cost |
|---|---|---|---|---|
| redact | 6.8 ms | 0 / 0 | $0 | 0% |
| retrieval (local bge-base embed + numpy cosine) | 5,745.2 ms | 0 / 0 | $0 | 0% |
| generation | 1,817.4 ms | 1,467 / 529 | **$0.00053745** (in $0.00022005 + out $0.00031740) | 100% |
| tools | 0 ms (0 calls) | 0 / 0 | $0 | 0% |
| **total** | **7,569.4 ms** | **1,996** | **$0.00053745** | |

Retrieval and tools cost $0 at the margin, not by omission. Retrieval runs on a local embedder (no API and no per-call fee; the compute is the host's), and this path makes no tool calls. The `tools` span is logged empty so the breakdown has no gap. Output tokens are 26% of tokens but 59% of the cost. 
Note: this was the planted line. Its answer text was swapped in after the model call, but the call, its tokens and its latency are real.

## All 70 logged requests (2026-10-27: 40, 2026-10-29: 30)
| | mean | p50 | p95 |
|---|---|---|---|
| cost / query | $0.000625 | $0.000587 | $0.000911 |
| tokens / query | 2,213 (1,563 in / 650 out) | 2,145 | 2,764 |
| retrieval latency | | 5,876 ms | 10,333 ms |
| generation latency | | 2,187 ms | 4,328 ms |
| end-to-end | | 8,029 ms | 12,498 ms |

**Retrieval is the slowest stage, and it's not the retriever.** Measured in one process, the query embed takes 39 ms warm, 1.6 s after 5 s idle, 7.0 s after 15 s and 10.1 s after 30 s. The local embedder goes cold between the paced traffic calls, which sleep to stay under the per-minute token limit. `evaluate.py`'s back-to-back timing (p50 23 ms) never sees this. It costs $0 and shrinks as traffic gets denser, so it's logged here, not fixed in Week 11. A warm-keeping ping, or a hosted embedder, would make sense if low-volume latency ever matters.
