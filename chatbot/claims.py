"""
chatbot/claims.py: the claims store behind get_claim_status and list_my_claims (M5).

What it is
----------
A simple lookup in datasets/claim_status.csv, loaded into memory once. This is
not retrieval (not RAG): nothing is ranked or searched, and the same claim ID
always returns the same record. In production this would be a call to the
claims system's API; the CSV stands in for it.

The access check lives here, in ordinary code, so it does not depend on the
model following its instructions:
  - the member comes from the session (rule R1), never from a tool argument;
  - a member sees only claims where they are the claimant (R2);
  - another member's claim and a claim that does not exist give the same
    "not found" result, so the bot cannot reveal that a claim exists (R3).
Because it is code, it is tested by the free tests in tests/test_chatbot_tools.py.

Fault injection
---------------
ClaimsStore(fault="claims_store_unavailable") makes every lookup raise
ClaimsStoreUnavailable, to test how the bot behaves when the claims system is
down (golden conversation C18, rule R22). Same idea as Day 3's broken
retriever: break one component on purpose and see what the rest does.

Change history:
  2026-11-05  v1  first version (M5).
  2026-11-05  v1.1  comments expanded; no code change.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

STATUS_PATH = Path(__file__).resolve().parent.parent / "datasets" / "claim_status.csv"
AS_OF = "2026-10-20"                     # the date the claim statuses describe
STANDARD_ID = re.compile(r"^HLH-\d{3}$")  # HLH- followed by exactly three digits

# Fields a member may see. member_id and source are internal and never returned.
MEMBER_FIELDS = ["claim_id", "claimant_name", "treatment", "treatment_date", "submission_date",
                 "amount_claimed", "status", "decision_code", "amount_paid", "last_updated",
                 "next_step", "claimant_note"]
# The short form returned by list_my_claims.
LIST_FIELDS = ["claim_id", "treatment", "treatment_date", "status"]


class ClaimsStoreUnavailable(RuntimeError):
    """Raised by every lookup while the store is faulted (C18)."""


def tidy_id(raw: str) -> str | None:
    """Rule R6b: the standard form of a recognisable claim ID, or None if it isn't one.

    Recognisable means: after removing spaces and hyphens, the letters HLH, HL,
    LH or none, then one to three digits. So HLH021, HL021, HLH-21 and
    'hlh 021' all give HLH-021, and 'ABC-021' gives None.

    The tools do not use this. They accept the standard form only, because the
    bot must confirm a tidied ID with the member before looking it up. It is
    used by the tests and the checks, and matches the same rule in
    datasets/validate_conversations.py.
    """
    m = re.fullmatch(r"(HLH|HL|LH)?(\d{1,3})", re.sub(r"[\s-]", "", raw.upper()))
    return f"HLH-{int(m.group(2)):03d}" if m else None


class ClaimsStore:
    """The claims data for all members, with the access check built in.

    store = ClaimsStore()                                   normal
    store = ClaimsStore(fault="claims_store_unavailable")   every lookup fails
    """

    def __init__(self, path: Path = STATUS_PATH, fault: str | None = None):
        if fault not in (None, "claims_store_unavailable"):
            raise ValueError(f"unknown fault {fault!r}")      # catches a typo in the golden file
        self.fault = fault
        with Path(path).open(encoding="utf-8") as f:
            self._rows = {r["claim_id"]: r for r in csv.DictReader(f)}   # claim_id -> full row

    def _check(self) -> None:
        """Fail every lookup while faulted."""
        if self.fault == "claims_store_unavailable":
            raise ClaimsStoreUnavailable("The claims system is not responding.")

    def get(self, member_id: str, claim_id: str) -> dict | None:
        """One claim for this member, or None.

        None is returned for all three cases below, deliberately the same:
          - the ID belongs to another member (R2, R3)
          - no claim has that ID (R3)
          - the ID is not in standard form, e.g. HLH021. Only trimming and
            upper-casing are applied (R6a); anything else the bot must confirm
            with the member first (R6b)
        The record returned leaves out the internal fields (member_id, source).
        """
        self._check()
        cid = claim_id.strip().upper()
        row = self._rows.get(cid) if STANDARD_ID.match(cid) else None
        if row is None or row["member_id"] != member_id:
            return None
        return {k: row[k] for k in MEMBER_FIELDS}

    def list_for(self, member_id: str) -> list[dict]:
        """This member's claims, short form (ID, treatment, date, status), in file order."""
        self._check()
        return [{k: r[k] for k in LIST_FIELDS} for r in self._rows.values() if r["member_id"] == member_id]

    def members(self) -> set[str]:
        """Every member ID in the file (used by the tests to check the golden set)."""
        return {r["member_id"] for r in self._rows.values()}
