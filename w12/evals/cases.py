"""Build evals/w12/cases.json: 30 claims, stratified, with expected outcomes.

    python -m w12.evals.cases           # (re)write cases.json

Cases are drawn from the 500 claim files by a fixed seed, per scenario, so a
case set is reproducible and every scenario that can fail differently gets at
least one draw. Expected values come from each claim's final_decision (the
adjuster's call the system never sees) and the policy records.

What a case expects is what an adjuster needs from a referral, not a
decision: the right in-force answer, the deciding clause cited from the right
version, and -- where money moves -- the right deductible / sub-limit / limit.
"""

import json
import random
from pathlib import Path

from w12 import store

ROOT = Path(__file__).resolve().parent.parent.parent
CASES_PATH = ROOT / "evals" / "w12" / "cases.json"
SEED = 1202

# scenario -> (draws, trajectory draws, why it is in the suite)
STRATA = [
    ("hh_surface_water_aug24", 3, 2, "the live wound: Aug-2024 rainfall flood, 2023 wording governs, 2025 wording reads better"),
    ("hh_surface_water_23", 1, 0, "2023-set rainfall flood outside August 2024"),
    ("hh_surface_water_23_floodzone", 1, 0, "HFL-23 §2.2's flood-zone condition"),
    ("hh_river_23", 2, 1, "river inundation: HFL-23 §2.1, not §2.2 -- the cause word decides"),
    ("hh_surface_water_25", 2, 1, "2025-set rainfall flood without Flood Plus"),
    ("hh_surface_water_25_floodplus", 1, 0, "2025-set Flood Plus: $5,000 deductible, $25,000 sub-limit"),
    ("hh_surface_water_crossboundary", 3, 2, "loss after 2025-04-01 on a term that started before it: 2023 set still governs"),
    ("hh_escape_of_water", 1, 1, "base wording peril with no endorsement in play"),
    ("hh_gradual_leak", 1, 0, "HX-1 wear and tear vs escape of water"),
    ("hh_mould", 1, 0, "HX-5 with a set-dependent sub-limit"),
    ("hh_theft_let", 1, 0, "HX-15 theft from let property"),
    ("hh_storm_fence", 1, 0, "HX-9 fences"),
    ("hh_liability_injury", 1, 1, "bodily injury in the notes: PII and a liability referral"),
    ("hh_below_deductible", 1, 0, "loss below the deductible"),
    ("mt_collision", 1, 1, "motor own damage with third-party injuries in the notes"),
    ("mt_collision_tpft", 1, 0, "TPFT has no own-damage cover: MT-PW §1.2"),
    ("mt_theft_keys", 1, 0, "MX-6 keys left in the vehicle"),
    ("mt_windscreen", 1, 0, "windscreen deductible and sub-limit, set-dependent"),
    ("mt_flood_warning_23", 1, 1, "car left in a flood-warning area, 2023 set: no such exclusion exists"),
    ("mt_flood_warning_25", 1, 0, "the same facts under the 2025 set: MFL-25 §2.2"),
    ("mt_hail", 1, 0, "hail deductible differs by set (MT-PW §3.2 vs MHA-25)"),
    ("mt_personal_accident", 1, 0, "permanent injury in the notes"),
    ("not_in_force", 3, 2, "loss in a lapse gap, before inception, or after cancellation"),
]

# Scenarios whose deciding clause carries money, so limits are asserted.
MONEY = {"paid", "no_payment", "referred_liability"}


def expected_for(claim):
    d = claim["final_decision"]
    facts = store.in_force(claim["policy_number"], claim["loss_date"])
    exp = {
        "in_force": facts["in_force"],
        "endorsement_set": facts.get("endorsement_set"),
        "calendar_set_differs": facts.get("calendar_set_differs", False),
        "deciding_clause": d["clause"],
        "outcome_for_reference_only": d["outcome"],
        "reason_code": d["reason_code"],
    }
    if d["limits"] and d["outcome"] in MONEY:
        exp["coverage"] = d["limits"]["coverage"]
        exp["limits"] = {k: d["limits"][k] for k in ("deductible", "sub_limit", "policy_limit")}
    return exp


def build():
    rng = random.Random(SEED)
    by_scenario = {}
    for cid in store.claim_ids():
        c = store.claim(cid)
        by_scenario.setdefault(c["scenario"], []).append(cid)
    cases = []
    for scenario, n, n_traj, why in STRATA:
        picks = rng.sample(sorted(by_scenario[scenario]), n)
        for i, cid in enumerate(picks):
            c = store.claim(cid)
            cases.append({
                "id": f"w12-{len(cases) + 1:02d}",
                "claim_id": cid,
                "scenario": scenario,
                "product": c["product"],
                "loss_date": c["loss_date"],
                "why": why,
                "trajectory": i < n_traj,
                "expected": expected_for(c),
            })
    return cases


def load(path=CASES_PATH):
    return json.loads(Path(path).read_text(encoding="utf-8"))["cases"]


def main():
    cases = build()
    CASES_PATH.parent.mkdir(parents=True, exist_ok=True)
    CASES_PATH.write_text(json.dumps({
        "_about": "Week 12 integrated-system cases, built by w12/evals/cases.py (seeded). "
                  "Regression cases added by the failure->test loop carry origin='regression'.",
        "cases": cases,
    }, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(cases)} cases ({sum(c['trajectory'] for c in cases)} trajectory) to {CASES_PATH}")


if __name__ == "__main__":
    main()
