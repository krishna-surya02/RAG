"""The compliance rule, enforced in code: nothing automated states a coverage decision.

The regulator's finding behind the rule is about what the system *says*, so
this checks the text the system emits -- referral summaries and RAG answers --
not the model's reasoning. Quoting the wording is allowed (HFL-25 §2.1 is
headed "Flood damage is not insured", and an adjuster needs to see that);
asserting it about this claim is not. So quoted spans and citation link
labels are removed before matching, and anything left that reads as a
decision trips the guard.

A tripped guard does not edit the sentence into something softer -- a
rewrite would be the system deciding what the model "meant". It withholds
the summary and says why; citations and limits, which come from tools, are
untouched.
"""

import re

DECISION_RE = re.compile(
    r"\b(?:not\s+)?covered\b"
    r"|\bcoverage\s+(?:applies|is\s+(?:confirmed|available|provided)|exists)\b"
    r"|\b(?:is|are|would\s+be|will\s+be|should\s+be)\s+(?:not\s+)?(?:insured|excluded|payable|denied|approved|declined|accepted|rejected|indemnified)\b"
    r"|\bnot\s+(?:insured|payable)\b"
    r"|\b(?:deny|denied|denial|approve|approved|decline[sd]?)\s+(?:the|this|your)\s+claim\b"
    r"|\bclaim\s+(?:is|should\s+be|will\s+be)\s+(?:paid|denied|approved|declined|accepted|rejected)\b"
    r"|\bwe\s+(?:will|would|can|cannot|can't)\s+(?:pay|cover|not\s+pay)\b"
    r"|\bno\s+coverage\b(?!\s+decision)|\bexclusion\s+applies\b|\bthe\s+loss\s+is\s+excluded\b"
    # "the Home is not in a flood zone, so exclusion HX-3 does not apply" is a
    # coverage conclusion in different words (first live run, trace 53146eb1).
    r"|\bexclusions?\b[^.;]{0,40}\b(?:does|do|would|will)\s*(?:not|n't)\s+apply\b"
    r"|\b(?:exclusion|clause|endorsement)\s+\S+\s+(?:applies|would\s+apply)\s+to\s+(?:this|the)\s+(?:loss|claim)\b"
    # "the loss falls under the flood exclusion" (w12-08), "which falls under the
    # escape-of-water coverage" (w12-02)
    r"|\b(?:loss|claim|damage|which|it)\s+(?:falls|fall|is|comes)\s+(?:under|within)\s+(?:the\s+)?(?:[\w-]+\s+){0,2}(?:exclusion|cover|coverage)\b"
    # "excludes inundation, which does not apply here" (w12-07, reached the adjuster)
    r"|\b(?:does|do|would|will)\s*(?:not|n't)\s+apply\s+(?:here|to\s+(?:this|the)\s+(?:loss|claim))\b",
    re.I,
)

_QUOTED = re.compile(r"\"[^\"]{0,600}\"|“[^”]{0,600}”|‘[^’]{0,600}’")
_LINK_LABEL = re.compile(r"\[[^\]]{0,300}\]\([^)]{0,300}\)")


def _unquoted(text):
    # gpt-oss writes non-breaking hyphens (U+2011); normalise so "escape-of-water" matches.
    text = re.sub(r"[\u2010-\u2015]", "-", text or "")
    return _QUOTED.sub(" ", _LINK_LABEL.sub(" ", text))


def violations(text):
    """Decision phrases outside quotes and citation labels."""
    return [m.group(0) for m in DECISION_RE.finditer(_unquoted(text))]


WITHHELD = (
    "Referred to an adjuster. The automated triage summary was withheld because it "
    "contained coverage-decision language ({found}), which this system may not state. "
    "The cited wording, in-force check and limits below are unaffected."
)


def enforce(text):
    """(text_to_emit, found). On a hit, the text is replaced, not softened."""
    found = violations(text)
    if not found:
        return text, []
    shown = ", ".join(sorted({f.lower() for f in found}))
    return WITHHELD.format(found=shown), found


def selftest():
    must_trip = [
        "This loss is covered under HFL-23 §2.2.",
        "The claim should be denied under HX-1.",
        "Flood damage is not insured for this policy.",
        "We will pay up to the sub-limit.",
        "The exclusion applies, so there is no coverage.",
        "It would be excluded under HFL-25 §2.1.",
        "The Home is not in a designated flood zone, so the exclusion HX-3 does not apply.",
        "Under HFL-23 §2.2 the loss is indemnified subject to the sub-limit.",
        "The claimant should be advised that the loss falls under the flood exclusion.",
        # Frozen from baseline case w12-07 (trace 25d475eb48c9): reached the
        # adjuster -- the guard missed it, the judge caught it.
        "Clause HFL‑23 §2.1 excludes coverage for inundation, which does not apply here as the water source was a fixed installation.",
    ]
    must_pass = [
        'HFL-25 §2.1 reads: "We do not insure loss or damage caused by flood, including surface water from heavy rainfall".',
        "HFL-23 §2.2 (pluvial accumulation, limited indemnity) may be relevant; the adjuster should check the flood-zone condition.",
        "Deductible $2,500; sub-limit $15,000; policy limit $500,000.",
        "HFL-23 §2.2 does not apply where the Home is in a declared flood zone; the adjuster should confirm the zone.",
        "The policy was not in force on the loss date. No coverage decision is made here.",
        "[HFL-23 §2.2 — \"Flood damage is not covered\"](data/wordings/x.md#a) is cited for loss date 2024-08-14.",
    ]
    # Deliberately strict: "the policyholder asked whether they are covered"
    # trips too. The brief's line is the word itself; a false positive costs
    # one withheld summary, a false negative is the regulator's finding again.
    fails = [t for t in must_trip if not violations(t)] + [t for t in must_pass if violations(t)]
    for f in fails:
        print("FAIL", f)
    print(f"{len(must_trip) + len(must_pass)} cases, {len(fails)} failure(s)")
    return not fails


if __name__ == "__main__":
    import sys

    sys.exit(0 if selftest() else 1)
