"""
tests/test_chatbot_compare.py: free tests for comparing runs (chatbot/compare.py) and
for the DeepEval comparison's set-up (chatbot/deepeval_compare.py).

What these tests are for
------------------------
compare.py turns saved results into the numbers the prompt experiments are judged
on, so its arithmetic and its safety checks (one judge version, split runs joined
correctly) must be right. deepeval_compare.py calls DeepEval, which costs money;
everything around the call (building the test cases, our verdict, the agreement
counts) is tested here with made-up data and a stand-in metric. No API calls.

  python -m pytest tests/test_chatbot_compare.py -v

Change history:
  2026-11-09  v1  first version (M5 step 4g).
  2026-11-09  v1.1  test that the general metric only reads fields DeepEval supports.
  2026-11-09  v1.2  the prompt each run used is read from the trace records.
"""
from __future__ import annotations

import json

import pytest

from chatbot.compare import load_run, measures, summarise
from chatbot.deepeval_compare import compare, our_verdicts, run, to_test_case


def write_run(folder, turns, rubric="fp1", judge_fail=()):
    """A run folder with checks.json and judge.json.
    turns: [(conv_id, turn, text_checks_passed)]; judge_fail: [(conv_id, turn, check)]"""
    folder.mkdir(parents=True, exist_ok=True)
    convs = {}
    for c, n, ok in turns:
        convs.setdefault(c, []).append({"turn": n, "passed": ok, "failures": [] if ok else ["x"]})
    (folder / "checks.json").write_text(json.dumps({
        "summary": {"cost_usd": 0.03, "retrieval_hit_rate": 1.0, "retrieval_turns": 2},
        "conversations": [{"conv_id": c, "turns": t} for c, t in convs.items()]}), encoding="utf-8")
    jt = [{"conv_id": c, "turn": n, "verdicts": {"plain_language": {
        "verdict": "fail" if (c, n, "plain_language") in judge_fail else "pass", "reason": "r"}}} for c, n, _ in turns]
    (folder / "judge.json").write_text(json.dumps({"meta": {"rubric_fp": rubric}, "summary": {"cost_usd": 0.5},
                                                   "turns": jt}), encoding="utf-8")
    return folder


# ============================================================================
# 1. compare.py
# ============================================================================

def test_both_layers_needs_text_checks_and_judge(tmp_path):
    """A turn counts as passing both layers only if it passed the text checks AND the
    judge; a conversation passes only if all its turns do."""
    d = write_run(tmp_path / "r", [("C01", 1, True), ("C01", 2, False), ("C02", 1, True)],
                  judge_fail=[("C02", 1, "plain_language")])
    m = measures(load_run(str(d)))
    assert (m["turns_text"], m["turns_judge"], m["turns_both"]) == (2, 2, 1)
    assert (m["convs_text"], m["convs_both"]) == (1, 0)
    assert m["judge_fails"] == {"plain_language": 1}


def test_split_run_is_joined(tmp_path):
    """A run spread over two folders (the baseline's C22 and C23 were run separately)
    is read as one run with all its turns and both costs."""
    a = write_run(tmp_path / "a", [("C01", 1, True)])
    b = write_run(tmp_path / "b", [("C22", 1, True)])
    run = load_run(f"{a}+{b}")
    assert set(run["det"]) == {("C01", 1), ("C22", 1)} and run["cost"] == pytest.approx(1.06)


def test_mixed_judge_versions_are_refused(tmp_path):
    """Folders judged with different rubric versions can't be joined into one run,
    because the comparison would mix two judges."""
    a = write_run(tmp_path / "a", [("C01", 1, True)], rubric="fp1")
    b = write_run(tmp_path / "b", [("C22", 1, True)], rubric="fp2")
    with pytest.raises(SystemExit):
        load_run(f"{a}+{b}")


def test_summary_is_mean_min_max():
    """A group of runs is reported as mean [min-max] for each measure."""
    base = {"turns_judge": 0, "turns_both": 0, "convs_text": 0, "convs_both": 0, "retrieval": None, "cost": 1,
            "judge_fails": {}}
    s = summarise([base | {"turns_text": 90}, base | {"turns_text": 84}, base | {"turns_text": 87}])
    assert s["turns_text"] == {"mean": 87, "min": 84, "max": 90}


# ============================================================================
# 2. deepeval_compare.py (no API calls)
# ============================================================================

RECORD = {"conv_id": "C01", "turns": [
    {"user": "What's happening with HLH-021?", "reply": "It was declined.",
     "tool_calls": [{"name": "get_claim_status", "args": {"claim_id": "HLH-021"}, "status": "success",
                     "result": "{\"status\": \"declined\"}"}]},
    {"user": "Why?", "reply": "The waiting period.", "tool_calls": []}]}
GOLDEN = {"scenario": "s", "expected_outcome": "o"}


def test_test_case_carries_tool_results_as_context():
    """Each bot turn becomes an assistant turn whose retrieval_context is what its tools
    returned, so TurnFaithfulness checks grounding against the same evidence our judge sees.
    A turn with no tool call has no context of its own."""
    tc = to_test_case(RECORD, GOLDEN)
    roles = [t.role for t in tc.turns]
    assert roles == ["user", "assistant", "user", "assistant"]
    assert "declined" in tc.turns[1].retrieval_context[0] and tc.turns[3].retrieval_context is None
    assert tc.scenario == "s" and tc.expected_outcome == "o" and tc.chatbot_role


def test_our_verdict_lists_failing_turns(tmp_path):
    """Our verdict for a conversation fails if any turn failed either layer, and lists
    which turn and check, so a DeepEval 'pass' can be compared with what we found."""
    d = write_run(tmp_path / "r", [("C01", 1, True), ("C01", 2, False)], judge_fail=[("C01", 1, "plain_language")])
    v = our_verdicts(str(d))["C01"]
    assert v["passed"] is False and "t1 plain_language" in v["failed"] and "t2 text checks" in v["failed"]


def test_agreement_counts_missed_and_extra():
    """'missed' = DeepEval passed a conversation we failed; 'extra' = DeepEval failed one
    we passed. An errored metric is counted separately, never as a pass."""
    rows = [{"conv_id": "C01", "ours_passed": False, "metrics": {"M": {"score": 0.9, "passed": True}}},
            {"conv_id": "C02", "ours_passed": True, "metrics": {"M": {"score": 0.2, "passed": False}}},
            {"conv_id": "C03", "ours_passed": True, "metrics": {"M": {"score": 0.8, "passed": True}}},
            {"conv_id": "C04", "ours_passed": True, "metrics": {"M": {"score": None, "passed": None}}}]
    c = compare(rows)["M"]
    assert c["missed"] == ["C01"] and c["extra"] == ["C02"] and c["agree_with_ours"] == 1 and c["errors"] == 1


def test_a_metric_error_does_not_stop_the_run(tmp_path):
    """If one metric raises (an API error, say), its score is recorded as an error and
    the other metrics and conversations still run."""
    d = write_run(tmp_path / "r", [("C01", 1, True), ("C01", 2, True)])
    (d / "C01.json").write_text(json.dumps(RECORD), encoding="utf-8")

    class Good:
        name, score, reason, evaluation_cost = "good", None, "ok", 0.01

        def measure(self, tc):
            self.score = 0.8

    class Bad(Good):
        def measure(self, tc):
            raise RuntimeError("API down")

    res = run(str(d), metrics_factory=lambda: [Good(), Bad()])
    m = res["conversations"][0]["metrics"]
    assert m["Good"]["score"] == 0.8 and m["Bad"]["score"] is None and "API down" in m["Bad"]["reason"]


def test_general_metric_reads_only_supported_fields(monkeypatch):
    """The general 'Overall quality' metric must only read fields ConversationalGEval
    supports in DeepEval 4.2.8. In the first trial it was given chatbot_role, which
    4.2.8 doesn't support, and it errored on every conversation."""
    from deepeval.metrics.g_eval.utils import CONVERSATIONAL_G_EVAL_PARAMS
    from chatbot.deepeval_compare import make_metrics
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-used")
    geval = [m for m in make_metrics(model="gpt-6-sol") if m.__class__.__name__ == "ConversationalGEval"][0]
    assert all(p in CONVERSATIONAL_G_EVAL_PARAMS for p in geval.evaluation_params)


def test_prompt_used_is_read_from_the_records(tmp_path):
    """compare shows which prompt a run used: records from before the experiments (no
    'experiments' field) count as the baseline, and an experiment run is named. A run
    whose conversations used different prompts is refused."""
    base = write_run(tmp_path / "b", [("C01", 1, True)])
    (base / "C01.json").write_text(json.dumps({"conv_id": "C01", "turns": []}), encoding="utf-8")
    exp = write_run(tmp_path / "e", [("C01", 1, True), ("C02", 1, True)])
    for c in ("C01", "C02"):
        (exp / f"{c}.json").write_text(json.dumps({"conv_id": c, "turns": [], "experiments": ["plain_language"]}),
                                       encoding="utf-8")
    assert load_run(str(base))["prompt"] == "baseline"
    assert load_run(str(exp))["prompt"] == "baseline + plain_language"
    (exp / "C02.json").write_text(json.dumps({"conv_id": "C02", "turns": [], "experiments": []}), encoding="utf-8")
    with pytest.raises(SystemExit):
        load_run(str(exp))
