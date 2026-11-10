"""
tests/test_chatbot_diagram.py: free tests for the sequence diagram builder (chatbot/diagram.py).

What these tests are for
------------------------
The diagram is drawn from a saved trace record, so it must show what actually
happened: each tool call with its arguments and result, the access-checked claim
lookups, turns answered from memory, and the check results. Mermaid also breaks
on some characters, so the text must be cleaned. Made-up record; no API calls.

  python -m pytest tests/test_chatbot_diagram.py -v

Change history:
  2026-11-10  v1  first version (M5 write-up, task T2).
"""
from __future__ import annotations

import json

from chatbot.diagram import clean, to_mermaid, verdicts

RECORD = {"conv_id": "C01", "member_id": "M-1021", "turns": [
    {"user": "What's happening with HLH-021?", "reply": "It was declined; you can appeal.",
     "tool_calls": [
         {"name": "get_claim_status", "args": {"claim_id": "HLH-021"}, "status": "success",
          "result": json.dumps({"found": True, "claim": {"claim_id": "HLH-021", "status": "declined",
                                                          "amount_paid": "0", "decision_code": "WAITING_PERIOD"}})},
         {"name": "search_policy", "args": {"query": "waiting period"}, "status": "success",
          "result": "[04_waiting_periods#1]\nWaiting periods...\n\n[09_appeals#2]\nHow to appeal..."}]},
    {"user": "Why?", "reply": "Because of the waiting period.", "tool_calls": []}]}


def test_diagram_shows_tools_lookups_and_memory():
    """Turn 1 shows both tool calls, the claim lookup going to the claims store with
    the access check, and the policy search going to the retriever with the chunks it
    returned; turn 2, with no tool call, is shown as answered from memory."""
    m = to_mermaid(RECORD).replace("<br/>", " ")          # line breaks don't matter here
    assert m.startswith("sequenceDiagram")
    assert "get_claim_status(HLH-021)" in m and "access check" in m
    assert "HLH-021: declined, paid 0, WAITING_PERIOD" in m
    assert "04 part 1" in m and "09 part 2" in m
    assert "answers from memory" in m and "turns 1 to 1" in m


def test_check_results_are_added_per_turn():
    """When the run was scored, each turn gets a note with the text-check result and the
    judge's checks, naming any check that failed."""
    m = to_mermaid(RECORD, {1: "text checks pass<br/>judge: 1 of 2 checks pass (fail: no_invented_fact)"})
    assert "fail: no_invented_fact" in m


def test_verdicts_read_from_the_run_folder(tmp_path):
    """The note text is built from checks.json and judge.json in the run folder."""
    (tmp_path / "checks.json").write_text(json.dumps({"conversations": [
        {"conv_id": "C01", "turns": [{"turn": 1, "passed": True}]}]}), encoding="utf-8")
    (tmp_path / "judge.json").write_text(json.dumps({"turns": [
        {"conv_id": "C01", "turn": 1, "verdicts": {"plain_language": {"verdict": "pass"},
                                                   "no_invented_fact": {"verdict": "fail"}}}]}), encoding="utf-8")
    assert verdicts(tmp_path, "C01")[1] == "text checks pass<br/>judge: 1 of 2 checks pass (fail: no_invented_fact)"


def test_text_is_made_safe_for_mermaid():
    """Semicolons and # (which Mermaid treats specially) are replaced, long text is cut
    with '...', and lines are wrapped at the width asked for."""
    t = clean("a; b # c " + "word " * 40, limit=60, wrap=20)
    assert ";" not in t and "#" not in t and t.endswith("...")
    assert all(len(line) <= 25 for line in t.split("<br/>"))
