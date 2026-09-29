# Week 6 — claim-summary judge/human agreement study

## What this measures

`summarize.py` writes a claim summary from adjuster intake notes (new this
week — see summarize.py's module docstring for why the claim number is kept
away from the model and spliced into the output afterward). This report
asks whether an LLM judge's quality score for that summary agrees with a
human's, on real generated output, before anyone routes claims work by it.

## Assertions vs judged criteria

4 deterministic assertions (evaluate_summaries.py's `check_assertions`) vs
3 fields the judge is still asked to grade (`verdict`, `failure_modes`,
`cites_correct_edition` — `rationale` is explanatory, not a graded
criterion):

- `claim_number_echoed`, `date_of_loss_parseable`, `deductible_numeric` —
  never were judge criteria for this feature; built deterministic from day
  one, since summarize.py's own design (claim number spliced in by code,
  never by the model) makes them checkable without an LLM at all.
- `exclusion_id_on_denial` — this is the one actually **moved out** of the
  judge: it re-implements, as a plain regex against the frozen Basis text,
  what judge_v1's first draft would otherwise have asked the LLM to
  self-report as an `exclusion_code_cited` field (mirroring how
  evaluate_answers.py's Q&A judge originally worked). `summary_judge_v1.txt`
  ships without that field, and says explicitly what it is not grading.

Result on all 27 frozen cases (25 goldenset + 2 regression): **77/88
applicable assertion checks passed** (87.5%). `exclusion_id_on_denial`
accounts for essentially all the failures — most denial summaries state the
right reasoning without stating the bare exclusion code letters, a distinct
finding from whether the *call* is correct (see below).

## agreement_before -> agreement_after

- **agreement_before = 22/25 = 88.0%** (`summary_judge_v1.txt` vs
  `labels_25.json`'s hand labels — see that file's `_labeling_provenance`
  for exactly how those labels were derived: AI-assisted, PDF-grounded,
  disclosed, not independent blind human review)
- **agreement_after = 23/25 = 92.0%** (`summary_judge_v2.txt`, which adds
  two few-shot examples from judge_v1's own disagreements)

All 3 original disagreements (`s01`, `s10`, `s22`) shared one shape: the
judge marked `right_call_wrong_support` because the summary's Basis text
never states the bare exclusion code (e.g. "E-17"), even when it
substantively and correctly explains the same distinction in its own words.
`s01` and `s10` were used as judge_v2's few-shot examples; `s22` was
deliberately held out to test whether the fix would transfer rather than
just be memorized.

## prediction.txt vs what happened

Predicted: agreement would rise from 88% toward 23-24/25 by flipping `s01`
and `s10` specifically, leaving the 9 genuinely-wrong-call cases untouched.

What actually happened: **half right**. `s01` and `s10` did flip to
`correct_supported`, exactly as predicted, and none of the 9 wrong_call
cases moved. But `s22` — the held-out case — did **not** flip; it's a
different failure shape (reasoning from the provision's *absence* rather
than substantively citing it, which is a distinct, already-documented
anti-pattern in the judge prompt, not a missing-code problem). And a case
the prediction never considered at risk, `s06`, flipped from agreeing
(both said fail) to disagreeing (judge now says pass) — the few-shot
leniency generalized further than intended, past "don't require the bare
code" into rewarding a summary that never substantively cites *any*
distinguishing exclusion at all. **The prediction assumed the fix would be
surgical; it wasn't** — it fixed the 2 intended cases but introduced one
new regression on a case that wasn't broken.

## The 2 remaining disagreements, and who's actually right

**s06 — human was right, judge_v2 is wrong.** Its Basis text: *"no provision
in the retrieved policy language extends coverage to earth movement"* —
this is absence-based reasoning (it never cites E-2 Earth Movement's actual
exclusionary text, verified directly in `docs/HO-0304_ed-01-22.pdf`), the
same structural flaw judge_v1's own anti-pattern list already warns
against. It also never flags that Endorsement HO-2405 cannot legally attach
to a 01-22 policy at all (confirmed from HO-2405's own CONDITIONS text) —
a real, separate gap. judge_v2's leniency about missing bare codes bled
into rewarding this too, which it shouldn't have.

**s22 — judge_v2 was right, human (this session's earlier labeling pass)
was too lenient.** Its Basis text claims the E-20 collapse provision "is
not found in the retrieved material" and denies on that absence — again the
documented absence-as-exclusion anti-pattern — even though HO-0304 Edition
01-22's actual E-20 text (verified directly) does support a denial here
(its exception list doesn't include ice/snow/sleet/rain, unlike 02-23 and
03-24). The original human label called this "pass" because the *call*
happened to be right; judge_v2 correctly declined to reward reasoning that
got there by claiming absence rather than by reading the actual provision.

## Deliverables

| File | Status |
|---|---|
| `summarize.py` | new claim-summary feature |
| `traffic.py --kind notes` | synthetic adjuster-notes generator, reused vocabulary |
| `traces/summary_traces.jsonl` | 28 real generated summaries, isolated from Q&A traces |
| `labels_25.json` | committed before any judge existed for this feature (see `_labeling_provenance`) |
| `summary_goldenset.json` | 25 cases, each PDF-verified gold facts + `taxonomy_mode` |
| `summary_regression_set.json` | 2 cases frozen verbatim, both independently re-confirmed against the policy text |
| `evaluate_summaries.py` | one command, judges everything pre-frozen, prints pass rate by mode |
| `summary_judge_v1.txt` / `summary_judge_v2.txt` | baseline and few-shot-iterated judge |
| `prediction.txt` | filed before judge_v2 was built |
| `eval_out/summary_judged_v1.md` / `v2.md` | the one-command pass-rate-by-mode table (gitignored, regenerable) |

## One honest caveat

`labels_25.json`'s labels are AI-derived (PDF-grounded, but not independent
blind human review) — disclosed there and repeated here so `agreement_before`
/`agreement_after` are read for what they actually measure: the judge's
agreement with a careful, disclosed AI-assisted read of the policy text, not
with a human adjuster's independent judgment. The s06/s22 findings above are
themselves evidence that this read wasn't rubber-stamped — it changed
under scrutiny, twice, once from checklist to PDF verification and once
here when checked against the judge's own reasoning.
