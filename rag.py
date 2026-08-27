"""Ask questions about the indexed developer profiles.

    python rag.py "Which developers have React experience?"   # one-shot
    python rag.py                                             # interactive

Run ingest.py first — this script only reads from the vector store.
"""

import os
import re
import sys

# transformers is installed without a torch/TF backend and warns about it on
# import. We never use it — silence the noise before langchain pulls it in.
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda, RunnablePassthrough
from langchain.prompts import PromptTemplate

import config

PROMPT = PromptTemplate(
    input_variables=["context", "question"],
    template="""You are an assistant answering questions about a set of software \
developer profiles (resumes).

Use ONLY the context below. If the answer is not in the context, say so plainly \
instead of guessing. When you mention a fact, name the developer it belongs to.

Context:
{context}

Question:
{question}

Answer:""",
)


def format_docs(docs):
    """Label each chunk with its source so the model can attribute answers."""
    return "\n\n".join(
        f"[{doc.metadata.get('source_file', 'unknown')}, page "
        f"{doc.metadata.get('page', '?')}]\n{doc.page_content}"
        for doc in docs
    )


def strip_think(text):
    """Belt and braces: reasoning=False should already suppress these."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def build_chain():
    retriever = config.get_vector_store().as_retriever(search_kwargs={"k": config.TOP_K})
    return (
        {"context": retriever | format_docs, "question": RunnablePassthrough()}
        | PROMPT
        | config.get_llm()
        | StrOutputParser()
        | RunnableLambda(strip_think)
    )


def main():
    config.preflight()
    chain = build_chain()

    question = " ".join(sys.argv[1:]).strip()
    if question:
        print(chain.invoke(question))
        return

    print(
        f"Asking {config.CHAT_MODEL} over '{config.COLLECTION_NAME}' "
        f"(top {config.TOP_K} chunks). Type 'exit' to quit.\n"
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
