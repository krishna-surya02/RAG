# Week 5 notes: reading the claims assistant's traces

Everything below can be re-derived from the repo: the trace file is committed, and every seed is written down.

## 0. Where the traces came from (read this first)

- **The assistant had no trace file.** `rag.py` returned a string and wrote nothing, and no trace file existed in
  the repo or on this machine. The "week of traffic" in this analysis is **synthetic**. `traffic.py --seed 11`
  wrote a guess at adjuster traffic and sent it through the same `rag.answer()` the CLI serves, in two sittings on
  the same code: seq 0–5 on 2026-09-18 and seq 6–81 on 2026-09-22. The mix is described in `traffic.py`'s
  docstring. The generator was written and committed before any trace existed, so it could not be tuned toward
  failures already seen. The frequencies below therefore describe this traffic mix, not production.
- **Which commit produced the traces.** The generator was first committed as `7dcb541` at 15:51:54 IST on
  2026-09-18, 45 s before the first trace. That commit was reset 17 s later, and its code was recommitted
  unchanged as `38d476b` (`git diff 7dcb541 38d476b` touches only `notes.md` and the trace file). So `7dcb541`
  survives only in the local reflog, and `38d476b` is the commit to check the code against. The reset is also why
  trace lines 1–6 record `c096f43` with `dirty: true`: the tree held the same code, uncommitted. Lines 7–83
  record `38d476b`, clean.
- The Groq key is on the **free tier**, read from response headers: `x-ratelimit-limit-tokens: 8000` per minute and
  `x-ratelimit-limit-requests: 1000` per day, with roughly 200k tokens a day on `openai/gpt-oss-120b`. The rule,
  fixed before the tier was known, was: Developer tier gets 1,000 traces, free tier gets whatever a 180k-token
  budget buys. That bought **82 traffic traces** (seq 0–81, no gaps). Seq 0–5 used 12,646 tokens on 2026-09-18,
  and seq 6–81 used 169,682 against the remaining 167,354. The runner checks the budget before each call, so it
  overshot by one call, to 182,328 in all. None errored or hit a rate limit, and every `finish_reason` is `stop`.
  All 83 lines (the 82 plus one CLI trace, line 7) carry prompt `claims-v1` (`efdedf48369f`) and index
  `0595a52b8940db8f`.
- Seeds were fixed in the plan before any trace existed: traffic `11`, replay pick `918`, sample `20260918`.

## 1. Are the traces replayable?

### Fields: what existed before this week, and what was added

| Required field | Before (`c096f43`) | Now (`38d476b`), in each trace line |
|---|---|---|
| prompt version | **missing**: no trace at all, and the prompt had no version | `prompt.version` (`claims-v1`), `prompt.template_sha256`, `prompt.rendered` (exact text sent) |
| retrieved chunk_ids + scores | **missing**: `retrieval.py` computed scores and `rag.py`'s chain discarded them inside the pipe | `retrieval.hits[]` with rank, chunk_id, score, file, page; plus `index_key`, `embed_model`, `embed_revision` (HF snapshot), chunk size/overlap, k |
| model + params | **missing** | `model.name`, temperature, max_tokens, reasoning_effort/format (None = provider default), top_p, timeout, retries, and a per-trace **`seed`** (new; the model was unseeded before) |
| raw output | **missing**: `StrOutputParser` + `strip_think` threw away everything but the text | `output.raw` (pre-strip), `output.reasoning`, `output.final`, finish_reason, token usage, `system_fingerprint`, model id returned |
| also added | | `trace_id`, UTC `ts`, `app.git_commit` + dirty flag, `input.redacted` counts, `latency_ms`, `error` |

### Replay evidence

```bash
python replay.py --seed 918     # every trace_id sorted, then random.Random(918).sample(ids, 1)
```

It picked `ee140943812b` (line 19, seq 17): "the newest HO-0304 (2024), no endorsements. A kitchen grease fire
damaged the cabinets and the ceiling. Should I pay or deny this one?" The trace was written 2026-09-22 on `38d476b`
(clean), and it is not in the §2 sample. It was replayed from the trace line alone, with the trace's model and
parameters (`openai/gpt-oss-120b`, T=0.4, seed 3994290499), not today's config.

| check | result |
|---|---|
| prompt, rebuilt from `claims-v1` + the redacted question + the 5 chunk ids | **byte-identical** to `prompt.rendered` |
| retrieval, re-run on the traced question | index key `0595a52b8940db8f` both times; same 5 chunk ids in the same order, scores equal to 6 decimals (0.660884 … 0.630961) |
| generation, same prompt, parameters and seed | **not identical**: character similarity 0.226, `system_fingerprint` `fp_e1a78f200e` → `fp_f640395b96`, 2,122 → 2,077 tokens |

The call reproduced, but the answer did not.
- **Both say pay.** The original opens "**Answer: Pay (approve) the claim.**" and the replay opens
  "**Answer – Pay the claim**".
- **The reasoning differs.** The original quotes Coverage A and the "Occurrence" definition, labelling both
  03-24. Its Coverage A sentence actually came from the 02-23 chunk (`eacaf2e1f072`), because 03-24's own Coverage A
  chunk wasn't retrieved; the wording is the same. The replay instead treats the declarations line
  "Deductible: $1,000 All Perils" as the coverage grant.
- **The backend changed.** The fingerprints differ, so the request ran on a different backend. That matches the
  README: Groq does not honour `seed` across backends, so a trace line reproduces the prompt and retrieval
  exactly and the answer only approximately.

So a trace is enough to rebuild what the model was given and ask it again, but not to get the same words back.
A replayed answer has to be judged with the same rubric as §3, not diffed against the original.

### Redaction happens before the trace is written, not after

- **Where:** `rag.answer()` calls `redact.redact(question)` as its first line, before retrieval, the model, or the
  trace record see the question ([rag.py](rag.py)). Retrieval, the prompt, the model and the trace all hold the
  redacted text `[CLAIMANT_1]` / `[CLAIM_NO_1]`. That is also why the replay's prompt can be byte-identical: had
  redaction happened only in the writer, the model would have seen text the trace does not hold.
- **Second lock:** `tracing.write_trace()` receives the raw values that were found, in memory only. It scrubs every
  string field for them, re-checks the serialised line, and raises instead of writing if one survives
  ([tracing.py](tracing.py)). The trace keeps only counts (`input.redacted`), never the values.
- **Evidence:**
  - `python redact.py --selftest`: 14 cases, 0 failures. That covers 7 must-redact cases and 7 must-not-redact
    cases, such as `HO-0304 ed. 03-24`, `E-17`, `HO 03 04 (01/22)`, "Water Backup and Sump Overflow", and
    "$18,500".
  - Held-out generator seed 999: 2,000 questions, 1,426 of them carrying a name and claim number. 0 were leaked
    and 0 over-redacted (re-run 2026-09-22).
  - Smoke trace (`df307053…`): a grep for the name and claim number found 0 hits. That trace is in neither
    `traces/claims_traces.jsonl` nor any commit, so this check can't be repeated from the repo.
  - `python traffic.py --seed 11 --check-leaks` over the full trace file checked 82 traffic traces, 68 of them
    carrying an injected name and claim number. It searched 123 distinct names, name parts and claim numbers and
    found **0 leaks** and 0 over-redacted questions. `input.guard_scrubbed` is `false` on all 83 lines, so the
    writer's second lock never had to catch anything.

## 2. The sample

```bash
python sample_traces.py --seed 20260918 --n 20
```

- **Rule** (fixed before any trace existed): `sorted(trace_ids)` → `random.Random(20260918).sample(ids, 20)`.
- **Drawn from** `traces/claims_traces.jsonl` with sha256 `90ddf04fbd1c9daa26456f6e39f264a04766ea1c72af1058de0d5445b8f677b5`,
  83 lines. That is 82 traffic traces (seed 11, seq 0–81, no gaps, no errors, every `finish_reason` `stop`) plus
  one CLI trace (line 7, 2026-09-22). The CLI trace is in the population because the rule samples every
  trace_id. It was not drawn.
- **Read before the draw:** the first ~300 characters of the answers on lines 1–7 were printed while checking the
  file, before the run finished. None of those lines was drawn.

| # | trace | line | seq | policy as asked | loss / question |
|---|---|---|---|---|---|
| 1 | `82bfc075e258` | 18 | 16 | HO-0304 02-23, none | hidden mold after a sudden pipe leak, $56,700 |
| 2 | `3d266f178bea` | 64 | 62 | HO-0304 02-23, HO-2306 basic | mold from years of humidity |
| 3 | `e5a9d62978c7` | 56 | 54 | HO-0304 03-24, none | water heater ruptured; "what code if we deny?" |
| 4 | `0ffc3d7d9a45` | 48 | 46 | HO-0304 03-24, none | theft from an addition under construction |
| 5 | `e518f7a73d92` | 14 | 12 | HO-0500 01-23, none | kitchen grease fire |
| 6 | `af3f7365bed6` | 57 | 55 | HO-0304 03-24, HO-2405 $50k | off-premises power outage, spoiled freezer |
| 7 | `921818bd2d78` | 12 | 10 | HO-0304 01-22, HO-2306 | power out, sump stopped; "most we'd pay?" |
| 8 | `864a614015e9` | 13 | 11 | HO-0304 02-23, **HO-2405 (mis-stated)** | termites, $6,500 |
| 9 | `41f42fe9eac0` | 46 | 44 | HO-0304 02-23, HO-2306 basic | kitchen grease fire |
| 10 | `e3e14bf432fa` | 65 | 63 | HO-0500 01-23, none | roof collapse under snow, $16,200 |
| 11 | `303e71745d11` | 74 | 72 | HO-0304 01-22, none | mold from years of humidity, $48,600; pay or deny |
| 12 | `d8da37c2495d` | 24 | 22 | HO-0304 02-23, **HO-2405 $50k (mis-stated)** | dishwasher inlet valve failed, $56,500 |
| 13 | `984d723911a5` | 67 | 65 | HO-0304 03-24, none | municipal sewer backup |
| 14 | `33ada8ae08dc` | 55 | 53 | HO-0304 03-24, **HO-2306 Enhanced (mis-stated)** | surface water under the garage door |
| 15 | `2b966bb4929f` | 81 | 79 | HO-0500 01-23 ("HO 05 00 (01/23)"), none | surface water, $54,500 |
| 16 | `509eb1b136e1` | 29 | 27 | HO-0304 03-24, HO-2405 $50k | creek overflowed; "what code if we deny?" |
| 17 | `49b3b6408320` | 72 | 70 | HO-0500 01-23, **HO-2306 Enhanced (mis-stated)** | surface water, $10,500 |
| 18 | `0f38d676e28c` | 37 | 35 | (general) | did E-17's wording change across 01-22, 02-23, 03-24? |
| 19 | `89cbab8a81b9` | 80 | 78 | HO-0500 01-23, none | ice and snow on a flat roof, ceiling caved in, $6,700 |
| 20 | `4912273888b1` | 11 | 9 | HO-0304 03-24, none | washing machine hose split, $49,600; pay or deny |

How the sample compares with the 63 traces it left out:

| | sample (20) | the other 63 |
|---|---|---|
| loss / general / health-form / CLI | 19 / 1 / 0 / 0 | 49 / 10 / 3 / 1 |
| mis-stated endorsement | 4 | 3 |
| carried a claimant name and claim number (redacted) | 18 | 50 |
| had a form-header chunk (declarations/definitions page) in the top 5 | 18 | 51 |
| context slots taken by form-header chunks | 49 of 100 | 131 of 315 |

The sample is almost all loss questions. It says nothing about the health-form questions and very little about
the general ones.

## 3. Open coding: one sentence per trace, verbatim

Each code was written against the policy text in the index, not against what the model was given. Quotes are
copied from `output.final`, including the model's non-breaking hyphens (`‑`), narrow no-break spaces and bold markers.

| # | open code |
|---|---|
| 1 | Retrieval brought 03-24's E-10 instead of 02-23's, and after saying so the model priced the claim off it anyway ("The only applicable provision I have is the one from Edition 03‑24, which would limit coverage to $10,000"), missing the 02-23-only condition that remediation begin within 30 days. |
| 2 | Read a retrieval miss as the policy having no mold exclusion ("there is no specific exclusion to apply to the mold growth described"), when 02-23 E-10 excludes humidity mold and just wasn't in the top 5. |
| 3 | Accepted the question's premise that there is something to deny, and cited E-17 to deny a sudden appliance discharge that 03-24 E-17 covers up to $10,000, quoting as the exclusion an HO-2405 sentence about sewer backup from outside the plumbing ("does not provide even with the sudden‑discharge carve‑back") while the E-17 chunk itself wasn't retrieved. |
| 4 | Correct: quoted E-19 from the 03-24 form itself and handled the endorsement question on a base-form policy ("the exclusion applies in full"). |
| 5 | Correct: fire is a named peril under HO-0500 Section II, quoted from the form, and the answer added the $2,500 deductible without being asked. |
| 6 | Retrieval returned 01-22's E-4 instead of 03-24's word-identical one, and the model rightly refused to transplant it, which left the adjuster with "would likely be excluded. However, that conclusion cannot be drawn from the 03‑24 text you provided." |
| 7 | Right limits ($5,000 basic / $10,000 Enhanced under HO-2306), but the support is "Exclusion E‑17 in HO‑0304 Edition 02‑23" for a 01-22 policy, and it never mentions E-4 (off-premises power failure), which a storm cutting power to the street invites. |
| 8 | Answered only the endorsement half ("we cannot say from this material whether the endorsement changes the answer for the termite‑damage claim"), never found the termite exclusion (E-15, not retrieved), and quoted the HO-2306 text placing HO-2405 on 03-24 policies without noticing that this rules HO-2405 out on a 02-23 policy. |
| 9 | Correct: covered under Coverage A, quoted from the 02-23 form, and "The HO‑2306 endorsement does not alter that coverage." |
| 10 | Right outcome (weight of snow is a named peril) on a false statement ("The HO‑0500 Broad Form, Edition 01‑23 does **not** contain a collapse exclusion"), when F-11 Collapse exists on a page that wasn't retrieved. |
| 11 | Right call, resting on the wrong edition ("Deny the claim on the basis that mold loss not caused by a covered plumbing leak is excluded (per the E‑10 exclusion language found in HO‑0304, Edition 03‑24)"), because 01-22's identical E-10 wasn't retrieved, so a denial letter would cite a form the insured doesn't hold. |
| 12 | Looked for the wrong exclusion (E-17 covers sewer and sump backup, not a dishwasher leak) and ended at "I cannot cite that provision", noting HO-2405 "attaches only to **Form HO‑0304, Edition 03‑24**" without telling the adjuster that the stated 02-23 policy can't carry it. |
| 13 | Correct: quoted the revised 03-24 E-17 ("or by backup through sewers or drains from outside the plumbing system, remains fully excluded") and said only HO-2405 would add the coverage. |
| 14 | Correct, and the only one of the sample's four mis-stated endorsements that was caught ("**HO‑2306 is not compatible with an Edition 03‑24 policy.**"), with E-3 for the surface water. |
| 15 | No HO-0500 chunk reached the top 5, so the model stopped at "The identifier **HO 05 00 (01/23)** does not appear in the material that was retrieved", which is correct under the prompt and useless to the adjuster when F-1 Flood would have answered it. |
| 16 | Correct code (E-3), but the quote is HO-2405's one-line reference ("Flood and surface water remain excluded under **Exclusion E‑3**.") rather than E-3's own wording, which wasn't retrieved. |
| 17 | Said "The material you provided does **not** contain any HO‑0500 ed 01‑23 form" and then answered with the HO-0304 code anyway ("**Exclusion E‑3** (flood/surface‑water exclusion) would apply"), though HO-0500's code is F-1 and HO-2306, which the answer itself quotes as "attached to HO‑0304, editions 01‑22 or 02‑23", can't be on this policy. |
| 18 | Three of the five chunks came from the health claim form and none held E-17, so the headline question about the 03-24 revision got "I cannot determine whether the wording of an “E‑17” provision changed between editions 01‑22, 02‑23, and 03‑24". |
| 19 | Right call (pay, less the $2,500 deductible) with the same false claim as #10 ("There is no collapse exclusion in HO‑0500"), when F-11's named-peril exception is what makes the loss payable. |
| 20 | Correct: applied the 03-24 carve-back ("**Pay** the $10,000 allowed under the sudden‑and‑accidental‑discharge provision"), the same provision #3 got backwards when its E-17 chunk was missing. |

### Tally

Each trace is judged on what its question asked for: pay or deny, covered or not, which code, or which limit.

| outcome | traces | n |
|---|---|---|
| correct, supported from the right form and edition | 4, 5, 9, 13, 14, 16, 20 | 7 |
| right call, wrong or false support | 7, 10, 11, 19 | 4 |
| no call | 1, 6, 8, 12, 15, 18 | 6 |
| wrong call | 2, 3, 17 | 3 |

Set against retrieval:

- **Every one of the 13 traces outside the first row was missing a chunk its answer needed.** Of the 7 correct
  answers, 6 had everything in context. #16 got by on the endorsement's one-line reference to E-3.
- **When the chunk that decides the call was in context, the call was right 10 of 10 times** (4, 5, 7, 9, 10, 13,
  14, 16, 19, 20). When it was missing (1, 2, 3, 6, 8, 11, 12, 15, 17, 18), the result was 1 right call, 6 no
  calls and 3 wrong calls.
- **Sibling edition in place of the asked one:** 1, 2, 6, 11, with 7 citing another edition's E-17. The exclusion
  chunks never name their edition in their text; only the `[HO-0304_ed-03-24.pdf, page 1]` label that
  `format_hits` adds does. E-4 and E-10 are word-for-word the same in 01-22 and 03-24.
- **Absence from context stated as absence from the policy:** 2, 10, 19.
- **Mis-stated endorsement not flagged:** 8, 12, 17. Only #14 was caught. In #12 and #17 the endorsement's own
  "attaches to" line was in the context and quoted.
- **Form-header chunks crowd the context:** in 18 of 20 traces they took 49 of the 100 context slots. Those are
  the first chunk of each form, which carries the form number and edition and so matches any question that
  names them.
- **Leading question:** #3 answered "what code would I cite if we deny?" by supplying one for a covered loss.

## 4. Prediction

Written 2026-09-22, after coding the 20 and before reading any answer among the other 63 traces. The one
exception is lines 1–7, whose first ~300 characters were printed while checking the file (see §2). They are
marked wherever a prediction touches them. The trace lists below were picked from questions and retrieval
metadata only.

**P1. The failures are retrieval failures.** In the other 63, every answer outside "correct, supported" will be
missing a chunk it needed from its top 5 (sample: 13 of 13). With the deciding chunk in context, the call will
be right at least 90% of the time (sample: 10 of 10).
*Falsified if* more than 3 wrong calls or no calls in the 63 were made with the deciding chunk in context.

**P2. The rate on loss questions.** The rest holds 49 loss questions, the same kind of question as 19 of the 20
sampled. Correct and supported: about 17 of 49 (35%, the sample's 7 of 20). The sample's 95% interval (Wilson,
7/20: 18–57%) allows 9 to 28.
*Falsified if* the count lands outside 9–28. Six of the 49 (seq 0–5, lines 1–6) were skimmed.

**P3. HO-0500 with no HO-0500 chunk.** Nine HO-0500 questions in the rest have no HO-0500 chunk in their top 5:
lines 10, 15, 16, 25, 36, 39, 43, 52, 70. None of them will be correct and supported. Each will either decline,
as #15 did, or answer in HO-0304 terms, as #17 did: E-codes, the $1,000 deductible, or E-10's $10,000 mold
sublimit.
- Sharper: at least one of lines 15 and 16 (the HO-0500 mold sublimit) will state $10,000, a figure that exists
  only in HO-0304. The corpus has no HO-0500 mold sublimit. F-9 points to a Limited Fungi endorsement that isn't
  in the corpus.
- The five HO-0500 questions that did get an HO-0500 chunk (lines 1, 38, 40, 60, 83) will have the right call in
  at least 4. Line 1 was skimmed.

**P4. Outside the sample's reach.** The sample has 1 general question and no health-form ones, so these rest on
mechanism, not on observed rates.
- The three health claim-form questions (lines 41, 61, 69) will be answered correctly. 23 of the 49 chunks are
  the claim form, and there is no edition to confuse.
- Line 71 (did E-17 change across the three editions?) will fail as #18 did. It needs E-17 from three files in
  five slots, and form-header chunks fill 43% of slots across the population.
- Lines 17 and 21 (can HO-2306 attach to 02-23?) will both be answered yes. HO-2306's first chunk opens with
  its attachment line.

**Check:** read the 63 with `python sample_traces.py --trace-id <id> --show`, and code them into the same four
outcomes and the same retrieval cross-cut. Record hits and misses under this section without editing the
predictions above.

## 5. Why a public benchmark would not have surfaced these

A public QA or RAG benchmark would have tested this assistant on its own corpus, its own questions and its own
idea of "correct". Each of those differs from what produced the failures in §3.

1. **The trap is in this corpus, and benchmark corpora are not built to contain it.** Three near-identical
   editions of one form, plus two endorsements that attach only to certain editions. The exclusion chunks don't
   name their edition. Only the file label does, and E-4 and E-10 are word-for-word the same in 01-22 and 03-24,
   so nothing in a chunk's text can steer a question about one edition to that edition's copy (#1, #2, #6, #11).
   Open-domain QA sets are built over passages that differ in content. They don't test near-duplicate versions
   where the right choice depends on a label outside the text.
2. **The questions are wrong on purpose, and benchmark questions are not.** Adjusters mis-state endorsements (4
   in the sample, and the model caught 1, #14). They write one form five ways ("the newest HO-0304 (2024)",
   "HO 05 00 (01/23)"). They ask leading questions ("What exclusion code would I cite if we deny?"), and #3
   answered one by inverting the 03-24 carve-back. Benchmark questions are written to have one well-formed
   answer.
3. **The usual scores would pass most of these failures.**
   - *Faithfulness to context:* #1, #11 and #17 quote retrieved text accurately. They are wrong because the
     text belongs to another edition or form, and a groundedness check would read them as grounded.
   - *Abstention counted as safe:* #6, #8, #12, #15 and #18 decline. A benchmark that rewards "I don't know" on
     unanswerable questions scores them well, but every one is answerable from this corpus. Retrieval lost the
     answer.
   - *A general judge:* #3 reads as a confident, cited denial. Catching it takes the 03-24 E-17 text and
     knowing which edition the policy is on, and a general judge has neither.
4. **One number points at the wrong fix.** A benchmark would report something like 7 of 20 correct, which sends
   the work to the prompt or the model. The traces say otherwise: all 13 failures were missing a chunk they
   needed, and with the deciding chunk in context the call was right 10 of 10 times. The problem is retrieval
   that doesn't know which edition it is searching. Only a record that puts chunk ids next to answers shows that.

This traffic is synthetic (§0), so the rates describe this mix, not production. None of the four points
depends on the rates.
