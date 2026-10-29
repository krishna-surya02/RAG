"""Slice the Week-11 request logs. Read-only.

    python logq.py --day yesterday --by hour                  # where's the traffic?
    python logq.py --day yesterday --call covered             # every "covered" answer
    python logq.py --day yesterday --input-type loss_question --user adj-04
    python logq.py --day yesterday --cost-outlier 2           # > mean + 2 sd
    python logq.py --grep "sump"                              # question or answer text
    python logq.py --show 3fa2c1 --json > trace.json          # one request, full spans

Each row: time, user, input type, prompt version, the answer's call, cost,
latency, and the opening of the question and the answer. Filters combine (AND).
The slices are the ones a vague complaint gives you something to work with:
when (time), who (user), which prompt (prompt version), what kind of question
(input type), and what it cost (cost outlier) — plus what the answer concluded,
which is the one fact every coverage complaint does carry.
"""

import argparse
import datetime
import json
import statistics
from collections import Counter

import config
import tracing


def _day_bounds(spec):
    today = datetime.datetime.now(datetime.timezone.utc).date()
    if spec == "today":
        day = today
    elif spec == "yesterday":
        day = today - datetime.timedelta(days=1)
    else:
        day = datetime.date.fromisoformat(spec)
    start = datetime.datetime.combine(day, datetime.time(), datetime.timezone.utc)
    return start, start + datetime.timedelta(days=1)


def _ts(record):
    return datetime.datetime.fromisoformat(record["ts"])


def _gen_ms(record):
    return (record.get("latency_ms") or {}).get("generation")


def _total_ms(record):
    return round(sum(s["latency_ms"] for s in record.get("spans") or []), 1)


def _one_line(text, width):
    text = " ".join((text or "").split())
    return text if len(text) <= width else text[: width - 1] + "…"


def select(traces, args):
    rows = traces
    if args.day:
        start, end = _day_bounds(args.day)
        rows = [t for t in rows if start <= _ts(t) < end]
    if args.since:
        rows = [t for t in rows if _ts(t) >= datetime.datetime.fromisoformat(args.since)]
    if args.until:
        rows = [t for t in rows if _ts(t) < datetime.datetime.fromisoformat(args.until)]
    if args.user:
        rows = [t for t in rows if t.get("user") == args.user]
    if args.prompt_version:
        rows = [t for t in rows if (t.get("prompt") or {}).get("version") == args.prompt_version]
    if args.input_type:
        rows = [t for t in rows if t.get("input_type") == args.input_type]
    if args.call:
        rows = [t for t in rows if t.get("answer_call") == args.call]
    if args.source:
        rows = [t for t in rows if t.get("source") == args.source]
    if args.grep:
        needle = args.grep.lower()
        rows = [
            t for t in rows
            if needle in t["input"]["question"].lower()
            or needle in ((t.get("output") or {}).get("final") or "").lower()
        ]
    if args.cost_outlier is not None:
        costs = [t.get("cost_usd") or 0 for t in rows]
        if len(costs) > 1:
            cut = statistics.mean(costs) + args.cost_outlier * statistics.pstdev(costs)
            rows = [t for t in rows if (t.get("cost_usd") or 0) > cut]
    return rows


def print_table(rows):
    print(f"{'trace':<12} {'time (UTC)':<19} {'user':<7} {'input_type':<17} {'prompt':<10} "
          f"{'call':<8} {'cost $':>9} {'ms':>7}  question | answer")
    for t in rows:
        answer = (t.get("output") or {}).get("final") or t.get("error", "")
        print(
            f"{t['trace_id'][:12]:<12} {t['ts'][:19]:<19} {t.get('user') or '-':<7} "
            f"{t.get('input_type') or '-':<17} {(t.get('prompt') or {}).get('version', '-'):<10} "
            f"{t.get('answer_call') or '-':<8} {t.get('cost_usd') or 0:>9.6f} {_total_ms(t):>7.0f}  "
            f"{_one_line(t['input']['question'], 70)} | {_one_line(answer, 70)}"
        )
    print(f"\n{len(rows)} rows")


def print_groups(rows, by):
    key = {
        "user": lambda t: t.get("user") or "-",
        "input_type": lambda t: t.get("input_type") or "-",
        "prompt_version": lambda t: (t.get("prompt") or {}).get("version", "-"),
        "call": lambda t: t.get("answer_call") or "-",
        "hour": lambda t: t["ts"][:13] + ":00",
    }[by]
    groups = {}
    for t in rows:
        groups.setdefault(key(t), []).append(t)
    print(f"{by:<20} {'n':>4} {'covered':>8} {'mean $':>10} {'p95 ms':>8}")
    for name in sorted(groups):
        g = groups[name]
        ms = sorted(_total_ms(t) for t in g)
        p95 = ms[min(len(ms) - 1, int(round(0.95 * (len(ms) - 1))))]
        covered = sum(1 for t in g if t.get("answer_call") == "covered")
        mean = statistics.mean(t.get("cost_usd") or 0 for t in g)
        print(f"{name:<20} {len(g):>4} {covered:>8} {mean:>10.6f} {p95:>8.0f}")
    print(f"\n{len(rows)} rows, calls: {dict(Counter(t.get('answer_call') for t in rows))}")


def trace_view(t):
    """The drill's trace.json: per-span latency, tokens and cost, the prompt
    version, and the context ids the answer was built from."""
    return {
        "trace_id": t["trace_id"],
        "ts": t["ts"],
        "user": t.get("user"),
        "source": t.get("source"),
        "input_type": t.get("input_type"),
        "question": t["input"]["question"],
        "answer_call": t.get("answer_call"),
        "answer": (t.get("output") or {}).get("final"),
        "prompt_version": (t.get("prompt") or {}).get("version"),
        "prompt_template_sha256": (t.get("prompt") or {}).get("template_sha256"),
        "model": (t.get("model") or {}).get("name"),
        "spans": t.get("spans"),
        "total_latency_ms": _total_ms(t),
        "total_tokens": sum(s["prompt_tokens"] + s["completion_tokens"] for s in t.get("spans") or []),
        "cost_usd": t.get("cost_usd"),
        "retrieval": {
            "mode": (t.get("retrieval") or {}).get("mode"),
            "k": (t.get("retrieval") or {}).get("k"),
            "context_ids": [
                {key: hit[key] for key in ("rank", "chunk_id", "score", "source_file", "page")}
                for hit in (t.get("retrieval") or {}).get("hits", [])
            ],
        },
        "app": t.get("app"),
        "error": t.get("error"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--traces", default=None, help="log file (default TRACE_PATH)")
    parser.add_argument("--day", help="today | yesterday | YYYY-MM-DD (UTC)")
    parser.add_argument("--since", help="ISO timestamp with offset, e.g. 2026-10-27T09:00+00:00")
    parser.add_argument("--until")
    parser.add_argument("--user")
    parser.add_argument("--prompt-version")
    parser.add_argument("--input-type")
    parser.add_argument("--call", choices=["covered", "excluded", "no_call", "other"])
    parser.add_argument("--source")
    parser.add_argument("--grep")
    parser.add_argument("--cost-outlier", type=float, metavar="Z", help="keep rows above mean + Z*sd")
    parser.add_argument("--by", choices=["user", "input_type", "prompt_version", "call", "hour"])
    parser.add_argument("--show", metavar="TRACE_ID")
    parser.add_argument("--json", action="store_true", help="with --show: the trace.json view, not the raw line")
    args = parser.parse_args()

    traces = tracing.load_traces(args.traces or config.TRACE_PATH)
    if args.show:
        t = tracing.find_trace(traces, args.show)
        if args.json:
            print(json.dumps(trace_view(t), indent=2, ensure_ascii=False))
        else:
            print(json.dumps(t, indent=2, ensure_ascii=False))
        return

    rows = select(traces, args)
    if args.by:
        print_groups(rows, args.by)
    else:
        print_table(rows)


if __name__ == "__main__":
    main()
