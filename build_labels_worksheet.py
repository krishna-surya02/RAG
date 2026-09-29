"""Draw a seeded sample of real claim summaries and write a blank worksheet
for a blind hand-labeling pass — no judge output, no gold answer, nothing but
the notes and the summary the model actually wrote.

    python build_labels_worksheet.py --seed 20260923 --n 25 \\
        --traces traces/summary_traces.jsonl --out labels_25.json

Same draw rule as sample_traces.py (sorted(trace_ids) -> random.Random(seed)
.sample(ids, n)), reused directly so this sample is re-derivable the same way
notes.md documents its own. This only builds the blank worksheet: every
`label` starts null. Week 6's brief requires the *filled-in* file to be
committed before any judge exists for this feature, so filling in `label`
(and, optionally, `note`) is a manual step — see labels_25.json's own
`_instructions` field once this has run.
"""

import argparse
import json

import sample_traces
import tracing


def build(seed, n, traces_path):
    traces = tracing.load_traces(traces_path)
    digest, lines = sample_traces.file_fingerprint(traces_path)
    chosen = sample_traces.draw(traces, seed, n)
    by_id = {trace["trace_id"]: trace for trace in traces}

    cases = []
    for number, trace_id in enumerate(chosen, start=1):
        trace = by_id[trace_id]
        cases.append(
            {
                "id": f"s{number:02d}",
                "trace_id": trace_id,
                "line": trace["_line"],
                "notes": trace["input"]["notes"],
                "summary": trace["output"]["final"],
                "label": None,
                "note": "",
            }
        )

    return {
        "_about": (
            f"Blind hand-labeling worksheet for the claim-summary feature "
            f"(summarize.py). Drawn from {traces_path} with sha256 {digest}, "
            f"{lines} lines. Rule: sorted(trace_ids) -> "
            f"random.Random({seed}).sample(ids, {n})."
        ),
        "_criterion": (
            "For each case, read `notes` and `summary` only -- no judge output "
            "exists yet for this feature, and none is shown here. Set `label` "
            "to \"pass\" or \"fail\":\n"
            "  pass = the summary reaches the correct pay/deny call, on the "
            "correct policy edition, with a correct or absent exclusion basis, "
            "and states no fact that contradicts the notes.\n"
            "  fail = any of the above is wrong."
        ),
        "_instructions": (
            "Fill in every `label` (and, optionally, a short `note` on your "
            "reasoning -- useful later for picking few-shot examples). Then "
            "commit this file before any judge prompt for this feature is "
            "written -- the commit timestamp is the ordering proof Week 6 asks "
            "for."
        ),
        "seed": seed,
        "n": n,
        "source_trace_file": traces_path,
        "source_sha256": digest,
        "source_lines": lines,
        "cases": cases,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--n", type=int, default=25)
    parser.add_argument("--traces", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    payload = build(args.seed, args.n, args.traces)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    print(f"Wrote {len(payload['cases'])} blank cases to {args.out}")
    print(f"sha256 {payload['source_sha256']}  lines {payload['source_lines']}  seed {args.seed}")


if __name__ == "__main__":
    main()
