"""
tests/test_harness_judge.py: free tests for the harness judge checks (harness/judge.py,
harness/check.py, harness/regression.py).

What these tests are for
------------------------
The judge's marks decide which cases FAIL (verdict incorrect or not in basis) and
which get a WARNING (atomic, duplicate, over-claimed AC, not concrete, unclear title,
AC with no verified test). These tests pin down that mapping, the duplicate groups,
how step objects reach the judge, cost reporting, reuse mode and the live-agreement
comparison. The model is replaced by a fake client that returns made-up marks, so
there are no API calls and no cost.

  python -m pytest tests/test_harness_judge.py -v

Change history:
  2026-11-12  v1  first version (M7 step 3).
  2026-11-13  v2  the fake client also answers the checklist judge.
  2026-11-13  v3  checklist in two passes (the fake client answers the story review).
  2026-11-13  v4  C09 is checked in every story, so the test-coverage call always runs (one more call per story).
"""
from __future__ import annotations

import json

import pytest
from types import SimpleNamespace

from harness import check
from harness.judge import duplicate_groups, judge_findings, judge_story, load_title_prompt
from harness.regression import live_agreement

@pytest.fixture(autouse=True)
def no_real_model(monkeypatch):
    """Safety net for every test in this file: a test that would create a real OpenAI client
    (and spend money) fails at once instead."""
    def refuse():
        """Stand-in for bench.generate.make_client that refuses to run."""
        raise AssertionError("a test tried to call the real model")
    monkeypatch.setattr("bench.generate.make_client", refuse)


STORY = {"story_id": "K03", "title": "Sanctions screening at onboarding", "as_a": "compliance analyst",
         "i_want": "every applicant screened", "so_that": "sanctioned persons are not onboarded",
         "acceptance_criteria": [{"ac_id": "AC1", "text": "An exact name match on the sanctions list blocks onboarding."},
                                 {"ac_id": "AC2", "text": "No match lets onboarding continue."}]}


def case(cid, covers=("AC1",), **changes):
    """A made-up well-formed case."""
    c = {"case_id": cid, "title": f"Applicant {cid} screened against the list", "covers": list(covers),
         "preconditions": ["The list holds 'Ivan Petrov'."], "steps": ["Onboard 'Ivan Petrov'."],
         "expected_result": "Onboarding is blocked."}
    c.update(changes)
    return c


def mark(cid, verdict="correct", atomic=True, concrete=True, duplicate_of="", claims=(("AC1", True),),
         technique="positive", reason=""):
    """A made-up case-judge mark in the judge_cases_v2 output shape."""
    return {"case_id": cid, "verdict": verdict, "technique": technique, "concrete": concrete, "atomic": atomic,
            "claims": [{"ac_id": a, "supported": s} for a, s in claims], "duplicate_of": duplicate_of,
            "reason": reason}


def judged(marks, titles=None):
    """A judge record as judge_story returns it, from lists of marks."""
    return {"cases_call": {"parsed": {"cases": marks}},
            "title_call": {"parsed": {"titles": titles}} if titles is not None else None}


def found(findings):
    """(check, level, case_id) for each finding, sorted, for easy comparison."""
    return sorted((f.check, f.level, f.case_id) for f in findings)


class FakeClient:
    """Stands in for the OpenAI client: answers the case judge, the title judge and the checklist
    judge with made-up marks, records every request, and reports fixed token counts."""

    def __init__(self, case_marks, title_marks=None):
        """case_marks / title_marks: {story_id: list of marks} to return for each story."""
        self.case_marks, self.title_marks, self.requests = case_marks, title_marks or {}, []
        self.responses = self

    def create(self, model, instructions, input, text=None):
        """Return the made-up marks for the story named in the input, like responses.create."""
        self.requests.append({"instructions": instructions, "input": input})
        sid = input.split("Story ID: ")[1].split("\n")[0]
        if "checklist of generic test ideas" in instructions:      # checklist story review: nothing applies
            body = {"items": []}
        elif "titles of test cases" in instructions:
            body = {"titles": self.title_marks.get(sid, [])}
        else:
            body = {"cases": self.case_marks[sid]}
        return SimpleNamespace(output_text=json.dumps(body), model=model,
                               usage=SimpleNamespace(input_tokens=1000, output_tokens=500))


def test_a_correct_clean_case_has_no_judge_findings():
    """Correct, atomic, concrete, no duplicate, claims supported, both ACs verified: nothing to report."""
    cases = [case("TC01"), case("TC02", covers=["AC2"])]
    marks = [mark("TC01"), mark("TC02", claims=[("AC2", True)])]
    assert found(judge_findings(STORY, cases, judged(marks))[0]) == []


def test_incorrect_and_not_in_basis_verdicts_fail_the_case():
    """A wrong expected result, or one the story does not define, is a FAIL with the judge's reason."""
    cases = [case("TC01"), case("TC02"), case("TC03", covers=["AC2"])]
    marks = [mark("TC01", verdict="incorrect", reason="blocks on a partial match"),
             mark("TC02", verdict="not_in_basis", reason="asserts an alert email"),
             mark("TC03", claims=[("AC2", True)])]
    findings, _ = judge_findings(STORY, cases, judged(marks))
    assert [(f.check, f.level, f.case_id) for f in findings if f.check == "verdict"] == [
        ("verdict", "fail", "TC01"), ("verdict", "fail", "TC02")]
    assert "blocks on a partial match" in findings[0].message


def test_not_atomic_and_not_concrete_are_warnings():
    """Bundled checks and class-level inputs are for a person to look at: WARNINGS, not failures (12 Nov)."""
    cases = [case("TC01"), case("TC02", covers=["AC2"])]
    marks = [mark("TC01", atomic=False, concrete=False), mark("TC02", claims=[("AC2", True)])]
    assert found(judge_findings(STORY, cases, judged(marks))[0]) == [
        ("atomic", "warn", "TC01"), ("concrete", "warn", "TC01")]


def test_a_duplicate_warning_names_the_earlier_case():
    """A duplicate is a WARNING on the later case, and its message names the case it repeats."""
    cases = [case("TC01"), case("TC02"), case("TC03", covers=["AC2"])]
    marks = [mark("TC01"), mark("TC02", duplicate_of="TC01"), mark("TC03", claims=[("AC2", True)])]
    findings, _ = judge_findings(STORY, cases, judged(marks))
    [dup] = [f for f in findings if f.check == "duplicate"]
    assert (dup.level, dup.case_id) == ("warn", "TC02") and dup.message.startswith("repeats TC01")


def test_a_duplicate_mark_pointing_forward_is_ignored():
    """As in bench/score.py, only a mark naming an EARLIER case counts, so a pair is never reported twice."""
    cases = [case("TC01"), case("TC02", covers=["AC2"])]
    marks = [mark("TC01", duplicate_of="TC02"), mark("TC02", claims=[("AC2", True)])]
    assert found(judge_findings(STORY, cases, judged(marks))[0]) == []


def test_duplicates_are_grouped_per_story():
    """TC02 and TC03 both repeat TC01, TC05 repeats TC04: two groups a reviewer can read at once."""
    cases = [case(f"TC0{i}") for i in range(1, 6)]
    marks = [mark("TC01"), mark("TC02", duplicate_of="TC01"), mark("TC03", duplicate_of="TC02"),
             mark("TC04", claims=[("AC2", True)]), mark("TC05", duplicate_of="TC04", claims=[("AC2", True)])]
    findings, _ = judge_findings(STORY, cases, judged(marks))
    assert duplicate_groups(findings) == {"K03": [["TC01", "TC02", "TC03"], ["TC04", "TC05"]]}


def test_an_over_claimed_ac_and_an_unverified_ac_are_warnings():
    """B2: TC01 lists AC2 but does not test it. A2: then no correct case really tests AC2 (story-level)."""
    cases = [case("TC01", covers=["AC1", "AC2"])]
    marks = [mark("TC01", claims=[("AC1", True), ("AC2", False)])]
    assert found(judge_findings(STORY, cases, judged(marks))[0]) == [
        ("ac_unverified", "warn", ""), ("over_claim", "warn", "TC01")]


def test_a_supported_claim_on_an_incorrect_case_does_not_verify_the_ac():
    """An AC counts as verified only through a case judged correct, as in bench/score.py."""
    cases = [case("TC01"), case("TC02", covers=["AC2"])]
    marks = [mark("TC01"), mark("TC02", verdict="incorrect", claims=[("AC2", True)])]
    assert ("ac_unverified", "warn", "") in found(judge_findings(STORY, cases, judged(marks))[0])


def test_an_unclear_title_is_a_warning_with_the_reason():
    """The title judge says a title does not tell a reader what is checked: WARNING with its reason."""
    cases = [case("TC01"), case("TC02", covers=["AC2"])]
    marks = [mark("TC01"), mark("TC02", claims=[("AC2", True)])]
    titles = [{"case_id": "TC01", "title_clear": False, "reason": "names only the topic"},
              {"case_id": "TC02", "title_clear": True, "reason": ""}]
    findings, _ = judge_findings(STORY, cases, judged(marks, titles))
    assert found(findings) == [("title_clear", "warn", "TC01")] and "names only the topic" in findings[0].message


def test_a_case_the_judge_skipped_is_reported_not_passed():
    """No mark came back for TC02: a judge_missing WARNING, never a silent pass."""
    cases = [case("TC01"), case("TC02", covers=["AC2"])]
    got = found(judge_findings(STORY, cases, judged([mark("TC01")]))[0])
    assert ("judge_missing", "warn", "TC02") in got


def test_step_objects_reach_the_judge_as_day4_style_text():
    """Steps written as {action, expected} are flattened before the frozen judge sees them, so it gets
    the Day 4 shape it was calibrated on: plain steps and one expected result."""
    steps = [{"action": "Onboard 'Ivan Petrov'.", "expected": "Onboarding is blocked."}]
    client = FakeClient({"K03": [mark("TC01")]})
    judge_story(STORY, [case("TC01", steps=steps, expected_result=None)], client, titles=False)
    sent = client.requests[0]["input"]
    assert '"Onboard \'Ivan Petrov\'."' in sent and '"expected_result": "Onboarding is blocked."' in sent


def test_the_title_prompt_is_domain_neutral():
    """The new title prompt must work for any domain: it names no insurance terms, and it loads with a fingerprint."""
    text, fp = load_title_prompt()
    assert len(fp) == 12 and not any(w in text.lower() for w in ("insurance", "claim", "policy", "treatment"))


def test_the_command_runs_the_judge_reports_cost_and_saves_its_replies(tmp_path):
    """End to end with the fake model: case, title and story-review calls, a not-in-basis case makes
    the run fail, the summary shows cost and time, and judge.json keeps the raw replies."""
    (tmp_path / "s.json").write_text(json.dumps({"stories": [STORY]}), encoding="utf-8")
    (tmp_path / "c.json").write_text(json.dumps({"stories": [{"story_id": "K03", "test_cases": [
        case("TC01"), case("TC02", covers=["AC2"])]}]}), encoding="utf-8")
    client = FakeClient({"K03": [mark("TC01", verdict="not_in_basis"), mark("TC02", claims=[("AC2", True)])]})
    result = check.run_checks(tmp_path / "s.json", tmp_path / "c.json", lints=[], client=client, cache_dir=None)
    check.write_outputs(result, tmp_path / "out", "test")
    # case judge, title judge, checklist story review, and test coverage: the story raises no idea, but
    # C09 audit trail is checked in every story (check = every_story), so the coverage call still runs
    assert result["judge"]["cost_usd"] > 0 and len(client.requests) == 4
    assert "Judge cost and time" in (tmp_path / "out" / "summary.md").read_text(encoding="utf-8")
    assert "K03" in json.loads((tmp_path / "out" / "judge.json").read_text(encoding="utf-8"))["stories"]
    assert any(f.level == "fail" for f in result["findings"])


def test_stories_judged_in_parallel_keep_their_order(tmp_path):
    """With 3 workers, three stories are judged at the same time, but the results come back in story order."""
    stories = [dict(STORY, story_id=f"K0{n}") for n in (3, 4, 5)]
    (tmp_path / "s.json").write_text(json.dumps({"stories": stories}), encoding="utf-8")
    (tmp_path / "c.json").write_text(json.dumps({"stories": [
        {"story_id": s["story_id"], "test_cases": [case("TC01"), case("TC02", covers=["AC2"])]} for s in stories]}),
        encoding="utf-8")
    marks = [mark("TC01"), mark("TC02", claims=[("AC2", True)])]
    client = FakeClient({s["story_id"]: marks for s in stories})
    result = check.run_checks(tmp_path / "s.json", tmp_path / "c.json", lints=[], client=client,
                              workers=3, cache_dir=None)
    # four calls per story (case, title, story review, test coverage for the every_story item C09)
    assert list(result["judge"]["records"]) == ["K03", "K04", "K05"] and len(client.requests) == 12


def test_reuse_mode_reads_day4_marks_without_calling_a_model(tmp_path):
    """--reuse-judge takes the marks from a Day 4 score file: same findings, no client needed, cost 0."""
    score = {"stories": [{"metrics": {"story_id": "K03"},
                          "judgement": {"cases_call": {"parsed": {"cases": [mark("TC01", atomic=False)]}}}}]}
    (tmp_path / "score.json").write_text(json.dumps(score), encoding="utf-8")
    (tmp_path / "s.json").write_text(json.dumps({"stories": [STORY]}), encoding="utf-8")
    (tmp_path / "c.json").write_text(json.dumps({"stories": [{"story_id": "K03", "test_cases": [case("TC01")]}]}),
                                     encoding="utf-8")
    result = check.run_checks(tmp_path / "s.json", tmp_path / "c.json", lints=[],
                              reuse=tmp_path / "score.json", titles=False)
    assert result["judge"]["cost_usd"] == 0 and ("atomic", "warn", "TC01") in found(result["findings"])


def test_live_agreement_counts_field_by_field(tmp_path):
    """Comparing a live run with Day 4: one case agrees on everything, one differs on atomic only."""
    day4 = {"stories": [{"metrics": {"story_id": "K03"}, "judgement": {"cases_call": {"parsed": {
        "cases": [mark("TC01"), mark("TC02")]}}}}]}
    live = {"stories": {"K03": {"cases_call": {"parsed": {"cases": [mark("TC01"), mark("TC02", atomic=False)]}}}}}
    (tmp_path / "d.json").write_text(json.dumps(day4), encoding="utf-8")
    (tmp_path / "l.json").write_text(json.dumps(live), encoding="utf-8")
    res = live_agreement(tmp_path / "l.json", tmp_path / "d.json")
    assert res["atomic"] == (1, 2) and res["verdict"] == (2, 2)
