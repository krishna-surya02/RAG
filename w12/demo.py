"""`python triage.py demo` -- the brief's live wound, then the fix, then one live claim.

Offline part (no Groq key needed):
  1. The wound: a 2024 rainfall-flood FNOL, searched with no date scope, ranks
     the 2025 flood endorsement first -- the newer wording reads better.
  2. The fix: the same search scoped to the loss date / policy term returns
     only the 2023 wording, and asking for HFL-25 on that loss is refused.
  3. The trap the calendar misses: a June-2025 loss on a term that started in
     2024 is still governed by the 2023 set.
  4. The PII line: the raw FNOL vs what any model or MCP client receives.
  5. The decision guard on three sentences.
Live part: one claim end to end, then its trace across the agent and MCP hops.
"""

import os

os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

AUG24 = "CLM-2024-000063"
CROSS = "CLM-2025-000059"


def _h(title):
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def offline():
    import numpy as np

    import retrieval
    from w12 import citations, guard, pii, store, wording_index

    c = store.claim(AUG24)
    query = "rainwater ran across the garden and in under the patio doors, flooding the kitchen"
    _h(f"1. THE WOUND  {AUG24}, loss {c['loss_date']}: search with no date scope")
    idx = wording_index.build(quiet=True)
    sc = idx.scores(query)
    for rank, i in enumerate([i for i in np.argsort(-sc) if idx.records[i]["product"] == "household"][:5], 1):
        r = idx.records[i]
        tag = "  <-- 2025 wording, NOT in force for a 2024 loss" if r["doc_id"] == "HEND-2025" else ""
        print(f"  {rank}. {r['ref']:<12} {r['doc_id']} {r['version']}  score {sc[i]:.3f}{tag}")

    _h("2. THE FIX  same query, scoped to the policy term covering the loss date")
    facts = store.in_force(c["policy_number"], c["loss_date"])
    print(f"  in force: {facts['in_force']}  term {facts['term']['start']} -> {facts['term']['end']}  "
          f"set {facts['endorsement_set']} {facts['endorsement_set_version']}")
    hits, res = retrieval.retrieve_in_force(query, "household", c["loss_date"], facts["endorsement_set"], k=5)
    for h in hits:
        print(f"  {h.rank}. {h.meta['ref']:<12} {h.meta['doc_id']} {h.meta['version']}")
    bad = citations.resolve("HFL-25 §2.1", "household", c["loss_date"], facts["endorsement_set"])
    print(f"  cite HFL-25 §2.1 for this loss -> valid={bad['valid']}: {bad['problems'][0]}")
    good = citations.resolve("HFL-23 §2.2", "household", c["loss_date"], facts["endorsement_set"])
    print(f"  cite HFL-23 §2.2 -> {citations.render(good)}")

    x = store.claim(CROSS)
    _h(f"3. THE CALENDAR TRAP  {CROSS}, loss {x['loss_date']} (after the 2025 set took effect)")
    f2 = store.in_force(x["policy_number"], x["loss_date"])
    print(f"  calendar says: {store.set_by_calendar('household', x['loss_date'])}")
    print(f"  policy term {f2['term']['start']} -> {f2['term']['end']} carries: {f2['endorsement_set']}  <- this governs")

    _h("4. THE PII LINE  raw FNOL vs what a model or another squad's MCP client gets")
    red, _ = pii.redact_claim(c)
    print("  raw     :", c["fnol_text"][:230], "...")
    print("  returned:", red["fnol_text"][:230], "...")
    print("  removed :", red["redacted_counts"])

    _h("5. THE DECISION GUARD")
    for s in ["Under HFL-23 §2.2 the loss is indemnified up to the sub-limit.",
              "HFL-23 §2.2 may be relevant; the adjuster should confirm the home is outside a declared flood zone.",
              'HFL-25 §2.1 reads "Flood damage is not insured" -- that set was not in force for this loss.']:
        v = guard.violations(s)
        print(f"  {'WITHHELD' if v else 'ok      '}  {s}" + (f"   ({', '.join(v)})" if v else ""))


def run_live(claim_id=AUG24):
    import config
    from w12 import agent, trace

    if not config.GROQ_API_KEY:
        print("\n(no GROQ_API_KEY: skipping the live claim)")
        return
    _h(f"6. LIVE  python triage.py claim {claim_id}")
    rec = agent.run(claim_id, verbose=True)
    print()
    print(agent.render_referral(rec))
    _h(f"7. ONE TRACE ACROSS BOTH HOPS  python triage.py trace {rec['trace_id'][:12]}")
    spans, _ = trace.load_trace(rec["trace_id"])
    print(f"  services: {sorted({s['service'] for s in spans})}")
    print(trace.render_tree(spans))


def main(live=True):
    offline()
    if live:
        run_live()
