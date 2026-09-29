# Week 8 — trajectory evaluation for the claims-triage agent

## What this measures

`race.py` (week 7) scores `claim_agent.py` against held-back ground truth by
checking four output fields: `claim_status`, `exclusion_code`, `payout`, `cap`.
It never looks at `tool_calls`. An agent that reaches the right payout without
ever opening the exclusions, on a claim that happens to be clean, scores a
pass. `trajectory_eval.py` scores the path instead: which tools were called,
whether each argument was grounded in a real prior result or invented, how
many steps it took, and what it cost — then reports the gap between "outcome
pass rate" and "trajectory pass rate" as a number.

## Expected tool sequences

For all 10 claims in `claims_data.json`, the valid tool sequence is a
**singleton set**: `(get_claim, check_policy_exclusions, compute_payout)`,
each called exactly once, in that order. This isn't an assumption baked into
the scorer — it's a documented finding:

- `check_policy_exclusions` needs `form`/`edition`/`cause`, and `cause` can
  only be read from `get_claim`'s notes — there is no other source.
- `compute_payout` needs a `claim_status`/`cap` decision that is only knowable
  after `check_policy_exclusions` returns (contract-specific facts, never
  guessable).
- `claim_agent.py`'s own system prompt makes `compute_payout` explicitly
  mandatory: *"you MUST call compute_payout to get the exact payout — never
  compute or guess the payout number yourself, even when it looks obvious."*

So `EXPECTED_SEQUENCES` is a genuinely generic mechanism — a dict mapping
`claim_id` to a *set* of acceptable tuples — and it happens that all 10 sets
contain exactly one tuple. A claim needing real branching would just get a
second tuple added to its set; none currently does. (The agent still found a
way to violate the "mandatory" tool — see below.)

## Trajectory numbers

Live-driven: 2 fresh trials per claim, all 10 claims, 20 runs total, against
the **unpatched** agent (2026-09-29, `since >= 2026-09-29`), paced with the
same `claims_common.RateLimiter` `race.py` uses.

| metric | value |
|---|---:|
| tool-choice accuracy | 90.0% (18/20) |
| argument validity rate | 94.9% |
| step efficiency (mean / max) | 0.97 / 1.00 |
| cost / claim (p50 / max) | $0.000533 / $0.000605 |
| tokens / claim (p50 / max) | 5,327 / 5,597 |
| latency / claim (p50 / max) | 2,909ms / 13,947ms |
| **outcome pass rate** | **100%** (20/20) |
| **trajectory pass rate** | **50%** (10/20) |
| **gap (outcome − trajectory)** | **+50.0 points** |

Every one of the 20 runs reached the numerically correct answer. Half of them
got there down a path that shouldn't be trusted. Validating the scorer first
against the pre-existing 2026-09-28 trace (10 claims, one trial each) found
the same pattern independently: outcome 100%, trajectory 50%
(`trajectory_baseline_summary.json`) — this isn't an artifact of one noisy
batch.

## Failure-mode tally (before mitigation)

| tag | count / 20 | detection |
|---|---:|---|
| `ungrounded_citation` | 10 | `check_policy_exclusions`'s citation is from a PDF whose embedded edition doesn't match the claim's real edition |
| `mandatory_tool_skipped` | 2 | a run with `status="ok"` whose tool sequence omits a mandatory tool |
| `wrong_tool_order` | 0 | all 3 tools present, wrong order |
| `argument_hallucination` | 0 | any other grounding check fails (cause misclassified, invented dollar figures, etc.) |
| `redundant_tool_call` | 0 | a tool called more than once |

`ungrounded_citation` is the volume leader by a wide margin (50% of runs vs.
10%), so it's the one the mitigation below targets.

## Two ways the same director gets burned

**The literal one.** Twice in this 20-run batch — `CLM-2026-010005` trial 2
and `CLM-2026-010008` trial 2, both "denied, no cap" claims — the agent called
`get_claim` and `check_policy_exclusions`, then went straight to a final
answer with `"payout": 0` **without ever calling `compute_payout`**, despite
the system prompt's explicit mandate. Both got the right number (a denied
claim always pays 0), so `race._passed()` scores both a clean pass. This is
the director's story almost exactly, just one tool earlier in the chain: the
agent skipped the arithmetic because the answer "looked obvious," not the
exclusions check.

**The required example — `CLM-2026-010003`.** Policy edition `01-22`,
earthquake. `check_policy_exclusions` returns `exclusion_code: "E-2"` —
correct, looked up from the hard-coded rules table keyed by the correct
edition — but its citation is:

```json
"citation": {"source_file": "HO-0304_ed-03-24.pdf", "page": 0, "chunk_id": "..."}
```

`03-24`, not the claim's real `01-22`. `race._passed()` passes this claim (all
four output fields match `expected`); the trajectory scorer fails it on
`check_policy_exclusions.citation_edition_matches_claim`. The decision was
right; the evidence trail backing it was borrowed from a different policy
edition. This is `taxonomy.md`'s own `sibling_edition` pattern — "E-4 and E-10
are word-for-word the same in 01-22 and 03-24" — re-surfacing at the tool-call
citation level instead of the RAG-answer level. Reproduced across both trials,
plus 4 other claims (`CLM-2026-010005/006/008/010`), 10 of the 20 runs total.

## Mitigation: argument validation, not a prompt edit

**Why not "tighter tool description."** `check_policy_exclusions` calls
`retrieval.retrieve()` *internally* — the model supplies only
`form`/`edition`/`cause` (already correct in every one of the 10 affected
runs) and never sees or picks the citation. No system-prompt or docstring
edit can change what the internal retrieval call returns. Worse: sibling
editions can be **textually identical** (`taxonomy.md`'s own finding), so no
amount of query rewording reliably separates them by embedding similarity —
this is a ranking problem, not a phrasing problem. Editing the prompt would
have measured a ~0 delta on the one real failure mode found, at the cost of a
second 20-run live batch (~20-25 more minutes against a Groq account that has
hit its daily quota before).

**The fix — `claims_tools.py`, `check_policy_exclusions`.** Retrieve 5
candidates instead of 1, then filter to the one whose filename's embedded
edition matches the requested edition, falling back to the top hit (flagged
`edition_mismatch: true`) only if none match:

```python
hits = retrieval.retrieve(f"{form} edition {edition}: {query}", k=5)
citation = None
if hits:
    same_edition = [h for h in hits if extract_edition(h.source_file) in (None, edition)]
    hit = same_edition[0] if same_edition else hits[0]
    citation = {"source_file": hit.source_file, "page": hit.page, "chunk_id": hit.chunk_id}
    if extract_edition(hit.source_file) not in (None, edition):
        citation["edition_mismatch"] = True
```

`extract_edition()` is a pure filename regex, defined once and shared by both
the runtime guard and `trajectory_eval.py`'s offline scorer, so they can never
drift apart. No change to `SYSTEM_PROMPT`, no change to any tool's argument
schema — the model's behavior (tool choice, tool order, every other argument)
is untouched by construction.

**Before → after**, replayed over the *same* 20-run batch (Tier 1: call the
patched function directly with each run's recorded args — deterministic,
local, zero new Groq calls):

| mode | before | after | delta | verdict |
|---|---:|---:|---:|---|
| `mandatory_tool_skipped` | 2 | 2 | +0 | unaffected |
| `wrong_tool_order` | 0 | 0 | +0 | unaffected |
| `argument_hallucination` | 0 | 0 | +0 | unaffected |
| **`ungrounded_citation`** | **10** | **0** | **−10** | **improved** |
| `redundant_tool_call` | 0 | 0 | +0 | unaffected |

`trajectory_pass_rate` on this batch moves from 50% → 85% (the 2
`mandatory_tool_skipped` runs are still failing, on the *other* mode — this
mitigation was never going to touch those, and doesn't).

**Price paid**, measured, not estimated: `retrieval.retrieve()` is a local
in-process vector lookup (no Groq call), so the patch costs **+0 tokens, +$0
cost/claim**. Latency: −0.51ms per `check_policy_exclusions` call (17.67ms →
17.16ms) — noise-level, since the corpus is small enough that k=5 vs. k=1
costs nothing measurable. This is about as cheap as a mitigation gets.

**Live confirmation (Tier 2).** Re-ran `CLM-2026-010003` twice, live, against
the patched code: both trials now cite `HO-0304_ed-01-22.pdf` (correct
edition) and both outputs are byte-for-byte unchanged (`denied`, `E-2`,
`payout: 0.0`) — the fix corrects the evidence without touching the decision.

## Regression check

All 5 modes checked, not just the targeted one (table above, repeated with
verdicts): 4 of 5 modes show `delta = 0` by construction — the patch only
ever rewrites `citation_edition_matches_claim`'s input, so that identity *is*
the regression check. No mode got worse. No new mode appeared.
`ungrounded_citation` improved; `mandatory_tool_skipped` remains open — a
step-limit or re-planning mitigation would be the next candidate if the
director wants that one closed too, but that's a second mitigation, out of
scope for this week's "exactly one."

## Verdict

The outcome eval said 100% and meant it — every one of 20 fresh runs reached
the numerically correct payout. The trajectory eval said 50% and also meant
it — half of those runs got there on a citation from the wrong policy
edition, and two of them skipped the mandatory payout calculation outright.
Both failures were invisible to `race.py` by construction: it only checks
where the agent landed, never how it got there. A 15-line, zero-marginal-cost
retrieval fix (filter by edition, don't just re-rank by text similarity)
closed the larger of the two gaps completely without moving anything else —
proof that the fix was surgical, not just hopeful. The smaller gap
(compute_payout skipped on "obvious" denials) is still open and is exactly
the kind of thing a hard step floor (require all 3 tools before accepting a
final answer) would catch next.

## Deliverables

| File | What it is |
|---|---|
| `trajectory_eval.py` | the trajectory scorer, sequence/argument checks, mitigation harness |
| `trajectory.csv` / `trajectory_summary.json` | per-run rows / the headline numbers, for the fresh 20-run batch |
| `trajectory_baseline.csv` / `trajectory_baseline_summary.json` | the same scorer validated against the pre-existing 2026-09-28 trace |
| `trajectory_mitigation.json` | before/after regression table and measured price for the citation-edition fix |
| `claims_tools.py` | patched (`extract_edition` + the citation-edition filter in `check_policy_exclusions`) |
