"""Index every PDF in PDF_DIR into pgvector. Run once, then query with rag.py.

Re-running is safe: each chunk gets a content-derived id, and PGVector upserts
on id conflict, so a second run overwrites the same rows instead of appending
duplicates.
"""

import argparse
import hashlib
import os
import sys
from pathlib import Path

# transformers is installed without a torch/TF backend and warns about it on
# import. We never use it — silence the noise before langchain pulls it in.
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

import config

BATCH_SIZE = 64


def chunk_id(chunk, index):
    """Stable id for a chunk, so re-ingesting upserts rather than appends."""
    key = "|".join(
        [
            chunk.metadata.get("source_file", ""),
            str(chunk.metadata.get("page", "")),
            str(index),
            chunk.page_content,
        ]
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def load_and_split(pdf_path, splitter):
    pages = list(PyPDFLoader(str(pdf_path)).lazy_load())
    chunks = splitter.split_documents(pages)
    for chunk in chunks:
        chunk.metadata["source_file"] = pdf_path.name
    return len(pages), chunks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="drop the collection first (use after changing chunk size or embedding model)",
    )
    args = parser.parse_args()

    config.preflight(require_chat_model=False)

    pdf_paths = sorted(Path(config.PDF_DIR).glob("*.pdf"))
    if not pdf_paths:
        sys.exit(f"No PDFs found in {config.PDF_DIR}")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE, chunk_overlap=config.CHUNK_OVERLAP
    )
    store = config.get_vector_store(pre_delete_collection=args.reset)
    if args.reset:
        print(f"Reset collection '{config.COLLECTION_NAME}'.")

    print(f"Indexing {len(pdf_paths)} PDF(s) from {config.PDF_DIR} -> {config.COLLECTION_NAME}\n")
    total = 0
    for pdf_path in pdf_paths:
        page_count, chunks = load_and_split(pdf_path, splitter)
        ids = [chunk_id(chunk, i) for i, chunk in enumerate(chunks)]

        for start in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[start : start + BATCH_SIZE]
            store.add_documents(batch, ids=ids[start : start + BATCH_SIZE])

        total += len(chunks)
        print(f"  {pdf_path.name}: {page_count} pages -> {len(chunks)} chunks")

    print(f"\nDone. {total} chunks indexed. Ask questions with:  python rag.py")


if __name__ == "__main__":
    main()
