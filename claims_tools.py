"""The three tools the claims-triage agent and workflow both call.

Kept in one module, shared by both systems, so "same tools" in the race is
literally true rather than two independently-written copies that happen to
agree. Each function is also wrapped as a LangChain tool (TOOLS list) for
claim_agent.py's bind_tools(); claim_workflow.py calls the plain functions
directly.

get_claim() is the only place raw_notes is read, and it redacts before
returning -- same ingress rule as rag.py/summarize.py: the model never sees a
claimant name.
"""

import json
from pathlib import Path
from typing import Literal, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

import redact

CLAIMS_PATH = Path(__file__).parent / "claims_data.json"

CauseCategory = Literal[
    "wear_and_tear",
    "hail",
    "earthquake",
    "sump_failure",
    "theft_construction",
    "fire",
    "sudden_discharge",
    "sewer_backup",
    "ice_snow_collapse",
    "other",
]

# Query phrasing fed to retrieval.retrieve() for each cause, so the citation
# it returns is actually about the right provision instead of a bag-of-words
# match on the raw cause key.
_CAUSE_QUERY = {
    "wear_and_tear": "continuous or repeated seepage, wear and deterioration exclusion",
    "hail": "hail damage to roof",
    "earthquake": "earthquake earth movement exclusion",
    "sump_failure": "sump pump overflow water backup exclusion and endorsement buy-back",
    "theft_construction": "theft of building materials during construction",
    "fire": "fire covered peril",
    "sudden_discharge": "sudden and accidental discharge from a household appliance sublimit",
    "sewer_backup": "backup through sewers or drains exclusion",
    "ice_snow_collapse": "collapse from weight of ice snow sleet or rain",
    "other": "homeowners policy exclusions",
}

# Grounded in the same PDF-verified facts already established in
# summary_goldenset.json's gold_answer fields (week 6). Keyed by
# (form, edition, cause); "excluded" is the base position before any
# endorsement buy-back, "buyback_endorsement" names the one endorsement (if
# any) that flips it, and "cap" is a payout ceiling that applies whenever the
# claim ends up payable (present even for causes that were never excluded,
# e.g. the E-17 sudden-discharge sublimit).
_RULES = {
    ("HO-0304", "03-24", "wear_and_tear"): dict(
        code="E-17", excluded=True, buyback=None, cap=None,
        basis="Continuous/repeated seepage over months is carved out of E-17's "
              "sudden-discharge coverage (matches E-11 wear/deterioration).",
    ),
    ("HO-0304", "02-23", "hail"): dict(
        code=None, excluded=False, buyback=None, cap=None,
        basis="No exclusion in HO-0304 ed 02-23 covers hail.",
    ),
    ("HO-0304", "01-22", "earthquake"): dict(
        code="E-2", excluded=True, buyback=None, cap=None,
        basis="E-2 Earth Movement excludes earthquake; no endorsement buys this back.",
    ),
    ("HO-0304", "02-23", "sump_failure"): dict(
        code="E-17", excluded=True, buyback="HO-2306", cap=None,
        basis="Sump overflow is excluded under E-17's water-backup language, "
              "bought back only by Endorsement HO-2306.",
    ),
    ("HO-0304", "01-22", "theft_construction"): dict(
        code="E-19", excluded=True, buyback=None, cap=None,
        basis="E-19 Theft in Course of Construction excludes theft of building "
              "materials from an unfinished addition.",
    ),
    ("HO-0304", "03-24", "fire"): dict(
        code=None, excluded=False, buyback=None, cap=None,
        basis="Fire is not excluded anywhere in the form; standard covered peril.",
    ),
    ("HO-0304", "03-24", "sudden_discharge"): dict(
        code="E-17", excluded=False, buyback=None, cap=10000,
        basis="Edition 03-24's E-17 covers sudden/accidental discharge from a "
              "household appliance with no endorsement required, capped at a "
              "$10,000 sublimit.",
    ),
    ("HO-0304", "03-24", "sewer_backup"): dict(
        code="E-17", excluded=True, buyback=None, cap=None,
        basis="Backup through sewers/drains from outside the plumbing system "
              "remains fully excluded under E-17 even with the sudden-discharge "
              "carve-back; no endorsement attached buys it back.",
    ),
    ("HO-0304", "02-23", "ice_snow_collapse"): dict(
        code="E-20", excluded=False, buyback=None, cap=None,
        basis="E-20's exception for edition 02-23 explicitly covers weight of "
              "ice, snow, sleet or rain on a roof.",
    ),
    ("HO-0304", "01-22", "ice_snow_collapse"): dict(
        code="E-20", excluded=True, buyback=None, cap=None,
        basis="For edition 01-22, E-20's exception does NOT include ice/snow/"
              "sleet/rain (only decay/insect/defective materials), so collapse "
              "from ice/snow is excluded.",
    ),
}


def _load_claims():
    return json.loads(CLAIMS_PATH.read_text(encoding="utf-8"))["claims"]


def _find_claim(claim_id):
    for claim in _load_claims():
        if claim["claim_id"] == claim_id:
            return claim
    return None


# --- Tool 1 ------------------------------------------------------------------


class GetClaimArgs(BaseModel):
    claim_id: str = Field(description="The claim id, e.g. 'CLM-2026-010007'.")


def get_claim(claim_id: str) -> dict:
    """Look up one claim's intake record: policy form/edition, any endorsement
    and its stated limit, date of loss, claimed amount, deductible, and the
    adjuster's notes with the claimant's name redacted. Does not judge
    coverage or compute anything -- call check_policy_exclusions and
    compute_payout for that."""
    claim = _find_claim(claim_id)
    if claim is None:
        return {"error": f"no claim with id {claim_id!r}"}

    clean_notes, _ = redact.redact(claim["raw_notes"])
    return {
        "claim_id": claim["claim_id"],
        "notes": clean_notes,
        "form": claim["form"],
        "edition": claim["edition"],
        "endorsement": claim["endorsement"],
        "endorsement_limit": claim["endorsement_limit"],
        "date_of_loss": claim["date_of_loss"],
        "claimed_amount": claim["claimed_amount"],
        "deductible": claim["deductible"],
    }


# --- Tool 2 ------------------------------------------------------------------


class CheckPolicyExclusionsArgs(BaseModel):
    form: str = Field(description="Policy form number, e.g. 'HO-0304'.")
    edition: str = Field(description="Policy edition, e.g. '03-24'.")
    cause: CauseCategory = Field(
        description="The loss cause read from the adjuster's notes, as one of "
        "the fixed categories."
    )


def check_policy_exclusions(form: str, edition: str, cause: str) -> dict:
    """Decide whether a loss cause is excluded under one policy form/edition,
    and whether a payout cap applies. Returns the governing exclusion code (if
    any), whether it bars payment outright, which single endorsement (if any)
    buys it back, any payout cap, a PDF citation, and the basis text. Does not
    know about a specific claim's dollar amounts or which endorsement (if any)
    is actually attached -- call get_claim for that and compute_payout for the
    arithmetic."""
    import retrieval

    query = _CAUSE_QUERY.get(cause, _CAUSE_QUERY["other"])
    hits = retrieval.retrieve(f"{form} edition {edition}: {query}", k=1)
    citation = None
    if hits:
        hit = hits[0]
        citation = {"source_file": hit.source_file, "page": hit.page, "chunk_id": hit.chunk_id}

    rule = _RULES.get((form, edition, cause))
    if rule is None:
        return {
            "exclusion_code": None,
            "excluded": False,
            "buyback_endorsement": None,
            "cap": None,
            "basis": f"No rule found for cause {cause!r} under {form} {edition}; "
                     "treating as not excluded.",
            "citation": citation,
        }
    return {
        "exclusion_code": rule["code"],
        "excluded": rule["excluded"],
        "buyback_endorsement": rule["buyback"],
        "cap": rule["cap"],
        "basis": rule["basis"],
        "citation": citation,
    }


# --- Tool 3 ------------------------------------------------------------------


class ComputePayoutArgs(BaseModel):
    claimed_amount: float = Field(description="The dollar amount claimed.")
    deductible: float = Field(description="The policy deductible to subtract.")
    claim_status: Literal["approved", "denied", "partial"] = Field(
        description="approved: pay in full above the deductible. denied: pay "
        "nothing. partial: pay up to a cap, above the deductible."
    )
    cap: Optional[float] = Field(
        default=None,
        description="Required when claim_status is 'partial': the dollar cap "
        "(a sublimit or endorsement limit) the payout is capped at before the "
        "deductible is subtracted. Ignored otherwise.",
    )


def compute_payout(
    claimed_amount: float, deductible: float, claim_status: str, cap: Optional[float] = None
) -> dict:
    """Compute the dollar amount payable to the claimant, given the claimed
    amount, the deductible, and a final claim_status decision. Does not decide
    claim status or check exclusions -- call check_policy_exclusions first to
    decide that, then call this once to do the arithmetic."""
    if claim_status == "denied":
        payout = 0.0
    else:
        base = min(claimed_amount, cap) if (claim_status == "partial" and cap is not None) else claimed_amount
        payout = max(0.0, base - deductible)
    return {"payout": round(payout, 2)}


# --- LangChain tool wrappers ---------------------------------------------

get_claim_tool = StructuredTool.from_function(
    func=get_claim,
    name="get_claim",
    description=get_claim.__doc__,
    args_schema=GetClaimArgs,
)

check_policy_exclusions_tool = StructuredTool.from_function(
    func=check_policy_exclusions,
    name="check_policy_exclusions",
    description=check_policy_exclusions.__doc__,
    args_schema=CheckPolicyExclusionsArgs,
)

compute_payout_tool = StructuredTool.from_function(
    func=compute_payout,
    name="compute_payout",
    description=compute_payout.__doc__,
    args_schema=ComputePayoutArgs,
)

TOOLS = [get_claim_tool, check_policy_exclusions_tool, compute_payout_tool]
TOOLS_BY_NAME = {t.name: t for t in TOOLS}
