"""
tests/test_chatbot_ci_gate.py: free tests for the weekly CI check of the chatbot agent (chatbot/ci_gate.py).

What these tests are for
------------------------
The CI check decides whether the weekly run goes red, so its gates must fail for
the right reasons and only those: a forbidden tool call, a banned term, the wrong
prompt or a conversation not played are HARD failures; a missed required tool or
fact is a warning only. The play step must ask chatbot.run for exactly the CI
conversations with the final prompt. Made-up results; no API calls.

  python -m pytest tests/test_chatbot_ci_gate.py -v

Change history:
  2026-11-10  v1  first version (M5 write-up, CI option (b)).
"""
from __future__ import annotations

from bench.ci_thresholds import CHATBOT_CI_CONVERSATIONS, CHATBOT_EXPERIMENTS, CHATBOT_PROMPT_FP
from chatbot import ci_gate


def make_run(**changes):
    """A made-up marked run where every gate passes; `changes` overrides summary values."""
    summary = {"run": "20261110T000000Z", "conversations": 9, "conversations_passed": 9, "turns": 24,
               "turns_passed": 24, "forbidden_tool_calls": 0, "absent_terms_found": 0, "key_facts_missing": 0,
               "required_tools": {"pass": 10, "pass_earlier": 1, "met_earlier": 0, "wrong_args": 0, "missing": 0},
               "cost_usd": 0.007}
    summary.update(changes)
    records = [{"conv_id": c, "error": None, "system_prompt_fp": CHATBOT_PROMPT_FP} for c in CHATBOT_CI_CONVERSATIONS]
    return {"summary": summary, "conversations": []}, records


def failed(gates):
    """The names and levels of the gates that failed."""
    return [(g.level, g.name) for g in gates if not g.passed]


def test_a_clean_run_passes_every_gate():
    """All nine conversations played with the final prompt and nothing wrong: no gate fails."""
    result, records = make_run()
    assert failed(ci_gate.gates(result, records)) == []


def test_forbidden_call_and_banned_term_are_hard_failures():
    """A forbidden tool call (for example another member's claim looked up) and a banned
    term in a reply each fail a HARD gate, so the CI run goes red."""
    result, records = make_run(forbidden_tool_calls=1, absent_terms_found=1)
    assert failed(ci_gate.gates(result, records)) == [
        ("HARD", "Chatbot: no forbidden tool call"), ("HARD", "Chatbot: no banned term in a reply")]


def test_wrong_prompt_or_missing_conversation_is_a_hard_failure():
    """A run with a different prompt, or with a conversation missing or stopped by an
    error, is not comparable with the M5 results, so it fails."""
    result, records = make_run()
    records[0]["system_prompt_fp"] = "000000000000"
    records[1]["error"] = "timeout"
    del records[2]
    levels = failed(ci_gate.gates(result, records))
    assert ("HARD", "Chatbot: final prompt in use (fingerprint)") in levels
    assert ("HARD", "Chatbot: every CI conversation played, no run errors") in levels


def test_missed_tool_or_fact_is_only_a_warning():
    """A required tool not called, or a required fact worded differently, is reported as
    a warning: the M5 runs showed such replies are sometimes still correct."""
    result, records = make_run(key_facts_missing=1,
                               required_tools={"pass": 9, "pass_earlier": 1, "met_earlier": 0,
                                               "wrong_args": 0, "missing": 1})
    assert {lvl for lvl, _ in failed(ci_gate.gates(result, records))} == {"WARN"}


def test_play_asks_for_the_ci_conversations_with_the_final_prompt(monkeypatch):
    """The play step passes every CI conversation and every final-prompt experiment line
    to chatbot.run, with Langfuse tracing off."""
    seen = {}
    monkeypatch.setattr(ci_gate.run, "main", lambda argv: seen.setdefault("argv", argv) and 0)
    monkeypatch.delenv("GITHUB_ENV", raising=False)
    ci_gate.main(["play"])
    argv = seen["argv"]
    assert "--no-tracing" in argv
    assert [argv[i + 1] for i, a in enumerate(argv) if a == "--conv"] == CHATBOT_CI_CONVERSATIONS
    assert [argv[i + 1] for i, a in enumerate(argv) if a == "--experiment"] == CHATBOT_EXPERIMENTS
