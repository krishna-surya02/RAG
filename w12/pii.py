"""PII handling for claim files: redact at the source, scrub again on the way out.

Two locks, as in week 5:
  1. redact.redact_many over every free-text field of one claim at once
     (pattern-based: names, addresses, phones, emails, injuries).
  2. a known-values scrub using what the *structured* record says about the
     policyholder (name, address, phone, email). Production has these from the
     policy system, so this lock is legitimate there too.

What neither lock knows in production -- witness and third-party names,
injuries -- rests on lock 1 alone. The audit (w12/evals/pii_audit.py) checks
against the generator's full ground truth, which only a synthetic corpus has.
"""

import redact
import tracing
from w12 import store, trace


def holder_values(policy_number):
    p = store.policy(policy_number) if policy_number else None
    if not p:
        return []
    h = p["holder"]
    vals = [h["name"], h["address"], h["street"], h["phone"], h["email"]]
    vals += [part for part in h["name"].split() if len(part) >= 3]
    return [v for v in vals if v]


def redact_claim(claim):
    """Redacted copies of a claim's free text, plus the raw values found (for
    the trace writer's second lock -- never returned to a caller)."""
    notes = [n["text"] for n in claim["adjuster_notes"]]
    texts = [claim["fnol_text"], *notes, *claim["photo_captions"]]
    clean, found = redact.redact_many(texts)
    n = len(notes)
    return {
        "fnol_text": clean[0],
        "adjuster_notes": [{"n": i + 1, "text": t} for i, t in enumerate(clean[1:1 + n])],
        "photo_captions": clean[1 + n:],
        "redacted_counts": redact.counts(found),
    }, [raw for _, raw, _ in found]


def scrub(obj, values):
    """Second lock on anything leaving a tool or server."""
    return tracing._scrub(obj, trace._patterns(values))
