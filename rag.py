"""Ask questions about the indexed policy documents.

    python rag.py "does exclusion E-17 apply under form HO-0304 ed. 03-24"
    python rag.py                                             # interactive

Retrieval lives in retrieval.py, which evaluate.py and inspect_view.py also
call, so what is measured is what is served.
"""

import hashlib
import os
import re
import sys

# sentence-transformers logs model-loading chatter on every run. Quiet it before
# the import; the first-run download bar comes from huggingface_hub and still shows.
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnableLambda

import config
import redact
import retrieval
import tracing

# Bump whenever PROMPT's text changes. The trace records this and a hash of the
# template, so an answer can always be tied to the exact instructions behind it.
# claims-v2 (week 11): added the "absence is not coverage" rule below. The
# planted drill failure (trace c4559f34, evals/case_w11_termite_0122.json) said
# termite damage on 01-22 was covered because 01-22's E-15 wasn't retrieved;
# notes.md section 3 #2, #10 and #19 are the same move made by the model itself.
# claims-v3 (week 11, never shipped v2): v2 also stopped the model applying an
# exception written into an exclusion's own text -- golden q04 (snow-load
# collapse, E-20) went 0/3, refusing because E-20's cross-referenced
# "Additional Coverage -- Collapse" provision wasn't retrieved. That provision
# is not in the corpus at all; E-20's text is the policy's only statement of it.
PROMPT_VERSION = "claims-v3"

# The "say so plainly" rule carries most of the weight here. An adjuster asking
# about one exclusion code is not helped by a fluent paragraph about a
# neighbouring one, and that near-miss is the failure that is hardest to catch
# by reading the answer — it is confident, on-topic, and wrong. Naming the code
# and edition the answer rests on makes the substitution visible.
PROMPT = PromptTemplate(
    input_variables=["context", "question"],
    template="""You are assisting a claims adjuster with questions about insurance \
policy forms, exclusions and endorsements.

Use ONLY the context below.

If the question names a specific exclusion code, form number, edition date or \
endorsement number, answer only from context that carries that exact identifier. \
If no passage in the context carries it, say plainly that the identifier does not \
appear in the retrieved material, and name what was retrieved instead. Do not \
answer from a related or adjacent provision as though it were the one asked about.

Never conclude a loss is covered because no exclusion for it appears in the \
context. The context is a few retrieved passages, not the whole policy. If the \
exclusions section for the named form and edition is not in the context, say \
that coverage cannot be confirmed from the retrieved material and name the \
form, edition and exclusion that would need to be checked.

That rule is about missing exclusions, not missing exceptions. When an \
exclusion's own text says it does not apply to a cause of loss ("except ..."), \
that is the policy's own wording: apply it and make the call, even if the \
exclusion refers to another provision that is not in the context.

Quote the provision you rely on, and name its form number, edition and code.

Context:
{context}

Question:
{question}

Answer:""",
)


def strip_think(text):
    """llama-3.3-70b emits no <think> blocks, but Groq's reasoning models do —
    keep this so swapping CHAT_MODEL doesn't leak scratchpads into answers."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


PROMPT_SHA256 = hashlib.sha256(PROMPT.template.encode("utf-8")).hexdigest()


def answer(question, source="cli", request=None, user=None):
    """Answer one question and append its trace. The path every served answer takes.

    The question is redacted before anything else touches it, so retrieval, the
    model and the trace all see the same text, and a replay sends the model
    exactly what it was sent the first time. The LLM is invoked directly rather
    than through StrOutputParser so the whole message survives: raw content,
    reasoning, token usage and fingerprint all go into the trace.
    """
    timer = tracing.Timer()
    clean, found = redact.redact(question)
    redact_ms = timer.ms()
    trace_id = tracing.new_trace_id()
    seed = tracing.seed_for(trace_id)
    record = {
        "trace_id": trace_id,
        "ts": tracing.now_utc(),
        "source": source,
        "user": user,
        "request": request or {},
        "app": tracing.app_version(),
        "input_type": tracing.classify_input(clean),
        "input": {"question": clean, "redacted": redact.counts(found)},
    }
    latency = {}
    # redact and retrieval run locally (regex, local embeddings): latency, no
    # tokens. This path makes no tool calls; the empty span says so explicitly.
    spans = [tracing.span("redact", redact_ms)]
    try:
        timer = tracing.Timer()
        k, candidates = config.TOP_K, config.CANDIDATE_K
        hits = retrieval.retrieve(clean, k=k, candidates=candidates)
        latency["retrieval"] = timer.ms()
        spans.append(tracing.span("retrieval", latency["retrieval"], hits=len(hits)))
        record["retrieval"] = tracing.retrieval_block(
            hits, k, candidates, config.RETRIEVAL_MODE, config.RETRIEVAL_BACKEND,
            retrieval._cache_key(),
        )

        rendered = PROMPT.format(context=retrieval.format_hits(hits), question=clean)
        record["prompt"] = {
            "version": PROMPT_VERSION,
            "template_sha256": PROMPT_SHA256,
            "rendered": rendered,
        }

        llm = config.get_llm()
        record["model"] = tracing.model_block(llm, seed)
        timer = tracing.Timer()
        message = llm.bind(seed=seed).invoke(rendered)
        latency["generation"] = timer.ms()

        usage = (message.response_metadata or {}).get("token_usage") or {}
        spans.append(tracing.span(
            "generation", latency["generation"],
            usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0),
        ))
        spans.append(tracing.span("tools", 0.0, calls=0))

        final = strip_think(message.content)
        record["output"] = tracing.output_block(message, final)
        record["answer_call"] = tracing.answer_call(final)
        return final
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        record["latency_ms"] = latency
        record["spans"] = spans
        record["cost_usd"] = round(sum(s["cost_usd"] for s in spans), 8)
        tracing.write_trace(record, pii_values=[value for _, value, _ in found])


def answer_with_context(question, k=None):
    """Answer, and hand back the chunks it was answered from.

    Returns the chunks alongside the answer, so the inspection view can show
    whether a wrong answer came from missing context or from misused context.
    Untraced on purpose: it serves the inspection view with an arbitrary k, and
    debugging runs do not belong in the trace population.
    """
    hits = retrieval.retrieve(question, k=k)
    chain = PROMPT | config.get_llm() | StrOutputParser() | RunnableLambda(strip_think)
    text = chain.invoke(
        {"context": retrieval.format_hits(hits), "question": question}
    )
    return hits, text


def main():
    config.preflight()

    question = " ".join(sys.argv[1:]).strip()
    if question:
        print(answer(question))
        return

    print(
        f"Asking {config.CHAT_MODEL} over '{config.PDF_DIR}' "
        f"(top {config.TOP_K} chunks, {config.RETRIEVAL_MODE} retrieval). "
        "Type 'exit' to quit.\n"
    )
    while True:
        try:
            question = input("Question: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if question.lower() in {"exit", "quit"}:
            return
        if not question:
            continue
        print(f"\n{answer(question)}\n")


if __name__ == "__main__":
    main()
