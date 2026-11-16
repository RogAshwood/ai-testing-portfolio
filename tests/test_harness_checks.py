"""
tests/test_harness_checks.py: free tests for the harness input contract and code checks
(harness/contract.py, harness/checks.py, harness/check.py).

What these tests are for
------------------------
The code checks decide which cases FAIL (break the input contract or a hard
rule) and which only get a WARNING. A wrong level either hides a real mistake
or buries reviewers in noise, so each rule is pinned down here with a small
made-up story and made-up cases. No API calls; no Day 4 files are needed.

  python -m pytest tests/test_harness_checks.py -v

Change history:
  2026-11-12  v1  first version (M7 step 1).
  2026-11-12  v2  steps with per-step expected results (Roger's review).
  2026-11-12  v3  the command test uses --no-judge (the judge is on by default from step 3).
"""
from __future__ import annotations

import json

import pytest

from harness import check
from harness.checks import run_code_checks
from harness.contract import InputError, load_cases, load_stories

@pytest.fixture(autouse=True)
def no_real_model(monkeypatch):
    """Safety net for every test in this file: a test that would create a real OpenAI client
    (and spend money) fails at once instead."""
    def refuse():
        """Stand-in for bench.generate.make_client that refuses to run."""
        raise AssertionError("a test tried to call the real model")
    monkeypatch.setattr("bench.generate.make_client", refuse)


STORY = {"story_id": "K01", "title": "Check customer age at onboarding", "as_a": "compliance analyst",
         "i_want": "applicants under 18 to be refused", "so_that": "we only onboard adults",
         "acceptance_criteria": [{"ac_id": "AC1", "text": "An applicant aged 18 or over can be onboarded."},
                                 {"ac_id": "AC2", "text": "An applicant under 18 is refused with reason UNDERAGE."}]}


def case(cid="TC01", **changes):
    """A made-up case that passes every code check; `changes` overrides or removes fields (None = remove)."""
    c = {"case_id": cid, "title": f"Applicant aged exactly 18 is onboarded ({cid})", "covers": ["AC1"],
         "preconditions": ["Applicant date of birth is 2008-11-12."], "steps": ["Submit the application on 2026-11-12."],
         "expected_result": "The applicant is onboarded."}
    for k, v in changes.items():
        if v is None:
            c.pop(k, None)
        else:
            c[k] = v
    return c


def findings(*cases):
    """Run the code checks on STORY with the given cases; return (check, level, case_id) tuples."""
    out = run_code_checks({"K01": STORY}, {"K01": list(cases)})
    return sorted((f.check, f.level, f.case_id) for f in out)


def test_a_clean_pair_of_cases_has_no_findings():
    """Two well-formed cases that between them cover both ACs: nothing to report."""
    assert findings(case("TC01"), case("TC02", covers=["AC2"])) == []


def test_missing_required_fields_fail_the_schema_check():
    """A case with no steps or no expected result breaks the input contract: FAIL, one finding each."""
    got = findings(case("TC01", steps=None, expected_result=""), case("TC02", covers=["AC2"]))
    assert got == [("schema", "fail", "TC01"), ("schema", "fail", "TC01")]


def test_technique_and_preconditions_are_optional():
    """The looser M7 contract: no technique label and no preconditions is still a valid case."""
    assert findings(case("TC01", preconditions=None), case("TC02", covers=["AC2"])) == []


def test_steps_with_their_own_expected_results_are_accepted():
    """Many test tools export steps as {action, expected}. Such a case is valid even with no case-level expected_result."""
    steps = [{"action": "Submit the application on 2026-11-12.", "expected": "The applicant is onboarded."}]
    assert findings(case("TC01", steps=steps, expected_result=None), case("TC02", covers=["AC2"])) == []


def test_a_case_with_no_expected_result_anywhere_fails():
    """No case-level expected_result and no step 'expected': nothing to check the outcome against, so FAIL."""
    steps = [{"action": "Submit the application."}]
    got = findings(case("TC01", steps=steps, expected_result=None), case("TC02", covers=["AC2"]))
    assert got == [("schema", "fail", "TC01")]


def test_repeated_case_id_fails():
    """Two cases with the same case_id in one story: the second one FAILS."""
    got = findings(case("TC01"), case("TC01", covers=["AC2"], title="Applicant aged 17 is refused"))
    assert ("schema", "fail", "TC01") in got


def test_title_rules_empty_only_the_id_or_repeated():
    """A title must exist, must say more than the case ID, and must not repeat another title word for word."""
    got = findings(case("TC01", title="  "), case("TC02", title="tc02", covers=["AC2"]),
                   case("TC03", title="Same title"), case("TC04", title="same   TITLE"))
    assert [g for g in got if g[0] == "title"] == [
        ("title", "fail", "TC01"), ("title", "fail", "TC02"), ("title", "fail", "TC04")]


def test_empty_or_missing_covers_is_a_warning_not_a_failure():
    """B1: a case linked to no AC (for example a specification-gap case) is a WARNING, never a FAIL."""
    got = findings(case("TC01"), case("TC02", covers=[]), case("TC03", covers=None),
                   case("TC04", covers=["AC2"]))
    assert got == [("no_ac_linked", "warn", "TC02"), ("no_ac_linked", "warn", "TC03")]


def test_covers_pointing_to_an_ac_the_story_does_not_have_fails():
    """A link to AC9 in a story with AC1-AC2 is a real mistake: FAIL."""
    got = findings(case("TC01", covers=["AC1", "AC9"]), case("TC02", covers=["AC2"]))
    assert got == [("unknown_ac", "fail", "TC01")]


def test_an_ac_that_no_case_lists_gets_a_story_level_warning():
    """A1: AC2 is never listed in any case's covers, so the story gets a WARNING for AC2 (no case ID)."""
    assert findings(case("TC01"), case("TC02", title="Applicant aged 40 is onboarded")) == [
        ("ac_no_tests", "warn", "")]


def test_stories_and_cases_files_must_match():
    """Cases for a story the stories file does not have FAIL; a story with no cases gets a WARNING."""
    out = run_code_checks({"K01": STORY}, {"K99": [case()]})
    assert sorted((f.story_id, f.check, f.level) for f in out) == [
        ("K01", "story_no_cases", "warn"), ("K99", "story_not_found", "fail")]


def test_all_three_cases_file_shapes_read_the_same(tmp_path):
    """Harness format, a plain list, and a Day 4 generation file all give the same cases."""
    cases = [case()]
    shapes = {"harness.json": {"stories": [{"story_id": "K01", "test_cases": cases}]},
              "list.json": [{"story_id": "K01", "test_cases": cases}],
              "day4.json": {"meta": {}, "records": [{"story_id": "K01", "parsed": {"test_cases": cases}}]}}
    for name, data in shapes.items():
        (tmp_path / name).write_text(json.dumps(data), encoding="utf-8")
        groups, problems = load_cases(tmp_path / name)
        assert groups == {"K01": cases} and problems == [], name


def test_an_unreadable_day4_reply_is_reported_not_skipped(tmp_path):
    """A Day 4 record whose reply could not be parsed gives a story-level FAIL, so it is not silently lost."""
    p = tmp_path / "day4.json"
    p.write_text(json.dumps({"records": [{"story_id": "K01", "parsed": None}]}), encoding="utf-8")
    groups, problems = load_cases(p)
    assert groups == {"K01": []} and [(f.check, f.level) for f in problems] == [("schema", "fail")]


def test_a_broken_stories_file_stops_the_run(tmp_path):
    """Repeated AC IDs in the stories file make every later check unreliable, so the run stops with a clear error."""
    bad = dict(STORY, acceptance_criteria=[{"ac_id": "AC1", "text": "x"}, {"ac_id": "AC1", "text": "y"}])
    p = tmp_path / "stories.json"
    p.write_text(json.dumps({"stories": [bad]}), encoding="utf-8")
    with pytest.raises(InputError, match="repeated AC IDs"):
        load_stories(p)


def test_the_command_writes_its_outputs_and_exit_code(tmp_path):
    """End to end (free checks only, no model call): the command writes cases.csv, findings.csv and
    summary.md, and exits 1 when a case fails."""
    (tmp_path / "s.json").write_text(json.dumps({"stories": [STORY]}), encoding="utf-8")
    (tmp_path / "c.json").write_text(json.dumps({"stories": [{"story_id": "K01", "test_cases": [
        case(), case("TC02", covers=["AC7"])]}]}), encoding="utf-8")
    code = check.main(["--stories", str(tmp_path / "s.json"), "--cases", str(tmp_path / "c.json"),
                       "--lints", "none", "--no-judge", "--out", str(tmp_path / "out")])
    assert code == 1
    assert {p.name for p in (tmp_path / "out").iterdir()} == {"cases.csv", "findings.csv", "summary.md"}
    assert "unknown_ac" in (tmp_path / "out" / "findings.csv").read_text(encoding="utf-8-sig")
