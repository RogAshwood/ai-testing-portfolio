"""
tests/test_harness_lints.py: free tests for the harness lints (harness/lints.py, lint_rules.toml).

What these tests are for
------------------------
Each lint must flag the problem it is named for and stay quiet on a good case,
and every lint can be switched off. The lints only ever give WARNINGS. The
cases are made up (a fictional customer-onboarding story); no API calls.

  python -m pytest tests/test_harness_lints.py -v

Change history:
  2026-11-12  v1  first version (M7 step 1).
  2026-11-12  v2  repeated_expected and per-step expected results (Roger's review).
  2026-11-12  v3  boundary_hint units: counts, days and periods (Roger's review sheet).
  2026-11-13  v4  two-value BVA default (three-value as an option); step_detail for low-level cases.
"""
from __future__ import annotations

import pytest

from harness.lints import LINT_NAMES, load_rules, numbers_in, run_lints, values_in

STORY = {"story_id": "K02", "title": "Enhanced due diligence above a deposit amount", "as_a": "compliance analyst",
         "i_want": "large first deposits checked", "so_that": "risk is reviewed",
         "acceptance_criteria": [{"ac_id": "AC1", "text": "A first deposit over 10,000 triggers enhanced due diligence."}]}


def good(cid="TC01", amount="10,000.00", **changes):
    """A made-up case that no lint should flag."""
    c = {"case_id": cid, "title": f"First deposit of {amount} does not trigger EDD", "covers": ["AC1"],
         "preconditions": ["Customer 'Ana Silva' is onboarded on 2026-11-12."],
         "steps": [f"Make a first deposit of {amount}."],
         "expected_result": "No enhanced due diligence case is opened."}
    c.update(changes)
    return c


BOUNDARY_SET = [good("TC01", "10,000.00"), good("TC02", "9,999.99"),
                good("TC03", "10,000.01", title="First deposit of 10,000.01 triggers EDD",
                     expected_result="An enhanced due diligence case is opened.")]


def lint(cases, only=None, **settings):
    """Run the lints (all enabled, or just `only`) on STORY; return (lint, case_id) pairs.
    `settings` overrides one lint's settings, e.g. repeated_expected={"across_cases": True}."""
    rules = load_rules(only=only)
    for name, values in settings.items():
        rules[name].update(values)
    return sorted((f.check, f.case_id) for f in run_lints({"K02": STORY}, {"K02": cases}, rules))


def test_good_cases_at_on_and_either_side_of_the_limit_raise_no_lint():
    """Three concrete cases at 9,999.99, 10,000.00 and 10,000.01: no lint has anything to say."""
    assert lint(BOUNDARY_SET) == []


def test_no_lint_ever_fails_a_case():
    """Lints never fail a case: every finding they produce is a warning (or an info reminder)."""
    bad = good("TC01", title="Test 1", steps=["Navigate to the deposit page and enter valid data."],
               preconditions=[], expected_result="Works as expected. TBD")
    rules = load_rules()
    assert {f.level for f in run_lints({"K02": STORY}, {"K02": [bad]}, rules)} <= {"warn", "info"}


@pytest.mark.parametrize("title", ["Test 1", "TC05", "Positive test", "Happy path", "Verify AC1", "Deposit"])
def test_generic_or_very_short_titles_are_flagged(title):
    """A title such as 'Test 1', 'Verify AC1' or a single word does not tell a reader what is tested."""
    assert lint([good(title=title)], only=["generic_title"]) == [("generic_title", "TC01")]


def test_vague_steps_are_flagged():
    """'Navigate to' and 'valid data' leave the tester to guess what to do and with what."""
    case = good(steps=["Navigate to the deposit screen.", "Enter valid data and submit."])
    assert lint([case], only=["vague_steps"]) == [("vague_steps", "TC01")]


def test_a_vague_expected_result_is_flagged():
    """'Works as expected' cannot be marked pass or fail."""
    assert lint([good(expected_result="The deposit works as expected.")], only=["vague_expected"]) == [
        ("vague_expected", "TC01")]


def test_no_concrete_value_in_preconditions_or_steps_is_flagged():
    """'A large deposit' with no amount, date or quoted value: the tester must invent the data."""
    case = good(preconditions=["A customer is onboarded."], steps=["Make a large first deposit."])
    assert lint([case], only=["missing_test_data"]) == [("missing_test_data", "TC01")]


@pytest.mark.parametrize("text", ["TBD", "xxx", "<amount>", "[insert amount]", "{{amount}}"])
def test_leftover_placeholders_are_flagged(text):
    """Template text such as TBD or <amount> left in a case means it was never finished."""
    assert lint([good(expected_result=f"EDD outcome {text}.")], only=["placeholders"]) == [
        ("placeholders", "TC01")]


def test_a_near_copy_with_the_same_values_is_flagged_on_the_later_case():
    """TC02 repeats TC01 with the same amount and only one word changed: the later case is flagged."""
    copy = good("TC02", title="First deposit of 10,000.00 does not trigger EDD review")
    assert lint([good(), copy], only=["near_duplicate"]) == [("near_duplicate", "TC02")]


def test_similar_cases_on_different_sides_of_a_limit_are_not_duplicates():
    """9,999.99 and 10,000.01 read almost the same but test different sides of the limit: not flagged."""
    assert lint(BOUNDARY_SET, only=["near_duplicate"]) == []


def test_two_value_needs_the_limit_and_one_neighbour_three_value_needs_both():
    """AC1 says 'over 10,000'. Cases at 10,000.00 and 9,999.99: two-value (the default) is satisfied by the
    limit plus a neighbour on either side; three-value also wants 10,000.01, so it gives a hint."""
    assert lint(BOUNDARY_SET[:2], only=["boundary_hint"]) == []
    three = {"boundary_hint": {"bva": "three-value"}}
    assert lint(BOUNDARY_SET[:2], only=["boundary_hint"], **three) == [("boundary_hint", "")]


def test_a_limit_with_no_case_on_it_gets_a_hint_in_both_modes():
    """Only 9,999.99 and 10,000.01 are tested: nobody tests exactly 10,000, so both modes give a hint."""
    cases = [BOUNDARY_SET[1], BOUNDARY_SET[2]]
    assert lint(cases, only=["boundary_hint"]) == [("boundary_hint", "")]


def test_the_same_expected_wording_on_several_steps_is_flagged():
    """Per-step expected results such as 'Works as expected' copied onto every step: flagged on that case."""
    steps = [{"action": "Open the deposit screen.", "expected": "Works as expected."},
             {"action": "Deposit 10,000.01.", "expected": "Works as expected"}]
    assert lint([good(steps=steps)], only=["repeated_expected"]) == [("repeated_expected", "TC01")]


def test_vague_wording_in_a_per_step_expected_result_is_flagged():
    """vague_expected reads per-step expected results too, not only the case-level expected_result."""
    steps = [{"action": "Deposit 10,000.01.", "expected": "No errors."}]
    assert lint([good(steps=steps)], only=["vague_expected"]) == [("vague_expected", "TC01")]


def test_the_across_cases_check_is_off_by_default_and_flags_once_when_on():
    """Three cases sharing word for word one expected result: no warning by default (cases often rightly
    share an outcome); with across_cases switched on, one warning on the first case."""
    cases = [good("TC01", "10,000.00"), good("TC02", "9,999.99"), good("TC03", "5,000.00")]
    assert lint(cases, only=["repeated_expected"]) == []
    on = {"repeated_expected": {"across_cases": True}}
    assert lint(cases, only=["repeated_expected"], **on) == [("repeated_expected", "TC01")]
    assert lint(cases[:2], only=["repeated_expected"], **on) == []


def test_counts_and_days_use_whole_steps_and_nothing_below_zero():
    """'8 visits' means 7 and 9 visits, not 7.99 or 8.01; 'day 0' has no day before it to test.
    Shown in both modes: three-value wants 7 visits too; two-value is happy with 8 and 9."""
    from harness.lints import lint_boundary_hint
    story = dict(STORY, acceptance_criteria=[
        {"ac_id": "AC1", "text": "A customer can make 8 visits a year. Cover starts on day 0."}])
    cases = [good("TC01", steps=["Record visit number 8."]), good("TC02", steps=["Record visit number 9."]),
             good("TC03", steps=["Record visit number 7 on day 0, then day 1."])]
    assert lint_boundary_hint(story, cases, load_rules()["boundary_hint"]) == []
    three = dict(load_rules()["boundary_hint"], bva="three-value")
    hints = lint_boundary_hint(story, cases[:2], three)
    assert [h.message for h in hints] == [
        "AC1 mentions 8 visits but no case uses just below (7 visits)",
        "AC1 mentions day 0 but no case uses the value itself (day 0); just above (day 1)"]
    two = lint_boundary_hint(story, cases[:2], load_rules()["boundary_hint"])     # 8 and 9 visits: fine
    assert [h.message for h in two] == [
        "AC1 mentions day 0 but no case uses the value itself (day 0); a value just either side (day 1)"]


def test_a_period_in_months_gets_an_info_reminder_not_a_warning():
    """'Within 12 months': 11 or 13 would make no sense; the boundary is a date, so the lint only reminds."""
    from harness.lints import lint_boundary_hint
    story = dict(STORY, acceptance_criteria=[{"ac_id": "AC1", "text": "Documents expire after 12 months."}])
    [hint] = lint_boundary_hint(story, [good()], load_rules()["boundary_hint"])
    assert hint.level == "info" and "one day before, on, and one day after" in hint.message


def test_step_detail_does_nothing_for_high_level_cases():
    """The default case_detail is high-level: 'Make a first deposit of 10,000.00.' is a fine one-step case."""
    assert lint([good()], only=["step_detail"]) == []


def test_step_detail_flags_thin_low_level_cases():
    """In low-level mode a one-step case, and a step that does not say where or how, are flagged;
    'Enter 10,000.01 in the Amount field' and 'Click Submit' say where and how."""
    low = {"case_detail": {"level": "low-level"}}
    assert lint([good()], only=["step_detail"], **low) == [("step_detail", "TC01"), ("step_detail", "TC01")]
    detailed = good(steps=["Enter 10,000.01 in the Amount field.", "Click Submit."])
    assert lint([detailed], only=["step_detail"], **low) == []


def test_an_age_limit_gets_a_birthday_reminder():
    """'18 or over' is an age: 17.99 or 18.01 make no sense; the boundary is the 18th birthday, a date."""
    from harness.lints import lint_boundary_hint
    story = dict(STORY, acceptance_criteria=[{"ac_id": "AC1", "text": "An applicant who is 18 or over can continue."}])
    [hint] = lint_boundary_hint(story, [good()], load_rules()["boundary_hint"])
    assert hint.level == "info" and "18th birthday" in hint.message


def test_lints_can_be_switched_off():
    """--lints none switches every lint off, so even a poor case raises no lint finding."""
    bad = good(title="Test 1", expected_result="Works as expected. TBD")
    assert lint([bad], only=[]) == []


def test_an_unknown_lint_name_is_rejected():
    """A typo in --lints is caught with the list of valid names, rather than silently running nothing."""
    with pytest.raises(ValueError, match="unknown lint"):
        load_rules(only=["vague_stepz"])


def test_values_are_read_from_numbers_dates_and_quotes_but_not_ids():
    """Amounts, dates and quoted text are test values; AC and case IDs and reason codes are not."""
    assert values_in("AC2 TC01 UNDER_18: customer 'Ana' deposits €1,000.50 on 12 March 2027") == {
        "1000.5", "12 march 2027", "ana"}
    assert numbers_in("For treatment on 29 February the last day is 28 February") == set()
    assert numbers_in("The list is replaced every day at 02:00 UTC; overdue at 23:59") == set()
    assert values_in("The member's GP and the provider's description") == set()


def test_every_lint_has_settings_in_the_rules_file():
    """Each lint named in the code has a section in lint_rules.toml, so a team can see and change it."""
    rules = load_rules()
    assert all(name in rules for name in LINT_NAMES)
