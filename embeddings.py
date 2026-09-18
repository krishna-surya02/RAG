"""Local sentence-transformers embeddings, wrapped for LangChain.

Groq serves chat completions only — it has no embeddings endpoint — so the
retrieval half of the pipeline stays local: no key, no per-chunk cost, and
ingesting a stack of resumes doesn't cost a round trip per batch.

The model downloads on first use (~440 MB for the default) and is cached in
~/.cache/huggingface thereafter.
"""

from functools import lru_cache
from typing import List

from langchain_core.embeddings import Embeddings
from sentence_transformers import SentenceTransformer

from config import EMBED_MODEL


@lru_cache(maxsize=1)
def get_embedder() -> SentenceTransformer:
    """Load the model once per process — it costs seconds and ~500 MB of RAM."""
    return SentenceTransformer(EMBED_MODEL)


def embed_texts(texts: List[str]) -> List[List[float]]:
    # normalize_embeddings=True pairs with PGVector's default cosine distance.
    embedder = get_embedder()
    return embedder.encode(texts, normalize_embeddings=True).tolist()


def embed_query(text: str) -> List[float]:
    return embed_texts([text])[0]


class SentenceTransformerEmbeddings(Embeddings):
    """Adapter so PGVector can consume the functions above.

    The base class supplies async variants that delegate to these two, and
    nothing in this project is async, so there is nothing else to implement.
    """

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return embed_texts(texts)

    def embed_query(self, text: str) -> List[float]:
        return embed_query(text)
