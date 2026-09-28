# RAG over policy PDFs

Question-answering over insurance policy documents, with a retrieval harness
that can prove where an answer went wrong. Generation runs on Groq, embeddings
run locally, and retrieval runs either in-process or on Postgres + pgvector.

| Piece | What it uses |
|---|---|
| Embeddings | local sentence-transformers `BAAI/bge-base-en-v1.5` (768-dim) |
| Chat model | Groq `openai/gpt-oss-120b` |
| Retrieval | in-process cosine index by default; pgvector on `localhost:5433` optionally |
| Documents | every `*.pdf` in `PDF_DIR` |

Groq serves chat completions only — it has no embeddings endpoint — so the
retrieval half stays local. Indexing costs nothing and needs no key; only
`rag.py` makes a network call.

Retrieval lives in one module, `retrieval.py`, which `rag.py`, `evaluate.py` and
`inspect_view.py` all call. That is deliberate: a benchmark that measures
retrieval code the application does not use produces numbers about something you
are not shipping.

## Setup

Requires the Postgres instance on port 5433 with the `vector` extension.

```bash
pip install -r requirements.txt
cp .env.example .env          # then set GROQ_API_KEY
```

Get a key at [console.groq.com/keys](https://console.groq.com/keys). Everything
else in `.env` is optional — the defaults in `config.py` work as-is.

The first ingest or query downloads the embedding model, about 440 MB into
`~/.cache/huggingface`. It prints a notice so the pause isn't mistaken for a
hang, and later runs load from cache.

## Usage

Point `PDF_DIR` at the policy documents, then ask away:

```bash
python rag.py "does exclusion E-17 apply under form HO-0304 ed. 03-24"
python rag.py                                             # interactive, 'exit' to quit
```

The default `local` backend chunks and embeds the corpus on first use and caches
the vectors under `.index_cache/`, so only the first query pays for it. To serve
from Postgres instead, run `python ingest.py` once and set
`RETRIEVAL_BACKEND=pgvector`. Both paths chunk through `ingest.py` and share the
same chunk ids, so a chunk means the same thing either way.

## Measuring retrieval

When an answer is wrong, three very different things could have happened, and
they need different fixes: retrieval never fetched the right chunk (R), the
right chunk was in the context and the model misused it (G), or nothing in the
corpus answers the question. Reading the answer cannot tell them apart — a
confident paragraph about a neighbouring exclusion looks the same as a correct
one.

`inspect_view.py` shows what was actually fetched, which chunks carry the
identifier that was asked about, where the known-correct chunk ranked, and the
model's answer, all on one screen:

```bash
python inspect_view.py "does exclusion E-17 apply under form HO-0304 ed. 03-24" --answer
python inspect_view.py --question q03 --answer      # by golden-set id
python inspect_view.py --find "Continuous Seepage"  # get a chunk id for the golden set
```

`goldenset.json` holds the evaluation questions, each tagged with the chunk id
that actually answers it. Tag those by finding the text with `--find`, never by
asking the retriever — letting retrieval choose its own ground truth makes the
measurement circular.

`evaluate.py` scores hit-rate@3 and p50 retrieval latency over that set:

```bash
python evaluate.py --mode dense --label before
python evaluate.py --compare eval_out/before.json eval_out/after.json
```

Latency covers the retrieval call only. Generation is a variable network round
trip and folding it in would hide what the retriever costs. The `--compare` view
is per question, so a change that fixes three questions and breaks one is not
reported as a net gain of two.

## Notes

**Why a separate `rag_ai` database.** The older scripts in `/Users/softsuave/RAG`
used `langchain.vectorstores.PGVector`, the deprecated shim, which created
`langchain_pg_embedding` in the `postgres` database with a schema the supported
`langchain-postgres` package can't use (a `uuid` column where it expects `id`,
`json` where it expects `jsonb`). Rather than migrate or drop that table — it
still holds the 1,725-row `my_docs` collection — this project gets its own
database on the same server. The old data is untouched and both can coexist.

**Re-running `ingest.py` is safe.** Each chunk's id is a SHA-256 of its source
file, page, position and text, and PGVector upserts on id conflict — so a second
run overwrites the same rows rather than appending duplicates. Drop a new PDF
into `PDF_DIR` and re-run to index just the new material.

**After changing `CHUNK_SIZE`, `CHUNK_OVERLAP` or `EMBED_MODEL`**, rebuild:

```bash
python ingest.py --reset
```

Different chunk settings produce different ids, so without `--reset` you'd end
up with both the old and new chunks in the collection.

**`EMBED_DIM` is harder to change than it looks.** `langchain_pg_embedding` has
a single `vector(N)` column, and its width is fixed when the table is first
created. `--reset` deletes the collection's rows but never rebuilds the table,
so switching to a model of a different width — `BAAI/bge-small-en-v1.5` at 384,
say — fails on insert with a dimension mismatch. Drop the table first:

```sql
DROP TABLE langchain_pg_embedding CASCADE;
```

Then set `EMBED_DIM` to match and run `python ingest.py --reset`. Staying on a
768-dim model avoids this entirely.

**Chunk ids are content hashes.** Each id is a SHA-256 of the chunk's source
file, page, position and text, which is what makes re-ingesting idempotent. It
also means changing `CHUNK_SIZE` or `CHUNK_OVERLAP` invalidates every
`gold_chunk_id` in `goldenset.json`. The evaluation resolves gold chunks by id
first and by their recorded text phrase second, and says which path it used, so
a stale id surfaces as a warning rather than as a fake retrieval miss.

**Tuning retrieval.** `TOP_K=5` is conservative; raise it for broad questions,
drop it if answers wander. Changing it needs no re-ingest. `RETRIEVAL_MODE`
selects the ranking strategy and `CANDIDATE_K` sets how deep a ranker looks
before the final cut — `dense` ignores the latter, but the evaluation uses it to
ask whether a missed chunk was ever fetched at all. That distinction decides
what can fix a miss: a reranker only reorders what was already retrieved, so a
chunk that never enters the candidate pool is beyond its reach.

**Changing the chat model.** Set `CHAT_MODEL` in `.env`. No re-ingest needed —
embeddings are independent of the chat model, so this is the cheapest thing in
the pipeline to change and, for retrieval failures, the least likely to help.

The published model list is not the list a given key can reach. This account
gets 404 `model_not_found` for `llama-3.3-70b-versatile`, which was the previous
default here and made every query fail at generation. Check before setting it:

```python
from groq import Groq; print([m.id for m in Groq(api_key=...).models.list().data])
```

Leave `MAX_TOKENS` empty for `gpt-oss` and `qwen`. They are reasoning models and
spend the budget reasoning before emitting anything, so a small cap yields an
empty answer rather than a truncated one. `<think>` blocks are stripped
automatically.

## Traces

Every answer `rag.py` serves appends one JSON line to `traces/claims_traces.jsonl`:
the redacted question, the prompt version and the exact prompt sent, every
retrieved chunk id with its score, the model and every sampling parameter
including a per-trace seed, and the raw output with its reasoning and token
usage. Claimant names and claim numbers are removed before retrieval, the model
or the trace sees the question, and the trace writer checks again before it
writes.

```bash
python replay.py --seed 918                      # replay one random trace from the line alone
python sample_traces.py --seed 20260918 --n 20   # seeded random sample
python sample_traces.py --trace-id 3f2a --show   # read one
```

Groq does not honour `seed` across backends, so a replay reproduces the prompt
and the retrieval exactly, but reproduces the answer only approximately.

## Files

- `config.py` — all settings and the store/LLM factories; every script reads from here
- `embeddings.py` — local sentence-transformers embedder, wrapped for LangChain
- `ingest.py` — PDFs → chunks → embeddings → pgvector (idempotent)
- `retrieval.py` — the one place ranking happens; shared by the app and the evaluation
- `rag.py` — `answer()`: redact, retrieve, prompt, generate, trace; one-shot or interactive
- `redact.py` — strips claimant names and claim numbers at ingress; `--selftest`
- `tracing.py` — one redacted JSON line per answer in `traces/claims_traces.jsonl`
- `replay.py` — rebuilds one trace's prompt, retrieval and answer from the trace line alone
- `sample_traces.py` — seeded random sample of trace ids, plus a reading view (`--show`)
- `traffic.py` — seeded synthetic adjuster traffic through `rag.answer`, and a PII leak check
- `inspect_view.py` — what was retrieved, what it carries, and where the gold chunk ranked
- `evaluate.py` — hit-rate@3 and p50 latency over the golden set, plus before/after compare
- `goldenset.json` — evaluation questions, each tagged with its known-correct chunk id
