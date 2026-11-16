"""
tests/test_harness_checklist.py: free tests for the two-pass checklist of generic test ideas
(harness/checklist.py, harness/checklist.toml, harness/prompts/judge_story_review_v3.txt and
judge_test_coverage_v3.txt, and the checklist parts of harness/check.py).

What these tests are for
------------------------
Each item's "check" setting decides when it is checked: when_raised (pass A decides from the
story), every_story (always checked in the test cases) or off (excluded, and named in the report).
Pass A (story review) sees the story and ACs only, and the when_raised items only; it returns the
ideas the story raises: 'defined' by an AC, or an 'ac_gap' (a question for the product owner). It
is saved and reused. Pass B (test coverage) checks the test cases for the defined ideas and every
every_story item: covered or not covered (a suggestion). Questions and suggestions must never fail a case or count as warnings. The
model is replaced by made-up answers; no API calls.

  python -m pytest tests/test_harness_checklist.py -v

Change history:
  2026-11-13  v1  first version (M7 step 4b): one call per story.
  2026-11-13  v2  two passes; caching; stories-only mode; parallel stories.
  2026-11-13  v3  rows carry the question, AC texts and case titles.
  2026-11-13  v4  19 items (C19 files); "check" setting; not_raised and excluded; grouped
                  summary lines; prompts v3. (Project context and not_stated tried and dropped.)
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from harness import check
from harness.checklist import (check_coverage, checklist_results, load_checklist, load_prompt, review_story,
                               triggered)


@pytest.fixture(autouse=True)
def no_real_model(monkeypatch):
    """Safety net for every test in this file: a test that would create a real OpenAI client
    (and spend money) fails at once instead."""
    def refuse():
        """Stand-in for bench.generate.make_client that refuses to run."""
        raise AssertionError("a test tried to call the real model")
    monkeypatch.setattr("bench.generate.make_client", refuse)


STORY = {"story_id": "K05", "title": "Approve a new customer", "as_a": "compliance analyst",
         "i_want": "to approve or reject new customers", "so_that": "only verified customers can trade",
         "acceptance_criteria": [
             {"ac_id": "AC1", "text": "Only a compliance analyst can approve a customer."},
             {"ac_id": "AC2", "text": "An approved customer's status changes from pending to active."}]}
CASE = {"case_id": "TC01", "title": "Compliance analyst approves a pending customer", "covers": ["AC1", "AC2"],
        "preconditions": ["Customer 'Ana Silva' is pending."], "steps": ["Approve the customer."],
        "expected_result": "The customer's status is active."}
REVIEW = [{"item_id": "C01", "status": "defined", "quote": "Only a compliance analyst can approve",
           "ac_ids": ["AC1"], "note": ""},
          {"item_id": "C07", "status": "defined", "quote": "changes from pending to active", "ac_ids": ["AC2"], "note": ""},
          {"item_id": "C03", "status": "ac_gap", "quote": "approve or reject new customers", "ac_ids": [],
           "note": "What must the analyst enter to reject?"}]
COVERAGE = [{"item_id": "C01", "covered": False, "case_ids": [],
             "note": "No case shows a user who is not an analyst being refused."},
            {"item_id": "C07", "covered": True, "case_ids": ["TC01"], "note": ""},
            {"item_id": "C09", "covered": False, "case_ids": [], "note": "No case checks the approval record."}]


class FakeClient:
    """Stands in for the OpenAI client: answers the story review and the test-coverage call with
    the made-up answers above, and records every request."""

    def __init__(self, review=REVIEW, coverage=COVERAGE):
        """review / coverage: the items each pass returns."""
        self.review, self.coverage, self.requests = review, coverage, []
        self.responses = self

    def create(self, model, instructions, input, text):
        """Return the story-review or test-coverage answer, depending on which prompt was sent."""
        kind = "review" if "You see no test cases" in instructions else "coverage"
        self.requests.append((kind, input))
        body = {"items": self.review if kind == "review" else self.coverage}
        return SimpleNamespace(output_text=json.dumps(body), model=model,
                               usage=SimpleNamespace(input_tokens=800, output_tokens=200))


def test_the_checklist_loads_with_19_unique_items_each_with_a_question():
    """checklist.toml: 19 items (C01/C18 split, C19 files added, 13 Nov), unique IDs; C09 is checked in
    every story and C12 is off (Roger's settings for these projects); every other item when raised."""
    items = load_checklist()
    assert [i["id"] for i in items] == [f"C{n:02d}" for n in range(1, 20)]
    assert items[0]["name"].startswith("Authorisation") and items[17]["name"].startswith("Authentication")
    assert items[18]["name"] == "Files and attachments"
    checks = {i["id"]: i["check"] for i in items}
    assert checks.pop("C09") == "every_story" and checks.pop("C12") == "off"
    assert set(checks.values()) == {"when_raised"}
    assert all(i["name"] and i["question"].strip() and i["triggers"] for i in items)


def test_both_checklist_prompts_are_domain_neutral():
    """The story-review and test-coverage prompts must work for any domain."""
    for name in ("judge_story_review_v3", "judge_test_coverage_v3"):
        text, fp = load_prompt(name)
        assert len(fp) == 12 and not any(w in text.lower() for w in ("insurance", "claim", "treatment", "patient"))
    assert "You see no test cases" in load_prompt("judge_story_review_v3")[0]


def test_pass_a_sees_no_test_cases_and_pass_b_gets_the_defined_and_every_story_ideas():
    """The story review is sent the story and the 17 when_raised ideas (not C09 every_story, not C12 off),
    never the cases; the coverage call is sent the cases, the ideas the review found defined (C01, C07)
    and the every_story idea (C09), but not the AC gap (C03) or the excluded C12."""
    client = FakeClient()
    review = review_story(STORY, client, load_checklist(), cache_dir=None)
    check_coverage(STORY, [CASE], review, client, load_checklist())
    (k1, sent_a), (k2, sent_b) = client.requests
    assert k1 == "review" and "Test cases" not in sent_a and sent_a.count('"item_id"') == 17
    assert '"C09"' not in sent_a and '"C12"' not in sent_a
    assert k2 == "coverage" and "TC01" in sent_b and all(f'"{x}"' in sent_b for x in ("C01", "C07", "C09"))
    assert '"C03"' not in sent_b and '"C12"' not in sent_b
    assert "the project checks it in every story" in sent_b


def test_statuses_findings_and_levels():
    """Not covered -> a suggestion with the quoted reason (or 'checked in every story'); AC gap -> a
    question; covered, not raised and excluded -> nothing. None is a failure or a warning."""
    client = FakeClient()
    review = review_story(STORY, client, load_checklist(), cache_dir=None)
    coverage = check_coverage(STORY, [CASE], review, client, load_checklist())
    findings, rows = checklist_results(STORY, review, coverage, load_checklist())
    status = {r["item_id"]: r["status"] for r in rows}
    assert (status["C01"], status["C07"], status["C03"], status["C09"], status["C14"], status["C12"]) == (
        "not_covered", "covered", "ac_gap", "not_covered", "not_raised", "excluded")
    assert sorted(f.level for f in findings) == ["question", "suggestion", "suggestion"]
    msgs = [f.message for f in findings if f.level == "suggestion"]
    assert any('raised by: "Only a compliance analyst can approve"' in m for m in msgs)
    assert any(m.startswith("C09 Record of the decision (audit trail) (checked in every story): No case") for m in msgs)
    _, rows = checklist_results(STORY, review, coverage, load_checklist(), [CASE])
    c07 = next(r for r in rows if r["item_id"] == "C07")          # the sheet spells out ACs and cases
    assert c07["ac_text"] == "AC2: An approved customer's status changes from pending to active."
    assert c07["case_titles"] == "TC01: Compliance analyst approves a pending customer" and c07["question"]


def test_the_story_review_is_saved_and_reused(tmp_path):
    """A second run of the same story with the same checklist reuses the saved review: no new call, marked cached."""
    client = FakeClient()
    first = review_story(STORY, client, load_checklist(), cache_dir=tmp_path)
    second = review_story(STORY, client, load_checklist(), cache_dir=tmp_path)
    assert first["cached"] is False and second["cached"] is True and len(client.requests) == 1
    changed = dict(STORY, acceptance_criteria=STORY["acceptance_criteria"] + [{"ac_id": "AC3", "text": "New rule."}])
    review_story(changed, client, load_checklist(), cache_dir=tmp_path)
    assert len(client.requests) == 2                          # a changed story is reviewed again


def test_no_coverage_call_when_nothing_is_defined():
    """If the review finds only AC gaps and no item is checked in every story, pass B is skipped:
    there is nothing to test against."""
    items = [i for i in load_checklist() if i["check"] != "every_story"]
    client = FakeClient(review=[REVIEW[2]])
    review = review_story(STORY, client, items, cache_dir=None)
    assert check_coverage(STORY, [CASE], review, client, items) is None and len(client.requests) == 1


def test_the_cross_check_flags_where_trigger_words_and_the_review_disagree():
    """'Only' in AC1 triggers C01 in code; if the review leaves C01 out, the row is a disagreement."""
    assert triggered(STORY, load_checklist()[0])
    _, rows = checklist_results(STORY, {"parsed": {"items": []}}, None, load_checklist())
    assert rows[0]["disagree"] is True and rows[0]["status"] == "not_raised"


def test_an_unknown_or_skipped_id_is_reported():
    """An invented checklist ID in the review, or an idea pass B skipped, gives a story warning."""
    client = FakeClient(review=REVIEW + [{"item_id": "C99", "status": "defined", "quote": "x", "ac_ids": [],
                                          "note": ""}],
                        coverage=COVERAGE[:1])
    review = review_story(STORY, client, load_checklist(), cache_dir=None)
    coverage = check_coverage(STORY, [CASE], review, client, load_checklist())
    findings, _ = checklist_results(STORY, review, coverage, load_checklist())
    [warn] = [f for f in findings if f.level == "warn"]
    assert "C99 is not a checklist ID" in warn.message and "C07 not judged" in warn.message


def test_stories_only_mode_reviews_stories_without_cases(tmp_path):
    """--stories-only: pass A for every story, no cases needed; defined ideas show as 'defined', every_story
    items as 'every_story' (to be checked once cases exist), AC gaps as questions."""
    (tmp_path / "s.json").write_text(json.dumps({"stories": [STORY]}), encoding="utf-8")
    result = check.run_checks(tmp_path / "s.json", None, client=FakeClient(), cache_dir=None)
    rows = result["judge"]["checklist_rows"]
    status = {r["item_id"]: r["status"] for r in rows}
    assert (status["C01"], status["C09"], status["C12"]) == ("defined", "every_story", "excluded")
    assert [f.level for f in result["findings"]] == ["question"]
    check.write_outputs(result, tmp_path / "out", "story review")
    assert "Checklist pass A: story review" in (tmp_path / "out" / "summary.md").read_text(encoding="utf-8")


def test_checklist_findings_do_not_change_the_exit_code(tmp_path):
    """A run whose only findings are checklist suggestions and questions has no failure."""
    client = FakeClient()
    review = review_story(STORY, client, load_checklist(), cache_dir=None)
    coverage = check_coverage(STORY, [CASE], review, client, load_checklist())
    findings, _ = checklist_results(STORY, review, coverage, load_checklist())
    assert not any(f.level in ("fail", "warn") for f in findings)


# --- the "check" setting, exclusions and grouping (design review with Roger, 13 Nov) ----------
def test_a_wrong_check_value_stops_the_run_with_a_plain_message(tmp_path):
    """A typo in the check setting must not silently switch an item on or off."""
    bad = tmp_path / "bad.toml"
    bad.write_text('[[item]]\nid = "C01"\nname = "x"\ncheck = "sometimes"\ntriggers = ["a"]\nquestion = "q"\n',
                   encoding="utf-8")
    with pytest.raises(ValueError, match="C01 check must be one of when_raised, every_story, off"):
        load_checklist(bad)


def test_the_summary_names_every_excluded_item_and_the_every_story_items(tmp_path):
    """The report shows exactly what was excluded (Roger: 'not checked' must never read as 'fine'),
    what is checked in every story, and the checklist file's fingerprint."""
    (tmp_path / "s.json").write_text(json.dumps({"stories": [STORY]}), encoding="utf-8")
    result = check.run_checks(tmp_path / "s.json", None, client=FakeClient(), cache_dir=None)
    text = check.summary_markdown(result, "x")
    assert "Excluded (check = off), NOT checked in any story: C12 Stated performance or volume" in text
    assert "Checked in every story's test cases (check = every_story): C09 Record of the decision" in text
    assert "Checklist file: checklist.toml (fingerprint " in text


def test_the_excluded_items_appear_in_checklist_csv(tmp_path):
    """checklist.csv carries the check setting and an 'excluded' row for every switched-off item."""
    (tmp_path / "s.json").write_text(json.dumps({"stories": [STORY]}), encoding="utf-8")
    result = check.run_checks(tmp_path / "s.json", None, client=FakeClient(), cache_dir=None)
    check.write_outputs(result, tmp_path / "out", "x")
    import csv
    rows = list(csv.DictReader(open(tmp_path / "out" / "checklist.csv", encoding="utf-8-sig")))
    c12 = next(r for r in rows if r["item_id"] == "C12")
    assert (c12["check"], c12["status"]) == ("off", "excluded")


def test_a_suggestion_repeated_across_stories_is_one_grouped_line():
    """The same item not covered in several stories is one summary line naming the stories, with each
    story's note underneath; an item found once stays a single line."""
    f = check.Finding
    findings = [f("S01", "", "checklist", "suggestion", "C09 Record of the decision (audit trail) (checked in every story): no record case"),
                f("S06", "", "checklist", "suggestion", "C09 Record of the decision (audit trail) (checked in every story): no record case either"),
                f("S02", "", "checklist", "suggestion", "C17 Dependent fields and options (AC1): change the category")]
    lines = check._grouped(findings, "suggestion", {"C09": "Record of the decision (audit trail)",
                                                    "C17": "Dependent fields and options"})
    assert lines[0] == "- C09 Record of the decision (audit trail): in 2 stories (S01, S06)"
    assert lines[1] == "    - S01: (checked in every story): no record case" and lines[3].startswith("- S02: C17")
