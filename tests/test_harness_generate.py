"""
tests/test_harness_generate.py: free tests for harness/generate.py, the generator for any stories
file (M7 step 5: the AML/KYC stories).

What these tests are for
------------------------
The same Day 4 v1/v2 prompts and the bare prompt must run on a second domain without touching
bench/. A fake model stands in for the real one; no API calls.

  python -m pytest tests/test_harness_generate.py -v

Change history:
  2026-11-24  v1  first version (M7 step 5).
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from bench.golden import ROOT
from harness import generate
from harness.contract import load_cases, load_stories


@pytest.fixture(autouse=True)
def no_real_model(monkeypatch):
    """Safety net for every test in this file: creating a real OpenAI client fails at once."""
    def refuse():
        """Stand-in for bench.generate.make_client that refuses to run."""
        raise AssertionError("a test tried to call the real model")
    monkeypatch.setattr("bench.generate.make_client", refuse)


def fake_client(calls: list):
    """A fake model that answers every story with one valid Day 4 case (technique label included)."""
    def create(model, instructions, input):
        """Fake responses.create: record the prompt and story card, return one case for that story."""
        sid = input.split("Story ID: ")[1].split("\n")[0]
        calls.append((instructions, sid))
        body = {"story_id": sid, "test_cases": [
            {"case_id": "TC01", "title": f"{sid} happy path", "technique": "positive", "covers": ["AC1"],
             "preconditions": ["An applicant 'Ana Silva'."], "steps": ["Submit the application."],
             "expected_result": "The application continues."}]}
        return SimpleNamespace(output_text=json.dumps(body), model=model,
                               usage=SimpleNamespace(input_tokens=600, output_tokens=400))
    return SimpleNamespace(responses=SimpleNamespace(create=create))


def test_the_aml_kyc_stories_file_is_valid_for_the_harness():
    """datasets/aml_kyc_stories.json: 12 stories (K01-K12) the harness can read."""
    stories = load_stories(ROOT / "datasets" / "aml_kyc_stories.json")
    assert list(stories) == [f"K{n:02d}" for n in range(1, 13)]


@pytest.mark.parametrize("prompt", ["v2", "bare"])
def test_any_stories_file_with_either_prompt_saves_a_file_the_harness_can_read(tmp_path, monkeypatch, prompt):
    """v2 and bare run on the AML/KYC file: one call per story, in story order, with the right prompt;
    the saved file names the stories file and its fingerprint, and harness.check can read it."""
    monkeypatch.setattr(generate, "OUT_DIR", tmp_path)
    calls = []
    out = generate.run(prompt, ROOT / "datasets" / "aml_kyc_stories.json", only=["K01", "K11", "K12"],
                       client=fake_client(calls), workers=2)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert sorted(sid for _, sid in calls) == ["K01", "K11", "K12"]
    assert [r["story_id"] for r in data["records"]] == ["K01", "K11", "K12"]          # order kept
    expected_text = generate.prompt_for(prompt)[0]
    assert all(instr == expected_text for instr, _ in calls)
    meta = data["meta"]
    assert meta["prompt_version"] == prompt and meta["stories_file"] == "aml_kyc_stories.json"
    assert len(meta["golden_fingerprint"]) == 12 and meta["totals"]["schema_valid"] == 3
    assert out.name.startswith(f"gen_{prompt}_") and "aml_kyc_stories" in out.name
    groups, problems = load_cases(out)
    assert set(groups) == {"K01", "K11", "K12"} and problems == []


def test_an_unknown_story_id_stops_the_run(tmp_path, monkeypatch):
    """A typo in --only must not silently generate fewer stories."""
    monkeypatch.setattr(generate, "OUT_DIR", tmp_path)
    with pytest.raises(SystemExit, match="unknown story IDs"):
        generate.run("v2", ROOT / "datasets" / "aml_kyc_stories.json", only=["K99"], client=fake_client([]))
