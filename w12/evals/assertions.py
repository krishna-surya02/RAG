"""Deterministic checks on one integrated run. These run before any judge.

Each check returns (name, passed or None if not applicable, detail). A case
fails on any False. The judge only grades what code cannot: whether the
summary is faithful to the cited wording and useful to an adjuster.
"""

import re

from w12 import store

AMOUNT = r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)"  # not [\d,]+: that eats the comma in "$2,500, sub-limit"


def _money(s):
    return int(s.replace(",", ""))


def summary_amounts(summary):
    """Dollar figures the summary attaches to each limit name."""
    # "<name> is $X" / "<name> of $X" (no other limit name or amount in between),
    # or "$X <name>" directly adjacent. The first smoke run read "The deductible
    # is $2,500, the sub-limit is $15,000" as a $2,500 sub-limit with a looser
    # pattern -- an assertion that false-fails is worse than none.
    out = {"deductible": set(), "sub_limit": set(), "policy_limit": set()}
    names = {"deductible": r"deductible", "sub_limit": r"sub[-‑\s]?limit", "policy_limit": r"policy\s+limit"}
    text = summary.replace("\u2011", "-")
    # Only "<name> [is|of|at|:] $X" and "$X [flood] <name>" count -- the shapes
    # a summary uses to state a limit. "the flood deductible replaces the $1,000
    # buildings deductible" names another line's deductible, not this one's.
    link = r"[\s:]*(?:(?:is|of|at|was|=|set\s+at|amounts\s+to|stated\s+as)\s+)?(?:\([^)]{0,40}\)\s*)?(?:(?:is|of)\s+)?"
    other = re.compile(r"(?:standard|buildings|contents|own[-\s]damage|usual|normal)\s*$", re.I)
    for name, pat in names.items():
        for m in re.finditer(rf"\b(?:{pat})\b{link}" + AMOUNT, text, re.I):
            if not other.search(text[max(0, m.start() - 20):m.start()]):
                out[name].add(_money(m.group(1)))
        for m in re.finditer(AMOUNT + rf"\s+(?:flood\s+|pluvial\s+accumulation\s+|flood\s+plus\s+)?(?:{pat})\b", text, re.I):
            out[name].add(_money(m.group(1)))
    return out


def pii_hits(claim, *blobs):
    p = claim["pii"]
    values = [p["claimant_name"], p["address"], p["street"], p["phone"], p["email"], *p["other_people"], *p["injuries"]]
    values += [x for v in [p["claimant_name"], *p["other_people"]] for x in v.split() if len(x) >= 3]
    text = "\n".join(blobs)
    return sorted({v for v in values if v and re.search(rf"(?<![\w'’-]){re.escape(v)}(?![\w-])", text)})


def check(case, rec, raw_run_line):
    exp = case["expected"]
    r = rec["referral"]
    agent_flags = set(rec.get("agent_flags") or [])
    refs = [c["ref"] for c in r["citations"]]
    out = []

    out.append(("referral_by_agent", rec["status"] == "ok",
                f"status={rec['status']}"))

    if exp["in_force"]:
        out.append(("in_force_not_misflagged", "NOT_IN_FORCE" not in agent_flags, f"agent flags {sorted(agent_flags)}"))
    else:
        out.append(("not_in_force_flagged", "NOT_IN_FORCE" in agent_flags, f"agent flags {sorted(agent_flags)}"))

    out.append(("citations_valid_for_loss_date", all(c.get("valid") for c in r["citations"]) if r["citations"] else None,
                "; ".join(p for c in r["citations"] for p in c.get("problems", [])) or "all in force"))

    if exp["in_force"] and exp["deciding_clause"]:
        out.append(("deciding_clause_cited", exp["deciding_clause"] in refs,
                    f"want {exp['deciding_clause']}, cited {refs}"))

    if exp.get("limits"):
        got = r["limits"] or {}
        triple = tuple(got.get(k) for k in ("deductible", "sub_limit", "policy_limit"))
        want = tuple(exp["limits"][k] for k in ("deductible", "sub_limit", "policy_limit"))
        out.append(("limits_for_right_coverage_line", triple == want,
                    f"coverage={r['coverage']} got {triple}, want {exp['coverage']} {want}"))

    amounts = summary_amounts(r["summary"] or "")
    if exp.get("limits") and any(amounts.values()):
        bad = []
        for k in ("deductible", "sub_limit", "policy_limit"):
            wrong = amounts[k] - {exp["limits"][k]}
            if wrong:
                bad.append(f"{k} stated as {sorted(wrong)} (is {exp['limits'][k]})")
        out.append(("summary_limits_not_conflated", not bad, "; ".join(bad) or "consistent"))

    out.append(("no_decision_language", not r["guard"]["tripped"],
                f"guard found {r['guard']['found']}" if r["guard"]["tripped"] else "clean"))

    claim = store.claim(case["claim_id"])
    leaked = pii_hits(claim, raw_run_line)
    out.append(("no_pii_in_run_or_referral", not leaked, f"leaked {leaked}" if leaked else "clean"))
    return out


def passed(results):
    return all(ok is not False for _, ok, _ in results)
