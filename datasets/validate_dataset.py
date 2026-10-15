"""
Reference implementation of the Harbourlight Health routing rules.

Checks that every expected result in claim_triage.csv follows from the specification
(plan_rules.md, sections 4 to 8). Run it whenever the rules or the dataset change.

Usage (from the repo root):
    python datasets/validate_dataset.py

Exit code 0 = every expected routing and reason code matches the rules; 1 = mismatches found.
(So it can also run as a check in CI.)

What this does and does not verify
----------------------------------
It verifies the RULE LOGIC: given a claim's category and facts, is the expected routing and
reason code what the rules produce? It applies the rules in the specified order and stops
at the first match, exactly as section 6 describes.

It does NOT verify free-text interpretation. Three judgements need a human reading of the
treatment description or claimant note, so they are labelled by hand rather than calculated:
  - the category of each claim (taken from expected_category)
  - whether the provider's description shows an accidental injury (ACCIDENT_SHOWN_BY_PROVIDER)
  - whether only the claimant's note claims an accident (CLAIMANT_ONLY_ACCIDENT)
Those labels are listed below so a reviewer can challenge them.
"""
import csv
import sys
from datetime import date
from pathlib import Path

DATASET = Path(__file__).with_name("claim_triage.csv")

# ---- Hand-labelled interpretive judgements (see docstring) ----
ACCIDENT_SHOWN_BY_PROVIDER = {"HLH-011"}                       # "...ankle sprain sustained in a fall at home"
CLAIMANT_ONLY_ACCIDENT = {"HLH-012", "HLH-034", "HLH-035"}    # accident mentioned only in the claimant note

# ---- Section 4: cover and limits (per visit/item limit, annual limit) ----
LIMITS = {
    "gp_visit": (60, 8),
    "consultant_visit": (120, 4),
    "physiotherapy": (50, 10),
    "prescription": (40, 12),
    "day_case": (1500, 2),
    "inpatient": (None, None),   # assessed individually
}
REFERRAL_REQUIRED = {"consultant_visit", "physiotherapy"}
PREAUTH_REQUIRED = {"day_case", "inpatient"}
WAITING_PERIOD_DAYS = 182
HIGH_VALUE = 1000


def deadline(treatment: date) -> date:
    """Section 5: same calendar date one year later; 29 February -> 28 February."""
    if (treatment.month, treatment.day) == (2, 29):
        return date(treatment.year + 1, 2, 28)
    return treatment.replace(year=treatment.year + 1)


def route(c: dict) -> tuple[str, str]:
    """Section 6: apply the steps in order and return (routing, reason_code) for the first match."""
    cid = c["claim_id"]
    category = c["expected_category"]
    start, treat, sub = (date.fromisoformat(c[k]) for k in ("policy_start_date", "treatment_date", "submission_date"))
    amount = float(c["amount_claimed"])
    receipt = c["receipt_attached"] == "yes"
    referral = c["referral_attached"] == "yes"
    preauth = c["preauth_number"].strip() != ""
    used = int(c["used_this_year"])

    in_waiting_period = (treat - start).days < WAITING_PERIOD_DAYS
    exempt = category == "gp_visit" or cid in ACCIDENT_SHOWN_BY_PROVIDER

    # Step 1: can the claim be assessed at all?
    if category == "unclear" or sub < treat:
        return "manual_review", "UNCLEAR"
    if in_waiting_period and not exempt and cid in CLAIMANT_ONLY_ACCIDENT:
        return "manual_review", "UNCLEAR"

    # Step 2: decline rules
    if category == "excluded":
        return "decline_recommended", "EXCLUDED"
    if in_waiting_period and not exempt:
        return "decline_recommended", "WAITING_PERIOD"
    if sub > deadline(treat):
        return "decline_recommended", "LATE_SUBMISSION"
    limit, annual = LIMITS[category]
    if annual is not None and used >= annual:
        return "decline_recommended", "ANNUAL_LIMIT_REACHED"

    # Step 3: manual review rules
    if not receipt:
        return "manual_review", "MISSING_RECEIPT"
    if category in REFERRAL_REQUIRED and not referral:
        return "manual_review", "MISSING_REFERRAL"
    if category in PREAUTH_REQUIRED and not preauth:
        return "manual_review", "MISSING_PREAUTH"
    if category == "inpatient":
        return "manual_review", "INPATIENT_REVIEW"
    if limit is not None and amount > limit:
        return "manual_review", "OVER_LIMIT"
    if amount > HIGH_VALUE:
        return "manual_review", "HIGH_VALUE"

    # Step 4: otherwise
    return "auto_approve", "WITHIN_RULES"


def main() -> int:
    with open(DATASET, newline="", encoding="utf-8") as f:
        claims = list(csv.DictReader(f))

    mismatches = []
    for c in claims:
        got = route(c)
        expected = (c["expected_routing"], c["expected_reason_code"])
        if got != expected:
            mismatches.append((c["claim_id"], expected, got))

    print(f"Checked {len(claims)} claims against the rules.")
    if mismatches:
        print(f"{len(mismatches)} mismatch(es):")
        for cid, expected, got in mismatches:
            print(f"  {cid}: dataset says {expected}, rules give {got}")
        return 1
    print("All expected routings and reason codes match the rules.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
