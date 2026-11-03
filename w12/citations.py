"""A citation that names the clause, the endorsement version, and the loss date
it was resolved against -- or it is not a citation here.

Citations are built from the clause registry (store.all_clauses), never parsed
out of model prose: the model names a clause ref ("HFL-23 §2.2"), and
`resolve` looks up which versions of that ref exist and whether the one in
force for this loss is among them. A ref that exists only in the other
endorsement set (HFL-25 on a 2023-set term) resolves to an INVALID citation
with the reason spelled out, rather than to the nearest thing that exists.
"""

import datetime as dt

from w12 import store


def _window_contains(c, day):
    lo = dt.date.fromisoformat(c["effective_from"])
    hi = dt.date.fromisoformat(c["effective_to"]) if c["effective_to"] else None
    return lo <= day and (hi is None or day <= hi)


def build(clause, loss_date, endorsement_set, resolved_by):
    """Citation dict for one clause record, as resolved for this loss."""
    eset = store.doc(endorsement_set) if endorsement_set else None
    is_endorsement = clause["kind"] == "endorsement_set"
    endorsement_id = clause["ref"].split()[0] if is_endorsement else None
    return {
        "ref": clause["ref"],
        "title": clause["title"],
        "doc_id": clause["doc_id"],
        "endorsement": endorsement_id,
        "version": clause["version"],
        # For a base-wording clause, the endorsement version is the set it is
        # read with for this loss -- the set can change what the clause means.
        "endorsement_version": f"{endorsement_id} {clause['version']}" if is_endorsement
        else (f"{eset['doc_id']} {eset['version']}" if eset else None),
        "endorsement_set": clause["doc_id"] if is_endorsement else endorsement_set,
        "page": clause["page"],
        "file": clause["file"],
        "href": f"{clause['file']}#{clause['anchor']}",
        "loss_date": str(loss_date),
        "window": [clause["effective_from"], clause["effective_to"]],
        "resolved_by": resolved_by,
    }


def resolve(ref, product, loss_date, endorsement_set, resolved_by="policy_term"):
    """Citation for `ref` as in force on loss_date, with `problems` listed."""
    day = dt.date.fromisoformat(str(loss_date))
    matches = store.find_clause(ref, product)
    if not matches:
        return {"ref": ref, "loss_date": str(loss_date), "valid": False,
                "problems": [f"no clause {ref!r} in any {product} document"]}
    allowed = store.doc_ids_in_force(product, endorsement_set) if endorsement_set else None
    live = [c for c in matches if (allowed is None or c["doc_id"] in allowed)]
    if not live:
        c = matches[0]
        cit = build(c, loss_date, endorsement_set, resolved_by)
        whose = (f"the term covering {loss_date} carries" if resolved_by == "policy_term"
                 else f"by calendar date the set in force on {loss_date} is")
        cit.update(valid=False, problems=[
            f"{ref} is in {c['doc_id']} {c['version']}, but {whose} {endorsement_set}; "
            f"{ref} was not in force for this loss"])
        return cit
    cit = build(live[0], loss_date, endorsement_set, resolved_by)
    cit["problems"] = problems(cit, endorsement_set)
    cit["valid"] = not cit["problems"]
    return cit


def problems(cit, expected_set=None):
    """Why a citation does not count. Empty list means it counts."""
    out = []
    if not cit.get("endorsement_version"):
        out.append("no endorsement version")
    if not cit.get("loss_date"):
        out.append("no loss date")
    else:
        day = dt.date.fromisoformat(cit["loss_date"])
        lo, hi = cit["window"]
        if cit["doc_id"].startswith(("HH-PW", "MT-PW")):
            if not _window_contains({"effective_from": lo, "effective_to": hi}, day):
                out.append(f"{cit['doc_id']} {cit['version']} not effective on {day}")
        if expected_set and cit.get("endorsement_set") and cit["endorsement_set"] != expected_set:
            out.append(f"cites {cit['endorsement_set']} but the term carries {expected_set}")
    return out


def render(cit):
    """Markdown with a clickable link to the clause anchor."""
    if not cit.get("href"):
        return f"{cit['ref']} — UNRESOLVED ({'; '.join(cit.get('problems', []))})"
    flag = "" if cit.get("valid", True) else f" ⚠ INVALID: {'; '.join(cit['problems'])}"
    label = f"{cit['ref']} — {cit['title']}"
    return (f"[{label}]({cit['href']}) · {cit['endorsement_version']} · p.{cit['page']} · "
            f"resolved for loss date {cit['loss_date']} ({cit['resolved_by'].replace('_', ' ')}){flag}")
