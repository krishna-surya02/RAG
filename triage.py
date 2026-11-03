"""Claims triage -- the one entry point for the week-12 integrated system.

    python triage.py claim CLM-2024-000063             # FNOL in -> agent -> referral out
    python triage.py ask "is rainwater flooding the kitchen insured?" \
        --product household --loss-date 2024-08-14 [--policy HH-2023-00068]
    python triage.py eval --label w12-live             # the whole eval suite, one command
    python triage.py eval --rescore w12-live           # re-grade a saved run, no generation calls
    python triage.py serve-mcp --http 8765             # our MCP server for another squad's client
    python triage.py trace <trace_id>                  # one trace across agent + MCP hops
    python triage.py check                             # offline: selftests, corpus, PII audit
    python triage.py demo                              # offline wound demo + one live claim
    python triage.py gen-corpus [--check]              # regenerate / verify data/

Nothing here states a coverage decision. A claim run ends in a referral to an
adjuster with the wording in force on the loss date, cited by clause,
endorsement version and loss date, and the deductible, sub-limit and policy
limit kept apart. See README.md "Week 12" and week12/architecture.md.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
ROOT = Path(__file__).resolve().parent


def cmd_claim(args):
    import config
    from w12 import agent

    config.preflight()
    rec = agent.run(args.claim_id, verbose=not args.quiet)
    print(json.dumps(rec, indent=1, ensure_ascii=False, default=str) if args.json else agent.render_referral(rec))
    print(f"\ntrace: python triage.py trace {rec['trace_id'][:12]}")


def cmd_ask(args):
    import config
    import rag
    from w12 import citations

    config.preflight()
    out = rag.answer_claim(args.question, args.product, args.loss_date, args.endorsement_set, args.policy)
    if args.json:
        print(json.dumps(out, indent=1, ensure_ascii=False))
        return
    res = out["resolution"]
    print(f"Wording in force for loss date {res['loss_date']}: {res['base_wording']} + "
          f"{res['endorsement_set']} {res['endorsement_set_version']} (by {res['resolved_by'].replace('_', ' ')})")
    if res.get("warning"):
        print(f"  ! {res['warning']}")
    print()
    print(out["answer"])
    print("\nCitations:")
    for c in out["citations"] or []:
        print(f"  - {citations.render(c)}")
    if not out["citations"]:
        print(f"  (answer named no retrieved clause; context was {out['context_refs']})")
    print(f"\ntrace {out['trace_id'][:12]}  cost ${out['cost_usd']:.6f}  guard tripped: {out['guard']['tripped']}")


def cmd_trace(args):
    from w12 import trace

    spans, runs = trace.load_trace(args.trace_id, args.dir)
    if not spans and not runs:
        sys.exit(f"no spans for {args.trace_id} under {args.dir or trace.trace_dir()}")
    ids = {s["trace_id"] for s in spans} | {r["trace_id"] for r in runs}
    if len(ids) > 1:
        sys.exit(f"{args.trace_id} matches {len(ids)} traces; give more characters")
    tid = ids.pop()
    services = sorted({s["service"] for s in spans})
    print(f"trace {tid}  services: {', '.join(services)}  spans: {len(spans)}")
    print(trace.render_tree(spans))
    for r in runs:
        print(f"\nrun: claim={r.get('claim_id')} status={r.get('status')} cost=${r.get('cost_usd', 0):.6f} "
              f"tokens={r.get('prompt_tokens')}+{r.get('completion_tokens')} latency={r.get('latency_ms')}ms")
        if args.json:
            print(json.dumps(r, indent=1, ensure_ascii=False))


def cmd_serve(args):
    script = ROOT / "w12" / ("mcp_wording_server.py" if args.server == "wording" else "mcp_claims_server.py")
    cmd = [sys.executable, str(script)] + (["--http", str(args.http), "--host", args.host] if args.http else [])
    os.execv(sys.executable, cmd)


def cmd_eval(args):
    from w12.evals import run as evalrun

    evalrun.main(args)


def cmd_check(args):
    """Everything that runs without a Groq key."""
    steps = [
        ("redaction selftest", [sys.executable, "redact.py", "--selftest"]),
        ("decision-language guard selftest", [sys.executable, "-m", "w12.guard"]),
        ("frozen decision-language failures replayed against the guard", [sys.executable, "-m", "w12.evals.regression"]),
        ("corpus is reproducible", [sys.executable, "-m", "w12.corpus_gen", "--check"]),
        ("PII audit (all w12 traces, referrals, eval runs, MCP outputs)", [sys.executable, "-m", "w12.evals.pii_audit"]),
    ]
    failed = 0
    for name, cmd in steps:
        print(f"== {name}")
        r = subprocess.run(cmd, cwd=ROOT)
        failed += r.returncode != 0
    sys.exit(1 if failed else 0)


def cmd_demo(args):
    from w12 import demo

    demo.main(live=not args.offline)


def cmd_gen(args):
    sys.argv = ["corpus_gen"] + (["--check"] if args.check else [])
    from w12 import corpus_gen

    corpus_gen.main()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("claim", help="triage one claim: FNOL in, referral out")
    p.add_argument("claim_id")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_claim)

    p = sub.add_parser("ask", help="ask a question of the wording in force on a loss date")
    p.add_argument("question")
    p.add_argument("--product", required=True, choices=["household", "motor"])
    p.add_argument("--loss-date", required=True)
    p.add_argument("--policy", help="policy number: take the endorsement set from its term")
    p.add_argument("--endorsement-set")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_ask)

    p = sub.add_parser("trace", help="show one trace across the agent and MCP hops")
    p.add_argument("trace_id")
    p.add_argument("--dir", help="trace directory (default traces/ or $W12_TRACE_DIR)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_trace)

    p = sub.add_parser("serve-mcp", help="run an MCP server (stdio, or HTTP for another squad)")
    p.add_argument("--http", type=int, metavar="PORT")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--server", choices=["wording", "claims"], default="wording")
    p.set_defaults(fn=cmd_serve)

    p = sub.add_parser("eval", help="run the integrated eval suite (or re-grade a saved run)")
    from w12.evals import run as evalrun

    evalrun.add_args(p)
    p.set_defaults(fn=cmd_eval)

    p = sub.add_parser("check", help="offline checks: selftests, corpus reproducibility, PII audit")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("demo", help="offline wound demo, then one live claim")
    p.add_argument("--offline", action="store_true")
    p.set_defaults(fn=cmd_demo)

    p = sub.add_parser("gen-corpus", help="regenerate data/ (or --check it is reproducible)")
    p.add_argument("--check", action="store_true")
    p.set_defaults(fn=cmd_gen)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
