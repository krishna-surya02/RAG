"""Shared configuration and factories for the RAG pipeline.

Generation runs on Groq (fast hosted inference, needs GROQ_API_KEY); embeddings
run locally via sentence-transformers, because Groq serves chat completions only
and has no embeddings endpoint. Both ingest.py and rag.py import their settings
from here so the two halves can never disagree about chunk size, collection name
or embedding model.

Every setting except GROQ_API_KEY has a working default. Put the key in .env.
"""

import os
import sys

from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_postgres import PGVector

load_dotenv()


def _int_env(name, default):
    return int(os.getenv(name, default))


def _optional_int_env(name):
    """Empty or unset means "no limit" — pass None straight through to the API."""
    raw = os.getenv(name, "").strip()
    return int(raw) if raw else None


# --- Documents -------------------------------------------------------------
PDF_DIR = os.getenv("PDF_DIR", "/Users/softsuave/RAG")

# --- Postgres / pgvector ---------------------------------------------------
# Note the "+psycopg" driver (psycopg3). langchain-postgres does not accept the
# older "+psycopg2" string that the previous scripts used.
#
# Its own database, not "postgres": the old langchain.vectorstores shim created
# langchain_pg_embedding there with an incompatible schema (a "uuid" column
# where langchain-postgres expects "id"). A separate DB keeps the legacy
# my_docs collection intact instead of forcing a migration.
CONNECTION_STRING = os.getenv(
    "PG_CONNECTION_STRING",
    "postgresql+psycopg://softsuave:softsuave@localhost:5433/rag_ai",
)
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "dev_profiles")

# --- Groq (generation) -----------------------------------------------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
# The previous default, llama-3.3-70b-versatile, is not available on this
# account — Groq answers 404 model_not_found for it, so every query failed at
# generation time. The accessible set differs per key; list yours with
# groq.Groq(api_key=...).models.list() rather than guessing from the docs.
CHAT_MODEL = os.getenv("CHAT_MODEL", "openai/gpt-oss-120b")
TEMPERATURE = float(os.getenv("TEMPERATURE", 0.4))
MAX_TOKENS = _optional_int_env("MAX_TOKENS")
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", 60))
MAX_RETRIES = _int_env("MAX_RETRIES", 2)

# --- Embeddings (local) ----------------------------------------------------
# EMBED_DIM must match the model's output width. It is baked into the
# langchain_pg_embedding "vector(N)" column when that table is first created,
# and --reset does not rebuild the table — see the README before changing it.
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-base-en-v1.5")
EMBED_DIM = _int_env("EMBED_DIM", 768)

# --- Retrieval -------------------------------------------------------------
CHUNK_SIZE = _int_env("CHUNK_SIZE", 1200)
CHUNK_OVERLAP = _int_env("CHUNK_OVERLAP", 200)
TOP_K = _int_env("TOP_K", 5)

# Ranking strategy, shared by rag.py and evaluate.py so the retriever that is
# measured is the retriever that ships. "dense" is the original behaviour:
# cosine nearest-neighbour over the embedding, nothing else.
RETRIEVAL_MODE = os.getenv("RETRIEVAL_MODE", "dense")

# How many chunks a ranker pulls before the final top-k cut. Only matters for
# modes that rerank or fuse; "dense" slices its top-k straight off the front.
CANDIDATE_K = _int_env("CANDIDATE_K", 25)

# --- Retrieval backend -----------------------------------------------------
# "local" embeds the corpus in-process and scores cosine in numpy; it needs no
# database and is what the evaluation runs on. "pgvector" uses the Postgres
# collection above. Both chunk through ingest.py, so chunk ids match either way.
RETRIEVAL_BACKEND = os.getenv("RETRIEVAL_BACKEND", "local")
INDEX_CACHE_DIR = os.getenv("INDEX_CACHE_DIR", ".index_cache")

# --- Traces ----------------------------------------------------------------
# Every answer rag.py serves appends one redacted JSON line here. Point it
# somewhere else for experiments, so they never mix with real traffic.
TRACE_PATH = os.getenv("TRACE_PATH", "traces/claims_traces.jsonl")


def preflight(require_chat_model=True):
    """Fail with a readable message instead of a raw traceback mid-query."""
    if require_chat_model and not GROQ_API_KEY:
        sys.exit(
            "GROQ_API_KEY is not set.\n"
            "Get a key at https://console.groq.com/keys, then add to .env:\n"
            "  GROQ_API_KEY=gsk_..."
        )

    # The first run downloads a few hundred MB of model weights. Say so, or a
    # silent two-minute pause looks like a hang.
    if not _embedder_is_cached():
        print(f"Downloading embedding model '{EMBED_MODEL}' (one time)...")


def _embedder_is_cached():
    """Best-effort check of the HuggingFace cache; wrong answers are harmless."""
    cache = os.getenv("HF_HOME") or os.path.expanduser("~/.cache/huggingface")
    folder = "models--" + EMBED_MODEL.replace("/", "--")
    return os.path.isdir(os.path.join(cache, "hub", folder))


def get_embeddings():
    # Imported here, not at module scope: embeddings.py reads EMBED_MODEL from
    # this module, so a top-level import would be circular. It also keeps the
    # multi-second torch import off code paths that never embed anything.
    from embeddings import SentenceTransformerEmbeddings

    return SentenceTransformerEmbeddings()


def get_vector_store(pre_delete_collection=False):
    return PGVector(
        embeddings=get_embeddings(),
        connection=CONNECTION_STRING,
        collection_name=COLLECTION_NAME,
        embedding_length=EMBED_DIM,
        use_jsonb=True,
        pre_delete_collection=pre_delete_collection,
    )


def get_llm():
    return ChatGroq(
        model=CHAT_MODEL,
        api_key=GROQ_API_KEY,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        timeout=REQUEST_TIMEOUT,
        max_retries=MAX_RETRIES,
    )
