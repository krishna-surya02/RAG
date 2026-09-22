"""Measure hit-rate@3 and p50 retrieval latency over the golden set.

    python evaluate.py                          # current mode from config
    python evaluate.py --mode dense --label before
    python evaluate.py --compare eval_out/before.json eval_out/after.json

Every run writes JSON and markdown to eval_out/, so a before and an after can be
diffed question by question rather than compared as two headline numbers. The
questions and gold ids come from goldenset.json and are never touched by a run,
which is what makes the two runs comparable at all.
"""

import argparse
import json
import statistics
import time
from pathlib import Path

import config
import retrieval
from inspect_view import find_identifiers, resolve_gold, token_presence

HIT_AT = 3


def load_questions(path):
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload["questions"]


def measure(questions, k, candidates, mode, repeats):
    """Rank once for correctness, then re-rank repeatedly for timing.

    Timing wraps the retrieval call only. The corpus embed happens before the
    clock starts, and generation is excluded — this change is a retrieval
    change, and folding a variable network call to Groq into the number would
    hide whatever the retriever actually costs.
    """
    index = retrieval.build_index(quiet=True)

    # Warm the embedding model and the caches before anything is timed.
    retrieval.retrieve(questions[0]["question"], k=k, candidates=candidates, mode=mode)

    rows = []
    for entry in questions:
        question = entry["question"]
        gold_id, resolved_by = resolve_gold(entry, index)
        hits = retrieval.retrieve(question, k=candidates, candidates=candidates, mode=mode)

        rank = next((hit.rank for hit in hits if hit.chunk_id == gold_id), None)
        tokens = entry.get("exact_tokens") or find_identifiers(question)

        samples = []
        for _ in range(repeats):
            start = time.perf_counter()
            retrieval.retrieve(question, k=k, candidates=candidates, mode=mode)
            samples.append((time.perf_counter() - start) * 1000.0)

        rows.append(
            {
                "id": entry["id"],
                "question": question,
                "exact_tokens": tokens,
                "gold_chunk_id": gold_id,
                "gold_resolved_by": resolved_by,
                "gold_rank": rank,
                f"hit@{HIT_AT}": bool(rank and rank <= HIT_AT),
                f"recall@{candidates}": bool(rank),
                "top_k_ids": [hit.chunk_id for hit in hits[:k]],
                "top_k_locators": [hit.locator() for hit in hits[:k]],
                "top_k_carries_token": [
                    any(state == "exact" for state in token_presence(hit.text, tokens).values())
                    for hit in hits[:k]
                ],
                "latency_ms_median": round(statistics.median(samples), 2),
            }
        )
    return rows


def summarise(rows, k, candidates, mode, repeats):
    total = len(rows)
    hits = sum(1 for row in rows if row[f"hit@{HIT_AT}"])
    recalled = sum(1 for row in rows if row[f"recall@{candidates}"])
    latencies = [row["latency_ms_median"] for row in rows]

    # The decision rule, computed from the misses. A reranker can only reorder
    # what was already fetched, so a gold chunk that never appears in the
    # candidate pool is beyond its reach no matter how good it is.
    misses = [row for row in rows if not row[f"hit@{HIT_AT}"] and row["gold_chunk_id"]]
    ceiling = [row["id"] for row in misses if row["gold_rank"] is None]
    misranked = [row["id"] for row in misses if row["gold_rank"] is not None]
    unresolved = [row["id"] for row in rows if not row["gold_chunk_id"]]

    return {
        "mode": mode,
        "backend": config.RETRIEVAL_BACKEND,
        "k": k,
        "candidates": candidates,
        "repeats": repeats,
        "questions": total,
        f"hit@{HIT_AT}": f"{hits}/{total}",
        f"hit@{HIT_AT}_pct": round(100.0 * hits / total, 1) if total else 0.0,
        f"recall@{candidates}": f"{recalled}/{total}",
        "p50_latency_ms": round(statistics.median(latencies), 2) if latencies else None,
        "p95_latency_ms": (
            round(sorted(latencies)[max(0, int(0.95 * len(latencies)) - 1)], 2)
            if latencies
            else None
        ),
        "misses_recall_ceiling": ceiling,
        "misses_misranked": misranked,
        "gold_unresolved": unresolved,
    }


def decision(summary):
    """The rule, fixed before the numbers existed, so the choice of change
    cannot be reverse-engineered from the result it produces."""
    ceiling = len(summary["misses_recall_ceiling"])
    misranked = len(summary["misses_misranked"])
    total = ceiling + misranked
    if total == 0:
        return "no retrieval failures to fix", None
    if ceiling * 2 >= total:
        return (
            f"{ceiling}/{total} retrieval misses never fetched the gold chunk at all, "
            "so a reranker cannot reach them",
            "bm25_rrf",
        )
    return (
        f"{misranked}/{total} retrieval misses fetched the gold chunk and ranked it "
        "below the cut, which is a ranking problem",
        "rerank",
    )


def to_markdown(summary, rows):
    lines = [
        f"### {summary['mode']} — hit@{HIT_AT} {summary[f'hit@{HIT_AT}']} "
        f"({summary[f'hit@{HIT_AT}_pct']}%), p50 {summary['p50_latency_ms']} ms",
        "",
        f"backend `{summary['backend']}`, k={summary['k']}, candidates={summary['candidates']}, "
        f"{summary['repeats']} timed repeats per question",
        "",
        "| id | question | exact token | gold chunk | gold rank | hit@3 |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        tokens = ", ".join(row["exact_tokens"]) or "—"
        gold = row["gold_chunk_id"][:12] if row["gold_chunk_id"] else "unresolved"
        rank = row["gold_rank"] if row["gold_rank"] is not None else f">{summary['candidates']}"
        mark = "yes" if row[f"hit@{HIT_AT}"] else "NO"
        question = row["question"].replace("|", "\\|")
        lines.append(f"| {row['id']} | {question} | {tokens} | `{gold}` | {rank} | {mark} |")
    return "\n".join(lines)


def compare(before_path, after_path):
    before = json.loads(Path(before_path).read_text(encoding="utf-8"))
    after = json.loads(Path(after_path).read_text(encoding="utf-8"))

    by_id = {row["id"]: row for row in after["rows"]}
    mismatched = [
        row["id"]
        for row in before["rows"]
        if by_id.get(row["id"], {}).get("gold_chunk_id") != row["gold_chunk_id"]
    ]
    if mismatched:
        print(f"WARNING: gold chunk ids differ between runs for: {', '.join(mismatched)}")
        print("The two runs are not comparable. Rebuild the index and re-run both.\n")

    lines = [
        "| id | exact token | before rank | after rank | before | after | outcome |",
        "|---|---|---|---|---|---|---|",
    ]
    counts = {"fixed": 0, "unchanged pass": 0, "still broken": 0, "regressed": 0}
    for row in before["rows"]:
        post = by_id.get(row["id"])
        if not post:
            continue
        was, now = row[f"hit@{HIT_AT}"], post[f"hit@{HIT_AT}"]
        outcome = (
            "fixed" if not was and now
            else "regressed" if was and not now
            else "unchanged pass" if was
            else "still broken"
        )
        counts[outcome] += 1
        fmt = lambda r: r if r is not None else "miss"
        lines.append(
            f"| {row['id']} | {', '.join(row['exact_tokens']) or '—'} | "
            f"{fmt(row['gold_rank'])} | {fmt(post['gold_rank'])} | "
            f"{'yes' if was else 'NO'} | {'yes' if now else 'NO'} | {outcome} |"
        )

    print("\n".join(lines))
    print()
    print(
        f"hit@{HIT_AT}: {before['summary'][f'hit@{HIT_AT}']} -> {after['summary'][f'hit@{HIT_AT}']}"
    )
    print(
        f"p50 retrieval latency: {before['summary']['p50_latency_ms']} ms -> "
        f"{after['summary']['p50_latency_ms']} ms"
    )
    print("outcomes: " + ", ".join(f"{name} {count}" for name, count in counts.items()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--goldenset", default="goldenset.json")
    parser.add_argument("--mode", default=None, help="retrieval mode (default from config)")
    parser.add_argument("--k", type=int, default=HIT_AT, help="chunks the model sees")
    parser.add_argument("--candidates", type=int, default=None)
    # Wall-clock retrieval is noisy enough that 5 samples move the median by
    # tens of percent between runs. 9 is still fast and much steadier.
    parser.add_argument("--repeats", type=int, default=9, help="timed repeats per question")
    parser.add_argument("--label", default=None, help="output filename stem, e.g. before")
    parser.add_argument("--out", default="eval_out")
    parser.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"))
    args = parser.parse_args()

    if args.compare:
        compare(*args.compare)
        return

    mode = args.mode or config.RETRIEVAL_MODE
    candidates = args.candidates or config.CANDIDATE_K
    questions = load_questions(args.goldenset)
    if not questions:
        raise SystemExit(
            f"{args.goldenset} has no questions yet.\n"
            "Build the golden set first: put the policy PDFs in PDF_DIR, then use\n"
            '  python inspect_view.py --find "<phrase from the clause>"\n'
            "to get the chunk id for each question's known-correct answer."
        )

    rows = measure(questions, args.k, candidates, mode, args.repeats)
    summary = summarise(rows, args.k, candidates, mode, args.repeats)
    rationale, choice = decision(summary)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = args.label or mode
    payload = {"summary": summary, "rows": rows, "decision": {"rationale": rationale, "choice": choice}}
    (out_dir / f"{stem}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (out_dir / f"{stem}.md").write_text(to_markdown(summary, rows), encoding="utf-8")

    print(to_markdown(summary, rows))
    print()
    print(f"recall@{candidates}: {summary[f'recall@{candidates}']}")
    print(f"p50 retrieval latency: {summary['p50_latency_ms']} ms "
          f"(p95 {summary['p95_latency_ms']} ms)")
    if summary["gold_unresolved"]:
        print(f"UNRESOLVED gold chunks: {', '.join(summary['gold_unresolved'])}")
    print()
    print("Miss breakdown")
    print(f"  never fetched (gold outside top {candidates}): "
          f"{', '.join(summary['misses_recall_ceiling']) or 'none'}")
    print(f"  fetched but ranked below {HIT_AT}: "
          f"{', '.join(summary['misses_misranked']) or 'none'}")
    print(f"  rule says: {rationale} -> {choice}")
    print(f"\nWrote {out_dir / (stem + '.json')} and {out_dir / (stem + '.md')}")


if __name__ == "__main__":
    main()
