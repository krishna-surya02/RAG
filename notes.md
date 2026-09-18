# Week 5 notes: reading the claims assistant's traces

Everything below can be re-derived from the repo: the trace file is committed, and every seed is written down.

## 0. Where the traces came from (read this first)

- **The assistant had no trace file.** `rag.py` returned a string and wrote nothing, and no trace file existed in
  the repo or on this machine. The "week of traffic" in this analysis is **synthetic**. `traffic.py --seed 11`
  wrote a guess at adjuster traffic and sent it through the same `rag.answer()` the CLI serves, on 2026-09-18,
  compressed into one sitting. The mix is described in `traffic.py`'s docstring. The generator was written and
  committed (`7dcb541`) before any trace existed, so it could not be tuned toward failures already seen. The
  frequencies below therefore describe this traffic mix, not production.
- The Groq key is on the **free tier**, read from response headers: `x-ratelimit-limit-tokens: 8000` per minute and
  `x-ratelimit-limit-requests: 1000` per day, with roughly 200k tokens a day on `openai/gpt-oss-120b`. The rule,
  fixed before the tier was known, was: Developer tier gets 1,000 traces, free tier gets whatever a 180k-token
  budget buys. __POPULATION__
- Seeds were fixed in the plan before any trace existed: traffic `11`, replay pick `918`, sample `20260918`.

## 1. Are the traces replayable?

### Fields: what existed before this week, and what was added

| Required field | Before (`c096f43`) | Now (`7dcb541`), in each trace line |
|---|---|---|
| prompt version | **missing**: no trace at all, and the prompt had no version | `prompt.version` (`claims-v1`), `prompt.template_sha256`, `prompt.rendered` (exact text sent) |
| retrieved chunk_ids + scores | **missing**: `retrieval.py` computed scores and `rag.py`'s chain discarded them inside the pipe | `retrieval.hits[]` with rank, chunk_id, score, file, page; plus `index_key`, `embed_model`, `embed_revision` (HF snapshot), chunk size/overlap, k |
| model + params | **missing** | `model.name`, temperature, max_tokens, reasoning_effort/format (None = provider default), top_p, timeout, retries, and a per-trace **`seed`** (new; the model was unseeded before) |
| raw output | **missing**: `StrOutputParser` + `strip_think` threw away everything but the text | `output.raw` (pre-strip), `output.reasoning`, `output.final`, finish_reason, token usage, `system_fingerprint`, model id returned |
| also added | | `trace_id`, UTC `ts`, `app.git_commit` + dirty flag, `input.redacted` counts, `latency_ms`, `error` |

### Replay evidence

__REPLAY__

### Redaction happens before the trace is written, not after

- **Where:** `rag.answer()` calls `redact.redact(question)` as its first line, before retrieval, the model, or the
  trace record see the question ([rag.py](rag.py)). Retrieval, the prompt, the model and the trace all hold the
  redacted text `[CLAIMANT_1]` / `[CLAIM_NO_1]`. That is also why the replay's prompt can be byte-identical: had
  redaction happened only in the writer, the model would have seen text the trace does not hold.
- **Second lock:** `tracing.write_trace()` receives the raw values that were found, in memory only. It scrubs every
  string field for them, re-checks the serialised line, and raises instead of writing if one survives
  ([tracing.py](tracing.py)). The trace keeps only counts (`input.redacted`), never the values.
- **Evidence:**
  - `python redact.py --selftest`: 14 cases, 0 failures. That covers 7 must-redact cases and 7 must-not-redact
    cases, such as `HO-0304 ed. 03-24`, `E-17`, `HO 03 04 (01/22)`, "Water Backup and Sump Overflow", and
    "$18,500".
  - Held-out generator seed 999: 2,000 questions, 0 leaked names or claim numbers, 0 over-redacted questions.
  - Smoke trace (`df307053…`): a grep for the name and claim number found 0 hits.
  - __LEAKCHECK__

## 2. The sample

__SAMPLE__

## 3. Open coding: one sentence per trace, verbatim

__OPENCODING__

## 4. Prediction

__PREDICTION__

## 5. Why a public benchmark would not have surfaced these

__BENCHMARK__
