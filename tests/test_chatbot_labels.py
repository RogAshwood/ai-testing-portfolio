"""
tests/test_chatbot_labels.py: free tests for the blind label sheet and agreement report
(chatbot/labels.py).

What these tests are for
------------------------
The agreement figure is only trustworthy if the labelling is blind, the split into
tune and held-out halves is fixed in advance, rubric example turns are left out,
and a missing label can never count as agreement. These tests check those
properties with small made-up data: no API call and no saved run needed.

  python -m pytest tests/test_chatbot_labels.py -v

Change history:
  2026-11-09  v1  first version (M5 step 4d).
  2026-11-09  v1.1  rekey tests.
"""
from __future__ import annotations

import csv
import json

import pytest

from chatbot.labels import agreement, choose_sample, half_for, read_labels, rekey, rubric_example_turns


def judged(*turns):
    """A minimal judge.json: judged(("C01", 1, {"plain_language": "fail"}), ...)."""
    return {"turns": [{"conv_id": c, "turn": t, "verdicts": {k: {"verdict": v, "reason": "r"} for k, v in vs.items()}}
                      for c, t, vs in turns]}


# ============================================================================
# 1. Choosing the sample
# ============================================================================

def test_rubric_example_turns_are_left_out():
    """A turn the rubric quotes as an example is never labelled, because the judge was
    shown the answer for it."""
    j = judged(("C01", 1, {"no_promise": "pass"}), ("C02", 1, {"no_promise": "pass"}))
    rows = choose_sample(j, excluded={("C01", 1)}, tool_turns=set())
    assert {(r["conv_id"], r["turn"]) for r in rows} == {("C02", 1)}


def test_every_judge_fail_on_plain_language_is_included():
    """All plain_language failures are labelled (they are the cases most worth checking),
    plus only a few passes."""
    turns = [(f"C{i:02d}", 1, {"plain_language": "fail" if i < 4 else "pass"}) for i in range(1, 30)]
    rows = choose_sample(judged(*turns), excluded=set(), tool_turns=set())
    pl = [r for r in rows if r["check"] == "plain_language"]
    assert sum(r["judge_verdict"] == "fail" for r in pl) == 3 and len(pl) == 3 + 5


def test_turn_specific_checks_are_all_included():
    """Checks asked only on some turns (no_leak, no_promise, ...) are rare, so all are labelled."""
    turns = [(f"C{i:02d}", 1, {"no_leak": "pass"}) for i in range(1, 8)]
    rows = choose_sample(judged(*turns), excluded=set(), tool_turns=set())
    assert len(rows) == 7


def test_halves_are_fixed_and_balanced():
    """The split into tune and held-out alternates within each check in a fixed order, so
    running the selection twice gives the same halves, and each check is split evenly."""
    turns = [(f"C{i:02d}", 1, {"no_promise": "pass"}) for i in range(1, 11)]
    a = choose_sample(judged(*turns), excluded=set(), tool_turns=set())
    b = choose_sample(judged(*turns), excluded=set(), tool_turns=set())
    assert [(r["conv_id"], r["half"]) for r in a] == [(r["conv_id"], r["half"]) for r in b]
    assert sum(r["half"] == "held_out" for r in a) == 5
    assert half_for(0) == "tune" and half_for(1) == "held_out"


def test_example_matching_uses_every_quoted_part(tmp_path):
    """A rubric example written with … for cut parts matches a reply only if every part
    is in it, so a short common phrase doesn't exclude unrelated turns."""
    (tmp_path / "C01.json").write_text(json.dumps({"conv_id": "C01", "turns": [
        {"reply": "I can only help with claims on your own account. He can check HLH-016."},
        {"reply": "I can only help with claims on your own account."}]}), encoding="utf-8")
    rubric = tmp_path / "rubric.md"
    rubric.write_text('- "I can only help with claims on your own account… He can check HLH-016." → fail\n',
                      encoding="utf-8")
    assert rubric_example_turns(tmp_path, rubric) == {("C01", 1)}


# ============================================================================
# 2. Agreement
# ============================================================================

KEY = [{"label_id": "H01", "check": "no_promise", "half": "tune", "judge_verdict": "pass", "judge_reason": "r",
        "conv_id": "C01", "turn": "1"},
       {"label_id": "H02", "check": "no_promise", "half": "held_out", "judge_verdict": "fail", "judge_reason": "r",
        "conv_id": "C02", "turn": "1"},
       {"label_id": "H03", "check": "plain_language", "half": "held_out", "judge_verdict": "pass",
        "judge_reason": "r", "conv_id": "C03", "turn": "1"}]


def labels(**v):
    return {k: {"label_id": k, "human_label": x, "human_notes": ""} for k, x in v.items()}


def test_agreement_counts_by_half_and_direction():
    """Agreement is reported for each half, and disagreements are split into 'judge
    stricter' (judge fail, human pass) and 'judge looser' (judge pass, human fail)."""
    res = agreement(labels(H01="pass", H02="pass", H03="Pass "), KEY)
    assert res["tune"]["agree"] == 1 and res["held_out"]["agree"] == 1 and res["held_out"]["n"] == 2
    assert res["held_out"]["judge_fail_human_pass"] == 1 and res["overall"]["rate"] == round(2 / 3, 3)


def test_missing_or_misspelt_label_stops_the_report():
    """A blank or misspelt label stops the report rather than being counted either way."""
    with pytest.raises(SystemExit):
        agreement(labels(H01="pass", H02="", H03="pass"), KEY)
    with pytest.raises(SystemExit):
        agreement(labels(H01="pass", H02="fial", H03="pass"), KEY)


def test_small_checks_are_marked_indicative():
    """A check with fewer than 5 held-out labels is reported as indicative only (decision D6)."""
    res = agreement(labels(H01="pass", H02="fail", H03="pass"), KEY)
    assert res["per_check"]["no_promise"]["status"].startswith("indicative")


def test_labels_file_resaved_by_excel_is_read(tmp_path):
    """The labels file can be read whether Excel saved it as UTF-8 or as its older Windows format."""
    for enc in ("utf-8-sig", "cp1252"):
        p = tmp_path / f"l_{enc}.csv"
        with p.open("w", encoding=enc, newline="") as f:
            w = csv.writer(f)
            w.writerow(["label_id", "reply", "human_label", "human_notes"])
            w.writerow(["H01", "We pay up to €60", "pass", ""])
        assert read_labels(p)["H01"]["human_label"] == "pass"


# ============================================================================
# 3. Refreshing the key after a rubric change
# ============================================================================

def test_rekey_takes_new_verdicts_and_keeps_the_halves():
    """After the run is judged again with a new rubric, rekey takes the new verdicts but
    leaves the label IDs and halves exactly as they were."""
    new = {"meta": {"rubric_fp": "new"}, "turns": [
        {"conv_id": "C01", "turn": 1, "verdicts": {"no_promise": {"verdict": "fail", "reason": "n1"}}},
        {"conv_id": "C02", "turn": 1, "verdicts": {"no_promise": {"verdict": "fail", "reason": "n2"}}},
        {"conv_id": "C03", "turn": 1, "verdicts": {"plain_language": {"verdict": "pass", "reason": "n3"}}}]}
    out = rekey(KEY, new)
    assert [(o["label_id"], o["half"]) for o in out] == [(k["label_id"], k["half"]) for k in KEY]
    assert out[0]["judge_verdict"] == "fail" and out[0]["judge_reason"] == "n1" and out[0]["rubric_fp"] == "new"


def test_rekey_stops_if_a_label_was_not_judged():
    """If the new judging didn't cover a labelled turn (for example a --limit run), rekey
    stops rather than leave an old verdict in place."""
    partial = {"meta": {"rubric_fp": "new"}, "turns": [
        {"conv_id": "C01", "turn": 1, "verdicts": {"no_promise": {"verdict": "pass", "reason": "r"}}}]}
    with pytest.raises(SystemExit):
        rekey(KEY, partial)
