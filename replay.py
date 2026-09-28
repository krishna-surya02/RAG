"""Replay one trace from the trace line alone, and show original against replay.

    python replay.py --seed 918                 # pick one trace at random, seeded
    python replay.py --trace-id df307053cbb0    # or name one
    python replay.py --seed 918 --no-generate   # prompt and retrieval checks only

Three checks, each answering "could this answer be reconstructed?":

  prompt      rebuild the prompt from prompt.version + the redacted question +
              the chunk ids (text looked up in the index), and compare it byte
              for byte with the prompt the trace says was sent
  retrieval   re-run retrieval on the traced question and compare chunk ids
              and scores, and the index key they were computed against
  generation  send the traced prompt to the traced model with the traced
              parameters and seed — the trace's, not today's config — and put
              the two outputs side by side

The random pick uses the same rule as sample_traces.py: sort every trace_id,
then random.Random(seed).
"""

import argparse
import difflib
import random
from pathlib import Path

from langchain_groq import ChatGroq

import config
import rag
import retrieval
import tracing

SCORE_TOLERANCE = 1e-5


def pick(traces, seed):
    ids = sorted(trace["trace_id"] for trace in traces)
    return random.Random(seed).sample(ids, 1)[0]


def check_prompt(trace, index):
    """Is (prompt version, question, chunk ids) enough to rebuild the prompt?"""
    version = trace["prompt"]["version"]
    if version != rag.PROMPT_VERSION or trace["prompt"]["template_sha256"] != rag.PROMPT_SHA256:
        return False, f"template {version} is not the one in this checkout; cannot re-render"

    hits = []
    for hit in trace["retrieval"]["hits"]:
        record = index.record(hit["chunk_id"])
        if record is None:
            return False, f"chunk {hit['chunk_id'][:12]} is not in the current index"
        hits.append(retrieval._hit_from_record(record, hit["score"], hit["rank"]))

    rebuilt = rag.PROMPT.format(
        context=retrieval.format_hits(hits), question=trace["input"]["question"]
    )
    same = rebuilt == trace["prompt"]["rendered"]
    return same, "byte-identical" if same else "differs from the traced prompt"


def check_retrieval(trace, index):
    traced = trace["retrieval"]
    hits = retrieval.retrieve(
        trace["input"]["question"],
        k=traced["k"],
        candidates=traced["candidates"],
        mode=traced["mode"],
        backend=traced["backend"],
    )
    rows = []
    for old, new in zip(traced["hits"], hits):
        rows.append(
            {
                "rank": old["rank"],
                "traced": old["chunk_id"][:12],
                "replayed": new.chunk_id[:12],
                "traced_score": old["score"],
                "replayed_score": round(float(new.score), 6),
                "same": old["chunk_id"] == new.chunk_id
                and abs(old["score"] - float(new.score)) <= SCORE_TOLERANCE,
            }
        )
    same_key = traced["index_key"] == retrieval._cache_key()
    return all(row["same"] for row in rows) and len(hits) == len(traced["hits"]), same_key, rows


def generate(trace):
    """Call the model exactly as the trace says it was called."""
    params = trace["model"]
    llm = ChatGroq(
        model=params["name"],
        api_key=config.GROQ_API_KEY,
        temperature=params["temperature"],
        max_tokens=params["max_tokens"],
        reasoning_effort=params["reasoning_effort"],
        reasoning_format=params["reasoning_format"],
        timeout=params["timeout"],
        max_retries=params["max_retries"],
    )
    bound = llm.bind(seed=params["seed"]) if params.get("seed") is not None else llm
    message = bound.invoke(trace["prompt"]["rendered"])
    return tracing.output_block(message, rag.strip_think(message.content))


def report(trace, prompt_check, retrieval_check, replayed, seed):
    lines = [f"# Replay of trace `{trace['trace_id']}`", ""]
    if seed is not None:
        lines += [
            f"Picked with `python replay.py --seed {seed}`: every trace_id sorted, then "
            f"`random.Random({seed}).sample(ids, 1)`.",
            "",
        ]
    lines += [
        f"- traced at {trace['ts']}, app commit `{(trace['app']['git_commit'] or '?')[:12]}`",
        f"- question (redacted at ingress): {trace['input']['question']}",
        f"- prompt `{trace['prompt']['version']}` sha256 `{trace['prompt']['template_sha256'][:12]}`",
        f"- model `{trace['model']['name']}` T={trace['model']['temperature']} "
        f"seed={trace['model']['seed']} max_tokens={trace['model']['max_tokens']} "
        f"reasoning_effort={trace['model']['reasoning_effort']}",
        "",
        "## Prompt reconstruction",
        "",
        f"Rebuilt from version + question + chunk ids: **{prompt_check[1]}**",
        "",
        "## Retrieval replay",
        "",
    ]
    same, same_key, rows = retrieval_check
    lines += [
        f"Index key traced `{trace['retrieval']['index_key']}`, current `{retrieval._cache_key()}` "
        f"({'same' if same_key else 'DIFFERENT'}). Ranking identical: **{same}**",
        "",
        "| rank | traced chunk | replayed chunk | traced score | replayed score | same |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['rank']} | `{row['traced']}` | `{row['replayed']}` | {row['traced_score']} "
            f"| {row['replayed_score']} | {'yes' if row['same'] else 'NO'} |"
        )

    if replayed is not None:
        original = trace["output"]["final"]
        again = replayed["final"]
        ratio = difflib.SequenceMatcher(None, original, again).ratio()
        lines += [
            "",
            "## Generation replay",
            "",
            f"Exact match: **{original == again}** · character similarity {ratio:.3f} · "
            f"fingerprint traced `{trace['output']['system_fingerprint']}`, "
            f"replayed `{replayed['system_fingerprint']}` · tokens traced "
            f"{trace['output']['token_usage']['total_tokens']}, replayed "
            f"{replayed['token_usage']['total_tokens']}",
            "",
            "| original (from trace) | replayed |",
            "|---|---|",
        ]
        left, right = original.splitlines(), again.splitlines()
        for i in range(max(len(left), len(right))):
            cell = lambda rows: (rows[i] if i < len(rows) else "").replace("|", "\\|")
            lines.append(f"| {cell(left)} | {cell(right)} |")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--seed", type=int, help="pick one trace at random with this seed")
    group.add_argument("--trace-id", help="replay this trace (a unique prefix is enough)")
    parser.add_argument("--traces", default=None, help="trace file (default TRACE_PATH)")
    parser.add_argument("--no-generate", action="store_true", help="skip the model call")
    parser.add_argument("--out", default="replay_out")
    args = parser.parse_args()

    traces = tracing.load_traces(args.traces)
    trace_id = pick(traces, args.seed) if args.seed is not None else args.trace_id
    trace = tracing.find_trace(traces, trace_id)
    if trace.get("error"):
        print(f"note: this trace recorded an error: {trace['error']}")

    index = retrieval.build_index(quiet=True)
    prompt_check = check_prompt(trace, index)
    retrieval_check = check_retrieval(trace, index)
    replayed = None
    if not args.no_generate and trace.get("output"):
        config.preflight()
        replayed = generate(trace)

    text = report(trace, prompt_check, retrieval_check, replayed, args.seed)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{trace['trace_id']}.md").write_text(text, encoding="utf-8")
    print(text)
    print(f"Wrote {out / (trace['trace_id'] + '.md')}")


if __name__ == "__main__":
    main()
