# Failure-mode taxonomy

Formal names for the five patterns `notes.md` §3 found by hand-coding 20 sampled
traces. Every definition below is sourced from that section's own wording, not
re-derived — see the quoted sentence under each tag. `judge_v1.txt` outputs the
first four as per-answer tags; `header_crowding` is diagnosed differently (see
its entry) and is never a judge output.

Four of the five are answer-level: the judge sees one question, its retrieved
context, and one answer, and decides whether that answer exhibits the tag.
`header_crowding` is corpus/retrieval-level — it's a property of *which chunks
got retrieved*, visible only by looking at hit lists across questions, not by
reading a single answer.

## `sibling_edition`

The answer cites a chunk from a different edition of the *same* form than the
one actually in force. Exclusion chunks in this corpus never name their own
edition inside the chunk text — only the `[file, page]` label `format_hits`
attaches does — and several exclusions are word-for-word identical across
editions (`notes.md` §3: "E-4 and E-10 are word-for-word the same in 01-22 and
03-24"), so a sibling chunk is not just similar, it can be textually
indistinguishable from the correct one.

> "Sibling edition in place of the asked one: 1, 2, 6, 11, with 7 citing
> another edition's E-17." — `notes.md` §3

- **Detection**: the cited provision's edition (from the `[file, page]` label
  the model was given) doesn't match the edition stated or implied in the
  question.
- **Canonical traces**: 1, 2, 6, 7, 11.
- **Golden-set exercises**: q02, q07 (E-10/E-17 identical text across
  editions), q04 (E-20's weather exception differs by edition), q05 (E-10's
  30-day condition is 02-23-only).

## `absence_as_exclusion`

A retrieval miss — the deciding chunk simply wasn't in the top-k — gets
reported as "the policy doesn't have this provision" instead of "it wasn't in
what I was given." This turns a retrieval failure into a false statement about
coverage.

> "Absence from context stated as absence from the policy: 2, 10, 19." —
> `notes.md` §3 (trace 2: "Read a retrieval miss as the policy having no mold
> exclusion ... when 02-23 E-10 excludes humidity mold and just wasn't in the
> top 5.")

- **Detection**: the answer asserts a provision doesn't exist in the policy,
  where `gold_answer` says it does and the gold chunk was absent from the
  context the model was actually given.
- **Canonical traces**: 2, 10, 19.

## `unflagged_endorsement_mismatch`

An endorsement's own "attaches to" condition is present in the retrieved
context and even quoted, but the answer doesn't check it against the policy
the question describes — so an endorsement that can't legally be on this
policy gets used anyway, or a relevant mismatch goes unmentioned.

> "Mis-stated endorsement not flagged: 8, 12, 17. Only #14 was caught. In #12
> and #17 the endorsement's own 'attaches to' line was in the context and
> quoted." — `notes.md` §3

- **Detection**: the question states an endorsement attached to a form/edition
  the endorsement's own CONDITIONS text excludes, and the answer doesn't say
  so.
- **Canonical traces**: 8, 12, 17 (14 is the counter-example — caught it).
- **Golden-set exercises**: q03 (HO-2306 wrongly stated on a 03-24 policy),
  q07 (HO-2306 is irrelevant to a mold claim), q11 (HO-2306 wrongly stated on
  an HO-0500 policy — corrected pair to regression trace #17).

## `leading_question_accepted`

The answer accepts a false premise baked into the question instead of
checking it against the retrieved evidence first.

> "Leading question: #3 answered 'what code would I cite if we deny?' by
> supplying one for a covered loss." — `notes.md` §3

- **Detection**: the question presupposes a call (deny/exclude/etc.) that
  `gold_answer` contradicts, and the answer goes along with the premise
  instead of correcting it.
- **Canonical trace**: 3 (frozen as a regression case — see
  `regression_set.json`).
- **Golden-set exercises**: q09 (same trap, reworded so it isn't a repeat of
  the frozen regression input).

## `header_crowding` (retrieval-level — not a judge tag)

The first chunk of a form (its declarations/form-number page) matches almost
any question that names that form, because the form number and edition sit
right there in the header text. Those header chunks crowd out the substantive
provision the question actually needs.

> "Form-header chunks crowd the context: in 18 of 20 traces they took 49 of
> the 100 context slots. Those are the first chunk of each form, which
> carries the form number and edition and so matches any question that names
> them." — `notes.md` §3

- **Detection**: not from reading one answer — from the hit list across
  questions. Measure the fraction of top-k slots that are a form's page-0
  chunk, the same way `notes.md` §2 measured it for the 20-sample (49/100).
  `evaluate_answers.py`'s report surfaces this as a corpus-level number
  alongside the judge's per-answer tags, not as one of them.
- **Canonical traces**: present in 18 of the 20 sampled traces.
