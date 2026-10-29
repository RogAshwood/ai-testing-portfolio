"""testcase_schema.py: parse and check the generator's output. Free and deterministic.

Two levels, reported separately so neither hides the other:
- strict JSON:  the reply is a JSON object with nothing around it, as the prompt asks.
- usable JSON:  a JSON object can be recovered, e.g. from inside ```json fences.
                Scoring uses usable JSON; the strict figure shows prompt compliance.

`check_cases()` then lists every way a parsed reply breaks the output contract
in bench/prompts/testgen_v*.txt. An empty list means schema-valid.

`covers` means the IDs of the story's own acceptance criteria (AC1, AC2, ...) as
written in datasets/testgen_golden.json. It never refers to plan_rules.md, which
the generator does not see. This check only confirms the IDs exist; whether a
case really tests the AC it claims is the judge's verified-coverage check.

Change history:
  2026-10-23  v1  first version (Day 4).
"""

from __future__ import annotations

import json
import re

TECHNIQUES = {"positive", "negative", "boundary"}
CASE_FIELDS = {
    "case_id": str, "title": str, "technique": str, "covers": list,
    "preconditions": list, "steps": list, "expected_result": str,
}
FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.S)


def parse_reply(text: str) -> tuple[dict | None, dict]:
    """Return (parsed object or None, info). info keys: strict_json, fenced, error."""
    info = {"strict_json": False, "fenced": False, "error": None}
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            info["strict_json"] = True
            return obj, info
        info["error"] = "top level is not a JSON object"
        return None, info
    except json.JSONDecodeError:
        pass

    m = FENCE.match(text)
    candidate = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    info["fenced"] = bool(m)
    try:
        obj = json.loads(candidate)
        if isinstance(obj, dict):
            return obj, info
        info["error"] = "top level is not a JSON object"
    except json.JSONDecodeError as e:
        info["error"] = f"not JSON: {e.msg} (line {e.lineno})"
    return None, info


def check_cases(obj: dict, story: dict) -> list[str]:
    """List contract violations for one parsed reply against its story."""
    issues: list[str] = []
    ac_ids = {a["ac_id"] for a in story["acceptance_criteria"]}

    if obj.get("story_id") != story["story_id"]:
        issues.append(f"story_id is {obj.get('story_id')!r}, expected {story['story_id']!r}")
    cases = obj.get("test_cases")
    if not isinstance(cases, list) or not cases:
        return issues + ["test_cases missing, empty or not a list"]

    seen = set()
    for n, case in enumerate(cases, start=1):
        if not isinstance(case, dict):
            issues.append(f"case {n}: not an object")
            continue
        cid = case.get("case_id", f"#{n}")
        for field, typ in CASE_FIELDS.items():
            if field not in case:
                issues.append(f"{cid}: missing {field}")
            elif not isinstance(case[field], typ):
                issues.append(f"{cid}: {field} should be {typ.__name__}")
        if cid in seen:
            issues.append(f"{cid}: duplicate case_id")
        seen.add(cid)
        if isinstance(case.get("technique"), str) and case["technique"] not in TECHNIQUES:
            issues.append(f"{cid}: technique {case['technique']!r} not in {sorted(TECHNIQUES)}")
        if isinstance(case.get("covers"), list):
            if not case["covers"]:
                issues.append(f"{cid}: covers is empty")
            unknown = [a for a in case["covers"] if a not in ac_ids]
            if unknown:
                issues.append(f"{cid}: covers unknown AC {unknown}")
    return issues
