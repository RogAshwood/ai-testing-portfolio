"""contract.py: read the stories file and the cases file, and check the input contract.

The input contract (agreed in the M7 scope note, 12 Nov 2026)
-------------------------------------------------------------
Stories file: JSON. Either {"stories": [...]} (the Day 4 golden set works as it is)
or a plain list. Each story needs:
    story_id, title, as_a, i_want, so_that, acceptance_criteria [{ac_id, text}]
Anything else (for example the golden set's expected ideas) is ignored here.

Cases file: JSON, in one of three shapes, so cases from any tool can be read:
    1. {"stories": [{"story_id": "S01", "test_cases": [...]}, ...]}   (harness format)
    2. [{"story_id": "S01", "test_cases": [...]}, ...]                 (the same, as a list)
    3. a Day 4 generation file (results/testgen/gen_*.json)            (for regression)
Each test case needs:  case_id, title, steps, and an expected result
Optional:              covers (AC IDs), preconditions, technique
Steps can be plain text, or objects {"action": ..., "expected": ...} as many
test-management tools export them. The expected result can be the case-level
`expected_result`, per-step `expected` text, or both; at least one is needed.
A missing or empty `covers` is allowed: it is reported later as "no AC linked"
(a warning), not as a schema failure. This is looser than the Day 4 contract,
which also required the generator's own technique label.

What this module reports
------------------------
Schema problems are returned as Finding records at level "fail". Nothing here
calls a model or the internet.

Change history:
  2026-11-12  v1  first version (M7 step 1).
  2026-11-12  v2  steps may be objects with a per-step expected result (Roger's review).
  2026-11-12  v3  flat_case keeps covers (the frozen judge needs it).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

STORY_FIELDS = ("story_id", "title", "as_a", "i_want", "so_that", "acceptance_criteria")
REQUIRED_CASE_FIELDS = ("case_id", "title", "steps")   # plus an expected result (see check_case_schema)
OPTIONAL_LIST_FIELDS = ("covers", "preconditions")


@dataclass
class Finding:
    """One thing the harness found. case_id is "" when the finding is about a whole story."""
    story_id: str
    case_id: str
    check: str          # short name of the check, e.g. "schema" or "vague_steps"
    level: str          # "fail", "warn", or "info" (a reminder the code cannot check; never counted as a warning)
    message: str        # plain-English explanation for the reviewer


class InputError(Exception):
    """The stories or cases file cannot be read at all (not a per-case problem)."""


def _read_json(path: Path) -> object:
    """Read a JSON file, turning any read or parse error into a plain InputError."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise InputError(f"file not found: {path}")
    except json.JSONDecodeError as e:
        raise InputError(f"{path} is not valid JSON: {e.msg} (line {e.lineno})")


def load_stories(path: Path) -> dict[str, dict]:
    """Read the stories file and return {story_id: story}.

    Raises InputError if a story is missing a required field or has duplicate AC IDs,
    because every later check depends on the stories being right."""
    data = _read_json(path)
    stories = data.get("stories") if isinstance(data, dict) else data
    if not isinstance(stories, list) or not stories:
        raise InputError(f"{path}: expected a list of stories or {{'stories': [...]}}")

    result: dict[str, dict] = {}
    for n, s in enumerate(stories, start=1):
        if not isinstance(s, dict):
            raise InputError(f"{path}: story {n} is not an object")
        missing = [f for f in STORY_FIELDS if f not in s]
        if missing:
            raise InputError(f"{path}: story {s.get('story_id', n)} is missing {missing}")
        ac_ids = [a.get("ac_id") for a in s["acceptance_criteria"]]
        if len(set(ac_ids)) != len(ac_ids) or None in ac_ids:
            raise InputError(f"{path}: story {s['story_id']} has missing or repeated AC IDs {ac_ids}")
        if s["story_id"] in result:
            raise InputError(f"{path}: story {s['story_id']} appears twice")
        result[s["story_id"]] = s
    return result


def load_cases(path: Path) -> tuple[dict[str, list], list[Finding]]:
    """Read the cases file in any of the three shapes and return ({story_id: [cases]}, findings).

    A Day 4 generation record whose reply could not be parsed gives a story-level
    "fail" finding and no cases, so the story is reported rather than skipped."""
    data = _read_json(path)
    findings: list[Finding] = []
    groups: dict[str, list] = {}

    if isinstance(data, dict) and "records" in data:           # shape 3: Day 4 generation file
        for rec in data["records"]:
            parsed = rec.get("parsed") or {}
            cases = parsed.get("test_cases")
            if not isinstance(cases, list):
                findings.append(Finding(rec.get("story_id", "?"), "", "schema", "fail",
                                        "the tool's reply for this story could not be read as test cases"))
                cases = []
            groups[rec.get("story_id", "?")] = cases
        return groups, findings

    entries = data.get("stories") if isinstance(data, dict) else data   # shapes 1 and 2
    if not isinstance(entries, list):
        raise InputError(f"{path}: expected {{'stories': [...]}}, a list, or a Day 4 generation file")
    for n, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict) or "story_id" not in entry:
            raise InputError(f"{path}: entry {n} has no story_id")
        cases = entry.get("test_cases")
        if not isinstance(cases, list):
            findings.append(Finding(entry["story_id"], "", "schema", "fail", "test_cases is missing or not a list"))
            cases = []
        groups.setdefault(entry["story_id"], []).extend(cases)
    return groups, findings


def _is_text_list(value: object) -> bool:
    """True if value is a list whose items are all strings."""
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def check_case_schema(story_id: str, case: object, n: int) -> list[Finding]:
    """List the ways one case breaks the input contract (all at level "fail")."""
    if not isinstance(case, dict):
        return [Finding(story_id, f"#{n}", "schema", "fail", "the case is not a JSON object")]
    cid = case.get("case_id") if isinstance(case.get("case_id"), str) and case.get("case_id") else f"#{n}"
    out: list[Finding] = []

    def fail(msg: str) -> None:
        """Record one schema failure for this case."""
        out.append(Finding(story_id, cid, "schema", "fail", msg))

    if cid == f"#{n}":
        fail("case_id is missing or empty")
    if not isinstance(case.get("title"), str):
        fail("title is missing or not text")
    steps = case.get("steps")
    if not isinstance(steps, list) or not steps:
        fail("steps is missing or empty")
    elif not all(_is_step(s) for s in steps):
        fail("each step should be text, or an object with an 'action' (text) and an optional 'expected' (text)")
    elif not any(step_action(s).strip() for s in steps):
        fail("every step is empty")
    expected = case.get("expected_result")
    has_step_expected = isinstance(steps, list) and any(step_expected(s).strip() for s in steps if _is_step(s))
    if expected is not None and not isinstance(expected, str):
        fail("expected_result should be text")
    elif not (expected or "").strip() and not has_step_expected:
        fail("no expected result: expected_result is missing or empty and no step has an 'expected'")
    for field in OPTIONAL_LIST_FIELDS:
        if field in case and case[field] is not None and not _is_text_list(case[field]):
            fail(f"{field} should be a list of text")
    return out


def case_key(case: dict, n: int) -> str:
    """The case ID to report under: its case_id, or #n if it has none."""
    cid = case.get("case_id") if isinstance(case, dict) else None
    return cid if isinstance(cid, str) and cid else f"#{n}"


def _is_step(step: object) -> bool:
    """True for a text step, or a step object with a text 'action' and an optional text 'expected'."""
    if isinstance(step, str):
        return True
    return (isinstance(step, dict) and isinstance(step.get("action"), str)
            and isinstance(step.get("expected", ""), str))


def step_action(step: object) -> str:
    """What the tester does in a step (the whole step if it is plain text)."""
    if isinstance(step, str):
        return step
    return step.get("action", "") if isinstance(step, dict) and isinstance(step.get("action"), str) else ""


def step_expected(step: object) -> str:
    """The step's own expected result, or "" for a plain-text step."""
    value = step.get("expected", "") if isinstance(step, dict) else ""
    return value if isinstance(value, str) else ""


def actions(case: dict) -> list[str]:
    """The step actions of a case, as text, whichever way the steps were written."""
    steps = case.get("steps") if isinstance(case, dict) else None
    return [step_action(s) for s in steps] if isinstance(steps, list) else []


def step_expecteds(case: dict) -> list[str]:
    """The per-step expected results of a case (empty strings dropped)."""
    steps = case.get("steps") if isinstance(case, dict) else None
    return [e for e in (step_expected(s) for s in steps) if e.strip()] if isinstance(steps, list) else []


def all_expected(case: dict) -> list[str]:
    """Every expected result in the case: the per-step ones, then the case-level one."""
    case_level = case.get("expected_result") if isinstance(case.get("expected_result"), str) else ""
    return step_expecteds(case) + ([case_level] if case_level.strip() else [])


def input_text(case: dict) -> str:
    """The input side of a case: title, preconditions and step actions (not the expected results)."""
    parts = [case.get("title") or ""]
    if _is_text_list(case.get("preconditions")):
        parts.extend(case["preconditions"])
    parts.extend(actions(case))
    return " ".join(p for p in parts if isinstance(p, str))


def flat_case(case: dict) -> dict:
    """The case with step objects flattened: steps as action text and one expected_result
    joining every expected result; covers kept (an empty list if missing). Used where code written
    for the Day 4 format (bench/score.py, bench/judge.py) needs plain text."""
    return {"case_id": case.get("case_id", ""), "title": case.get("title") or "",
            "covers": case.get("covers") if _is_text_list(case.get("covers")) else [],
            "preconditions": case.get("preconditions") if _is_text_list(case.get("preconditions")) else [],
            "steps": actions(case), "expected_result": " ".join(all_expected(case))}
