"""Shared configuration and factories for the local RAG pipeline.

Everything runs on Ollama — no API keys, no per-query cost. Both ingest.py and
rag.py import their settings from here so the two halves can never disagree
about chunk size, collection name or embedding model.

Every setting has a working default; a .env file is optional.
"""

import os
import sys
from urllib.error import URLError
from urllib.request import urlopen

from dotenv import load_dotenv
from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_postgres import PGVector

load_dotenv()


def _int_env(name, default):
    return int(os.getenv(name, default))


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

# --- Ollama ----------------------------------------------------------------
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
EMBED_DIM = _int_env("EMBED_DIM", 768)
CHAT_MODEL = os.getenv("CHAT_MODEL", "deepseek-r1:1.5b")
TEMPERATURE = float(os.getenv("TEMPERATURE", 0.4))
NUM_CTX = _int_env("NUM_CTX", 8192)

# --- Retrieval -------------------------------------------------------------
# Small chunks and a small k: a 1.5B model degrades sharply as context grows,
# and 100 chunks bury the relevant ones rather than helping.
CHUNK_SIZE = _int_env("CHUNK_SIZE", 1200)
CHUNK_OVERLAP = _int_env("CHUNK_OVERLAP", 200)
TOP_K = _int_env("TOP_K", 5)


def preflight(require_chat_model=True):
    """Fail with a readable message instead of a raw connection traceback."""
    try:
        with urlopen(f"{OLLAMA_BASE_URL}/api/tags", timeout=5) as response:
            import json

            installed = {m["name"] for m in json.load(response)["models"]}
    except URLError:
        sys.exit(
            f"Cannot reach Ollama at {OLLAMA_BASE_URL}.\n"
            "Start it with:  ollama serve"
        )

    def missing(model):
        # `ollama list` reports "name:tag"; users often configure the bare name.
        return not any(n == model or n.startswith(f"{model}:") for n in installed)

    needed = [EMBED_MODEL] + ([CHAT_MODEL] if require_chat_model else [])
    for model in needed:
        if missing(model):
            sys.exit(f"Ollama model '{model}' is not installed.\nRun:  ollama pull {model}")


def get_embeddings():
    return OllamaEmbeddings(model=EMBED_MODEL, base_url=OLLAMA_BASE_URL)


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
    # reasoning=False suppresses deepseek-r1's <think> blocks at the source.
    return ChatOllama(
        model=CHAT_MODEL,
        base_url=OLLAMA_BASE_URL,
        temperature=TEMPERATURE,
        num_ctx=NUM_CTX,
        reasoning=False,
    )
