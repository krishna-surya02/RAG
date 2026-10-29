"""For a squadmate: plant one bad coverage answer in the Week-11 logs.

    # Ask a real question and let the live model answer (it may or may not fail):
    TRACE_PATH=traces/claims_traces_w11.jsonl python plant.py --live \\
        --question-file q.txt --user adj-04

    # Ask a real question but replace the model's answer with your own text:
    TRACE_PATH=traces/claims_traces_w11.jsonl python plant.py \\
        --question-file q.txt --answer-file a.txt --user adj-04

Either way the line goes through rag.answer(), the path every served answer
takes: real redaction, real retrieval ids, a real model call with its real
latency and token usage. In --answer-file mode only the text the model returned
is swapped before it is logged. Nothing about the line marks it as planted — it
carries source "traffic" and a traffic-shaped request like the rest of the day,
because a plant that a grep for "plant" finds tests nothing.

It prints only that it wrote a line. Keep q.txt/a.txt to yourself until the
drill is timed; the finder needs the question afterwards to build the eval case.
"""

import argparse
import random
from pathlib import Path

import config
import rag


class _SwappedAnswer:
    """Wraps the real client: makes the real call, then replaces the text."""

    def __init__(self, llm, text):
        self._llm = llm
        self._text = text
        self.model_name = llm.model_name
        self.temperature = llm.temperature
        self.max_tokens = llm.max_tokens
        self.reasoning_effort = llm.reasoning_effort
        self.reasoning_format = llm.reasoning_format
        self.request_timeout = llm.request_timeout
        self.max_retries = llm.max_retries

    def bind(self, **kwargs):
        self._llm = self._llm.bind(**kwargs)
        return self

    def invoke(self, prompt):
        message = self._llm.invoke(prompt)
        message.content = self._text
        return message


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--question-file", required=True)
    parser.add_argument("--answer-file", help="replace the model's answer with this text")
    parser.add_argument("--live", action="store_true", help="keep the model's own answer")
    parser.add_argument("--user", required=True, help="adjuster id, e.g. adj-04")
    parser.add_argument("--seed", type=int, default=21, help="the traffic seed the day was run with")
    args = parser.parse_args()
    if bool(args.answer_file) == args.live:
        parser.error("pass exactly one of --answer-file or --live")

    config.preflight()
    question = Path(args.question_file).read_text(encoding="utf-8").strip()
    if args.answer_file:
        text = Path(args.answer_file).read_text(encoding="utf-8").strip()
        real_get_llm = config.get_llm
        config.get_llm = lambda model=None: _SwappedAnswer(real_get_llm(model), text)

    # A seq past the day's run, so it can't collide with a real traffic line.
    request = {"seed": args.seed, "seq": random.randrange(200, 1000)}
    rag.answer(question, source="traffic", request=request, user=args.user)
    print(f"wrote 1 line to {config.TRACE_PATH}")


if __name__ == "__main__":
    main()
