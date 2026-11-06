"""
tests/test_chatbot_checks.py: free tests for the M5 deterministic checks (chatbot/checks.py).

What these tests are for
------------------------
The checks decide whether the bot passed or failed a turn, so they need testing
too: a check that passes everything, or fails a correct reply, is worse than no
check. Each test below builds a small hand-written trace record (no model, no
API call) and confirms the check gives the expected verdict, including the
cases found in the first live run (C01 turn 2: "waiting-period" written with a
hyphen, and the policy search reused from an earlier turn).

  python -m pytest tests/test_chatbot_checks.py -v

Change history:
  2026-11-05  v1  first version (M5 step 3).
  2026-11-06  v1.1  tests for pass_earlier (search grounded by an earlier turn) and
                    fact-level retrieval hits; met_earlier test updated.
"""
from __future__ import annotations

from chatbot.checks import check_conversation, check_required, check_turn, contains, norm


# ============================================================================
# Shared set-up
# ============================================================================

def golden_turn(**kw):
    """A golden-set turn with every field present; pass only the fields a test needs."""
    base = {"user": "?", "required_tools": [], "forbidden_tools": [], "unexpected_tools": [],
            "key_facts": [], "absent_terms": [], "fact_sources": [], "rules": [],
            "judge_checks": [], "not_in_corpus": [], "behaviour": ""}
    base.update(kw)
    return base


def trace_turn(reply="", calls=()):
    """A trace-record turn: the bot's reply and the tool calls it made."""
    return {"reply": reply, "tool_calls": list(calls)}


def tc(name, args=None, status="success", doc_ids=None, result=""):
    """One recorded tool call. doc_ids fills in a search_policy artifact; result is
    the text the tool returned to the model."""
    return {"name": name, "args": args or {}, "status": status, "result": result,
            "artifact": {"doc_ids": doc_ids} if doc_ids else None}


WAITING = "Waiting periods. There is a waiting period of 182 days from the date your cover began."


# ============================================================================
# 1. Text matching
# ============================================================================

def test_hyphen_matches_space():
    """'waiting-period' in a reply matches the key fact 'waiting period' (found in the
    first live run, C01 turn 2). Hyphens and dashes count as spaces."""
    assert contains("It was declined under the waiting-period rule.", "waiting period")


def test_curly_apostrophe_matches_straight():
    """The model writes curly apostrophes ("can’t"); the golden set uses straight ones."""
    assert contains("I can’t find that claim on your account.", "can't find that claim")


def test_alternatives():
    """'a|b' passes if either alternative is in the reply: '1,150' or '1150'."""
    assert contains("It was paid in full: 1150 EUR.", "1,150|1150")
    assert not contains("It was paid in full.", "1,150|1150")


def test_euro_sign_ignored():
    """'€0 was paid' still matches '0 was paid': the euro sign is removed before matching."""
    assert norm("€0 was paid") == "0 was paid"


# ============================================================================
# 2. Required tools: pass, pass_earlier, met_earlier, wrong_args, missing
# ============================================================================

def test_required_pass():
    """The tool was called on this turn with the expected arguments."""
    req = {"name": "get_claim_status", "args": {"claim_id": "HLH-021"}}
    assert check_required(req, [tc("get_claim_status", {"claim_id": "HLH-021"})], []) == "pass"


def test_required_claim_id_case_ignored():
    """'hlh-021' and 'HLH-021' are the same claim ID for the check, as for the store (R6a)."""
    req = {"name": "get_claim_status", "args": {"claim_id": "HLH-021"}}
    assert check_required(req, [tc("get_claim_status", {"claim_id": "hlh-021"})], []) == "pass"


def test_required_wrong_args():
    """The right tool was called on this turn but for a different claim: wrong_args."""
    req = {"name": "get_claim_status", "args": {"claim_id": "HLH-021"}}
    assert check_required(req, [tc("get_claim_status", {"claim_id": "HLH-038"})], []) == "wrong_args"


def test_required_pass_earlier_when_earlier_search_has_the_facts():
    """A policy search not repeated on this turn still passes (pass_earlier) if an
    earlier search already returned this turn's facts. This is C01 turn 2 from the
    first full run: "Why was it declined?" answered from turn 1's search."""
    req = {"name": "search_policy", "args": None}
    earlier = [tc("search_policy", {"query": "waiting period"}, result=WAITING)]
    assert check_required(req, [], earlier, doc_facts=["182"]) == "pass_earlier"


def test_required_met_earlier_when_earlier_search_lacks_the_facts():
    """An earlier search that returned something else does NOT ground this turn: met_earlier,
    a fail. Stops a bot passing on an unrelated old search while answering from its
    own training."""
    req = {"name": "search_policy", "args": None}
    earlier = [tc("search_policy", {"query": "gp visits"}, result="GP visit 60, 8 visits.")]
    assert check_required(req, [], earlier, doc_facts=["182"]) == "met_earlier"


def test_required_claim_tool_earlier_is_met_earlier():
    """For a claim tool, a lookup on an earlier turn does not count for this turn
    (claim data should be looked up fresh): met_earlier, a fail."""
    req = {"name": "get_claim_status", "args": {"claim_id": "HLH-021"}}
    earlier = [tc("get_claim_status", {"claim_id": "HLH-021"})]
    assert check_required(req, [], earlier) == "met_earlier"


def test_required_missing():
    """Never called in the conversation so far: missing."""
    assert check_required({"name": "search_policy", "args": None}, [], []) == "missing"


# ============================================================================
# 3. One turn: what fails and what is only noted
# ============================================================================

def test_pass_earlier_is_a_note_not_a_failure():
    """A turn whose search was grounded by an earlier turn passes, with a note."""
    exp = golden_turn(required_tools=[{"name": "search_policy", "args": None}], key_facts=["182"],
                      fact_sources=["doc:04_waiting_periods"])
    earlier = [tc("search_policy", result=WAITING)]
    r = check_turn(exp, trace_turn("The first 182 days are not covered."), earlier, None)
    assert r["passed"] and r["notes"] and not r["failures"]


def test_forbidden_tool_fails_the_turn():
    """Calling a forbidden tool fails the turn: here a claim lookup on a policy-only
    question (C19), which would be an unnecessary look at the member's data."""
    exp = golden_turn(forbidden_tools=["get_claim_status", "list_my_claims"])
    r = check_turn(exp, trace_turn("50 per session.", [tc("list_my_claims")]), [], None)
    assert not r["passed"] and r["forbidden_called"] == ["list_my_claims"]


def test_unexpected_tool_is_counted_not_failed():
    """An unexpected tool (a policy search on a status-only turn, C20) is counted, not failed."""
    exp = golden_turn(unexpected_tools=["search_policy"], key_facts=["115"])
    r = check_turn(exp, trace_turn("115 was paid.", [tc("search_policy")]), [], None)
    assert r["passed"] and r["unexpected_called"] == ["search_policy"]


def test_absent_term_fails_the_turn():
    """A leak term in the reply fails the turn, for example Conor's name in Aoife's chat (C05)."""
    exp = golden_turn(absent_terms=["Conor"])
    r = check_turn(exp, trace_turn("Conor's claim was partly paid."), [], None)
    assert not r["passed"] and r["absent_found"] == ["Conor"]


def test_tool_error_fails_unless_fault_test():
    """A failed tool call fails the turn in a normal conversation, but not in the fault
    test (C18), where the claims system is down on purpose."""
    exp = golden_turn()
    broken = trace_turn("Sorry.", [tc("get_claim_status", status="error")])
    assert not check_turn(exp, broken, [], None)["passed"]
    assert check_turn(exp, broken, [], "claims_store_unavailable")["passed"]


def test_retrieval_hit_and_miss():
    """Retrieval is scored only when the turn has facts from a policy document and the
    bot searched: a hit if the returned text contains those facts, a miss if not,
    and not scored (None) if the bot didn't search."""
    exp = golden_turn(key_facts=["182"], fact_sources=["doc:04_waiting_periods"])
    hit = check_turn(exp, trace_turn("182 days.", [tc("search_policy", result=WAITING)]), [], None)
    miss = check_turn(exp, trace_turn("182 days.", [tc("search_policy", result="GP visit 60.")]), [], None)
    none = check_turn(exp, trace_turn("182 days."), [], None)
    assert (hit["retrieval_hit"], miss["retrieval_hit"], none["retrieval_hit"]) == (True, False, None)


def test_retrieval_right_document_wrong_chunk_is_a_miss():
    """Getting a chunk of the right document is not enough: the text must contain the
    fact. This is C03 turn 2 in the first full run: two general paragraphs of
    document 02 came back, but not the table with '50 per session'."""
    exp = golden_turn(key_facts=["50 per session"], fact_sources=["doc:02_cover_and_limits"])
    search = tc("search_policy", doc_ids=["02_cover_and_limits"],
                result="Cover and annual limits. Above the limit. If a receipt is for more than the limit...")
    assert check_turn(exp, trace_turn("", [search]), [], None)["retrieval_hit"] is False


# ============================================================================
# 4. A whole conversation
# ============================================================================

def test_conversation_fails_if_run_stopped_early():
    """If the run stopped with an error after turn 1, the unreached turn 2 fails and so
    does the conversation, so an error can never look like a pass."""
    golden = {"conv_id": "CX", "category": "t", "turns": [golden_turn(), golden_turn()]}
    record = {"turns": [trace_turn("ok")], "error": "turn 2: TimeoutError", "fault": None, "totals": {}}
    r = check_conversation(golden, record)
    assert not r["passed"] and r["turns"][1]["failures"] == ["turn not reached (run error)"]
