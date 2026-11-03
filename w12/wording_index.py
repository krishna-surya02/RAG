"""Clause-level embedding index over data/wordings, for retrieval.retrieve_in_force.

One chunk per clause, never a fixed-size window: a citation has to name a
clause, and a window that straddles HFL-23 §2.1 and §2.2 can't be cited as
either. Each record carries the clause's document, version and effective
window, so the date filter needs no second lookup.

The embedded text is the clause ref + title + body. It deliberately does NOT
include the version or set: week 5 found sibling editions that are textually
identical, and the filter -- not the embedding -- is what should separate
them. Cached like retrieval.LocalIndex, keyed on the wording files' bytes.
"""

import hashlib
import json
from pathlib import Path

import numpy as np

import config
from w12 import store

CACHE_VERSION = 1
_INDEX = None


def _key():
    h = hashlib.sha256(f"{CACHE_VERSION}|{config.EMBED_MODEL}".encode())
    for d in store.versions():
        h.update((store.ROOT / d["file"]).read_bytes())
    return "w12_" + h.hexdigest()[:16]


def records():
    out = []
    for c in store.all_clauses():
        body = f"{c['ref']} — {c['title']}\n{c['text']}"
        cid = hashlib.sha256(f"{c['doc_id']}|{c['version']}|{c['ref']}|{body}".encode()).hexdigest()
        out.append({
            "chunk_id": cid, "text": body, "source_file": Path(c["file"]).name, "page": c["page"],
            "ref": c["ref"], "title": c["title"], "anchor": c["anchor"], "doc_id": c["doc_id"],
            "product": c["product"], "kind": c["kind"], "version": c["version"], "file": c["file"],
            "effective_from": c["effective_from"], "effective_to": c["effective_to"],
        })
    return out


class WordingIndex:
    def __init__(self, recs, vectors):
        self.records = recs
        self.vectors = vectors

    def scores(self, query):
        from embeddings import embed_query

        return self.vectors @ np.asarray(embed_query(query), dtype=np.float32)


def build(rebuild=False, quiet=False):
    global _INDEX
    if _INDEX is not None and not rebuild:
        return _INDEX
    cache = Path(config.INDEX_CACHE_DIR)
    key = _key()
    vec_path, rec_path = cache / f"{key}.npy", cache / f"{key}.json"
    if not rebuild and vec_path.exists() and rec_path.exists():
        _INDEX = WordingIndex(json.loads(rec_path.read_text(encoding="utf-8")), np.load(vec_path))
        return _INDEX
    recs = records()
    if not quiet:
        print(f"Embedding {len(recs)} wording clauses (one time)...")
    from embeddings import embed_texts

    vectors = np.asarray(embed_texts([r["text"] for r in recs]), dtype=np.float32)
    cache.mkdir(parents=True, exist_ok=True)
    np.save(vec_path, vectors)
    rec_path.write_text(json.dumps(recs), encoding="utf-8")
    _INDEX = WordingIndex(recs, vectors)
    return _INDEX
