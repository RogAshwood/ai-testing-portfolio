"""checks.py: the free code checks (no model). Each returns Finding records.

Check names and levels
----------------------
  schema            fail   the case breaks the input contract (contract.py)
  title             fail   title empty, just the case ID, or repeated in the story
  unknown_ac        fail   covers lists an AC ID that is not in the story
  no_ac_linked      warn   covers is empty or missing (B1: test with no AC)
  ac_no_tests       warn   no case lists the AC in covers (A1: AC with no tests),
                           story-level, so case_id is ""
  story_not_found   fail   the cases file has a story that is not in the stories file
  story_no_cases    warn   a story in the stories file has no cases

A1 and B1 are the "claimed" level of traceability: they trust each case's own
`covers` list. The judge (M7 step 3) adds the "verified" level: A2 (no correct
case really tests the AC) and B2 (a case claims an AC it does not test).

Why an empty `covers` is a warning, not a failure: test-design guidance (and
Day 4 prompt v2) asks for specification-gap cases, which test something the
story does not define and so link to no AC. Tools also produce stray cases that
map to nothing. Both are worth a look; neither breaks the input.

Change history:
  2026-11-12  v1  first version (M7 step 1).
"""

from __future__ import annotations

import re

from harness.contract import Finding, case_key, check_case_schema

_SPACE = re.compile(r"\s+")


def _norm(text: str) -> str:
    """Lower-case text with runs of spaces collapsed, for comparing titles."""
    return _SPACE.sub(" ", text).strip().lower()


def check_case_ids(story_id: str, cases: list[dict]) -> list[Finding]:
    """Fail a case whose case_id was already used by an earlier case in the same story."""
    out: list[Finding] = []
    seen: set[str] = set()
    for case in cases:
        cid = case.get("case_id") if isinstance(case, dict) else None
        if isinstance(cid, str) and cid:
            if cid in seen:
                out.append(Finding(story_id, cid, "schema", "fail", "case_id is used by an earlier case"))
            seen.add(cid)
    return out


def check_titles(story_id: str, cases: list[dict]) -> list[Finding]:
    """Fail a case whose title is empty, only repeats its case ID, or repeats another title."""
    out: list[Finding] = []
    seen: dict[str, str] = {}
    for n, case in enumerate(cases, start=1):
        if not isinstance(case, dict) or not isinstance(case.get("title"), str):
            continue                                    # already reported by the schema check
        cid, title = case_key(case, n), _norm(case["title"])
        if not title:
            out.append(Finding(story_id, cid, "title", "fail", "the title is empty"))
        elif title == _norm(cid):
            out.append(Finding(story_id, cid, "title", "fail", "the title only repeats the case ID"))
        elif title in seen:
            out.append(Finding(story_id, cid, "title", "fail",
                               f"the title repeats {seen[title]}'s title word for word"))
        else:
            seen[title] = cid
    return out


def check_ac_links(story: dict, cases: list[dict]) -> list[Finding]:
    """B1 and unknown AC IDs per case, then A1 (ACs with no tests) for the story."""
    sid = story["story_id"]
    ac_ids = [a["ac_id"] for a in story["acceptance_criteria"]]
    out: list[Finding] = []
    claimed: set[str] = set()

    for n, case in enumerate(cases, start=1):
        if not isinstance(case, dict):
            continue
        cid, covers = case_key(case, n), case.get("covers")
        if not isinstance(covers, list) or not covers:
            out.append(Finding(sid, cid, "no_ac_linked", "warn",
                               "the case is not linked to any acceptance criterion (covers is empty or missing)"))
            continue
        unknown = [a for a in covers if a not in ac_ids]
        if unknown:
            out.append(Finding(sid, cid, "unknown_ac", "fail",
                               f"covers lists {', '.join(map(str, unknown))}, which the story does not have"))
        claimed.update(a for a in covers if a in ac_ids)

    for ac in ac_ids:
        if ac not in claimed:
            out.append(Finding(sid, "", "ac_no_tests", "warn", f"{ac} has no test case linked to it"))
    return out


def run_code_checks(stories: dict[str, dict], groups: dict[str, list]) -> list[Finding]:
    """Run every code check over every story and return all findings, in story order."""
    out: list[Finding] = []
    for sid in groups:
        if sid not in stories:
            out.append(Finding(sid, "", "story_not_found", "fail",
                               "the cases file has this story but the stories file does not"))
    for sid, story in stories.items():
        cases = groups.get(sid)
        if cases is None:
            out.append(Finding(sid, "", "story_no_cases", "warn", "no test cases were supplied for this story"))
            continue
        for n, case in enumerate(cases, start=1):
            out.extend(check_case_schema(sid, case, n))
        out.extend(check_case_ids(sid, cases))
        out.extend(check_titles(sid, cases))
        out.extend(check_ac_links(story, cases))
    return out
