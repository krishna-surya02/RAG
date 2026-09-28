"""Write a claim summary from an adjuster's intake notes.

    python summarize.py "Claim CLM-2026-004512, insured Priya Raman. Policy is \\
HO-0304 ed. 03-24, no endorsements. Date of loss: March 3, 2026. The washing \\
machine hose split and flooded the laundry room. Estimate is $8,200."

Same served path as rag.answer(): redact, retrieve, prompt, generate, trace.
The one deliberate difference is the claim number. rag.answer() never needed
it — a coverage decision doesn't turn on who's asking or what file it's in.
A claim summary does: it has to carry the claim number back out so ops can
file it against the right claim. So the number is still kept away from the
model (redact.redact() replaces it with a placeholder before the notes are
sent, same as always, so the model never sees or invents one), but it is
spliced into the finished summary afterward, in code, from the value
redact.redact() found at ingress — never from anything the model wrote.

That means the trace's second-lock PII scrub (tracing.write_trace) has to be
told, for this one field, that the claim number showing up in the output is
correct, not a leak. See the pii_values filter in summarize() below. The
claimant's name gets no such exception — a claim summary needs the claim
number back, never the name.
"""

import hashlib
import re
import sys

import config
import redact
import retrieval
import tracing
from rag import strip_think

PROMPT_VERSION = "summary-v1"

from langchain_core.prompts import PromptTemplate

SUMMARY_PROMPT = PromptTemplate(
    input_variables=["context", "notes"],
    template="""You are drafting a claim summary for a claims adjuster, from their \
intake notes on one loss.

Use ONLY the policy context below to determine coverage. If the notes name a \
specific exclusion code, form number, edition date or endorsement number, answer \
only from context that carries that exact identifier. If no passage in the \
context carries it, say plainly that the identifier does not appear in the \
retrieved material, and name what was retrieved instead. Do not answer from a \
related or adjacent provision as though it were the one asked about.

The notes below have had the claim number and claimant name replaced with \
placeholders (e.g. [CLAIM_NO_1], [CLAIMANT_1]). Do not restate a placeholder, \
and do not invent a claim number or a name in their place.

Write the summary as exactly these labeled fields, one per line, in this exact \
order and with these exact labels. Do not add a "Claim" or "Claim Number" \
field — that line is added separately, outside this summary.

Date of Loss: <the date stated in the notes, restated exactly as given>
Policy & Edition: <the form number and edition in force>
Loss Description: <one or two plain-language sentences>
Coverage Determination: <pay or deny, with any limit or sublimit that bounds it>
Basis: <quote the provision relied on, and name its form number, edition and code>
Deductible: <the dollar amount that applies, or "not stated" if the notes and \
context don't establish one>

Context:
{context}

Notes:
{notes}

Summary:""",
)

SUMMARY_PROMPT_SHA256 = hashlib.sha256(SUMMARY_PROMPT.template.encode("utf-8")).hexdigest()

CLAIM_LINE_RE = re.compile(r"^Claim:\s*(.+)$", re.M)


def summarize(notes, source="cli", request=None):
    """Summarize one claim from adjuster notes and append its trace.

    Mirrors rag.answer() field for field (redact -> retrieve -> prompt ->
    generate -> trace), with one addition after generation: the real claim
    number, captured at redaction time and never sent to the model, is
    prepended as a "Claim: <number>" header line on the finished summary.
    """
    clean, found = redact.redact(notes)
    claim_number = next((value for kind, value, _ in found if kind == "claim_number"), None)

    trace_id = tracing.new_trace_id()
    seed = tracing.seed_for(trace_id)
    record = {
        "trace_id": trace_id,
        "ts": tracing.now_utc(),
        "source": source,
        "request": request or {},
        "app": tracing.app_version(),
        "input": {"notes": clean, "redacted": redact.counts(found)},
        "claim_number": claim_number,
    }
    latency = {}
    try:
        timer = tracing.Timer()
        k, candidates = config.TOP_K, config.CANDIDATE_K
        hits = retrieval.retrieve(clean, k=k, candidates=candidates)
        latency["retrieval"] = timer.ms()
        record["retrieval"] = tracing.retrieval_block(
            hits, k, candidates, config.RETRIEVAL_MODE, config.RETRIEVAL_BACKEND,
            retrieval._cache_key(),
        )

        rendered = SUMMARY_PROMPT.format(context=retrieval.format_hits(hits), notes=clean)
        record["prompt"] = {
            "version": PROMPT_VERSION,
            "template_sha256": SUMMARY_PROMPT_SHA256,
            "rendered": rendered,
        }

        llm = config.get_llm()
        record["model"] = tracing.model_block(llm, seed)
        timer = tracing.Timer()
        message = llm.bind(seed=seed).invoke(rendered)
        latency["generation"] = timer.ms()

        body = strip_think(message.content)
        header = f"Claim: {claim_number if claim_number else 'not stated in notes'}"
        final = f"{header}\n{body}"
        record["output"] = tracing.output_block(message, final)
        return final
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        record["latency_ms"] = latency
        # The claim number is deliberately in output.final (see module
        # docstring) — exclude it from the scrub list, unlike the claimant
        # name, which has no business appearing anywhere in a coverage
        # summary and stays covered by the second-lock scrub.
        pii_values = [value for kind, value, _ in found if kind != "claim_number"]
        tracing.write_trace(record, pii_values=pii_values)


def main():
    config.preflight()

    notes = " ".join(sys.argv[1:]).strip()
    if not notes:
        sys.exit(__doc__)
    print(summarize(notes))


if __name__ == "__main__":
    main()
