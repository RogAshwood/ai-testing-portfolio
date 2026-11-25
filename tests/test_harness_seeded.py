"""
tests/test_harness_seeded.py: free tests for M7 step 4: the seeded-defects set and its scorer
(datasets/harness_seeded_cases.json, harness/seeded.py), the calendar-edge caution on
duplicate warnings (harness/judge.py) and the bare-prompt generator (harness/generate_bare.py).

What these tests are for
------------------------
Criterion 3 of the go/no-go is "all seeded defects are caught", so the seed file must be
well formed, the free checks must catch every free seed with no false alarm on the clean
controls, and the scorer must call a miss a miss. The judge part of the seeded run costs
money and is run by hand (python -m harness.seeded); here the model is never called.

  python -m pytest tests/test_harness_seeded.py -v

Change history:
  2026-11-12  v1  first version (M7 step 4).
  2026-11-24  v2  the AML/KYC seed set (datasets/aml_seeded_cases.json, --set aml).
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from harness import generate_bare, seeded
from harness.contract import Finding, load_cases, load_stories
from harness.judge import calendar_caution, calendar_edges, judge_findings, story_rules_use_dates


@pytest.fixture(autouse=True)
def no_real_model(monkeypatch):
    """Safety net for every test in this file: a test that would create a real OpenAI client
    (and spend money) fails at once instead."""
    def refuse():
        """Stand-in for bench.generate.make_client that refuses to run."""
        raise AssertionError("a test tried to call the real model")
    monkeypatch.setattr("bench.generate.make_client", refuse)


DATED = {"story_id": "K04", "title": "Document expiry", "as_a": "analyst", "i_want": "expired IDs refused",
         "so_that": "only valid IDs are used",
         "acceptance_criteria": [{"ac_id": "AC1", "text": "An ID that expired more than 30 days ago is refused."}]}
UNDATED = dict(DATED, acceptance_criteria=[{"ac_id": "AC1", "text": "The ID shows the expiry date and the holder's name."}])


def case(cid, when):
    """A made-up case whose only input is a date."""
    return {"case_id": cid, "title": f"ID checked on {when}", "covers": ["AC1"],
            "preconditions": [f"The ID expired on {when}."], "steps": ["Check the ID."], "expected_result": "Refused."}


# --- the seed file ----------------------------------------------------------------
def test_the_seed_file_is_a_valid_cases_file_and_every_expectation_points_at_a_real_case():
    """The seed file can be passed straight to harness.check, and no expectation names a missing case or story."""
    groups, problems = load_cases(seeded.HARNESS_SEEDS)
    golden = load_stories(seeded.GOLDEN)
    assert problems == [] and set(groups) <= set(golden)
    _, case_exp, story_exp = seeded.harness_set()
    ids = {(sid, c["case_id"]) for sid, cases in groups.items() for c in cases}
    assert all((e["story_id"], e["case_id"]) in ids for e in case_exp)
    assert all(e["story_id"] in groups for e in story_exp)
    assert sum(e["control"] for e in case_exp) == 7


def test_the_free_checks_catch_every_free_seed_with_no_false_alarm(tmp_path):
    """Without the judge: every seed whose defect a free check can see is caught, every clean
    control stays clean, and the judge-only seeds are reported as 'not run' (not as passes)."""
    rows, _ = seeded.run_set("harness", tmp_path, judge=False)
    results = {r["seed_id"]: r["result"] for r in rows}
    assert not [s for s, r in results.items() if r in ("missed", "false alarm")]
    assert results["HS06"] == "caught" and results["HS15"] == "caught" and results["HS25"] == "caught"
    assert results["HS08"] == "not run" and results["HS01"] == "ok"


def test_the_aml_seed_file_points_at_real_aml_stories_and_cases():
    """datasets/aml_seeded_cases.json is a valid cases file on the AML/KYC stories: 18 case
    expectations (6 clean controls) and 2 story-level seeds, each naming a real case or story."""
    groups, problems = load_cases(seeded.AML_SEEDS)
    stories = load_stories(seeded.AML_STORIES)
    assert problems == [] and set(groups) <= set(stories)
    _, case_exp, story_exp = seeded.harness_set(seeded.AML_SEEDS)
    ids = {(sid, c["case_id"]) for sid, cases in groups.items() for c in cases}
    assert all((e["story_id"], e["case_id"]) in ids for e in case_exp)
    assert len(case_exp) == 18 and sum(e["control"] for e in case_exp) == 6 and len(story_exp) == 2


def test_the_free_checks_catch_the_free_aml_seeds_with_no_false_alarm(tmp_path):
    """Second domain, free checks only: missing expected result, unknown AC, an untested AC and an
    untested range end are caught; controls stay clean; judge-only seeds are 'not run'."""
    rows, _ = seeded.run_set("aml", tmp_path, judge=False)
    results = {r["seed_id"]: r["result"] for r in rows}
    assert not [s for s, r in results.items() if r in ("missed", "false alarm")]
    assert [results[k] for k in ("AS17", "AS18", "AS19", "AS20")] == ["caught"] * 4
    assert results["AS02"] == "not run" and results["AS01"] == "ok"


def test_day4_seeds_become_must_and_must_not_checks():
    """Day 4 seed SD01 (deadline day treated as late) expects verdict 'incorrect', so the harness must
    fail it on verdict; a Day 4 control expecting 'correct' becomes 'verdict must not fire'."""
    _, exps, _ = seeded.day4_set()
    by_id = {e["seed_id"]: e for e in exps}
    assert by_id["SD01"]["must_fire"] == ["verdict"]
    assert any(e["must_fire"] == [] and "verdict" in e["must_not_fire"] for e in exps)


# --- the scorer -------------------------------------------------------------------
def test_the_scorer_reports_a_miss_a_false_alarm_and_a_missing_caution():
    """A must_fire check that did not appear is 'missed'; anything on a control is a 'false alarm';
    a duplicate on a calendar-edge seed without the caution counts as missed."""
    seed = {"seed_id": "X1", "story_id": "S", "case_id": "TC1", "defect": "d", "must_fire": ["atomic"], "control": False}
    assert seeded.score_case(seed, [], judge_ran=True)["result"] == "missed"
    control = dict(seed, must_fire=[], control=True)
    noise = [Finding("S", "TC1", "concrete", "warn", "x")]
    assert seeded.score_case(control, noise, judge_ran=True)["result"] == "false alarm"
    cal = dict(seed, must_fire=[], if_duplicate_then_caution=True, tolerate=["duplicate"])
    dup = [Finding("S", "TC1", "duplicate", "warn", "repeats TC0 (same condition).")]
    assert seeded.score_case(cal, dup, judge_ran=True)["missed"] == "calendar caution"


# --- calendar-edge caution --------------------------------------------------------
def test_calendar_edges_are_recognised():
    """Year end, month end, 28/29 February and end of day are edges; an ordinary date is not."""
    assert calendar_edges("on 31 December 2027 at 23:59") == {"year end", "end of day"}
    assert calendar_edges("2024-02-29") == {"28/29 February (leap year)"}
    assert calendar_edges("30/04/2026") == {"month end"} and calendar_edges("10 March 2027") == set()


def test_only_stories_whose_rules_use_dates_get_the_caution():
    """'30 days' makes dates part of the rule; a date that is only shown on a document does not.
    'Day case' (a type of hospital procedure) is not about time."""
    assert story_rules_use_dates(DATED) and not story_rules_use_dates(UNDATED)
    day_case = dict(DATED, acceptance_criteria=[{"ac_id": "AC1", "text": "A day case procedure needs approval."}])
    assert not story_rules_use_dates(day_case)


def test_a_duplicate_across_a_calendar_edge_carries_the_caution():
    """The judge calls the year-end case a duplicate: in a dated story the warning adds a caution;
    in an undated story it does not."""
    cases = [case("TC01", "10 March 2027"), case("TC02", "31 December 2027")]
    marks = {"cases_call": {"parsed": {"cases": [
        {"case_id": "TC01", "verdict": "correct", "atomic": True, "concrete": True, "claims": [], "duplicate_of": ""},
        {"case_id": "TC02", "verdict": "correct", "atomic": True, "concrete": True, "claims": [], "duplicate_of": "TC01"}]}}}
    [dated] = [f for f in judge_findings(DATED, cases, marks)[0] if f.check == "duplicate"]
    [plain] = [f for f in judge_findings(UNDATED, cases, marks)[0] if f.check == "duplicate"]
    assert "Caution" in dated.message and "year end" in dated.message and "Caution" not in plain.message
    assert calendar_caution(DATED, cases[0], case("TC03", "11 March 2027")) == ""


# --- bare-prompt generator --------------------------------------------------------
def test_the_bare_prompt_has_no_guardrails():
    """The bare prompt asks only for test cases in the JSON shape: no 'do not invent', no techniques."""
    text, fp = generate_bare.load_bare_prompt()
    assert len(fp) == 12 and "Write test cases for the user story below." in text
    assert not any(w in text.lower() for w in ("invent", "boundary", "technique", "equivalence"))


def test_the_bare_generator_saves_a_file_the_harness_can_read(tmp_path, monkeypatch):
    """With a fake model: one call per story, the file lands in results/m7 (here a temp folder),
    and harness.check can read it as a cases file. A case without an expected result is reported."""
    reply = {"story_id": "S01", "test_cases": [
        {"case_id": "TC01", "title": "Submit a claim", "covers": ["AC1"], "preconditions": [],
         "steps": ["Submit."], "expected_result": "It works."},
        {"case_id": "TC02", "title": "Submit again", "steps": ["Submit."]}]}
    calls = []

    def create(model, instructions, input):
        """Fake responses.create: record the call and return the made-up reply."""
        calls.append(input)
        return SimpleNamespace(output_text=json.dumps(dict(reply, story_id=input.split("Story ID: ")[1][:3])),
                               model=model, usage=SimpleNamespace(input_tokens=500, output_tokens=300))

    monkeypatch.setattr(generate_bare, "OUT_DIR", tmp_path)
    out = generate_bare.run(["S01", "S05"], client=SimpleNamespace(responses=SimpleNamespace(create=create)))
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(calls) == 2 and data["meta"]["prompt_version"] == "bare"
    assert data["records"][0]["schema_valid"] is False and "no expected result" in data["records"][0]["schema_issues"][0]
    groups, problems = load_cases(out)
    assert set(groups) == {"S01", "S05"} and problems == []
