"""
tests/test_chatbot_judge.py: free tests for the M5 conversation judge (chatbot/judge.py).

What these tests are for
------------------------
The judge's verdicts come from a model and are calibrated separately (seeded
replies and blind labels). Everything around the model is ordinary code and is
tested here, with no API call: reading the rubric and spec as data, building the
packet of evidence, keeping the golden set's expected answers out of the packet,
reading the judge's answer strictly, retrying a bad answer, and combining the
judge's verdicts with the deterministic checks. A scripted model stands in for
the judge where one is needed.

  python -m pytest tests/test_chatbot_judge.py -v

Change history:
  2026-11-06  v1  first version (M5 step 4).
  2026-11-09  v1.1  the SESSION line: shown when a member is given, and the plan name
                    kept in step with the bot's prompt.
"""
from __future__ import annotations

import json
from collections import Counter

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from chatbot.judge import (GOLDEN_PATH, PLAN_NAME, SEEDED_PATH, JudgeAnswerError, build_packet, checks_for_turn,
                           evidence, judge_run, judge_turn, load_rubric, parse_verdicts, render_packet, rule_ids,
                           spec_rules)
from chatbot.prompt import SYSTEM_PROMPT


# ============================================================================
# Shared set-up
# ============================================================================

@pytest.fixture(scope="module")
def golden():
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def rubric():
    return load_rubric()


def turn(golden, conv_id, n):
    """One golden turn by conversation ID and turn number."""
    return next(c for c in golden["conversations"] if c["conv_id"] == conv_id)["turns"][n - 1]


class ScriptedJudge(BaseChatModel):
    """A stand-in for the judge model that returns pre-written answers in order."""
    script: list

    @property
    def _llm_type(self) -> str:
        return "scripted-judge"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        text = self.script.pop(0)
        msg = AIMessage(content=text, usage_metadata={"input_tokens": 1000, "output_tokens": 50, "total_tokens": 1050})
        return ChatResult(generations=[ChatGeneration(message=msg)])


def answer(**verdicts):
    """A well-formed judge answer: answer(no_promise="pass", plain_language="fail")."""
    return json.dumps({"verdicts": [{"check": c, "verdict": v, "reason": "r"} for c, v in verdicts.items()]})


# ============================================================================
# 1. The rubric and spec, read as data
# ============================================================================

def test_rubric_defines_every_check_the_golden_set_uses(golden, rubric):
    """Every judge check named in the golden set (per turn and every turn) has a rubric
    section, and every rubric section has a question, a pass rule and a fail rule."""
    _, checks, _ = rubric
    used = set(golden["judge_checks_every_turn"])
    used |= {j for c in golden["conversations"] for t in c["turns"] for j in t["judge_checks"]}
    assert used <= set(checks)
    for cid, sec in checks.items():
        assert "Question:" in sec and "Pass if:" in sec and "Fail if:" in sec, cid


def test_rubric_rules_exist_in_the_spec(rubric):
    """Every rule a check cites (for example R12) exists in the spec, so the judge is
    always shown the rule text."""
    _, checks, _ = rubric
    rules = spec_rules()
    for cid, sec in checks.items():
        assert rule_ids(sec), cid
        assert all(r in rules for r in rule_ids(sec)), cid


def test_instructions_ask_for_json_only(rubric):
    """The judge's instructions fix the answer format: JSON with a verdict per check."""
    instructions, _, _ = rubric
    assert '"verdicts"' in instructions and "pass" in instructions and "fail" in instructions


# ============================================================================
# 2. The packet of evidence
# ============================================================================

def test_checks_for_turn_adds_every_turn_checks_once(golden):
    """A turn's checks are its own judge checks plus the every-turn ones, with no repeats."""
    checks = checks_for_turn(golden, turn(golden, "L01", 9))   # has no_invented_fact itself and every turn
    assert checks.count("no_invented_fact") == 1 and "plain_language" in checks


def test_evidence_includes_earlier_turns():
    """The evidence for a turn includes tool results from earlier turns, because the bot
    may answer from memory (C01 turn 2 used turn 1's search)."""
    rec_turns = [{"turn": 1, "tool_calls": [{"name": "search_policy", "args": {"query": "q"}, "status": "success",
                                             "result": "182 days"}]},
                 {"turn": 2, "tool_calls": []}]
    lines = evidence(rec_turns, 2)
    assert len(lines) == 1 and "[turn 1]" in lines[0] and "182 days" in lines[0]


def test_packet_holds_no_expected_answers(golden, rubric):
    """The judge never sees the golden set's expected answers (key facts, absent terms):
    only the evidence the bot had. C05 turn 2 has the absent term 'Conor', which the
    member never typed, so it must not appear anywhere in the packet."""
    _, checks, _ = rubric
    gt = turn(golden, "C05", 2)
    p = build_packet(gt, [], "I can only help with claims on your own account.", [], checks_for_turn(golden, gt),
                     checks, spec_rules())
    text = render_packet(p)
    assert "Conor" not in text and "key_fact" not in text and "absent" not in text


def test_packet_gives_the_date_answer_from_code(golden, rubric):
    """On a date turn the packet states the correct answer worked out in code, so the
    judge compares instead of calculating."""
    _, checks, _ = rubric
    gt = turn(golden, "W01", 1)
    text = render_packet(build_packet(gt, [], "reply", [], checks_for_turn(golden, gt), checks, spec_rules()))
    assert "2026-11-17 is day 181, inside the waiting period" in text and "Covered from: 2026-11-18" in text


def test_packet_shows_the_session(golden, rubric):
    """The packet shows who is signed in and their plan, because the bot is told this by
    the portal rather than by a tool. Without it the judge called "Essential Plus" an
    invented fact (decision D7). With no member given, there is no SESSION line."""
    _, checks, _ = rubric
    gt = turn(golden, "C02", 1)
    with_session = render_packet(build_packet(gt, [], "reply", [], checks_for_turn(golden, gt), checks,
                                              spec_rules(), member_id="M-1002"))
    without = render_packet(build_packet(gt, [], "reply", [], checks_for_turn(golden, gt), checks, spec_rules()))
    assert "SESSION" in with_session and "M-1002" in with_session and PLAN_NAME in with_session
    assert "SESSION" not in without


def test_plan_name_matches_the_bot_prompt():
    """The plan name shown to the judge is the one the bot's prompt gives it, so the two
    cannot drift apart without this test failing."""
    assert PLAN_NAME in SYSTEM_PROMPT


# ============================================================================
# 3. Reading the judge's answer strictly
# ============================================================================

def test_parse_valid_answer():
    """A well-formed answer is read, including one wrapped in a code fence."""
    v = parse_verdicts("```json\n" + answer(no_promise="pass", plain_language="fail") + "\n```",
                       ["no_promise", "plain_language"])
    assert v["no_promise"]["verdict"] == "pass" and v["plain_language"]["verdict"] == "fail"


@pytest.mark.parametrize("bad, why", [
    ("not json at all", "not JSON"),
    (json.dumps({"verdicts": [{"check": "no_promise", "verdict": "pass"}]}), "missing check"),
    (answer(no_promise="pass", plain_language="pass", no_leak="pass"), "extra check"),
    (answer(no_promise="0.8", plain_language="pass"), "a score, not pass or fail"),
])
def test_parse_rejects_bad_answers(bad, why):
    """Anything other than one pass or fail per check asked is rejected, so a malformed
    answer can never be counted as a pass."""
    with pytest.raises(JudgeAnswerError):
        parse_verdicts(bad, ["no_promise", "plain_language"])


def test_bad_answer_is_retried_once():
    """A malformed first answer is retried; a good second answer is used, and the tokens
    of both calls are counted."""
    judge = ScriptedJudge(script=["oops", answer(no_promise="pass")])
    r = judge_turn(judge, "system", "packet", ["no_promise"])
    assert r["verdicts"]["no_promise"]["verdict"] == "pass" and r["error"] is None and r["input_tokens"] == 2000


def test_two_bad_answers_become_judge_error():
    """Two malformed answers in a row are recorded as judge_error for every check, never as a pass."""
    r = judge_turn(ScriptedJudge(script=["oops", "still oops"]), "system", "packet", ["no_promise", "no_leak"])
    assert {v["verdict"] for v in r["verdicts"].values()} == {"judge_error"} and r["error"]


# ============================================================================
# 4. Judging a run and combining with the deterministic checks
# ============================================================================

def test_judge_run_combines_with_checks(tmp_path, golden):
    """Judging a run folder writes a verdict per turn, and the combined score counts a
    turn as passing only if it passed the deterministic checks AND every judge check."""
    conv = next(c for c in golden["conversations"] if c["conv_id"] == "C14")       # 2 turns
    rec = {"conv_id": "C14", "turns": [{"turn": n, "user": t["user"], "reply": "ok", "tool_calls": []}
                                       for n, t in enumerate(conv["turns"], start=1)]}
    (tmp_path / "C14.json").write_text(json.dumps(rec), encoding="utf-8")
    (tmp_path / "checks.json").write_text(json.dumps({"conversations": [{"conv_id": "C14", "turns": [
        {"turn": 1, "passed": True}, {"turn": 2, "passed": True}]}]}), encoding="utf-8")
    checks1 = checks_for_turn(golden, conv["turns"][0])
    checks2 = checks_for_turn(golden, conv["turns"][1])
    judge = ScriptedJudge(script=[answer(**{c: "pass" for c in checks1}),
                                  answer(**{c: ("fail" if c == "plain_language" else "pass") for c in checks2})])
    res = judge_run(tmp_path, llm=judge)
    c = res["summary"]["combined"]
    assert (c["turns_judged"], c["turns_passing_both"], c["conversations_passing_both"]) == (2, 1, 0)
    assert res["meta"]["rubric_fp"] and all(r["system_prompt_fp"] for r in res["turns"])


# ============================================================================
# 5. The seeded replies
# ============================================================================

def test_seeds_cover_every_check_with_fails_and_a_pass(rubric):
    """The seeded set has, for every rubric check, at least two replies that must fail and
    at least one that must pass (the clean one catches a judge that is too strict)."""
    _, checks, _ = rubric
    seeds = json.loads(SEEDED_PATH.read_text(encoding="utf-8"))["seeds"]
    counts = Counter((s["check"], s["expected"]) for s in seeds)
    for cid in checks:
        assert counts[(cid, "fail")] >= 2 and counts[(cid, "pass")] >= 1, cid
    assert len({s["seed_id"] for s in seeds}) == len(seeds)


def test_seeds_point_at_real_golden_turns(golden):
    """Every seed names a real conversation and turn, so its packet uses that turn's
    rules and checks."""
    convs = {c["conv_id"]: c for c in golden["conversations"]}
    for s in json.loads(SEEDED_PATH.read_text(encoding="utf-8"))["seeds"]:
        assert s["conv_id"] in convs and 1 <= s["turn"] <= len(convs[s["conv_id"]]["turns"]), s["seed_id"]
        assert len(s["history"]) == s["turn"] - 1, s["seed_id"]
