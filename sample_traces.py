"""Draw a seeded random sample of traces, and read them.

    python sample_traces.py --seed 20260918 --n 20           # the sample list
    python sample_traces.py --seed 20260918 --n 20 --show    # and a reading view
    python sample_traces.py --trace-id 3f2a --show           # one trace

The rule is fixed so anyone can re-derive the list from the trace file: take
every trace_id, sort ascending, then random.Random(seed).sample(ids, n). The
file's sha256 and line count are printed with it — the same seed on a different
file is a different sample, and that should be visible.
"""

import argparse
import hashlib
import random
import textwrap
from pathlib import Path

import config
import retrieval
import tracing
from inspect_view import find_identifiers, snippet, token_presence


def draw(traces, seed, n):
    ids = sorted(trace["trace_id"] for trace in traces)
    return random.Random(seed).sample(ids, n)


def file_fingerprint(path):
    data = Path(path).read_bytes()
    return hashlib.sha256(data).hexdigest(), data.count(b"\n")


def show(trace, index, reasoning=False):
    """Everything needed to judge one answer on one screen: the question, the
    chunks the model was given and whether each carries the identifiers asked
    about, and what the model said."""
    question = trace["input"]["question"]
    tokens = find_identifiers(question)
    out = [
        "=" * 100,
        f"trace {trace['trace_id']}   line {trace['_line']}   {trace['ts']}   source={trace['source']}",
        "",
        "QUESTION (redacted):",
        textwrap.indent(textwrap.fill(question, 96), "  "),
        f"  identifiers: {', '.join(tokens) if tokens else '(none)'}",
        "",
        "RETRIEVED (what the model was given):",
    ]
    for hit in trace.get("retrieval", {}).get("hits", []):
        record = index.record(hit["chunk_id"])
        text = record["text"] if record else ""
        carries = token_presence(text, tokens) if tokens else {}
        marks = " ".join(f"{t}={s}" for t, s in carries.items() if s != "absent")
        out.append(
            f"  {hit['rank']}. {hit['score']:.4f}  {hit['chunk_id'][:12]}  "
            f"{hit['source_file']} p{hit['page']}  {marks}"
        )
        out.append(textwrap.indent(textwrap.fill(snippet(text, tokens, width=220), 92), "       "))
    if trace.get("error"):
        out += ["", f"ERROR: {trace['error']}"]
    if trace.get("output"):
        out += ["", "ANSWER:", textwrap.indent(trace["output"]["final"], "  ")]
        if reasoning and trace["output"].get("reasoning"):
            out += ["", "REASONING:", textwrap.indent(textwrap.fill(trace["output"]["reasoning"], 96), "  ")]
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--n", type=int, default=20)
    parser.add_argument("--trace-id", help="show one trace instead of sampling")
    parser.add_argument("--traces", default=None, help="trace file (default TRACE_PATH)")
    parser.add_argument("--show", action="store_true", help="print a reading view per trace")
    parser.add_argument("--reasoning", action="store_true", help="include the model's reasoning")
    args = parser.parse_args()

    path = args.traces or config.TRACE_PATH
    traces = tracing.load_traces(path)

    if args.trace_id:
        chosen = [tracing.find_trace(traces, args.trace_id)["trace_id"]]
    else:
        if args.seed is None:
            parser.error("give --seed (and --n), or --trace-id")
        digest, lines = file_fingerprint(path)
        chosen = draw(traces, args.seed, args.n)
        print(f"trace file   {path}")
        print(f"sha256       {digest}")
        print(f"lines        {lines} ({len(traces)} traces)")
        print(f"rule         sorted(trace_ids) -> random.Random({args.seed}).sample(ids, {args.n})")
        print()
        by_id = {trace["trace_id"]: trace for trace in traces}
        for number, trace_id in enumerate(chosen, start=1):
            print(f"  {number:>2}. {trace_id}  (line {by_id[trace_id]['_line']})")

    if args.show:
        index = retrieval.build_index(quiet=True)
        by_id = {trace["trace_id"]: trace for trace in traces}
        for trace_id in chosen:
            print()
            print(show(by_id[trace_id], index, reasoning=args.reasoning))


if __name__ == "__main__":
    main()
