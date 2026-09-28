"""Strip claimant names and claim numbers out of an adjuster's question.

    python redact.py --selftest
    python redact.py "Claimant Priya Raman, claim CLM-2026-004512: is the sump covered?"

This runs at ingress, in rag.answer, before retrieval, the model or the tracer
sees the question. Redacting only inside the trace writer would be simpler, but
then the model is answering text the trace does not hold, and no replay could
ever be byte-identical. Redacting first keeps the trace and the model input the
same thing — and a coverage decision never needed the claimant's name.

The hard part is not finding PII, it is not finding things that look like it.
"HO-0304 ed. 03-24", "E-17" and "Water Backup" are the whole question for an
adjuster, and redacting any of them would quietly break the answer. Hence the
stoplist, and the must-not-redact half of the self-test.
"""

import re
import sys

# --- Claim numbers -----------------------------------------------------------
# Form numbers (HO-0304), exclusion codes (E-17, F-3) and edition dates (03-24)
# are all short digit runs. Claim numbers are long ones, or they follow the word
# "claim". Anything that could be a form number is refused by the lookahead.
_NOT_A_FORM = r"(?!HO[-\s]?\d)(?![EF]-\d{1,2}\b)(?!\d{2}[-/]\d{2}\b)"

CLAIM_NUMBER_RES = [
    re.compile(r"\bCLM[-\s]?\d{2,4}[-\s]?\d{3,}\b"),
    re.compile(
        r"(?i:\bclaim\s*(?:no\.?|number|num\.?|#|id)?\s*[:#]?\s*)"
        + _NOT_A_FORM
        + r"(?P<id>[A-Z0-9][A-Z0-9-]*\d{4,}[A-Z0-9-]*)"
    ),
    re.compile(r"\b[A-Z]{2,4}-?\d{6,}\b"),
    re.compile(r"\b\d{2}-\d{5,}\b"),
]

# --- Claimant names ----------------------------------------------------------
_CAP = r"(?:[A-Z]['’])?[A-Z][a-zà-ÿ]+(?:[A-Z][a-zà-ÿ]+)?(?:-[A-Z][a-zà-ÿ]+)?"
_TRIGGER = (
    r"(?:\b(?:Mr|Mrs|Ms|Mx|Dr)\.?\s+"
    r"|\b(?i:claimant|insured|policyholder|homeowner|customer)\s+(?:is\s+)?)"
)
TRIGGERED_NAME_RE = re.compile(_TRIGGER + rf"(?P<name>{_CAP}(?:\s+{_CAP}){{0,2}})")
# The trailing lookahead lets a possessive through ("Priya Raman's basement")
# while refusing a name that is only the front of a longer word.
RUN_OF_CAPS_RE = re.compile(rf"(?<![\w'’-]){_CAP}(?:\s+{_CAP}){{1,2}}(?![\w-]|['’](?!s\b))")

# Capitalised words that are not names. Adjusters capitalise form titles,
# exclusion names and the first word of a sentence; every one of those would
# otherwise look like "Firstname Lastname".
STOPWORDS = {
    word.lower()
    for word in """
    A About Accidental Additional Addition Adjuster After Air Also An And Any Appliance Are
    As Assurance At Backup Backs Basement Basic Before Birds Breakdown Broad But Can Claim
    Claimant Claims Collapse Company Conditions Continuous Could Coverage Coverages Cracking
    Damage Declarations Deductible Definitions Deterioration Did Discharge Do Does Drain
    Drains Dwelling E Earth Edition Editions Endorsement Endorsements Enhanced Exclusion
    Exclusions Fire Flood For Form Forms Fungus Governmental Has Have Health Heavy Hi His
    Homeowner Homeowners Hospital How However I If In India Insurance Insured Intentional Is
    It Law Limit Limits Loss Mechanical Mediclaim Mold My Named Need New No Nuclear Of On Or
    Ordinance Other Our Overflow Part Please Perils Personal Policy Policyholder Power
    Property Provided Quick Re Revised Rot Rust Section See Seepage Settling Sewer Should
    So Special Structures Sublimit Sudden Sump Surface Tear The Their Theft They This
    Thanks Under Use Vacant Vandalism War Was Water Wear Wet What When Which While Who Why
    Will With Would Yes You Your January February March April May June July August
    September October November December Monday Tuesday Wednesday Thursday Friday Saturday
    Sunday
    """.split()
}


def _is_name(candidate):
    return all(token.lower() not in STOPWORDS for token in candidate.split())


def _strip_stopwords(candidate):
    """Drop leading capitalised stopwords, so "Called Priya Raman" yields the name."""
    tokens = candidate.split()
    while tokens and tokens[0].lower() in STOPWORDS:
        tokens.pop(0)
    return " ".join(tokens)


def _find_names(text):
    found = []
    for match in TRIGGERED_NAME_RE.finditer(text):
        name = _strip_stopwords(match.group("name"))
        if name and _is_name(name):
            found.append(name)
    for match in RUN_OF_CAPS_RE.finditer(text):
        name = _strip_stopwords(match.group(0))
        if len(name.split()) >= 2 and _is_name(name):
            found.append(name)
    # Longest first, so "Priya Raman" is replaced before "Priya" alone.
    return sorted(set(found), key=len, reverse=True)


def _find_claim_numbers(text):
    found = []
    for pattern in CLAIM_NUMBER_RES:
        for match in pattern.finditer(text):
            found.append(match.group("id") if "id" in pattern.groupindex else match.group(0))
    return sorted(set(found), key=len, reverse=True)


def redact(text):
    """Return (clean_text, found).

    `found` is a list of (kind, raw_value, placeholder). The raw values are
    handed to the trace writer as a last check and are never written anywhere;
    the trace records only how many of each kind were removed.
    """
    found = []
    clean = text

    for index, number in enumerate(_find_claim_numbers(text), start=1):
        placeholder = f"[CLAIM_NO_{index}]"
        clean = clean.replace(number, placeholder)
        found.append(("claim_number", number, placeholder))

    names = _find_names(clean)
    # A full name mentioned once is usually mentioned again by first or last
    # name alone. Those later mentions carry no trigger, so propagate each
    # detected name's parts and replace them wherever they stand as a word.
    people = []
    for name in names:
        if not any(name in person for person in people):
            people.append(name)
    for index, person in enumerate(people, start=1):
        placeholder = f"[CLAIMANT_{index}]"
        parts = [person] + [part for part in person.split() if len(part) >= 3]
        for part in parts:
            pattern = re.compile(rf"(?<![\w'’-]){re.escape(part)}(?![\w-])")
            if pattern.search(clean):
                clean = pattern.sub(placeholder, clean)
                found.append(("claimant_name", part, placeholder))

    return clean, found


def counts(found):
    """What the trace may keep: how many distinct things of each kind were removed."""
    return {
        "claimant_name": len({p for kind, _, p in found if kind == "claimant_name"}),
        "claim_number": len({p for kind, _, p in found if kind == "claim_number"}),
    }


# --- Self-test ---------------------------------------------------------------

MUST_REDACT = [
    ("Claimant Priya Raman, claim CLM-2026-004512: is the sump covered?", ["Priya", "Raman", "CLM-2026-004512"]),
    ("Marcus Oyelaran's basement flooded (claim #26-0418834).", ["Marcus", "Oyelaran", "26-0418834"]),
    ("Re: claim no. PRP20260771 / insured Liam O'Connell. Liam says the pump died.", ["Liam", "O'Connell", "PRP20260771"]),
    ("Called Fatima Al-Sayed back about claim number 7734219.", ["Fatima", "Al-Sayed", "7734219"]),
    ("Adjusting for Tomás Herrera — Mr. Herrera's roof caved in.", ["Tomás", "Herrera"]),
    ("Policyholder Grace Nguyen-Tran reports a burst pipe.", ["Grace", "Nguyen-Tran"]),
    ("This is for Jordan McBride, CLM-2025-118273.", ["Jordan", "McBride", "CLM-2025-118273"]),
]

MUST_NOT_REDACT = [
    "Does exclusion E-17 apply under form HO-0304 ed. 03-24?",
    "Does Endorsement HO-2405 attach to HO 03 04 (01/22)?",
    "Is Water Backup and Sump Overflow excluded under the Homeowners Special Form?",
    "What does F-3 say in HO-0500 Edition 01-23, and is the Enhanced Limit $25,000?",
    "The estimate is $18,500 and the deductible is $1,000.",
    "What documents go with the Mediclaim / Health Insurance claim form?",
    "Named Insured is on the Declarations page; Section III lists the exclusions.",
]


def selftest():
    failures = []
    for text, secrets in MUST_REDACT:
        clean, _ = redact(text)
        for secret in secrets:
            if re.search(rf"(?<![\w-]){re.escape(secret)}(?![\w-])", clean):
                failures.append(f"LEAK  {secret!r} survived in: {clean}")
    for text in MUST_NOT_REDACT:
        clean, found = redact(text)
        if clean != text:
            failures.append(f"OVER  {text!r} -> {clean!r} ({[v for _, v, _ in found]})")
    for line in failures:
        print(line)
    total = len(MUST_REDACT) + len(MUST_NOT_REDACT)
    print(f"{total} cases, {len(failures)} failure(s)")
    return not failures


def main():
    if sys.argv[1:] == ["--selftest"]:
        sys.exit(0 if selftest() else 1)
    text = " ".join(sys.argv[1:])
    if not text:
        sys.exit(__doc__)
    clean, found = redact(text)
    print(clean)
    print(counts(found))


if __name__ == "__main__":
    main()
