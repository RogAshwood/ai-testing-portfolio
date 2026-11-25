"""
tests/test_harness_report.py: free tests for harness/report.py, the HTML page per run (M7 step 6).

What these tests are for
------------------------
The page must show the right numbers (a coverage map that only counts an AC as verified when the
judge marked the case correct AND the claim supported), name every excluded checklist item, put
flagged cases first, stay safe when case text holds HTML, and be rebuildable for an earlier run
without calling the model. No API calls.

  python -m pytest tests/test_harness_report.py -v

Change history:
  2026-11-24  v1  first version (M7 step 6).
  2026-11-24  v2  glossary links, checklist matrix, findings-by-check chart, severity bars, filter.
  2026-11-25  v3  total ACs, not-verified reasons, over-claim reasons, checklist ideas in the glossary,
                  clickable findings bars.
  2026-11-25  v4  checklist titles and descriptions; older runs take them from the checklist.
"""
from __future__ import annotations

import json

from harness import check
from harness.contract import Finding
from harness.report import build_html, coverage_rows, result_from_folder, step_counts

STORY = {"story_id": "K06", "title": "Calculate the customer risk rating", "as_a": "compliance officer",
         "i_want": "every new customer given a risk rating", "so_that": "due diligence matches the risk",
         "acceptance_criteria": [{"ac_id": "AC1", "text": "The risk score is a whole number from 0 to 100."},
                                 {"ac_id": "AC2", "text": "A score from 70 to 100 is HIGH."}]}
CASES = [{"case_id": "TC01", "title": "Score 70 is HIGH", "covers": ["AC2"], "preconditions": ["Score 70."],
          "steps": ["Calculate the rating."], "expected_result": "The rating is HIGH."},
         {"case_id": "TC02", "title": "<script>alert(1)</script> score 69", "covers": ["AC1", "AC2"],
          "preconditions": [], "steps": ["Enter 69.", "Calculate.", "Check."], "expected_result": "HIGH."}]
RECORDS = {"K06": {"cases_call": {"parsed": {"cases": [
    {"case_id": "TC01", "verdict": "correct", "technique": "boundary", "claims": [{"ac_id": "AC2", "supported": True}]},
    {"case_id": "TC02", "verdict": "incorrect", "technique": "boundary",
     "claims": [{"ac_id": "AC1", "supported": True}, {"ac_id": "AC2", "supported": True}]}]}}}}
FINDINGS = [Finding("K06", "TC02", "verdict", "fail", "the expected result contradicts the acceptance criteria"),
            Finding("K06", "", "ac_unverified", "warn", "AC1: no case judged correct really tests this criterion")]
ROWS = [{"story_id": "K06", "item_id": "C09", "name": "Record of the decision (audit trail)", "check": "every_story",
         "status": "not_covered"},
        {"story_id": "K06", "item_id": "C12", "name": "Stated performance or volume", "check": "off", "status": "excluded"}]


def result() -> dict:
    """A small run result in the shape harness.check builds."""
    return {"stories": {"K06": STORY}, "groups": {"K06": CASES}, "findings": FINDINGS, "rules": {},
            "judge": {"mode": "live", "model": "gpt-6-sol", "cost_usd": 0.05, "seconds": 9.0,
                      "records": RECORDS, "checklist_rows": ROWS}}


def test_an_ac_is_verified_only_by_a_correct_case_with_a_supported_claim():
    """TC02 claims AC1 and AC2 with supported claims but is judged incorrect, so only TC01 verifies AC2
    and AC1 has no verified case; its ac_unverified flag sits on the AC1 row."""
    rows = {r["ac_id"]: r for r in coverage_rows(STORY, CASES, FINDINGS, RECORDS)}
    assert rows["AC1"]["claimed"] == ["TC02"] and rows["AC1"]["verified"] == []
    assert rows["AC2"]["claimed"] == ["TC01", "TC02"] and rows["AC2"]["verified"] == ["TC01"]
    assert [f.check for f in rows["AC1"]["flags"]] == ["ac_unverified"] and rows["AC2"]["flags"] == []
    assert rows["AC2"]["techniques"] == {"boundary": 2}


def test_steps_are_counted_into_buckets():
    """One case with 1 step, one with 3."""
    counts = step_counts({"K06": CASES})
    assert counts["1"] == 1 and counts["3"] == 1 and counts["5+"] == 0


def test_the_page_names_excluded_items_shows_flagged_cases_and_escapes_html():
    """The excluded checklist item is named; the failing case is listed; case text holding HTML is shown as
    text, never run as a script; the page loads nothing from the internet."""
    html = build_html(result(), "cases.json against stories.json")
    assert "C12 Stated performance or volume" in html and "C09 Record of the decision" in html
    assert "TC02" in html and "the expected result contradicts" in html
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html
    assert "http://" not in html.replace("http://www.w3", "") and "https://" not in html


def test_harness_check_writes_report_html(tmp_path):
    """A free run (no judge) writes report.html next to summary.md."""
    (tmp_path / "s.json").write_text(json.dumps({"stories": [STORY]}), encoding="utf-8")
    (tmp_path / "c.json").write_text(json.dumps({"stories": [{"story_id": "K06", "test_cases": CASES}]}), encoding="utf-8")
    res = check.run_checks(tmp_path / "s.json", tmp_path / "c.json", judge=False)
    check.write_outputs(res, tmp_path / "out", "x")
    assert "Coverage map per acceptance criterion" in (tmp_path / "out" / "report.html").read_text(encoding="utf-8")


def test_a_report_can_be_rebuilt_from_an_earlier_run_folder(tmp_path):
    """From findings.csv, checklist.csv and judge.json plus the original files, with no model call."""
    (tmp_path / "s.json").write_text(json.dumps({"stories": [STORY]}), encoding="utf-8")
    (tmp_path / "c.json").write_text(json.dumps({"stories": [{"story_id": "K06", "test_cases": CASES}]}), encoding="utf-8")
    res = result()
    res["judge"]["checklist_rows"] = [dict(r, quote="", ac_ids=[], ac_text="", case_ids=[], case_titles="", note="",
                                           question="q", triggered=False, disagree=False, review_cached=False) for r in ROWS]
    check.write_outputs(res, tmp_path / "run", "x")
    rebuilt = result_from_folder(tmp_path / "run", tmp_path / "s.json", tmp_path / "c.json")
    assert [f.check for f in rebuilt["findings"]] == ["verdict", "ac_unverified"]
    assert rebuilt["judge"]["records"]["K06"]["cases_call"]["parsed"]["cases"][0]["case_id"] == "TC01"
    # rows saved without a title (runs before 25 Nov) take today's title from checklist.toml
    assert "C12 Performance and volume check" in build_html(rebuilt, "x")


# --- v2: glossary, matrix, charts, filter (Roger's review, 24 Nov) --------------------------
def test_every_term_the_page_links_to_is_in_the_glossary():
    """Every check name and status the page can link resolves to a glossary entry, so no link is dead."""
    from harness.report import GLOSSARY, TERM_OF
    assert set(TERM_OF.values()) <= set(GLOSSARY)
    assert all(g["term"] and g["definition"] and g["group"] for g in GLOSSARY.values())


def test_check_names_link_to_their_glossary_entry_with_the_definition_on_hover():
    """The fail chip on TC02 links to #g-verdict and carries the definition; the glossary section has that anchor."""
    html = build_html(result(), "x")
    assert 'href="#g-verdict"' in html and 'id="g-verdict"' in html and 'id="g-not_raised"' in html
    assert "contradicts the acceptance criteria. Not in basis" in html            # the definition as the hover text


def test_the_checklist_matrix_marks_each_status_with_a_letter():
    """C09 not covered -> N, C12 excluded -> X, both with the words in the tooltip (meaning never colour alone)."""
    from harness.report import checklist_matrix
    grid = checklist_matrix(ROWS)
    assert '<span class="cell warn" title="K06 C09: not covered (suggestion)">N</span>' in grid
    assert '<span class="cell off" title="K06 C12: excluded (check = off)">X</span>' in grid


def test_findings_by_check_and_severity_bars_carry_their_numbers():
    """The chart counts the verdict fail; the story bar says how many cases fail, warn or are clean."""
    from harness.report import findings_chart, severity_bar
    assert "verdict (fail): 1" in findings_chart(FINDINGS)
    assert 'aria-label="1 with a fail, 0 warnings only, 1 clean"' in severity_bar(1, 0, 1)


def test_the_flagged_cases_can_be_filtered_without_the_internet():
    """Each flagged row carries its story, level and checks for the filter, and the filter script is inline."""
    html = build_html(result(), "x")
    assert 'data-story="K06" data-level="fail" data-checks=" verdict "' in html
    assert 'id="f-story"' in html and "<script>" in html and "src=" not in html


# --- v3: Roger's review of v2 (25 Nov) -------------------------------------------------
def test_the_headline_shows_the_total_number_of_acceptance_criteria():
    """Two ACs in the one story -> a tile '2 acceptance criteria'."""
    html = build_html(result(), "x")
    assert '<div class="n">2</div><div class="l">acceptance criteria</div>' in html


def test_the_coverage_map_says_which_claiming_cases_are_not_verified_and_why():
    """TC02 claims AC2 but failed, so AC2 is '1 of 2 verified' and TC02 is listed as not verified (fail)."""
    rows = {r["ac_id"]: r for r in coverage_rows(STORY, CASES, FINDINGS, RECORDS)}
    assert rows["AC2"]["not_verified"] == {"TC02": "fail"}
    assert "1 of 2 verified" in build_html(result(), "x") and "TC02 (fail)" in build_html(result(), "x")


def test_an_over_claim_from_an_older_run_gets_the_judges_reason():
    """A saved over-claim message with no reason is shown with the judge's reason for that case."""
    res = result()
    res["judge"]["records"]["K06"]["cases_call"]["parsed"]["cases"][0]["reason"] = "Score 70 only sets up the case."
    res["findings"] = FINDINGS + [Finding("K06", "TC01", "over_claim", "warn", "covers lists AC2 but the case does not really test it")]
    assert "does not really test it: Score 70 only sets up the case." in build_html(res, "x")


def test_checklist_ideas_are_in_the_glossary_and_the_matrix_links_to_them():
    """Each checklist idea the run used has a glossary entry with its question; matrix rows link to it."""
    res = result()
    res["judge"]["checklist_rows"] = [dict(r, question="A case that checks the record itself.") for r in ROWS]
    html = build_html(res, "x")
    assert 'id="g-C09"' in html and "A case that checks the record itself. Checked in every story." in html
    assert 'href="#g-C09"' in html and 'id="g-C12"' in html and "Switched off in this run" in html


def test_findings_bars_are_coloured_by_level_and_clickable():
    """The verdict bar is a fail bar carrying its check, so a click can filter the flagged cases."""
    from harness.report import findings_chart
    assert '<g class="bar fail" data-check="verdict" data-level="fail" tabindex="0" role="link">' in findings_chart(FINDINGS)
