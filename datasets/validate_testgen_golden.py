"""Validate datasets/testgen_golden.json before it is used in the Day 4 benchmark.

Errors (exit code 1) are structural problems that would break scoring:
  - schema violations (if jsonschema is installed)
  - duplicate story, AC or idea IDs; idea IDs not prefixed with their story ID
  - ideas pointing at ACs that do not exist
  - ACs with no expected idea
  - stories with no negative idea, or no boundary idea (unless boundary_exempt_reason is set)

Warnings (exit code 0) are content checks that need a human decision:
  - routing values or reason codes that are not in plan_rules.md sections 2 and 7
  - reason codes that do not appear in the story's own ACs (the generator only sees the
    story card, so an idea that relies on another story's rule is not derivable)
  - very small or very large idea counts per story

Usage:  python datasets/validate_testgen_golden.py [path/to/testgen_golden.json]
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_PATH = HERE / "testgen_golden.json"
SCHEMA_PATH = HERE / "testgen_golden.schema.json"

ROUTINGS = {"auto_approve", "manual_review", "decline_recommended"}
REASON_CODES = {
    "UNCLEAR", "EXCLUDED", "WAITING_PERIOD", "LATE_SUBMISSION", "ANNUAL_LIMIT_REACHED",
    "MISSING_RECEIPT", "MISSING_REFERRAL", "MISSING_PREAUTH", "INPATIENT_REVIEW",
    "OVER_LIMIT", "HIGH_VALUE", "WITHIN_RULES",
}
MIN_IDEAS, MAX_IDEAS = 4, 10

ROUTING_LIKE = re.compile(r"\b(auto[\s_-]?approv\w*|manual[\s_-]review\w*|decline[\s_-]recommend\w*)\b", re.I)
CODE_LIKE = re.compile(r"\b[A-Z][A-Z_]{3,}\b")


def load(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def schema_errors(data: dict) -> list[str]:
    try:
        import jsonschema
    except ImportError:
        return ["(jsonschema not installed: schema check skipped; pip install jsonschema)"]
    if not SCHEMA_PATH.exists():
        return [f"(schema not found at {SCHEMA_PATH}: schema check skipped)"]
    validator = jsonschema.Draft202012Validator(load(SCHEMA_PATH))
    return [f"schema: {'/'.join(map(str, e.path)) or '(root)'}: {e.message}"
            for e in sorted(validator.iter_errors(data), key=lambda e: list(e.path))]


def check(data: dict) -> tuple[list[str], list[str], list[dict]]:
    errors, warnings, summary = [], [], []
    errors += [e for e in schema_errors(data) if not e.startswith("(")]
    warnings += [e for e in schema_errors(data) if e.startswith("(")]

    stories = data.get("stories", [])
    for sid, n in Counter(s.get("story_id") for s in stories).items():
        if n > 1:
            errors.append(f"duplicate story_id {sid}")

    all_ideas = Counter(i.get("idea_id") for s in stories for i in s.get("expected_ideas", []))
    for iid, n in all_ideas.items():
        if n > 1:
            errors.append(f"duplicate idea_id {iid} ({n} times)")

    for s in stories:
        sid = s.get("story_id", "?")
        acs = [a.get("ac_id") for a in s.get("acceptance_criteria", [])]
        ac_set = set(acs)
        ac_text = " ".join(a.get("text", "") for a in s.get("acceptance_criteria", []))
        story_codes = set(CODE_LIKE.findall(ac_text)) & REASON_CODES
        ideas = s.get("expected_ideas", [])

        for ac, n in Counter(acs).items():
            if n > 1:
                errors.append(f"{sid}: duplicate ac_id {ac}")

        covered = set()
        for i in ideas:
            iid = i.get("idea_id", "?")
            if not str(iid).startswith(f"{sid}-"):
                errors.append(f"{iid}: idea_id does not start with {sid}-")
            for ac in i.get("ac_ids", []):
                if ac not in ac_set:
                    errors.append(f"{iid}: refers to {ac}, which {sid} does not have")
                covered.add(ac)

            text = i.get("idea", "")
            for m in ROUTING_LIKE.findall(text):
                if m not in ROUTINGS:
                    warnings.append(f"{iid}: '{m}' is not a routing value (use {', '.join(sorted(ROUTINGS))})")
            for code in set(CODE_LIKE.findall(text)):
                if code in REASON_CODES and code not in story_codes:
                    warnings.append(f"{iid}: {code} is not in {sid}'s ACs, so the generator cannot derive it")
                elif code not in REASON_CODES and "_" in code:
                    warnings.append(f"{iid}: '{code}' is not a reason code from plan_rules.md section 7")

        for ac in acs:
            if ac not in covered:
                errors.append(f"{sid}: {ac} has no expected idea")

        techniques = Counter(i.get("technique") for i in ideas)
        if ideas and techniques["negative"] == 0:
            errors.append(f"{sid}: no negative idea")
        if ideas and techniques["boundary"] == 0 and not s.get("boundary_exempt_reason"):
            errors.append(f"{sid}: no boundary idea (add one, or set boundary_exempt_reason)")
        if not ideas:
            warnings.append(f"{sid}: no expected ideas yet")
        elif not MIN_IDEAS <= len(ideas) <= MAX_IDEAS:
            warnings.append(f"{sid}: {len(ideas)} ideas (guide is {MIN_IDEAS} to {MAX_IDEAS})")

        summary.append({"story": sid, "acs": len(acs), "ideas": len(ideas),
                        "positive": techniques["positive"], "negative": techniques["negative"],
                        "boundary": techniques["boundary"]})
    return errors, warnings, summary


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PATH
    data = load(path)
    errors, warnings, summary = check(data)

    print(f"{path.name}  version {data.get('version')}\n")
    print(f"{'story':<6}{'ACs':>5}{'ideas':>7}{'pos':>5}{'neg':>5}{'bnd':>5}")
    for r in summary:
        print(f"{r['story']:<6}{r['acs']:>5}{r['ideas']:>7}{r['positive']:>5}{r['negative']:>5}{r['boundary']:>5}")
    tot = {k: sum(r[k] for r in summary) for k in ("acs", "ideas", "positive", "negative", "boundary")}
    print(f"{'total':<6}{tot['acs']:>5}{tot['ideas']:>7}{tot['positive']:>5}{tot['negative']:>5}{tot['boundary']:>5}\n")

    for label, items in (("ERRORS", errors), ("WARNINGS", warnings)):
        print(f"{label} ({len(items)})")
        for item in items:
            print(f"  - {item}")
        print()
    print("FAIL" if errors else "PASS")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
