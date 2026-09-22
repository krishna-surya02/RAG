"""Show what retrieval actually fetched for one question, and why it ranked.

    python inspect_view.py "does exclusion E-17 apply under form HO-0304 ed. 03-24"
    python inspect_view.py --question q03 --answer
    python inspect_view.py "..." --gold <chunk_id> --candidates 25 --json

A wrong answer has three very different causes and they need different fixes:

  R   retrieval never fetched the right chunk, so no model could have cited it
  G   the right chunk was in the context and the model answered from it wrongly
  N   nothing in the corpus answers the question

Reading the answer alone cannot separate these — a confident paragraph about a
neighbouring exclusion looks the same either way. This view puts the retrieved
chunks, whether each carries the identifier that was asked about, where the
known-correct chunk ranked, and the model's answer on one screen, so the label
follows from evidence instead of impression.
"""

import argparse
import json
import re
import sys

import config
import retrieval

# Identifiers dense embeddings are structurally bad at: exclusion codes, form
# numbers, edition dates, endorsement numbers. An embedding places "E-17" next
# to "E-16" and "E-18" because they are near-identical strings in near-identical
# sentences, which is exactly the wrong neighbourhood for an exact-match lookup.
IDENTIFIER_RE = re.compile(
    r"\b(?:[A-Za-z]{1,6}[-‑ ]?\d{1,6}(?:[-/ ]\d{2,4})*|\d{2,4}-\d{2,4})\b"
)

SEPARATORS = r"[\s\-‑./]*"

# An answer that names the identifier only to report it missing is not citing it.
# Telling those apart matters: if the gold chunk was in the context and the model
# still said the identifier was not retrieved, that is the model misusing good
# context, not a retrieval failure.
DECLINE_RE = re.compile(
    r"(does not appear|do(es)? not (contain|include)|not (present|included|contained|found)"
    r"|no (provision|passage|clause|text) (labeled|labelled|carrying|with)"
    r"|not in the retrieved|cannot (confirm|locate|find)|could not (be )?(locate|found))",
    re.I,
)


def find_identifiers(text):
    """Pull the exact-match tokens out of a question, in order, deduplicated."""
    seen, out = set(), []
    for match in IDENTIFIER_RE.findall(text):
        token = match.strip()
        key = re.sub(r"[^a-z0-9]", "", token.lower())
        # A bare year or a one-digit token is not an identifier worth tracking.
        if len(key) < 3 or key.isalpha():
            continue
        if key not in seen:
            seen.add(key)
            out.append(token)
    return out


def _token_patterns(token):
    """Two regexes per token, because forms write the same id several ways.

    Strict joins the token's alphanumeric runs across any separators, so "E-17"
    finds "E 17" and "E17". Loose additionally allows separators between single
    characters, so "HO-0304" still finds "HO 03 04", which is how the number is
    printed on the form itself.
    """
    runs = re.findall(r"[A-Za-z]+|\d+", token)
    if not runs:
        return None, None
    strict = re.compile(r"\b" + SEPARATORS.join(map(re.escape, runs)) + r"\b", re.I)
    chars = [re.escape(c) for run in runs for c in run]
    loose = re.compile(r"\b" + SEPARATORS.join(chars) + r"\b", re.I)
    return strict, loose


def token_presence(text, tokens):
    """For each token: 'exact', 'loose' (spaced variant only), or 'absent'."""
    presence = {}
    for token in tokens:
        strict, loose = _token_patterns(token)
        if strict is None:
            presence[token] = "absent"
        elif strict.search(text):
            presence[token] = "exact"
        elif loose.search(text):
            presence[token] = "loose"
        else:
            presence[token] = "absent"
    return presence


def _highlight(text, tokens, use_color):
    for token in tokens:
        strict, _ = _token_patterns(token)
        if strict is None:
            continue
        replacement = "\033[7m\\g<0>\033[0m" if use_color else "»\\g<0>«"
        text = strict.sub(replacement, text)
    return text


def snippet(text, tokens, width=260):
    """Window the snippet onto the first identifier match when there is one, so
    the evidence is visible instead of buried past the cut."""
    flat = " ".join(text.split())
    start = 0
    for token in tokens:
        strict, _ = _token_patterns(token)
        match = strict.search(flat) if strict else None
        if match:
            start = max(0, match.start() - width // 3)
            break
    piece = flat[start : start + width]
    prefix = "..." if start else ""
    suffix = "..." if start + width < len(flat) else ""
    return prefix + piece + suffix


# --- Gold chunk resolution -------------------------------------------------


def load_goldenset(path="goldenset.json"):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)["questions"]
    except FileNotFoundError:
        return []


def resolve_gold(entry, index):
    """Find the gold chunk by id, falling back to its human-readable locator.

    Chunk ids are a hash of the text, so any change to chunk size silently
    invalidates every id in the golden set. Scoring that as a retrieval miss
    would be a lie about the retriever, so the locator is the safety net and a
    mismatch is reported rather than swallowed.
    """
    chunk_id = entry.get("gold_chunk_id")
    if chunk_id and index.record(chunk_id):
        return chunk_id, "id"

    locator = entry.get("gold_locator") or {}
    phrase = (locator.get("phrase") or "").strip()
    if not phrase:
        return None, "unresolved"

    needle = " ".join(phrase.split()).lower()
    matches = [
        record["chunk_id"]
        for record in index.records
        if (not locator.get("source_file") or record["source_file"] == locator["source_file"])
        and needle in " ".join(record["text"].split()).lower()
    ]
    if len(matches) == 1:
        return matches[0], "locator"
    if len(matches) > 1:
        return matches[0], "locator-ambiguous"
    return None, "unresolved"


def gold_verdict(gold_id, hits, k, candidates):
    """Where the known-correct chunk landed. This is the whole diagnosis.

    Absent from the candidate pool means a reranker cannot help: it only
    reorders what was already fetched. Present but below k means the chunk is
    being fetched and mis-ranked, which is what a reranker is for.
    """
    if not gold_id:
        return {"status": "unresolved", "rank": None, "rerankable": False}

    rank = next((hit.rank for hit in hits if hit.chunk_id == gold_id), None)
    if rank is None:
        return {"status": f"absent from top {candidates}", "rank": None, "rerankable": False}
    if rank <= k:
        return {"status": f"retrieved at rank {rank}", "rank": rank, "rerankable": True}
    return {"status": f"rank {rank}, below k={k}", "rank": rank, "rerankable": True}


# --- Rendering -------------------------------------------------------------


def render(report, use_color):
    lines = []
    lines.append(f"Question: {report['question']}")
    if report["question_id"]:
        lines.append(f"Golden set id: {report['question_id']}")
    lines.append(
        f"Retrieval: mode={report['mode']} backend={report['backend']} "
        f"k={report['k']} candidates={report['candidates']} corpus={report['corpus_chunks']} chunks"
    )
    tokens = report["identifiers"]
    lines.append(f"Exact tokens in question: {', '.join(tokens) if tokens else '(none)'}")
    lines.append("")

    lines.append(f"Top {report['k']} — this is what the model was given:")
    for hit in report["hits"][: report["k"]]:
        lines.append(_render_hit(hit, tokens, use_color, gold_id=report["gold_chunk_id"]))

    below = report["hits"][report["k"] :]
    if below:
        lines.append("")
        lines.append(f"Candidates {report['k'] + 1}..{len(report['hits'])} — fetched, not shown to the model:")
        for hit in below:
            marker = "  <-- GOLD" if hit["chunk_id"] == report["gold_chunk_id"] else ""
            carries = [t for t, state in hit["tokens"].items() if state != "absent"]
            lines.append(
                f"  {hit['rank']:>3}. {hit['score']:+.4f}  {hit['chunk_id'][:12]}  "
                f"{hit['locator']:<28} {'carries ' + ','.join(carries) if carries else ''}{marker}"
            )

    lines.append("")
    gold = report["gold"]
    if report["gold_resolved_by"] == "none":
        lines.append("Gold chunk: none given, so there is nothing to score against")
    else:
        lines.append(f"Gold chunk: {report['gold_chunk_id'] or '(unresolved)'} "
                     f"({report['gold_resolved_by']})")
        lines.append(f"Gold verdict: {gold['status']}")
    if report["gold_snippet"]:
        lines.append(f"Gold text: {report['gold_snippet']}")

    if report["answer"] is not None:
        lines.append("")
        lines.append("Answer:")
        for line in report["answer"].splitlines():
            lines.append(f"  {line}")
        lines.append("")
        lines.append(f"Answer names the asked identifier: {report['answer_mentions_identifier']}")
        lines.append(f"Answer reports it as not retrieved: {report['answer_reports_it_missing']}")

    lines.append("")
    lines.append(f"Suggested label: {report['suggested_label']}")
    lines.append(f"Evidence: {report['evidence']}")
    return "\n".join(lines)


def _render_hit(hit, tokens, use_color, gold_id):
    marker = "  <-- GOLD" if hit["chunk_id"] == gold_id else ""
    header = (
        f"  {hit['rank']:>3}. {hit['score']:+.4f}  {hit['chunk_id'][:12]}  "
        f"{hit['locator']}{marker}"
    )
    if tokens:
        states = ", ".join(f"{t}={state}" for t, state in hit["tokens"].items())
        header += f"\n       tokens: {states}"
    body = _highlight(hit["snippet"], tokens, use_color)
    return f"{header}\n       {body}"


# --- Main ------------------------------------------------------------------


def inspect(question, k, candidates, mode, gold_id=None, entry=None, want_answer=False):
    index = retrieval.build_index(quiet=True)
    tokens = find_identifiers(question)

    hits = retrieval.retrieve(question, k=candidates, candidates=candidates, mode=mode)

    resolved_by = "given" if gold_id else "none"
    if gold_id and not index.record(gold_id):
        # The report prints 12-character ids, so that is what people paste back.
        matches = [r["chunk_id"] for r in index.records if r["chunk_id"].startswith(gold_id)]
        if len(matches) != 1:
            sys.exit(f"--gold {gold_id} matches {len(matches)} chunks; give more characters.")
        gold_id = matches[0]
    if not gold_id and entry:
        gold_id, resolved_by = resolve_gold(entry, index)

    gold_record = index.record(gold_id) if gold_id else None
    verdict = gold_verdict(gold_id, hits, k, candidates)

    hit_dicts = []
    for hit in hits:
        data = hit.as_dict()
        data["locator"] = hit.locator()
        data["tokens"] = token_presence(hit.text, tokens)
        data["snippet"] = snippet(hit.text, tokens)
        data.pop("text")
        hit_dicts.append(data)

    answer = None
    mentions = None
    declines = None
    if want_answer:
        from rag import answer_with_context

        _, answer = answer_with_context(question, k=k)
        declines = bool(DECLINE_RE.search(answer))
        if tokens:
            presence = token_presence(answer, tokens)
            mentions = any(state == "exact" for state in presence.values())

    gold_in_context = bool(verdict["rank"] and verdict["rank"] <= k)
    label, evidence = _suggest_label(
        tokens, hit_dicts, k, candidates, gold_id, gold_in_context, verdict,
        answer, mentions, declines,
    )

    return {
        "question": question,
        "question_id": entry.get("id") if entry else None,
        "mode": mode,
        "backend": config.RETRIEVAL_BACKEND,
        "k": k,
        "candidates": candidates,
        "corpus_chunks": len(index),
        "identifiers": tokens,
        "hits": hit_dicts,
        "gold_chunk_id": gold_id,
        "gold_resolved_by": resolved_by,
        "gold": verdict,
        "gold_snippet": snippet(gold_record["text"], tokens) if gold_record else None,
        "answer": answer,
        "answer_mentions_identifier": mentions,
        "answer_reports_it_missing": declines,
        "suggested_label": label,
        "evidence": evidence,
    }


def _suggest_label(
    tokens, hits, k, candidates, gold_id, gold_in_context, verdict, answer, mentions, declines
):
    """Propose R / G / Not-In-Corpus and the one line of evidence behind it.

    Suggested, not decided: whether an answer is actually wrong is a judgement
    a person makes by reading it. What this settles mechanically is the half of
    the question that is not a judgement — whether the right chunk was there.
    """
    if gold_id is None:
        # No gold chunk means nobody said which chunk is correct, not that the
        # corpus lacks the answer. Not-In-Corpus is a finding a person makes
        # after --find turns up nothing; the tool must not infer it.
        return (
            "unlabelled — no gold chunk given",
            "pass --gold <chunk_id> or --question <id>; get the id with --find",
        )

    shown = hits[:k]

    if not gold_in_context:
        where = verdict["status"]
        detail = (
            f"gold {gold_id[:12]} was {where}; "
            f"top-{k} returned {', '.join(h['chunk_id'][:12] for h in shown)}"
        )
        if tokens:
            # Per token, not lumped together: the whole failure is that chunks
            # carrying the common tokens crowd out the one carrying the rare
            # one, and a combined count hides exactly that.
            counts = ", ".join(
                f"{token} in {sum(1 for h in shown if h['tokens'].get(token) == 'exact')}/{len(shown)}"
                for token in tokens
            )
            detail += f"; top-{k} carries {counts}"
        if verdict["rerankable"]:
            return "R (mis-ranked, in candidate pool)", detail
        return "R (not fetched, recall ceiling)", detail

    if answer is None:
        return (
            "G candidate — rerun with --answer",
            f"gold {gold_id[:12]} was in the top-{k} context, so retrieval did its job here",
        )
    if declines:
        return (
            "G (good context, misused)",
            f"gold {gold_id[:12]} was in context at rank {verdict['rank']} "
            "but the answer reports the material as not retrieved",
        )
    if mentions is False and tokens:
        return (
            "G (good context, misused)",
            f"gold {gold_id[:12]} was in context at rank {verdict['rank']} "
            f"but the answer never names {'/'.join(tokens)}",
        )
    if tokens:
        return (
            "pass (gold in context, identifier named)",
            f"gold {gold_id[:12]} at rank {verdict['rank']} and the answer names "
            f"{'/'.join(tokens)}",
        )
    return (
        "pass (gold in context)",
        f"gold {gold_id[:12]} at rank {verdict['rank']} and the answer was built from it",
    )


def find_chunks(phrase, limit=10):
    """Locate chunks containing a literal phrase, for building the golden set.

    Tagging a question with the chunk id you *know* is correct means finding
    that chunk by its text, not by asking the retriever — using retrieval to
    pick its own ground truth would make the whole measurement circular.
    """
    index = retrieval.build_index(quiet=True)
    tokens = find_identifiers(phrase)
    needle = " ".join(phrase.split()).lower()

    found = []
    for record in index.records:
        flat = " ".join(record["text"].split()).lower()
        if needle in flat:
            found.append(record)
        elif tokens and all(
            state == "exact" for state in token_presence(record["text"], tokens).values()
        ):
            found.append(record)
        if len(found) >= limit:
            break

    if not found:
        print(f"No chunk contains '{phrase}'. It may be split across a chunk boundary.")
        return

    print(f"{len(found)} chunk(s) matching '{phrase}':\n")
    for record in found:
        page = record["page"] if record["page"] is not None else "?"
        print(f"  {record['chunk_id']}")
        print(f"    {record['source_file']} p{page}")
        print(f"    {snippet(record['text'], tokens)}\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", nargs="*", help="the question to inspect")
    parser.add_argument(
        "--find", help="find chunks containing a literal phrase, to tag a golden-set answer"
    )
    parser.add_argument("--question", dest="question_id", help="golden set id, e.g. q03")
    parser.add_argument("--gold", help="known-correct chunk id, overrides the golden set")
    parser.add_argument("--k", type=int, default=3, help="chunks shown to the model (default 3)")
    parser.add_argument(
        "--candidates", type=int, default=None, help="how deep to look for the gold chunk"
    )
    parser.add_argument("--mode", default=None, help="retrieval mode (default from config)")
    parser.add_argument("--answer", action="store_true", help="also run generation")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a report")
    parser.add_argument("--goldenset", default="goldenset.json")
    args = parser.parse_args()

    if args.find:
        find_chunks(args.find)
        return

    entry = None
    question = " ".join(args.question).strip()
    if args.question_id:
        entries = load_goldenset(args.goldenset)
        entry = next((e for e in entries if e["id"] == args.question_id), None)
        if entry is None:
            sys.exit(f"No question '{args.question_id}' in {args.goldenset}")
        question = question or entry["question"]
    if not question:
        sys.exit("Give a question, or --question <id> from the golden set.")

    if args.answer:
        config.preflight()

    report = inspect(
        question,
        k=args.k,
        candidates=args.candidates or config.CANDIDATE_K,
        mode=args.mode or config.RETRIEVAL_MODE,
        gold_id=args.gold,
        entry=entry,
        want_answer=args.answer,
    )

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render(report, use_color=sys.stdout.isatty()))


if __name__ == "__main__":
    main()
