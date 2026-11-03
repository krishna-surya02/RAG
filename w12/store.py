"""Read-only access to the week-12 corpus under data/.

Every other w12 module goes through here for policies, terms, versions,
limits, claim files and clause text, so "which wording was in force" is
answered in exactly one place (`in_force`). Nothing here redacts: callers
that hand data to a model or a log must go through w12.pii first.
"""

import csv
import datetime as dt
import json
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

PRODUCTS = ("household", "motor")


def _date(s):
    return dt.date.fromisoformat(s) if isinstance(s, str) else s


@lru_cache(maxsize=1)
def versions():
    return json.loads((DATA / "versions.json").read_text(encoding="utf-8"))["documents"]


def doc(doc_id):
    for d in versions():
        if d["doc_id"] == doc_id:
            return d
    raise KeyError(doc_id)


@lru_cache(maxsize=1)
def _policies():
    rows = json.loads((DATA / "policies.json").read_text(encoding="utf-8"))["policies"]
    return {p["policy_number"]: p for p in rows}


def policy(policy_number):
    return _policies().get(policy_number.strip().upper())


@lru_cache(maxsize=None)
def claim(claim_id):
    path = DATA / "claims" / f"{claim_id.strip().upper()}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def claim_ids():
    return sorted(p.stem for p in (DATA / "claims").glob("CLM-*.json"))


def term_on(policy_number, loss_date):
    p = policy(policy_number)
    if p is None:
        return None
    day = _date(loss_date)
    for t in p["terms"]:
        if _date(t["start"]) <= day <= _date(t["end"]):
            return t
    return None


def set_by_calendar(product, day):
    """The endorsement set new/renewing terms received on `day`. This is NOT
    necessarily the set in force for a policy on that day -- see in_force()."""
    day = _date(day)
    for d in versions():
        if d["product"] == product and d["kind"] == "endorsement_set":
            if _date(d["effective_from"]) <= day and (d["effective_to"] is None or day <= _date(d["effective_to"])):
                return d["doc_id"]
    return None


def base_wording(product):
    return next(d["doc_id"] for d in versions() if d["product"] == product and d["kind"] == "wording")


def in_force(policy_number, loss_date):
    """Was the policy in force on the loss date, and which documents govern it?

    The endorsement set comes from the policy TERM covering the loss date,
    never from the calendar: a term that incepted in January 2025 carries the
    2023 set until it renews, even for a loss in June 2025."""
    p = policy(policy_number)
    if p is None:
        return {"found": False, "policy_number": policy_number}
    day = _date(loss_date)
    t = term_on(policy_number, day)
    out = {"found": True, "policy_number": p["policy_number"], "product": p["product"],
           "loss_date": day.isoformat(), "in_force": t is not None}
    if t is None:
        nearest = sorted(p["terms"], key=lambda x: abs((_date(x["start"]) - day).days))[:2]
        out["terms_nearby"] = [{"start": x["start"], "end": x["end"]} for x in sorted(nearest, key=lambda x: x["start"])]
        out["reason"] = "loss date falls outside every period of insurance on this policy"
        return out
    eset = doc(t["endorsement_set"])
    out.update({
        "term": {"start": t["start"], "end": t["end"], "cancelled": t.get("cancelled", False)},
        "endorsement_set": eset["doc_id"],
        "endorsement_set_version": eset["version"],
        "endorsements": eset["endorsements"],
        "base_wording": base_wording(p["product"]),
        "schedule": {k: t[k] for k in ("flood_plus", "cover_level") if k in t},
        "designated_flood_zone": p.get("designated_flood_zone", False),
        "calendar_set_differs": set_by_calendar(p["product"], day) != eset["doc_id"],
    })
    return out


@lru_cache(maxsize=1)
def _limits():
    with (DATA / "limits.csv").open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    out = {}
    for r in rows:
        out[(r["product"], r["endorsement_set"], r["coverage"])] = {
            "coverage": r["coverage"],
            "deductible": int(r["deductible"]),
            "sub_limit": int(r["sub_limit"]) if r["sub_limit"] else None,
            "policy_limit": int(r["policy_limit"]),
            "source": r["source_clause"],
        }
    return out


def limits(product, endorsement_set, coverage):
    return _limits().get((product, endorsement_set, coverage))


def coverages(product, endorsement_set=None):
    return sorted({c for (p, e, c) in _limits() if p == product and (endorsement_set is None or e == endorsement_set)})


# --- Wording clauses ----------------------------------------------------------

_ANCHOR = re.compile(r'^<a id="(?P<anchor>[a-z0-9-]+)"></a>$')
_HEAD = re.compile(r"^### (?P<ref>.+?) — (?P<title>.+)$")
_PAGE = re.compile(r"^<!-- page (\d+) -->$")


def parse_wording(path):
    """Split one wording file into clauses: ref, title, anchor, page, text.
    The page is the one the clause heading sits on."""
    clauses, cur, page = [], None, 1
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _PAGE.match(line)
        if m:
            page = int(m.group(1))
        elif _ANCHOR.match(line) and i + 1 < len(lines) and _HEAD.match(lines[i + 1]):
            if cur:
                clauses.append(cur)
            h = _HEAD.match(lines[i + 1])
            cur = {"ref": h["ref"], "title": h["title"], "anchor": _ANCHOR.match(line)["anchor"],
                   "page": page, "lines": []}
            i += 2
            continue
        elif line.startswith("## ") or line.startswith("# "):
            if cur:
                clauses.append(cur)
                cur = None
        elif cur is not None:
            cur["lines"].append(line)
        i += 1
    if cur:
        clauses.append(cur)
    for c in clauses:
        c["text"] = "\n".join(c.pop("lines")).strip()
    return clauses


@lru_cache(maxsize=1)
def all_clauses():
    """Every clause in every document, tagged with its document's version and window."""
    out = []
    for d in versions():
        for c in parse_wording(ROOT / d["file"]):
            out.append({**c, "doc_id": d["doc_id"], "product": d["product"], "kind": d["kind"],
                        "version": d["version"], "file": d["file"],
                        "effective_from": d["effective_from"], "effective_to": d["effective_to"]})
    return out


def _norm_ref(ref):
    return re.sub(r"\s+", " ", ref.replace("Section", "§").replace("s.", "§")).strip().upper().replace("§ ", "§")


def find_clause(ref, product=None):
    """All clauses whose ref matches, across versions -- the caller decides
    which version applies. 'HFL-23 §2.2' and 'hfl-23 §2.2' both work."""
    want = _norm_ref(ref)
    return [c for c in all_clauses() if _norm_ref(c["ref"]) == want and (product is None or c["product"] == product)]


def doc_ids_in_force(product, endorsement_set):
    """Documents an in-force policy term is read against: base wording + its set."""
    return {base_wording(product), endorsement_set}


# --- PII registry -------------------------------------------------------------


@lru_cache(maxsize=1)
def pii_values():
    """Every PII value the generator wrote. Production would not have this list;
    here it lets the audit count leaks exactly instead of estimating them."""
    vals = set()
    for p in _policies().values():
        h = p["holder"]
        vals.update([h["name"], h["address"], h["street"], h["phone"], h["email"]])
        vals.update(part for part in h["name"].split() if len(part) >= 3)
    for cid in claim_ids():
        c = claim(cid)
        pii = c["pii"]
        for person in pii["other_people"]:
            vals.add(person)
            vals.update(part for part in person.split() if len(part) >= 3)
        vals.update(pii["injuries"])
    return sorted(v for v in vals if v)
