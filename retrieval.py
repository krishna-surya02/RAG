"""The one place retrieval happens, shared by rag.py and evaluate.py.

Before this module, retrieval lived inline in rag.py's LCEL chain and threw the
scores away, so nothing could see what was fetched or why. Evaluating a
retriever you cannot observe is guesswork, and evaluating one the app does not
actually call is worse — the numbers describe code you are not shipping. So
both halves import `retrieve` from here.

Two backends sit behind one interface:

  local     chunks the PDFs with ingest.py, embeds them once, caches the
            vectors, and scores cosine in numpy. No database, no Docker.
  pgvector  the Postgres collection, for when that server is up.

Both chunk through `ingest.load_and_split` and id through `ingest.chunk_id`, so
a chunk has the same id whichever backend served it. That is what lets a golden
set built against one backend be checked against the other.
"""

import hashlib
import json
import os
from pathlib import Path

# sentence-transformers logs model-loading chatter on every run. Quiet it before
# the import; the first-run download bar comes from huggingface_hub and still shows.
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

import numpy as np
from langchain_text_splitters import RecursiveCharacterTextSplitter

import config
import ingest

# Cache format version. Bump when the record layout changes, so stale caches are
# rebuilt rather than silently misread.
CACHE_VERSION = 1


class Hit:
    """One retrieved chunk, with everything the inspection view needs to explain
    why it is here: the score that ranked it, and, for fused rankings, the rank
    each contributing ranker gave it."""

    __slots__ = ("chunk_id", "text", "source_file", "page", "score", "rank", "components")

    def __init__(self, chunk_id, text, source_file, page, score, rank=0, components=None):
        self.chunk_id = chunk_id
        self.text = text
        self.source_file = source_file
        self.page = page
        self.score = score
        self.rank = rank
        self.components = components or {}

    @property
    def short_id(self):
        return self.chunk_id[:12]

    def locator(self):
        """Human-readable position, for reading a results table without a DB."""
        page = self.page
        page = "?" if page is None else page
        return f"{self.source_file} p{page}"

    def as_dict(self):
        return {
            "rank": self.rank,
            "chunk_id": self.chunk_id,
            "score": round(float(self.score), 6),
            "source_file": self.source_file,
            "page": self.page,
            "components": self.components,
            "text": self.text,
        }


# --- Corpus ----------------------------------------------------------------


def corpus_records():
    """Chunk every PDF in PDF_DIR exactly the way ingest.py does.

    The per-PDF `enumerate` matters: ingest.py numbers chunks within a file, not
    across the corpus, and that index is hashed into the id. Numbering globally
    here would produce ids that no ingested row shares.
    """
    pdf_paths = sorted(Path(config.PDF_DIR).glob("*.pdf"))
    if not pdf_paths:
        raise SystemExit(
            f"No PDFs found in {config.PDF_DIR}.\n"
            "Set PDF_DIR in .env to the directory holding the policy documents."
        )

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE, chunk_overlap=config.CHUNK_OVERLAP
    )

    records = []
    for pdf_path in pdf_paths:
        _, chunks = ingest.load_and_split(pdf_path, splitter)
        for index, chunk in enumerate(chunks):
            records.append(
                {
                    "chunk_id": ingest.chunk_id(chunk, index),
                    "text": chunk.page_content,
                    "source_file": chunk.metadata.get("source_file", pdf_path.name),
                    "page": chunk.metadata.get("page"),
                }
            )
    return records


def _cache_key():
    """Anything that changes chunk boundaries, ids or vectors goes in the key,
    so a stale cache can never be mistaken for a fresh one."""
    parts = [
        str(CACHE_VERSION),
        config.EMBED_MODEL,
        str(config.CHUNK_SIZE),
        str(config.CHUNK_OVERLAP),
    ]
    for pdf_path in sorted(Path(config.PDF_DIR).glob("*.pdf")):
        stat = pdf_path.stat()
        parts.append(f"{pdf_path.name}:{stat.st_size}:{int(stat.st_mtime)}")
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


# --- Local index -----------------------------------------------------------


class LocalIndex:
    """Chunks plus their embeddings, held in memory, scored with one matmul.

    Vectors come out of embeddings.py already L2-normalised, so the dot product
    is cosine similarity — the same metric PGVector is configured with. Higher
    is better here; PGVector reports a distance, and the backend below flips it
    so callers never have to care which way a score points.
    """

    def __init__(self, records, vectors):
        self.records = records
        self.vectors = vectors
        self._by_id = {r["chunk_id"]: i for i, r in enumerate(records)}

    def __len__(self):
        return len(self.records)

    def position_of(self, chunk_id):
        return self._by_id.get(chunk_id)

    def record(self, chunk_id):
        pos = self._by_id.get(chunk_id)
        return None if pos is None else self.records[pos]

    def search(self, query, k):
        from embeddings import embed_query

        scores = self.vectors @ np.asarray(embed_query(query), dtype=np.float32)
        k = min(k, len(scores))
        # argpartition finds the top k without sorting the whole corpus, then
        # only those k get ordered. On a small corpus this is noise; it keeps
        # the latency number honest as the corpus grows.
        top = np.argpartition(-scores, k - 1)[:k]
        top = top[np.argsort(-scores[top])]
        return [
            _hit_from_record(self.records[i], float(scores[i]), rank)
            for rank, i in enumerate(top, start=1)
        ]


def _hit_from_record(record, score, rank):
    return Hit(
        chunk_id=record["chunk_id"],
        text=record["text"],
        source_file=record["source_file"],
        page=record["page"],
        score=score,
        rank=rank,
    )


_INDEX = None


def build_index(rebuild=False, quiet=False):
    """Load the cached index, or chunk and embed the corpus and cache it.

    Embedding the whole corpus costs seconds to minutes. Doing it inside a
    latency measurement would swamp the thing being measured, so it happens
    once, here, and every timed call reads from RAM.
    """
    global _INDEX
    if _INDEX is not None and not rebuild:
        return _INDEX

    cache_dir = Path(config.INDEX_CACHE_DIR)
    key = _cache_key()
    vectors_path = cache_dir / f"{key}.npy"
    records_path = cache_dir / f"{key}.json"

    if not rebuild and vectors_path.exists() and records_path.exists():
        records = json.loads(records_path.read_text(encoding="utf-8"))
        vectors = np.load(vectors_path)
        _INDEX = LocalIndex(records, vectors)
        return _INDEX

    records = corpus_records()
    if not quiet:
        print(f"Embedding {len(records)} chunks from {config.PDF_DIR} (one time)...")

    from embeddings import embed_texts

    vectors = np.asarray(embed_texts([r["text"] for r in records]), dtype=np.float32)

    cache_dir.mkdir(parents=True, exist_ok=True)
    np.save(vectors_path, vectors)
    records_path.write_text(json.dumps(records), encoding="utf-8")

    _INDEX = LocalIndex(records, vectors)
    return _INDEX


# --- Backends --------------------------------------------------------------


def _search_local(query, k):
    return build_index(quiet=True).search(query, k)


def _search_pgvector(query, k):
    """PGVector returns a cosine *distance*, so flip it to a similarity to match
    the local backend's ordering. Document.id is the ingest-time chunk id."""
    store = config.get_vector_store()
    results = store.similarity_search_with_score(query, k=k)
    hits = []
    for rank, (doc, distance) in enumerate(results, start=1):
        hits.append(
            Hit(
                chunk_id=doc.id or doc.metadata.get("chunk_id", ""),
                text=doc.page_content,
                source_file=doc.metadata.get("source_file", "unknown"),
                page=doc.metadata.get("page"),
                score=1.0 - float(distance),
                rank=rank,
            )
        )
    return hits


BACKENDS = {"local": _search_local, "pgvector": _search_pgvector}


def _backend(name=None):
    name = name or config.RETRIEVAL_BACKEND
    try:
        return BACKENDS[name]
    except KeyError:
        raise SystemExit(
            f"Unknown RETRIEVAL_BACKEND '{name}'. Choose one of: {', '.join(BACKENDS)}"
        )


# --- Ranking modes ---------------------------------------------------------


def _rank_dense(query, k, candidates, backend):
    """The original behaviour: cosine nearest neighbours, top k off the front.

    `candidates` is ignored — there is no second stage to feed. It stays in the
    signature so every mode is called the same way, and so the evaluation can
    ask a dense retriever for its top 25 to find out whether a missed chunk was
    ever fetched at all.
    """
    return backend(query, max(k, 1))


MODES = {"dense": _rank_dense}


def retrieve(query, k=None, candidates=None, mode=None, backend=None):
    """Rank chunks for one query. The single entry point for the whole project."""
    k = config.TOP_K if k is None else k
    candidates = config.CANDIDATE_K if candidates is None else candidates
    mode = mode or config.RETRIEVAL_MODE

    try:
        rank_fn = MODES[mode]
    except KeyError:
        raise SystemExit(
            f"Unknown RETRIEVAL_MODE '{mode}'. Choose one of: {', '.join(MODES)}"
        )

    hits = rank_fn(query, k, candidates, _backend(backend))
    return hits[:k]


def format_hits(hits):
    """Assemble retrieved chunks into prompt context.

    Kept here rather than in rag.py so the inspection view can show byte-for-byte
    what the model was given, instead of an approximation of it.
    """
    return "\n\n".join(
        f"[{hit.source_file}, page {hit.page if hit.page is not None else '?'}]\n{hit.text}"
        for hit in hits
    )
