"""One JSON line per answered question, with enough in it to replay the answer.

Before this module the assistant wrote nothing: a wrong coverage answer left no
record of what was asked, what was retrieved, what the model was sent, or what
it said. A trace here holds all four, plus the knobs that shaped them:

  input      the question, already redacted (see redact.py) and how much was removed
  prompt     the template version, its hash, and the exact text sent to the model
  retrieval  the index it ran against, and every chunk id with its score
  model      provider, model id and every sampling parameter, including the seed
  output     the raw completion, the reasoning, the final answer, token usage

replay.py rebuilds an answer from one of these lines and nothing else, which is
the test that the list above is complete.
"""

import datetime
import json
import os
import re
import subprocess
import time
import uuid
from functools import lru_cache
from pathlib import Path

import config


def new_trace_id():
    return uuid.uuid4().hex


def seed_for(trace_id):
    """A per-trace sampling seed, derived from the id so the trace alone recovers it."""
    return int(trace_id[:8], 16)


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")


@lru_cache(maxsize=1)
def app_version():
    """The commit the answer was produced by. The trace file itself is excluded
    from the dirty check — appending to it is not a code change."""
    root = Path(__file__).resolve().parent
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no", "--", ".",
             f":!{Path(config.TRACE_PATH).parent}"],
            cwd=root, capture_output=True, text=True, check=True,
        ).stdout.strip()
        return {"git_commit": commit, "dirty": bool(status)}
    except (OSError, subprocess.CalledProcessError):
        return {"git_commit": None, "dirty": None}


@lru_cache(maxsize=1)
def embed_revision():
    """The HuggingFace snapshot the embedder loaded. The model name alone is not
    a version: `main` moves, and a re-download can change every vector."""
    cache = os.getenv("HF_HOME") or os.path.expanduser("~/.cache/huggingface")
    ref = Path(cache, "hub", "models--" + config.EMBED_MODEL.replace("/", "--"), "refs", "main")
    try:
        return ref.read_text().strip()
    except OSError:
        return None


def retrieval_block(hits, k, candidates, mode, backend, index_key):
    return {
        "mode": mode,
        "backend": backend,
        "k": k,
        "candidates": candidates,
        "embed_model": config.EMBED_MODEL,
        "embed_revision": embed_revision(),
        "chunk_size": config.CHUNK_SIZE,
        "chunk_overlap": config.CHUNK_OVERLAP,
        "pdf_dir": config.PDF_DIR,
        "index_key": index_key,
        "hits": [
            {
                "rank": hit.rank,
                "chunk_id": hit.chunk_id,
                "score": round(float(hit.score), 6),
                "source_file": hit.source_file,
                "page": hit.page,
            }
            for hit in hits
        ],
    }


def model_block(llm, seed):
    """Every parameter the call was made with. None means "provider default",
    recorded as None rather than guessed, because a default can move."""
    return {
        "provider": "groq",
        "name": llm.model_name,
        "temperature": llm.temperature,
        "max_tokens": llm.max_tokens,
        "reasoning_effort": llm.reasoning_effort,
        "reasoning_format": llm.reasoning_format,
        "top_p": None,
        "seed": seed,
        "timeout": llm.request_timeout,
        "max_retries": llm.max_retries,
    }


def output_block(message, final):
    meta = message.response_metadata or {}
    return {
        "raw": message.content,
        "reasoning": message.additional_kwargs.get("reasoning_content"),
        "final": final,
        "finish_reason": meta.get("finish_reason"),
        "model_returned": meta.get("model_name"),
        "system_fingerprint": meta.get("system_fingerprint"),
        "token_usage": meta.get("token_usage"),
    }


class Timer:
    def __init__(self):
        self.start = time.perf_counter()

    def ms(self):
        return round((time.perf_counter() - self.start) * 1000.0, 1)


# --- Writing -----------------------------------------------------------------


def _scrub(value, patterns):
    if isinstance(value, str):
        for pattern in patterns:
            value = pattern.sub("[REDACTED]", value)
        return value
    if isinstance(value, dict):
        return {key: _scrub(item, patterns) for key, item in value.items()}
    if isinstance(value, list):
        return [_scrub(item, patterns) for item in value]
    return value


def write_trace(record, pii_values=(), path=None):
    """Append one trace. Redaction is re-checked here, before a byte hits disk.

    rag.answer already redacted the question at ingress, so nothing downstream
    should ever hold the raw values. This is the second lock: every string field
    is scrubbed of the values redact.py found, and the serialised line is checked
    for them once more. A match after scrubbing refuses the write outright —
    a lost trace is recoverable, a claimant's name on disk is not.
    """
    patterns = [
        re.compile(rf"(?<![\w'’-]){re.escape(value)}(?![\w-])") for value in pii_values if value
    ]
    scrubbed = _scrub(record, patterns)
    # True means a raw value got past ingress redaction into some field. It was
    # caught, but it is a bug upstream and should read as one.
    guard_caught = scrubbed != record
    scrubbed.setdefault("input", {})["guard_scrubbed"] = guard_caught

    line = json.dumps(scrubbed, ensure_ascii=False)
    leaked = [p.pattern for p in patterns if p.search(line)]
    if leaked:
        raise RuntimeError(f"refusing to write trace {record.get('trace_id')}: PII survived scrubbing")

    path = Path(path or config.TRACE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    return scrubbed


# --- Reading -----------------------------------------------------------------


def load_traces(path=None):
    path = Path(path or config.TRACE_PATH)
    if not path.exists():
        raise SystemExit(f"No trace file at {path}.")
    traces = []
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if line.strip():
                record = json.loads(line)
                record["_line"] = number
                traces.append(record)
    return traces


def find_trace(traces, trace_id):
    matches = [t for t in traces if t["trace_id"].startswith(trace_id)]
    if len(matches) != 1:
        raise SystemExit(f"trace id '{trace_id}' matches {len(matches)} traces")
    return matches[0]
