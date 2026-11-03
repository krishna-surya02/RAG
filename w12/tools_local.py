"""The agent's in-process tools: policy lookup, in-force check, limits, referral.

These four live in-process because they read the policy system, not the
wording -- the wording and claim files are behind MCP (w12/mcp_*_server.py)
and their tools are discovered at runtime. Same StructuredTool + pydantic
pattern as claims_tools.py.

None of these returns a coverage decision, and `refer_to_adjuster` is the only
way a run ends normally. week 7's check_policy_exclusions is deliberately not
reused: it decided coverage from a hard-coded table and answered "not
excluded" for any combination it had no rule for.
"""

import re
from typing import List, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from w12 import store

CLAIM_RE = re.compile(r"^CLM-\d{4}-\d{6}$", re.I)


class LookupPolicyArgs(BaseModel):
    identifier: str = Field(description="A claim id (CLM-2024-000063) or a policy number (HH-2023-00068).")


def lookup_policy(identifier: str) -> dict:
    """Find a policy by claim id or policy number: product, status, flood-zone
    flag, and every term with its endorsement set. Personal details withheld.
    Use check_in_force to test a date."""
    ident = identifier.strip().upper()
    if CLAIM_RE.match(ident):
        c = store.claim(ident)
        if c is None:
            return {"error": f"no claim {identifier!r}"}
        ident = c["policy_number"]
    p = store.policy(ident)
    if p is None:
        return {"error": f"no policy {identifier!r}"}
    return {
        "policy_number": p["policy_number"],
        "product": p["product"],
        "status": p["status"],
        "policyholder": "[withheld]",
        "designated_flood_zone": p.get("designated_flood_zone", False),
        "terms": [{k: t[k] for k in ("start", "end", "endorsement_set", "flood_plus", "cover_level", "cancelled") if k in t}
                  for t in p["terms"]],
    }


class CheckInForceArgs(BaseModel):
    policy_number: str = Field(description="Policy number, e.g. 'HH-2023-00068'.")
    loss_date: str = Field(description="Date of loss, YYYY-MM-DD.")


def check_in_force(policy_number: str, loss_date: str) -> dict:
    """Was the policy in force on the loss date? Returns the term covering it,
    its endorsement set (from the TERM, not the calendar -- pass it to every
    wording call) and schedule options (flood_plus, cover_level)."""
    try:
        out = store.in_force(policy_number, loss_date)
    except ValueError:
        return {"error": f"loss_date must be YYYY-MM-DD, got {loss_date!r}"}
    if not out.get("found"):
        return {"error": f"no policy {policy_number!r}"}
    if out["in_force"] and out.get("calendar_set_differs"):
        out["note"] = (f"This term started before the {out['endorsement_set']} set was replaced, so "
                       f"{out['endorsement_set']} governs this loss even though newer wording existed on "
                       f"{loss_date}. Pass endorsement_set={out['endorsement_set']} to wording searches.")
    out.pop("calendar_set_differs", None)
    return out


class GetLimitsArgs(BaseModel):
    product: str = Field(description="'household' or 'motor'.")
    endorsement_set: str = Field(description="The endorsement set from check_in_force, e.g. 'HEND-2023'.")
    coverage: str = Field(description=(
        "Coverage line. household: buildings, contents, escape_of_water, flood_surface_water (2023 set), "
        "flood_plus (2025 set), mould, theft, storm, subsidence, liability, accidental_damage. "
        "motor: own_damage, theft, windscreen, flood, hail, third_party_property, third_party_injury, "
        "personal_accident, medical_expenses."))


def get_limits(product: str, endorsement_set: str, coverage: str) -> dict:
    """Deductible, sub-limit and policy limit for one coverage line under one
    endorsement set. Three different numbers -- never add them."""
    row = store.limits(product, endorsement_set, coverage)
    if row is None:
        return {"error": f"no limits row for {product}/{endorsement_set}/{coverage}",
                "valid_coverages": store.coverages(product, endorsement_set)}
    return {"product": product, "endorsement_set": endorsement_set, **row,
            "order_of_application": "assessed loss - deductible, then capped at sub_limit (if any), then at policy_limit"}


class ReferArgs(BaseModel):
    claim_id: str = Field(description="The claim id being referred.")
    summary: str = Field(description="Facts of the loss, in-force status, and what the cited wording says. No coverage decision.")
    citations: List[str] = Field(description="Clause refs exactly as returned, e.g. ['HFL-23 §2.2', 'HX-17'].")
    coverage: Optional[str] = Field(default=None, description="Coverage line you looked up limits for.")
    flags: List[str] = Field(default_factory=list, description="e.g. NOT_IN_FORCE, FLOOD_ZONE, INJURY_REPORTED, CLAIMANT_ASKED_FOR_DECISION.")


def refer_to_adjuster(claim_id: str, summary: str, citations: List[str],
                      coverage: Optional[str] = None, flags: Optional[List[str]] = None) -> dict:
    """Refer the claim to a human adjuster. Ends triage: call once, last."""
    # The agent loop intercepts this call (it needs the run's trace and
    # claim context); this body only runs if the tool is invoked directly.
    return {"referred": True, "claim_id": claim_id}


def _tool(func, args_schema):
    return StructuredTool.from_function(func=func, name=func.__name__, description=func.__doc__, args_schema=args_schema)


TOOLS = [
    _tool(lookup_policy, LookupPolicyArgs),
    _tool(check_in_force, CheckInForceArgs),
    _tool(get_limits, GetLimitsArgs),
    _tool(refer_to_adjuster, ReferArgs),
]
TOOLS_BY_NAME = {t.name: t for t in TOOLS}
TERMINAL = "refer_to_adjuster"
