"""Ask questions about the indexed policy documents.

    python rag.py "does exclusion E-17 apply under form HO-0304 ed. 03-24"
    python rag.py                                             # interactive

Retrieval lives in retrieval.py, which evaluate.py and inspect_view.py also
call, so what is measured is what is served.
"""

import os
import re
import sys

# sentence-transformers logs model-loading chatter on every run. Quiet it before
# the import; the first-run download bar comes from huggingface_hub and still shows.
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnableLambda, RunnablePassthrough

import config
import retrieval

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


def build_chain():
    fetch_context = RunnableLambda(
        lambda question: retrieval.format_hits(retrieval.retrieve(question))
    )
    return (
        {"context": fetch_context, "question": RunnablePassthrough()}
        | PROMPT
        | config.get_llm()
        | StrOutputParser()
        | RunnableLambda(strip_think)
    )


def answer_with_context(question, k=None):
    """Answer, and hand back the chunks it was answered from.

    The chain above hides its context inside the pipe, which is exactly what
    makes a bad answer hard to diagnose. This variant returns both, so the
    inspection view can show whether a wrong answer came from missing context
    or from misused context.
    """
    hits = retrieval.retrieve(question, k=k)
    chain = PROMPT | config.get_llm() | StrOutputParser() | RunnableLambda(strip_think)
    answer = chain.invoke(
        {"context": retrieval.format_hits(hits), "question": question}
    )
    return hits, answer


def main():
    config.preflight()
    chain = build_chain()

    question = " ".join(sys.argv[1:]).strip()
    if question:
        print(chain.invoke(question))
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
        print(f"\n{chain.invoke(question)}\n")


if __name__ == "__main__":
    main()
