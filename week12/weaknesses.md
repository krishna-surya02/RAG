# Top-3 weaknesses (Wednesday, written before the eval results or any reviewer). DRAFT

> **DRAFT for the author to review.** Written on 2026-11-02, *before* the baseline eval finished. It is based on the first live runs and the offline retrieval probes, so it is a prediction to check against the eval report, not a conclusion drawn from it. Edit it to your own judgement.

## 1. The 2023 flood carve-back is hard to retrieve in claimant language
HFL-23 §2.2, the clause that decides every 2023-set rainfall claim, is written in legal register ("Pluvial accumulation … indemnified"). For a claimant-worded query ("rainwater ran across the garden and under the patio doors"), the correctly scoped search returns HX-17, the garden extensions and HX-9. HFL-23 doesn't make the top 5 (`python triage.py demo --offline`, step 2).
- **What the fix does and doesn't do:** the date filter stops the *wrong* wording (HFL-25 ranks #1 unscoped). It does not make the *right* wording rank.
- **What correctness rests on:** the agent reformulating its query or fetching §2.2 by ref after seeing §1's definitions.
- **What breaks:** a run that cites HFL-23 §1/§2.3 but not §2.2 sends the adjuster to the deductible, not the carve-back.
- **Where it would show:** `missed_deciding_clause` on the `hh_surface_water_*` cases.

## 2. Redaction removes the cause of loss in river floods
`redact.py`'s name detector takes "Calder River" for a person. In all 15 river claims the FNOL that reaches the agent says "the [CLAIMANT_2] burst its banks". River (HFL-23 §2.1, inundation) vs rainfall (HFL-23 §2.2, pluvial accumulation) is the distinction the clause turns on. The model may still infer it from "burst its banks", or it may not.
- **Why it's an integration fault:** the PII fix (Week 5) and the retrieval and agent fix (Weeks 3–7) each pass their own tests. This failure exists only once they are joined.
- **Where it would show:** `redaction_strips_cause` on `hh_river_23` cases.

## 3. The coverage line is the model's choice, and the limits follow it
Limits come from the table, so the numbers are never invented. But *which row* is keyed on the coverage line the model picks. In the first live run it picked `buildings` for a rainfall flood, so the referral showed the $1,000 buildings deductible and no sub-limit instead of the $2,500 flood deductible and the $15,000 sub-limit. That is exactly the "keep deductible and sub-limit distinct" failure the client cares about, wearing correct-looking numbers.
- **Where it would show:** `wrong_coverage_line` on the money-carrying cases.

## Runners-up
- **Quota:** the Groq daily quota is smaller than one full eval run. Every number in the eval report comes from a run spread over more than one day, or a subset.
- **Judge agreement:** there is none until a human labels the worksheet. Week 6's 92% was a different judge, on different outputs, with Claude-made labels.
- **Synthetic data:** template-generated notes are kinder to regex redaction than real adjuster notes. 0 misses on 500 synthetic files says little about real ones.
