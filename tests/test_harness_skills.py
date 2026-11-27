"""
tests/test_harness_skills.py: free tests for M7 step 7, the team's two skills
(harness/skills/testcase-writer, harness/skills/testcase-reviewer), the skill option of
harness/generate.py and the review-skill runner harness/skill_review.py.

What these tests are for
------------------------
Step 7 compares (A) the writing skill with the plain prompts, and (B) the review skill with the
harness on the seeded sets. The comparison is only fair if the skills are loaded as written, the
writing skill's checklist matches the harness checklist, every seeded defect is something the review
skill can name, and the review skill is scored by the same rules as the harness. A fake model
stands in for the real one; no API calls.

  python -m pytest tests/test_harness_skills.py -v

Change history:
  2026-11-25  v1  first version (M7 step 7).
  2026-11-25  v2  real cases mode: agreement with a harness run, scoring against reviewer labels.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from bench.golden import ROOT
from harness import generate, seeded, skill_review
from harness.checklist import load_checklist


@pytest.fixture(autouse=True)
def no_real_model(monkeypatch):
    """Safety net for every test in this file: creating a real OpenAI client fails at once."""
    def refuse():
        """Stand-in for bench.generate.make_client that refuses to run."""
        raise AssertionError("a test tried to call the real model")
    monkeypatch.setattr("bench.generate.make_client", refuse)


# --- the writing skill ----------------------------------------------------------------
def test_the_writing_skill_is_loaded_without_front_matter_and_with_its_reference_checklist():
    """The model gets the house rules and the checklist, not the name/description an assistant uses to pick skills."""
    text = generate.load_skill("testcase-writer")
    assert text.startswith("# Writing test cases") and "description:" not in text
    assert "## House rules" in text and "Reference file: reference/checklist.md" in text


def test_the_writing_skills_checklist_matches_the_harness_checklist():
    """reference/checklist.md lists every harness checklist item by its current title, so the skill and
    the harness talk about the same test ideas (regenerate the file when checklist.toml changes)."""
    ref = (ROOT / "harness" / "skills" / "testcase-writer" / "reference" / "checklist.md").read_text(encoding="utf-8")
    assert all(f"{i['id']} {i['title']}" in ref for i in load_checklist())


def test_the_skill_option_generates_a_file_the_harness_can_read(tmp_path, monkeypatch):
    """--prompt skill sends the skill as the instructions and saves a Day 4-shaped file; a 'questions'
    list for the product owner is kept with the reply."""
    calls = []

    def create(model, instructions, input):
        """Fake responses.create: one valid case per story plus a question."""
        sid = input.split("Story ID: ")[1].split("\n")[0]
        calls.append(instructions)
        body = {"story_id": sid, "questions": ["Is day 90 inside the period?"], "test_cases": [
            {"case_id": "TC01", "title": f"{sid} on the limit", "technique": "boundary", "covers": ["AC1"],
             "preconditions": ["Applicant 'Ana Silva'."], "steps": ["Submit on 24/11/2026."], "expected_result": "It continues."}]}
        return SimpleNamespace(output_text=json.dumps(body), model=model, usage=SimpleNamespace(input_tokens=900, output_tokens=500))

    monkeypatch.setattr(generate, "OUT_DIR", tmp_path)
    out = generate.run("skill", ROOT / "datasets" / "aml_kyc_stories.json", only=["K01"],
                       client=SimpleNamespace(responses=SimpleNamespace(create=create)))
    data = json.loads(out.read_text(encoding="utf-8"))
    assert calls == [generate.load_skill("testcase-writer")] and data["meta"]["prompt_version"] == "skill"
    assert data["records"][0]["schema_valid"] and data["records"][0]["parsed"]["questions"]


# --- the review skill -----------------------------------------------------------------
NAME_FOR = {check: name for name, (check, _) in skill_review.PROBLEM_TO_CHECK.items() if name != "not_in_basis"}
STORY_NAME_FOR = {check: name for name, check in skill_review.STORY_PROBLEM_TO_CHECK.items()}


def all_expectations():
    """Every case and story expectation in the three seed sets."""
    out = []
    for name in ("harness", "day4", "aml"):
        groups, cases, story = (seeded.harness_set() if name == "harness" else
                                seeded.harness_set(seeded.AML_SEEDS) if name == "aml" else seeded.day4_set())
        out.append((name, cases, story))
    return out


def test_every_seeded_defect_is_something_the_review_skill_can_name():
    """If a seed needs a check the skill has no word for, the skill could never catch it and the
    comparison would be unfair to the skill."""
    for _, cases, story in all_expectations():
        assert {c for e in cases for c in e["must_fire"]} <= set(NAME_FOR)
        assert {e["check"] for e in story} <= set(STORY_NAME_FOR)


def fake_reviewer(perfect: bool):
    """A fake model answering the review skill: either exactly what the seeds expect, or nothing at all."""
    exp = {}
    story_exp = {}
    for _, cases, story in all_expectations():
        for e in cases:
            exp[(e["story_id"], e["case_id"])] = e["must_fire"]
        for e in story:
            story_exp.setdefault(e["story_id"], []).append(e)

    def create(model, instructions, input, text):
        """Fake responses.create: read the story ID and case IDs from the input and answer."""
        sid = input.split("Story ID: ")[1].split("\n")[0]
        cases = json.loads(input.split("Test cases:\n", 1)[1])
        body = {"story_id": sid, "cases": [], "story_problems": []}
        for c in cases:
            names = [NAME_FOR[x] for x in exp.get((sid, c["case_id"]), [])] if perfect else []
            body["cases"].append({"case_id": c["case_id"], "problems": [
                {"name": n, "reason": "seeded", "duplicate_of": "", "acs": []} for n in names]})
        if perfect:
            body["story_problems"] = [{"name": STORY_NAME_FOR[e["check"]], "ac_id": e["contains"] if e["contains"].startswith("AC") else "AC1",
                                       "limit": "" if e["contains"].startswith("AC") else e["contains"], "reason": "seeded"}
                                      for e in story_exp.get(sid, [])]
        return SimpleNamespace(output_text=json.dumps(body), model=model, usage=SimpleNamespace(input_tokens=1000, output_tokens=300))
    return SimpleNamespace(responses=SimpleNamespace(create=create))


@pytest.mark.parametrize("name", ["harness", "day4", "aml"])
def test_a_perfect_reviewer_scores_every_seed_caught_and_every_control_clean(tmp_path, name):
    """Scored by the harness's own rules, answers that match the seeds catch every defect with no false alarm."""
    rows, recs, cost = skill_review.run_set(name, tmp_path, fake_reviewer(True), workers=2)
    t = skill_review.totals(rows)
    assert (t["caught"], t["clean"], t["false_alarms"]) == (t["seeds"], t["controls"], 0) and cost > 0
    assert all(r["result"] in ("caught", "ok") for r in rows)


def test_a_silent_reviewer_misses_every_defect_but_leaves_controls_clean(tmp_path):
    """Saying nothing catches nothing: the scorer cannot be fooled by an empty review."""
    rows, _, _ = skill_review.run_set("aml", tmp_path, fake_reviewer(False), workers=2)
    t = skill_review.totals(rows)
    assert t["caught"] == 0 and t["clean"] == t["controls"]


def test_consistency_counts_seeds_with_the_same_result_in_every_run():
    """Two runs that differ on one seed: 1 of 2 consistent."""
    a = [{"set": "aml", "seed_id": "AS01", "result": "ok", "found": "none"},
         {"set": "aml", "seed_id": "AS02", "result": "caught", "found": "verdict"}]
    b = [dict(a[0]), dict(a[1], result="missed", found="none")]
    assert skill_review.consistency([a, b]) == (1, 2)


# --- real cases mode (v2) ---------------------------------------------------------------
def test_agreement_counts_both_only_and_neither_and_kappa():
    """Skill flags A and B, harness flags B and C, out of four cases: both 1, one each only, neither 1."""
    cases = {("K01", x) for x in ("TC01", "TC02", "TC03", "TC04")}
    skill = {c: set() for c in skill_review.COMPARED}
    harness = {c: set() for c in skill_review.COMPARED}
    skill["atomic"] = {("K01", "TC01"), ("K01", "TC02")}
    harness["atomic"] = {("K01", "TC02"), ("K01", "TC03")}
    row = next(r for r in skill_review.agreement(skill, harness, cases) if r["check"] == "atomic")
    assert (row["both"], row["harness_only"], row["skill_only"], row["neither"], row["agree_pct"]) == (1, 1, 1, 1, 50.0)
    assert row["kappa"] == 0.0                     # 50% agreement is exactly what chance gives here


def test_labels_from_both_sheet_formats_are_read_and_scored(tmp_path):
    """The blind sheet gives verdict, atomic and title; the sample gives confirmed faulty verdicts.
    A checker is right when it flags a faulty case and leaves a correct, single-purpose, clearly titled one alone."""
    blind = tmp_path / "blind.csv"
    blind.write_text("n,story,case_id,Q1_correct,Q2_single_purpose,Q3_title_clear\n"
                     "1,K01,TC01,correct,y,y\n2,K01,TC02,incorrect,n,y\n", encoding="utf-8")
    sample = tmp_path / "sample.csv"
    sample.write_text("n,story,kind,cases_or_judge_note,my_agree\n"
                      "1,K02,case verdict fail,\"TC09: Document expiring / Steps: ...\",y\n"
                      "2,K02,checklist covered,\"TC01: x\",y\n", encoding="utf-8")
    labels = skill_review.load_labels([blind, sample])
    assert labels[("K02", "TC09")] == {"verdict_faulty": True} and len(labels) == 3
    flags = {c: set() for c in skill_review.COMPARED}
    flags["verdict"] = {("K01", "TC02"), ("K02", "TC09")}
    flags["atomic"] = {("K01", "TC01")}
    assert skill_review.score_against_labels(labels, flags) == {"verdict": (3, 3), "atomic": (0, 2), "title_clear": (2, 2)}
