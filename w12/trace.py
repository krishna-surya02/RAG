"""One trace id from FNOL in to referral out, across the agent and MCP hops.

Weeks 7-11 each minted their own trace id, and minted it *after* the run, so
nothing could follow a claim from the agent into a tool server. Here the id is
minted once at ingress (triage.py), every unit of work is a span with its own
span_id and its parent's, and the MCP hop carries the context in the request's
`_meta.traceparent` (W3C shape: 00-<trace_id>-<span_id>-01). The server writes
its own spans under the same trace id, to its own file -- it is a separate
process -- and `triage.py trace <id>` joins the files back into one tree.

Every line goes through the same second lock as tracing.write_trace: string
fields are scrubbed of the PII values known for this request, and the
serialised line is checked once more. A surviving value refuses the write.
"""

import json
import os
import re
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import tracing

ROOT = Path(__file__).resolve().parent.parent


def trace_dir():
    """W12_TRACE_DIR lets an eval run keep its spans apart from live traffic.
    Passed to MCP server subprocesses explicitly (see agent.server_config)."""
    return Path(os.getenv("W12_TRACE_DIR") or ROOT / "traces")


def spans_path():
    return trace_dir() / "w12_spans.jsonl"


def server_spans_path():
    return trace_dir() / "w12_mcp.jsonl"


def runs_path():
    return trace_dir() / "w12_runs.jsonl"


def new_span_id():
    return uuid.uuid4().hex[:16]


def traceparent(trace_id, span_id):
    return f"00-{trace_id}-{span_id}-01"


def parse_traceparent(value):
    m = re.fullmatch(r"00-([0-9a-f]{32})-([0-9a-f]{16})-0[01]", value or "")
    return (m.group(1), m.group(2)) if m else (None, None)


class PiiLeak(RuntimeError):
    pass


def _patterns(values):
    return [re.compile(rf"(?<![\w'’-]){re.escape(v)}(?![\w-])") for v in values if v and len(v) >= 3]


def safe_line(record, pii_values=()):
    """Scrub, serialise, re-check. Returns (line, scrubbed_anything)."""
    patterns = _patterns(pii_values)
    scrubbed = tracing._scrub(record, patterns)
    line = json.dumps(scrubbed, ensure_ascii=False, default=str)
    if any(p.search(line) for p in patterns):
        raise PiiLeak(f"refusing to write {record.get('trace_id')}: PII survived scrubbing")
    return line, scrubbed != record


def append(path, record, pii_values=()):
    line, caught = safe_line(record, pii_values)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    return caught


class Tracer:
    """Collects spans for one trace. Spans are written as they close, so a
    crash mid-run still leaves everything up to the crash on disk."""

    def __init__(self, trace_id=None, path=None, pii_values=(), service="triage"):
        self.trace_id = trace_id or tracing.new_trace_id()
        self.path = Path(path) if path else spans_path()
        self.pii_values = list(pii_values)
        self.service = service
        self.spans = []
        self.guard_caught = 0
        self._stack = []

    def add_pii(self, values):
        self.pii_values.extend(v for v in values if v)

    @property
    def current(self):
        return self._stack[-1] if self._stack else None

    @contextmanager
    def span(self, name, kind, parent_id=None, **attrs):
        span = {
            "trace_id": self.trace_id,
            "span_id": new_span_id(),
            "parent_id": parent_id if parent_id is not None else (self.current or {}).get("span_id"),
            "service": self.service,
            "name": name,
            "kind": kind,
            "start": tracing.now_utc(),
            "attrs": attrs,
            "status": "ok",
        }
        t0 = time.perf_counter()
        self._stack.append(span)
        try:
            yield span
        except Exception as exc:
            span["status"] = "error"
            span["error"] = f"{type(exc).__name__}: {exc}"[:300]
            raise
        finally:
            self._stack.pop()
            span["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            span.setdefault("prompt_tokens", 0)
            span.setdefault("completion_tokens", 0)
            span["cost_usd"] = tracing.cost_usd(span["prompt_tokens"], span["completion_tokens"], span.get("model"))
            self.spans.append(span)
            self.guard_caught += append(self.path, span, self.pii_values)

    def totals(self):
        own = [s for s in self.spans if s["trace_id"] == self.trace_id]
        return {
            "cost_usd": round(sum(s["cost_usd"] for s in own), 8),
            "prompt_tokens": sum(s["prompt_tokens"] for s in own),
            "completion_tokens": sum(s["completion_tokens"] for s in own),
            "llm_calls": sum(s["kind"] == "llm" for s in own),
        }


def server_tracer(ctx, service, tool, args):
    """Tracer for one MCP tool call, continuing the caller's trace when the
    request carries _meta.traceparent and starting a fresh one when it doesn't.
    Returns (tracer, parent_span_id, span_attrs)."""
    meta = {}
    try:
        meta = dict(ctx.request_context.meta or {})
    except Exception:
        pass
    trace_id, parent = parse_traceparent(meta.get("traceparent"))
    tracer = Tracer(trace_id=trace_id, path=server_spans_path(), service=service)
    return tracer, parent, {"tool": tool, "args": args, "trace_propagated": trace_id is not None}


# --- Reading ------------------------------------------------------------------


def _load(path):
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def load_trace(trace_id, directory=None):
    """Every span and run record carrying this trace id (prefix ok), from the
    client and server files, plus the run summary."""
    d = Path(directory) if directory else trace_dir()
    spans = [s for f in ("w12_spans.jsonl", "w12_mcp.jsonl") for s in _load(d / f)
             if s.get("trace_id", "").startswith(trace_id)]
    runs = [r for r in _load(d / "w12_runs.jsonl") if r.get("trace_id", "").startswith(trace_id)]
    return spans, runs


def render_tree(spans):
    """Indented span tree with latency and cost per span."""
    by_parent = {}
    ids = {s["span_id"] for s in spans}
    for s in sorted(spans, key=lambda s: s["start"]):
        parent = s.get("parent_id") if s.get("parent_id") in ids else None
        by_parent.setdefault(parent, []).append(s)
    lines = []

    def walk(parent, depth):
        for s in by_parent.get(parent, []):
            tok = f" tok={s['prompt_tokens']}/{s['completion_tokens']}" if s["prompt_tokens"] else ""
            lines.append(f"{'  ' * depth}{s['service']}:{s['name']} [{s['kind']}] "
                         f"{s['latency_ms']:.0f}ms ${s['cost_usd']:.6f}{tok}"
                         f"{'' if s['status'] == 'ok' else ' ' + s['status'].upper()}")
            walk(s["span_id"], depth + 1)

    walk(None, 0)
    return "\n".join(lines)
