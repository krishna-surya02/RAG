# Local RAG over developer profile PDFs

Question-answering over resume PDFs, running entirely on your machine — Ollama
for both embeddings and generation, Postgres + pgvector for storage. No API
keys, no per-query cost.

| Piece | What it uses |
|---|---|
| Embeddings | Ollama `nomic-embed-text` (768-dim) |
| Chat model | Ollama `deepseek-r1:1.5b` |
| Vector store | pgvector on `localhost:5433`, database `rag_ai`, collection `dev_profiles` |
| Documents | every `*.pdf` in `/Users/softsuave/RAG` |

## Setup

Requires a running Ollama and the Postgres instance on port 5433 with the
`vector` extension (both already set up on this machine).

```bash
ollama pull nomic-embed-text        # 275 MB, the only download
pip install -r requirements.txt     # already satisfied in /opt/anaconda3
```

Copy `.env.example` to `.env` if you want to override any defaults — it's
entirely optional and holds no secrets.

## Usage

Index the PDFs once:

```bash
python ingest.py
```

Then ask away:

```bash
python rag.py "Which developers have React experience?"   # one-shot
python rag.py                                             # interactive, 'exit' to quit
```

Queries don't re-embed anything, so follow-ups are fast.

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

**Tuning retrieval.** `TOP_K=5` keeps the prompt around 1.7k tokens, which suits
a 1.5B model — small models get worse, not better, as context grows. Raise it to
8–10 for broad questions spanning all six resumes ("who knows React?"); drop to
3 if answers start wandering.

**Upgrading the chat model.** If answers feel thin, `ollama pull llama3.1:8b` and
set `CHAT_MODEL=llama3.1:8b` in `.env`. No re-ingest needed — the embeddings are
independent of the chat model.

## Files

- `config.py` — all settings and the store/LLM factories; both scripts read from here
- `ingest.py` — PDFs → chunks → embeddings → pgvector (idempotent)
- `rag.py` — retriever + LLM chain, one-shot or interactive
