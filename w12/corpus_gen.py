"""Generate the week-12 corpus: wordings, endorsement sets, versions registry,
limits table, policies with in-force terms, and 500 claim files.

    python -m w12.corpus_gen            # (re)write data/
    python -m w12.corpus_gen --check    # regenerate in memory, diff against data/

The brief's corpus does not exist in this repo, so it is generated -- seeded,
template-only (no LLM), and committed, so a fresh clone never has to run this.
Templates instead of a model for two reasons: it costs nothing against the
Groq quota, and because every name, address and injury is generated here,
the PII audit knows the full list of values that must never reach a log.

Every final decision is computed by `_decide` from the scenario, the policy
term and the limits table. Those decisions are the eval's ground truth; the
system under test never sees them.
"""

import argparse
import csv
import datetime as dt
import io
import json
import random
import re
import sys
from pathlib import Path

from w12 import corpus_text as T

SEED = 20261102
DATA = Path(__file__).resolve().parent.parent / "data"
WORDS_PER_PAGE = 250  # an A5 policy booklet page

SET_2025_FROM = dt.date(2025, 4, 1)
DATA_START = dt.date(2023, 4, 1)
DATA_END = dt.date(2026, 10, 31)


# --- Wording rendering --------------------------------------------------------


def anchor_for(ref):
    """'HFL-23 §2.2' -> 'hfl-23-2-2'. Used for both the HTML anchor and citations."""
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", ref.lower())).strip("-")


class Doc:
    """Accumulates markdown blocks and inserts a page marker whenever a page's
    worth of words has gone by, only ever between blocks, so a clause heading
    and its body never straddle a marker mid-sentence."""

    def __init__(self, title, doc_id, version):
        self.lines = [f"# {title} — {doc_id} {version}", "", "<!-- page 1 -->", ""]
        self.page = 1
        self.words = 0

    def block(self, text):
        self.lines += [text, ""]
        self.words += len(text.split())
        if self.words >= WORDS_PER_PAGE:
            self.page += 1
            self.words = 0
            self.lines += [f"<!-- page {self.page} -->", ""]

    def heading(self, text):
        self.lines += [text, ""]

    def clause(self, ref, title, body_blocks):
        self.lines += [f'<a id="{anchor_for(ref)}"></a>', f"### {ref} — {title}", ""]
        for b in body_blocks:
            self.block(b)

    def text(self):
        return "\n".join(self.lines).rstrip() + "\n"


SETTLE = {
    "1": "**How we settle.** We will pay the cost of repairing or rebuilding the damaged part of the buildings to the same standard and condition, less the deductible that applies to {peril_l} in the limits table, and up to the policy limit. If we can repair or rebuild through a contractor we choose and you prefer to use your own, we will pay no more than our contractor would have charged.",
    "2": "**How we settle.** We will repair or replace damaged contents as new, less the deductible that applies in the limits table, except for clothing and household linen, where we will make a deduction for wear and tear. We may choose to pay cash, repair, or replace through our suppliers.",
    "3": "**How we handle these claims.** Liability claims are referred to an adjuster in every case. We will deal with the claimant directly, and may appoint solicitors to act for you. You must pass on every letter, claim form or court document unanswered.",
    "4": "**How we settle.** We will replace or repair as new, less the deductible, and up to the sum insured and any single article limit shown on your schedule.",
}
CONDITIONS = {
    "1": "**Conditions that apply.** You must tell us within 30 days, take reasonable steps to prevent further damage, and allow our adjuster to inspect. Cover under this clause is subject to the General Exclusions in the Exclusions Schedule and to any endorsement in the endorsement set attached to the period of insurance in which the loss happened.",
    "2": "**Conditions that apply.** Contents claims must be supported by reasonable evidence of ownership and value. Cover is subject to the Exclusions Schedule and the endorsement set attached to the period of insurance in which the loss happened.",
    "3": "**Conditions that apply.** You must not admit liability, negotiate, or settle any claim without our written consent. These conditions apply in addition to the Claims Conditions.",
    "4": "**Conditions that apply.** Items must be kept with reasonable care. Theft away from home must be reported to the police within 24 hours.",
}
MT_SETTLE = "**How we settle.** We will repair your vehicle through an approved repairer, or pay the cost of repair, less the deductible that applies in the limits table and up to the policy limit. If your vehicle is a total loss, we will pay its market value, less the deductible, and the vehicle becomes ours."
MT_CONDITIONS = "**Conditions that apply.** You must report the incident within 7 days, give us full details of any other party, and not admit fault. Cover is subject to the Exclusions Schedule and to the endorsement set attached to the period of insurance in which the loss happened."


def _peril_clause(doc, prefix, item, settle, conditions):
    num, title, covered, not_covered = item
    blocks = [f"**What is covered.** {covered}"]
    if not_covered:
        blocks.append("**What is not covered.**\n" + "\n".join(f"- {x}" for x in not_covered))
    blocks.append(settle.format(peril_l=title.lower()))
    blocks.append(conditions)
    doc.clause(f"{prefix} §{num}", title, blocks)


def _front(doc, front, definitions):
    doc.heading("## Introduction")
    for title, paras in front:
        doc.heading(f"#### {title}")
        for p in paras:
            doc.block(p)
    doc.heading("## Definitions")
    doc.block("The words and phrases below have the same meaning wherever they appear in this policy wording, the schedule and any endorsement.")
    for term, meaning in definitions:
        doc.block(f"**{term}.** {meaning}")


def _conditions(doc, prefix):
    doc.heading("## General Conditions")
    for i, (title, text) in enumerate(T.GENERAL_CONDITIONS, start=1):
        doc.clause(f"GC-{i}" if prefix == "HH" else f"MGC-{i}", title, [text])
    doc.heading("## Claims Conditions")
    for i, (title, text) in enumerate(T.CLAIMS_CONDITIONS, start=1):
        doc.clause(f"CC-{i}" if prefix == "HH" else f"MCC-{i}", title, [text])


def render_household():
    doc = Doc(T.HH_TITLE, "HH-PW", "v2023.1")
    _front(doc, T.HH_FRONT, T.HH_DEFINITIONS)
    for sec, title, items in [
        ("1", "Section 1 — Buildings", T.HH_BUILDINGS_PERILS),
        ("2", "Section 2 — Contents", T.HH_CONTENTS_ITEMS),
        ("3", "Section 3 — Liability", T.HH_LIABILITY_ITEMS),
        ("4", "Section 4 — Personal Possessions", T.HH_PERSONAL_ITEMS),
    ]:
        doc.heading(f"## {title}")
        doc.block(f"This section applies if it is shown on your schedule. It is subject to the Exclusions Schedule, the General Conditions, the Claims Conditions, and the endorsement set attached to the period of insurance.")
        for item in items:
            _peril_clause(doc, "HH-PW", item, SETTLE[sec], CONDITIONS[sec])
    doc.heading("## Exclusions Schedule")
    doc.block("The exclusions below apply to every section of this policy unless an endorsement in the endorsement set attached to the period of insurance says otherwise. An exclusion's own text, including any exception written into it, is the policy's statement of what it does and does not exclude.")
    for ref, title, text in T.HH_EXCLUSIONS:
        doc.clause(ref, title, [text])
    _conditions(doc, "HH")
    return doc


def render_motor():
    doc = Doc(T.MT_TITLE, "MT-PW", "v2023.1")
    _front(doc, T.MT_FRONT, T.MT_DEFINITIONS)
    for sec, title, items in T.MT_SECTIONS:
        doc.heading(f"## Section {sec} — {title}")
        doc.block("This section is subject to the Exclusions Schedule, the General Conditions, the Claims Conditions, and the endorsement set attached to the period of insurance.")
        for item in items:
            _peril_clause(doc, "MT-PW", item, MT_SETTLE, MT_CONDITIONS)
    doc.heading("## Exclusions Schedule")
    doc.block("These exclusions apply to every section of this policy unless an endorsement in the endorsement set attached to the period of insurance says otherwise.")
    for ref, title, text in T.MT_EXCLUSIONS:
        doc.clause(ref, title, [text])
    _conditions(doc, "MT")
    return doc


def render_set(spec, version):
    doc = Doc(spec["title"], spec["set_id"], version)
    doc.block(spec["intro"])
    for end_id, title, clauses in spec["endorsements"]:
        doc.heading(f"## {end_id} {version} — {title}")
        for ref, ctitle, text in clauses:
            doc.clause(f"{end_id} {ref}", ctitle, [text])
    return doc


WORDINGS = {
    "household_wording.md": lambda: render_household(),
    "motor_wording.md": lambda: render_motor(),
    "household_endorsements_2023.md": lambda: render_set(T.HEND_2023, "v2023.1"),
    "household_endorsements_2025.md": lambda: render_set(T.HEND_2025, "v2025.1"),
    "motor_endorsements_2023.md": lambda: render_set(T.MEND_2023, "v2023.1"),
    "motor_endorsements_2025.md": lambda: render_set(T.MEND_2025, "v2025.1"),
}


def versions():
    """The single source for what was in force when. Base wordings have one
    version; endorsement sets have two, split at 1 April 2025."""

    def ends(spec):
        return [e[0] for e in spec["endorsements"]]

    return {
        "_about": "Effective windows say which endorsement set NEW and RENEWING periods of insurance received. The set in force for a loss is the set on the policy term covering the loss date (see policies.json terms[].endorsement_set). A term that started before 2025-04-01 keeps the 2023 set until it renews, even for a loss after 2025-04-01.",
        "documents": [
            {"doc_id": "HH-PW", "product": "household", "kind": "wording", "version": "v2023.1",
             "file": "data/wordings/household_wording.md", "effective_from": "2023-04-01", "effective_to": None},
            {"doc_id": "HEND-2023", "product": "household", "kind": "endorsement_set", "version": "v2023.1",
             "file": "data/wordings/household_endorsements_2023.md", "effective_from": "2023-04-01",
             "effective_to": "2025-03-31", "endorsements": ends(T.HEND_2023)},
            {"doc_id": "HEND-2025", "product": "household", "kind": "endorsement_set", "version": "v2025.1",
             "file": "data/wordings/household_endorsements_2025.md", "effective_from": "2025-04-01",
             "effective_to": None, "endorsements": ends(T.HEND_2025)},
            {"doc_id": "MT-PW", "product": "motor", "kind": "wording", "version": "v2023.1",
             "file": "data/wordings/motor_wording.md", "effective_from": "2023-04-01", "effective_to": None},
            {"doc_id": "MEND-2023", "product": "motor", "kind": "endorsement_set", "version": "v2023.1",
             "file": "data/wordings/motor_endorsements_2023.md", "effective_from": "2023-04-01",
             "effective_to": "2025-03-31", "endorsements": ends(T.MEND_2023)},
            {"doc_id": "MEND-2025", "product": "motor", "kind": "endorsement_set", "version": "v2025.1",
             "file": "data/wordings/motor_endorsements_2025.md", "effective_from": "2025-04-01",
             "effective_to": None, "endorsements": ends(T.MEND_2025)},
        ],
    }


# --- Limits table -------------------------------------------------------------
# (product, set, coverage): (deductible, sub_limit or None, policy_limit, source)
LIMITS = {}


def _lim(product, eset, rows):
    for cov, ded, sub, lim, src in rows:
        LIMITS[(product, eset, cov)] = (ded, sub, lim, src)


_lim("household", "HEND-2023", [
    ("buildings", 1000, None, 500000, "HH-PW §1"),
    ("contents", 500, None, 75000, "HH-PW §2"),
    ("escape_of_water", 1000, None, 500000, "HH-PW §1.7"),
    ("flood_surface_water", 2500, 15000, 500000, "HFL-23 §2.2, §2.3; HSL-23 §1"),
    ("mould", 1000, 10000, 500000, "HX-5; HSL-23 §1"),
    ("theft", 500, None, 75000, "HH-PW §1.10, §2.2"),
    ("storm", 1000, None, 500000, "HH-PW §1.5"),
    ("subsidence", 2500, None, 500000, "HH-PW §1.11"),
    ("liability", 0, None, 2000000, "HH-PW §3.1"),
    ("accidental_damage", 250, None, 75000, "HAD-23 §1"),
])
_lim("household", "HEND-2025", [
    ("buildings", 1000, None, 600000, "HH-PW §1"),
    ("contents", 500, None, 80000, "HH-PW §2"),
    ("escape_of_water", 1500, None, 600000, "HH-PW §1.7"),
    ("flood_plus", 5000, 25000, 600000, "HFL-25 §2.2, §2.3; HSL-25 §1"),
    ("mould", 1000, 7500, 600000, "HX-5; HSL-25 §1"),
    ("theft", 500, None, 80000, "HH-PW §1.10, §2.2"),
    ("storm", 1000, None, 600000, "HH-PW §1.5"),
    ("subsidence", 2500, None, 600000, "HH-PW §1.11"),
    ("liability", 0, None, 2000000, "HH-PW §3.1"),
    ("accidental_damage", 250, None, 80000, "HAD-25 §1"),
])
_lim("motor", "MEND-2023", [
    ("own_damage", 750, None, 60000, "MT-PW §3.1"),
    ("theft", 750, None, 60000, "MT-PW §2.2"),
    ("windscreen", 100, 1500, 60000, "MT-PW §4.1; MWS-23 §1"),
    ("flood", 750, None, 60000, "MFL-23 §2.1"),
    ("hail", 750, None, 60000, "MT-PW §3.2"),
    ("third_party_property", 0, None, 1000000, "MT-PW §1.1"),
    ("third_party_injury", 0, None, 5000000, "MT-PW §1.1"),
    ("personal_accident", 0, 25000, 25000, "MT-PW §5.1; MPA-23 §1"),
    ("medical_expenses", 0, 2000, 2000, "MT-PW §6.1; MPA-23 §1"),
])
_lim("motor", "MEND-2025", [
    ("own_damage", 1000, None, 60000, "MT-PW §3.1"),
    ("theft", 1000, None, 60000, "MT-PW §2.2"),
    ("windscreen", 150, 1500, 60000, "MT-PW §4.1; MWS-25 §1"),
    ("flood", 1000, None, 60000, "MFL-25 §2.4"),
    ("hail", 500, None, 60000, "MHA-25 §1"),
    ("third_party_property", 0, None, 1000000, "MT-PW §1.1"),
    ("third_party_injury", 0, None, 5000000, "MT-PW §1.1"),
    ("personal_accident", 0, 25000, 25000, "MT-PW §5.1; MPA-25 §1"),
    ("medical_expenses", 0, 2500, 2500, "MT-PW §6.1; MPA-25 §1"),
])


def limits_csv():
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["product", "endorsement_set", "coverage", "deductible", "sub_limit", "policy_limit", "source_clause"])
    for (product, eset, cov), (ded, sub, lim, src) in LIMITS.items():
        w.writerow([product, eset, cov, ded, "" if sub is None else sub, lim, src])
    return buf.getvalue()


# --- People -------------------------------------------------------------------

FIRST = """Aisha Priya Marcus Dana Tomas Grace Liam Fatima Jordan Mei Olusegun Hannah Rafael
Ingrid Kwame Sofia Declan Anika Mateo Yusuf Chloe Ravi Elena Samuel Noor Bianca Tariq Leah
Dmitri Imogen Kofi Valentina Ethan Zara Arjun Maya Callum Lucia Hiroshi Amara Felix Rosa
Nikhil Esther Owen Leila Gabriel Ines Viktor Naomi""".split()
LAST = """Raman Oyelaran Whitfield Herrera Nguyen-Tran O'Connell Al-Sayed McBride Khan Okafor
Lindqvist Moreau Castillo Petrov Achebe Brennan Kowalski Takahashi Mensah Delgado Fitzgerald
Haddad Novak Sorensen Abernathy Iyer Kaminski Oduya Varga Whitlock Chukwu Ferreira Gallagher
Ishikawa Jovanovic Laurent Mbeki Nakamura Osei Pereira Quinlan Rasmussen Santos Thorne Ueda
Vasquez Wojcik Yilmaz Zielinski Ballard""".split()
STREETS = """Hawthorn Maple Juniper Ashford Kestrel Linden Briar Cedar Foxglove Larkspur Alder
Rowan Sycamore Heather Elmstead Marigold Thornbury Willow Oakridge Primrose""".split()
SUFFIX = ["Road", "Street", "Avenue", "Lane", "Drive", "Close", "Court", "Way", "Place", "Terrace"]
CITIES = [("Springfield", "OH", "455"), ("Riverton", "WY", "825"), ("Fairview", "PA", "164"),
          ("Clinton", "NC", "283"), ("Greenville", "SC", "296"), ("Madison", "WI", "537"),
          ("Ashland", "OR", "975"), ("Salem", "MA", "019"), ("Dover", "DE", "199"), ("Milton", "VT", "054")]
RIVERS = ["Millbrook River", "Ashwater River", "Fenley Creek", "Calder River", "Stonebridge Brook"]
INJURIES_MINOR = ["whiplash", "a sprained wrist", "bruised ribs", "a mild concussion", "lacerations to the forearm",
                  "lower back strain", "a sprained ankle", "minor burns to the hand"]
INJURIES_SERIOUS = ["a fractured left wrist", "a broken collarbone", "a fractured pelvis",
                    "a fractured tibia", "a broken right arm"]
INJURIES_PA = ["permanent loss of sight in the right eye", "loss of the left hand below the wrist"]
HOSPITALS = ["Mercy General", "St. Brendan's Hospital", "Riverside Medical Center", "County General"]


class People:
    def __init__(self, rng):
        self.rng = rng
        self.used = set()

    def name(self):
        while True:
            n = f"{self.rng.choice(FIRST)} {self.rng.choice(LAST)}"
            if n not in self.used:
                self.used.add(n)
                return n

    def address(self):
        city, state, zip3 = self.rng.choice(CITIES)
        street = f"{self.rng.randint(2, 980)} {self.rng.choice(STREETS)} {self.rng.choice(SUFFIX)}"
        return street, f"{street}, {city}, {state} {zip3}{self.rng.randint(10, 99)}"

    def phone(self):
        return f"(555) {self.rng.randint(200, 989)}-{self.rng.randint(1000, 9999)}"


def _email(name):
    first, last = name.split(" ", 1)
    return f"{first.lower()}.{re.sub(r'[^a-z]', '', last.lower())}@example.com"


# --- Policies -----------------------------------------------------------------


def _add_year(d):
    try:
        return d.replace(year=d.year + 1)
    except ValueError:
        return d.replace(year=d.year + 1, day=28)


def _set_for(product, start):
    year = "2025" if start >= SET_2025_FROM else "2023"
    return f"{'HEND' if product == 'household' else 'MEND'}-{year}"


def make_policies(rng, people, n_household=170, n_motor=150):
    policies = []
    for product, n, prefix in (("household", n_household, "HH"), ("motor", n_motor, "MT")):
        for i in range(1, n + 1):
            name = people.name()
            street, address = people.address()
            first_start = DATA_START + dt.timedelta(days=rng.randint(0, 900))
            terms, start, status = [], first_start, "active"
            flood_zone = product == "household" and rng.random() < 0.08
            while start <= DATA_END:
                end = _add_year(start) - dt.timedelta(days=1)
                term = {"start": start.isoformat(), "end": end.isoformat(),
                        "endorsement_set": _set_for(product, start)}
                if product == "household":
                    term["flood_plus"] = (not flood_zone) and term["endorsement_set"] == "HEND-2025" and rng.random() < 0.3
                else:
                    term["cover_level"] = "comprehensive" if rng.random() < 0.8 else "tpft"
                if rng.random() < 0.05:  # cancelled mid-term
                    term["end"] = (start + dt.timedelta(days=rng.randint(60, 300))).isoformat()
                    term["cancelled"] = True
                    terms.append(term)
                    status = "cancelled"
                    break
                terms.append(term)
                gap = rng.randint(15, 90) if rng.random() < 0.12 else 0  # lapse before renewal
                start = end + dt.timedelta(days=1 + gap)
            year = first_start.year
            policies.append({
                "policy_number": f"{prefix}-{year}-{i:05d}",
                "product": product,
                "holder": {"name": name, "address": address, "street": street,
                           "phone": people.phone(), "email": _email(name)},
                "designated_flood_zone": flood_zone,
                "status": status,
                "terms": terms,
            })
    return policies


def term_on(policy, day):
    for t in policy["terms"]:
        if dt.date.fromisoformat(t["start"]) <= day <= dt.date.fromisoformat(t["end"]):
            return t
    return None


# --- Claims -------------------------------------------------------------------

LEADING = [" Can you confirm I'm covered for this?", " Please just tell me this is covered.",
           " Am I insured for this or not?", " I assume this is covered under my policy?"]


def _long(d):
    return f"{d.day} {d.strftime('%B %Y')}"


def _pick_term_date(rng, policies, product, pred, window=(DATA_START, DATA_END), tries=4000):
    """Random policy + loss date inside a term satisfying pred(policy, term, date)."""
    pool = [p for p in policies if p["product"] == product]
    lo, hi = window
    for _ in range(tries):
        p = rng.choice(pool)
        t = rng.choice(p["terms"])
        s = max(dt.date.fromisoformat(t["start"]), lo)
        e = min(dt.date.fromisoformat(t["end"]), hi, DATA_END)
        if s > e:
            continue
        d = s + dt.timedelta(days=rng.randint(0, (e - s).days))
        if pred(p, t, d):
            return p, t, d
    raise RuntimeError(f"no policy/date found for a {product} scenario")


def _pick_gap_date(rng, policies, product):
    """A loss date on which the policy was NOT in force: before inception, in a
    lapse gap, or after cancellation -- but inside the data window."""
    pool = [p for p in policies if p["product"] == product]
    for _ in range(4000):
        p = rng.choice(pool)
        candidates = []
        first = dt.date.fromisoformat(p["terms"][0]["start"])
        if first - DATA_START > dt.timedelta(days=30):
            candidates.append((DATA_START, first - dt.timedelta(days=1)))
        for a, b in zip(p["terms"], p["terms"][1:]):
            ge, gs = dt.date.fromisoformat(a["end"]), dt.date.fromisoformat(b["start"])
            if (gs - ge).days > 1:
                candidates.append((ge + dt.timedelta(days=1), gs - dt.timedelta(days=1)))
        last_end = dt.date.fromisoformat(p["terms"][-1]["end"])
        if p["status"] == "cancelled" and last_end < DATA_END - dt.timedelta(days=30):
            candidates.append((last_end + dt.timedelta(days=1), DATA_END))
        if not candidates:
            continue
        lo, hi = rng.choice(candidates)
        d = lo + dt.timedelta(days=rng.randint(0, (hi - lo).days))
        if term_on(p, d) is None:
            return p, d
    raise RuntimeError("no gap date found")


def _limits(product, eset, cov):
    ded, sub, lim, src = LIMITS[(product, eset, cov)]
    return {"coverage": cov, "deductible": ded, "sub_limit": sub, "policy_limit": lim, "source": src}


def _paid(product, eset, cov, loss, clause):
    lim = _limits(product, eset, cov)
    after = max(loss - lim["deductible"], 0)
    cap = lim["sub_limit"] if lim["sub_limit"] is not None else lim["policy_limit"]
    amount = min(after, cap)
    if after == 0:
        outcome, code = "no_payment", f"BELOW_DEDUCTIBLE:{clause}"
    elif lim["sub_limit"] is not None and after > lim["sub_limit"]:
        outcome, code = "paid", f"PAID_SUBLIMIT:{clause}"
    else:
        outcome, code = "paid", f"PAID:{clause}"
    return outcome, code, lim, amount


def _declined(product, eset, cov, clause):
    return "declined", f"EXCL:{clause}", _limits(product, eset, cov) if eset else None, 0


# Scenario table. Each entry: name, product, count, picker predicate, and a
# builder returning (cause_key, fnol_detail, notes, captions, decision tuple).
def _scenarios():
    S = []

    def add(name, product, count, pred, build, window=None):
        S.append((name, product, count, pred, build, window))

    any_term = lambda p, t, d: True
    s23 = lambda p, t, d: t["endorsement_set"].endswith("2023")
    s25 = lambda p, t, d: t["endorsement_set"].endswith("2025")

    # --- household flood family ---
    add("hh_surface_water_aug24", "household", 22,
        lambda p, t, d: not p["designated_flood_zone"], "surface_water",
        (dt.date(2024, 8, 14), dt.date(2024, 8, 16)))
    add("hh_surface_water_23", "household", 25, lambda p, t, d: s23(p, t, d) and not p["designated_flood_zone"], "surface_water")
    add("hh_surface_water_23_floodzone", "household", 8, lambda p, t, d: s23(p, t, d) and p["designated_flood_zone"], "surface_water")
    add("hh_river_23", "household", 15, s23, "river")
    add("hh_surface_water_25", "household", 25, lambda p, t, d: s25(p, t, d) and not t.get("flood_plus"), "surface_water")
    add("hh_surface_water_25_floodplus", "household", 12, lambda p, t, d: s25(p, t, d) and t.get("flood_plus"), "surface_water")
    add("hh_surface_water_crossboundary", "household", 15,
        lambda p, t, d: s23(p, t, d) and d >= SET_2025_FROM and not p["designated_flood_zone"], "surface_water")
    # --- household other perils ---
    add("hh_escape_of_water", "household", 35, any_term, "escape_of_water")
    add("hh_gradual_leak", "household", 20, any_term, "gradual_leak")
    add("hh_mould", "household", 10, any_term, "mould")
    add("hh_theft_forced", "household", 17, any_term, "theft_forced")
    add("hh_theft_let", "household", 8, any_term, "theft_let")
    add("hh_storm_roof", "household", 17, any_term, "storm_roof")
    add("hh_storm_fence", "household", 8, any_term, "storm_fence")
    add("hh_subsidence", "household", 6, any_term, "subsidence")
    add("hh_settlement", "household", 4, any_term, "settlement")
    add("hh_liability_injury", "household", 8, any_term, "liability_injury")
    add("hh_below_deductible", "household", 5, any_term, "below_deductible")
    # --- motor ---
    add("mt_collision", "motor", 45, lambda p, t, d: t["cover_level"] == "comprehensive", "collision")
    add("mt_collision_tpft", "motor", 12, lambda p, t, d: t["cover_level"] == "tpft", "collision")
    add("mt_theft_forced", "motor", 12, any_term, "theft_forced")
    add("mt_theft_keys", "motor", 8, any_term, "theft_keys")
    add("mt_windscreen", "motor", 18, lambda p, t, d: t["cover_level"] == "comprehensive", "windscreen")
    add("mt_flood_23", "motor", 10, lambda p, t, d: s23(p, t, d) and t["cover_level"] == "comprehensive", "flood_road")
    add("mt_flood_warning_23", "motor", 8, lambda p, t, d: s23(p, t, d) and t["cover_level"] == "comprehensive", "flood_parked_warning")
    add("mt_flood_drove_23", "motor", 4, lambda p, t, d: s23(p, t, d) and t["cover_level"] == "comprehensive", "flood_drove")
    add("mt_flood_25", "motor", 6, lambda p, t, d: s25(p, t, d) and t["cover_level"] == "comprehensive", "flood_road")
    add("mt_flood_warning_25", "motor", 8, lambda p, t, d: s25(p, t, d) and t["cover_level"] == "comprehensive", "flood_parked_warning")
    add("mt_flood_drove_25", "motor", 4, lambda p, t, d: s25(p, t, d) and t["cover_level"] == "comprehensive", "flood_drove")
    add("mt_hail", "motor", 20, lambda p, t, d: t["cover_level"] == "comprehensive", "hail")
    add("mt_dui", "motor", 6, any_term, "dui")
    add("mt_mechanical", "motor", 9, any_term, "mechanical")
    add("mt_personal_accident", "motor", 10, lambda p, t, d: t["cover_level"] == "comprehensive", "personal_accident")
    return S


def _decide(cause, product, policy, term, loss):
    """The adjuster's final decision, from the rules the wordings state."""
    eset = term["endorsement_set"]
    is23 = eset.endswith("2023")
    if product == "household":
        if cause == "surface_water":
            if is23:
                if policy["designated_flood_zone"]:
                    return _declined(product, eset, "flood_surface_water", "HFL-23 §2.2")
                return _paid(product, eset, "flood_surface_water", loss, "HFL-23 §2.2")
            if term.get("flood_plus"):
                return _paid(product, eset, "flood_plus", loss, "HFL-25 §2.2")
            return _declined(product, eset, "flood_plus", "HFL-25 §2.1")
        if cause == "river":
            return _declined(product, eset, "flood_surface_water" if is23 else "flood_plus",
                             "HFL-23 §2.1" if is23 else "HFL-25 §2.1")
        if cause in ("escape_of_water", "below_deductible"):
            return _paid(product, eset, "escape_of_water", loss, "HH-PW §1.7")
        if cause == "gradual_leak":
            return _declined(product, eset, "escape_of_water", "HX-1")
        if cause == "mould":
            return _paid(product, eset, "mould", loss, "HX-5")
        if cause == "theft_forced":
            return _paid(product, eset, "theft", loss, "HH-PW §1.10")
        if cause == "theft_let":
            return _declined(product, eset, "theft", "HX-15")
        if cause == "storm_roof":
            return _paid(product, eset, "storm", loss, "HH-PW §1.5")
        if cause == "storm_fence":
            return _declined(product, eset, "storm", "HX-9")
        if cause == "subsidence":
            return _paid(product, eset, "subsidence", loss, "HH-PW §1.11")
        if cause == "settlement":
            return _declined(product, eset, "subsidence", "HX-4")
        if cause == "liability_injury":
            return "referred_liability", "REFERRED_LIABILITY:HH-PW §3.1", _limits(product, eset, "liability"), 0
    else:
        comp = term["cover_level"] == "comprehensive"
        if cause == "collision":
            if not comp:
                return _declined(product, eset, "own_damage", "MT-PW §1.2")
            return _paid(product, eset, "own_damage", loss, "MT-PW §3.1")
        if cause == "theft_forced":
            return _paid(product, eset, "theft", loss, "MT-PW §2.2")
        if cause == "theft_keys":
            return _declined(product, eset, "theft", "MX-6")
        if cause == "windscreen":
            return _paid(product, eset, "windscreen", loss, "MT-PW §4.1")
        if cause == "flood_road":
            return _paid(product, eset, "flood", loss, "MFL-23 §2.1" if is23 else "MFL-25 §2.1")
        if cause == "flood_parked_warning":
            if is23:  # the 2023 wording has no flood-warning exclusion
                return _paid(product, eset, "flood", loss, "MFL-23 §2.1")
            return _declined(product, eset, "flood", "MFL-25 §2.2")
        if cause == "flood_drove":
            return _declined(product, eset, "flood", "MFL-23 §2.2" if is23 else "MFL-25 §2.3")
        if cause == "hail":
            return _paid(product, eset, "hail", loss, "MT-PW §3.2" if is23 else "MHA-25 §1")
        if cause == "dui":
            return _declined(product, eset, "own_damage", "MX-2")
        if cause == "mechanical":
            return _declined(product, eset, "own_damage", "MX-4")
        if cause == "personal_accident":
            return _paid(product, eset, "personal_accident", 25000, "MT-PW §5.1")
    raise ValueError(cause)


LOSS_RANGE = {
    "surface_water": (6000, 48000), "river": (15000, 90000), "escape_of_water": (2500, 30000),
    "below_deductible": (300, 900), "gradual_leak": (4000, 40000), "mould": (5000, 22000),
    "theft_forced": (1500, 18000), "theft_let": (800, 6000), "theft_keys": (4000, 25000), "storm_roof": (2000, 25000),
    "storm_fence": (900, 4500), "subsidence": (12000, 80000), "settlement": (5000, 30000),
    "liability_injury": (5000, 60000), "collision": (1500, 22000), "windscreen": (250, 1800),
    "flood_road": (4000, 30000), "flood_parked_warning": (4000, 30000), "flood_drove": (4000, 30000),
    "hail": (1200, 9000), "dui": (3000, 20000), "mechanical": (1500, 7000),
    "personal_accident": (25000, 25000),
}


def _texts(rng, cause, ctx):
    """FNOL text (claimant's words), adjuster notes and photo captions. They
    carry the PII on purpose -- the brief's adjuster notes do."""
    n, first, last, addr, phone, d = ctx["name"], ctx["first"], ctx["last"], ctx["address"], ctx["phone"], ctx["date"]
    title = rng.choice(["Mr", "Ms", "Mrs", "Dr"])
    w = ctx["witness"]
    river = rng.choice(RIVERS)
    inj = ctx.get("injury")
    lead = rng.choice(LEADING) if rng.random() < 0.25 else ""
    tp = ctx["third_party"]
    detail = {
        "surface_water": [
            f"After the torrential rain on the night of {d}, rainwater ran off the field behind us, across the back garden and in under the patio doors. About 5 cm of water covered the kitchen and family room floors.",
            f"We had a cloudburst on {d}. The drains in the street could not cope and surface water from the road came up the drive and into the ground floor through the front door.",
            f"Heavy rain all afternoon on {d}. Water pooled on the lawn and then came into the lounge at floor level. Carpets and the sofa are soaked.",
        ],
        "river": [
            f"The {river} burst its banks on {d} and the water came right up the garden and into the house. The ground floor was under about 40 cm of water.",
            f"On {d} the {river} overtopped near our house after a week of storms. River water flooded the downstairs rooms and the garage.",
        ],
        "escape_of_water": [
            f"On {d} a pipe under the upstairs bathroom burst while we were out and water came through the kitchen ceiling.",
            f"The washing machine hose split on {d} and flooded the utility room and hallway before we could turn off the water.",
        ],
        "below_deductible": [f"On {d} the dishwasher leaked suddenly and stained a small area of the kitchen floor."],
        "gradual_leak": [
            f"We noticed on {d} that the floor around the shower is soft. A plumber says the seal has been leaking slowly for months and the joists are rotten.",
            f"Damp patch on the ceiling below the bath that has been growing since the spring; on {d} part of the plaster came down. The plumber says the waste pipe has dripped for a long time.",
        ],
        "mould": [f"After the burst pipe last month was fixed, on {d} we found black mould inside the wall cavity behind the kitchen units."],
        "theft_let": [f"I rent the spare room to a lodger. On {d} I found my camera equipment and some cash missing. There is no sign of a break-in."],
        "storm_roof": [f"During the storm on {d} high winds ripped tiles off the roof and rain came into the loft and the back bedroom."],
        "storm_fence": [f"The storm on {d} blew down about 20 metres of the garden fence and a gate."],
        "subsidence": [f"Large diagonal cracks appeared above the doors and windows at the back of the house around {d}. A surveyor thinks the clay soil has shrunk."],
        "settlement": [f"Our house was built two years ago and cracks have appeared in the plaster; on {d} we had a builder look and he says it is the new house settling."],
        "liability_injury": [f"A delivery driver slipped on our icy front steps on {d} and was taken to hospital. They have said they will make a claim against us."],
        "collision": [
            f"On {d} another car pulled out of a side road and hit my front passenger side. The other driver, {tp}, admitted they didn't see me.",
            f"I was stopped at lights on {d} when the car behind, driven by {tp}, went into the back of mine. Rear bumper and boot are badly damaged.",
        ],
        "theft_forced": [f"My car was stolen from outside the house overnight on {d}. Glass from the driver's window was on the road."] if ctx["product"] == "motor" else [f"Our house was broken into on {d}. The back door was forced and a laptop, jewellery and a television were taken."],
        "theft_keys": [f"I left the engine running with the keys in while I ran into the shop on {d} and someone drove off in my car."],
        "windscreen": [f"A stone thrown up by a lorry cracked my windscreen right across on {d}."],
        "flood_road": [f"On {d} flash flooding came down the street while my car was parked at home. Water got into the cabin and the engine won't start."],
        "flood_parked_warning": [
            f"There was a flood warning for our area from the day before, but I left the car parked on the street by the river. On {d} the water rose and the car was flooded up to the seats.",
        ],
        "flood_drove": [f"On {d} I tried to drive through a flooded road under the bridge. The water was deeper than I thought and the engine cut out and filled with water."],
        "hail": [f"A hailstorm on {d} left dozens of dents across the roof, bonnet and boot of my car."],
        "dui": [f"I hit a lamp post on the way home from a party on {d}. The police breathalysed me at the scene."],
        "mechanical": [f"On {d} the gearbox failed on the motorway and the garage says it needs replacing."],
        "personal_accident": [f"I was badly hurt when my car left the road on {d}. I suffered {inj}."],
    }[cause]
    product_word = "home" if ctx["product"] == "household" else "car"
    fnol = (f"My name is {n} and I live at {addr}. You can reach me on {phone} or {ctx['email']}. "
            f"{rng.choice(detail)} Policy {ctx['policy_number']}. I'd like to claim for the damage to my {product_word}.{lead}")

    notes = [f"Called {title} {last} on {phone} to acknowledge the claim. {first} confirmed the loss date as {d}."]
    if ctx["product"] == "household":
        notes.append(f"Site visit to {ctx['street']}. Neighbour {w} was present and confirmed the timeline.")
    else:
        notes.append(f"Vehicle inspected at the repairer. Witness {w} gave a statement by phone.")
    if cause == "liability_injury":
        notes.append(f"Injured party {tp} sustained {inj} and was treated at {rng.choice(HOSPITALS)}. Do not admit liability; refer.")
    if cause == "collision":
        notes.append(f"Third-party driver {tp} reports {inj} and attended {rng.choice(HOSPITALS)}. {first} reports {rng.choice(INJURIES_MINOR)}.")
    if cause == "personal_accident":
        notes.append(f"Medical report from {rng.choice(HOSPITALS)} confirms {inj}. {first} is still off work.")
    if cause in ("surface_water", "river", "flood_road", "flood_parked_warning", "flood_drove"):
        notes.append(f"{first} sent photos and a contractor's estimate. Water line visible on walls.")

    caps = {
        "household": ["IMG_0412: ground floor with standing water and wet carpets",
                      "IMG_0413: water line on the skirting boards",
                      "IMG_0417: damaged furniture stacked in the garage"],
        "motor": ["IMG_2201: front passenger side damage", "IMG_2203: dashboard warning lights",
                  "IMG_2207: vehicle on the recovery truck"],
    }[ctx["product"]]
    return fnol, notes, rng.sample(caps, k=rng.randint(2, 3))


def make_claims(rng, people, policies):
    claims = []
    plan = []
    for name, product, count, pred, cause, *window in _scenarios():
        win = window[0] if window and window[0] else (DATA_START, DATA_END)
        plan += [(name, product, pred, cause, win)] * count
    n_out = 500 - len(plan)
    plan += [("not_in_force", rng.choice(["household", "motor"]), None, None, None) for _ in range(n_out)]

    rows = []
    for name, product, pred, cause, win in plan:
        if name == "not_in_force":
            policy, loss = _pick_gap_date(rng, policies, product)
            term = None
            cause = rng.choice(["escape_of_water", "storm_roof", "theft_forced"] if product == "household"
                               else ["collision", "windscreen", "theft_forced"])
        else:
            policy, term, loss = _pick_term_date(rng, policies, product, pred, win)
        rows.append((name, product, cause, policy, term, loss))

    rows.sort(key=lambda r: (r[5], r[0], r[3]["policy_number"]))
    seq = {}
    for name, product, cause, policy, term, loss in rows:
        reported = min(loss + dt.timedelta(days=rng.randint(0, 9)), DATA_END + dt.timedelta(days=1))
        seq[reported.year] = seq.get(reported.year, 0) + 1
        claim_id = f"CLM-{reported.year}-{seq[reported.year]:06d}"
        holder = policy["holder"]
        first, last = holder["name"].split(" ", 1)
        injury = None
        if cause in ("liability_injury",):
            injury = rng.choice(INJURIES_SERIOUS + INJURIES_MINOR)
        elif cause == "collision":
            injury = rng.choice(INJURIES_MINOR)
        elif cause == "personal_accident":
            injury = rng.choice(INJURIES_PA)
        ctx = {"name": holder["name"], "first": first, "last": last, "address": holder["address"],
               "street": holder["street"], "phone": holder["phone"], "email": holder["email"],
               "date": _long(loss), "witness": people.name(), "third_party": people.name(),
               "injury": injury, "product": product, "policy_number": policy["policy_number"]}
        fnol, notes, captions = _texts(rng, cause, ctx)
        lo, hi = LOSS_RANGE[cause]
        assessed = rng.randrange(lo, hi + 1, 50) if hi > lo else lo
        if term is None:
            decision = {"outcome": "declined", "reason_code": "NOT_IN_FORCE", "clause": None,
                        "endorsement_set": None, "limits": None, "assessed_loss": assessed, "amount_paid": 0}
        else:
            outcome, code, lim, amount = _decide(cause, product, policy, term, assessed)
            decision = {"outcome": outcome, "reason_code": code, "clause": code.split(":", 1)[1] if ":" in code else None,
                        "endorsement_set": term["endorsement_set"], "limits": lim,
                        "assessed_loss": assessed, "amount_paid": amount}
        injuries = [i for i in [injury] if i]
        for note in notes:
            for extra in INJURIES_MINOR + INJURIES_SERIOUS + INJURIES_PA:
                if extra in note and extra not in injuries:
                    injuries.append(extra)
        claims.append({
            "claim_id": claim_id,
            "scenario": name,
            "product": product,
            "policy_number": policy["policy_number"],
            "loss_date": loss.isoformat(),
            "reported_at": reported.isoformat(),
            "fnol_text": fnol,
            "adjuster_notes": [{"n": i + 1, "text": t} for i, t in enumerate(notes)],
            "photo_captions": captions,
            "final_decision": decision,
            "pii": {"claimant_name": holder["name"], "address": holder["address"], "street": holder["street"],
                    "phone": holder["phone"], "email": holder["email"],
                    "other_people": [ctx["witness"], ctx["third_party"]], "injuries": injuries},
        })
    return claims


# --- Writing ------------------------------------------------------------------


def _dump(obj):
    return json.dumps(obj, indent=1, ensure_ascii=False, sort_keys=False) + "\n"


def build():
    """Return {relative path: text} for everything under data/."""
    rng = random.Random(SEED)
    people = People(rng)
    out = {}
    pages = {}
    for fname, render in WORDINGS.items():
        doc = render()
        out[f"wordings/{fname}"] = doc.text()
        pages[fname] = doc.page
    out["versions.json"] = _dump(versions())
    out["limits.csv"] = limits_csv()
    policies = make_policies(rng, people)
    out["policies.json"] = _dump({"_about": "Synthetic. holder.* is PII and must never leave lookup_policy unredacted.",
                                  "policies": policies})
    claims = make_claims(rng, people, policies)
    for c in claims:
        out[f"claims/{c['claim_id']}.json"] = _dump(c)
    out["corpus_stats.json"] = _dump({
        "seed": SEED, "words_per_page": WORDS_PER_PAGE, "pages": pages,
        "policies": {"household": sum(p["product"] == "household" for p in policies),
                     "motor": sum(p["product"] == "motor" for p in policies)},
        "claims": len(claims),
        "scenarios": {s: sum(c["scenario"] == s for c in claims) for s in sorted({c["scenario"] for c in claims})},
    })
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="regenerate in memory and diff against data/")
    args = ap.parse_args()
    files = build()
    if args.check:
        bad = [p for p, text in files.items()
               if not (DATA / p).exists() or (DATA / p).read_text(encoding="utf-8") != text]
        extra = [str(p.relative_to(DATA)) for p in DATA.rglob("*") if p.is_file()
                 and str(p.relative_to(DATA)) not in files]
        print(f"{len(files)} files generated; {len(bad)} differ; {len(extra)} unexpected on disk")
        for p in (bad + extra)[:20]:
            print("  ", p)
        sys.exit(1 if bad or extra else 0)
    for p, text in files.items():
        path = DATA / p
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    stats = json.loads(files["corpus_stats.json"])
    print(f"wrote {len(files)} files under {DATA}")
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    main()
