"""
tests/test_chatbot_tools.py: free tests for the M5 bot's code (no API calls, no cost).

What these tests are for
------------------------
The M5 bot has two kinds of part:
  - the model's behaviour (which tool it picks, what it says): non-deterministic,
    tested later by playing the golden conversations and judging the replies;
  - ordinary code (the access check, ID handling, the claims-store fault, the
    document 10 swap, how LangGraph passes messages around): deterministic, so
    it can and should be tested like any other code.
This file tests the second kind. If one of these fails, the problem is in our
code, not in the model.

Where a model is needed (the LangGraph wiring tests), a ScriptedModel stands in
for it: it returns replies written in advance, so the test controls exactly
what the "model" does and checks how the rest of the bot handles it.

Each test's docstring says in plain English what it checks and which spec rule
(datasets/chatbot_spec.md) it protects. Run with -v to see each test's name:

  python -m pytest tests/test_chatbot_tools.py -q      summary only
  python -m pytest tests/test_chatbot_tools.py -v      one line per test

Change history:
  2026-11-05  v1  first version (M5).
  2026-11-05  v1.1  plain-English docstring for every test and helper; no test changed.
  2026-11-06  v1.2  section 4b: tests for the M5 chunking (tables split by row, the
                    exclusions list by item) and the M5 version of document 04.
"""
from __future__ import annotations

import inspect
import json

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from chatbot.bot import build_graph, load_golden, run_conversation
from chatbot.claims import ClaimsStore, ClaimsStoreUnavailable, tidy_id
from chatbot.policy import SPLIT_LIST_DOCS, build_m5_retriever, chunk_m5, load_m5_docs
from chatbot.tools import NOT_FOUND, build_tools
from rag_pipeline import DOCS_DIR, chunk_docs


# ============================================================================
# Shared set-up (fixtures and helpers)
# ============================================================================

@pytest.fixture(scope="module")
def store():
    """The real claims store, loaded once and shared by the tests in this file."""
    return ClaimsStore()


@pytest.fixture(scope="module")
def retriever():
    """The real M5 retriever (Day 3 TF-IDF over the M5 documents), built once."""
    return build_m5_retriever()


def tool(tools, name):
    """Pick one tool out of the list build_tools() returns, by name."""
    return next(t for t in tools if t.name == name)


class ScriptedModel(BaseChatModel):
    """A stand-in for the LLM that returns pre-written replies, in order.

    script  the AIMessages to return, one per model call
    seen    filled in as the test runs: the messages the "model" was sent on
            each call, so a test can check what the bot passed to it
    It accepts bind_tools() and ignores it, because it doesn't need to choose.
    """
    script: list
    seen: list = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(list(messages))
        return ChatResult(generations=[ChatGeneration(message=self.script.pop(0))])


def call(name, args, cid="c1"):
    """A scripted model message that asks for one tool call."""
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": cid, "type": "tool_call"}])


# ============================================================================
# 1. Claim IDs (rule R6): how a typed ID is tidied
# ============================================================================

@pytest.mark.parametrize("raw, tidied", [
    ("HLH-021", "HLH-021"), ("hlh-021", "HLH-021"), ("HLH021", "HLH-021"), ("HL021", "HLH-021"),
    ("HLH-21", "HLH-021"), ("hlh 021", "HLH-021"), ("021", "HLH-021"), ("ABC-021", None), ("HLH-0213", None),
])
def test_tidy_id(raw, tidied):
    """Each way a member might type a claim ID is tidied to HLH-NNN, and things that
    aren't claim IDs (wrong letters, four digits) are not. Rule R6b.
    One test per row in the table above, so a failure names the exact input."""
    assert tidy_id(raw) == tidied


# ============================================================================
# 2. Access check (rules R1 to R3): a member sees only their own claims
# ============================================================================

def test_own_claim_found(store):
    """A member asking about their own claim gets the right record:
    David (M-1021) sees HLH-021 as declined for the waiting period."""
    rec = store.get("M-1021", "HLH-021")
    assert rec["status"] == "declined" and rec["decision_code"] == "WAITING_PERIOD"


def test_lower_case_standard_id_found(store):
    """A correctly formed ID typed in lower case still finds the claim. Rule R6a."""
    assert store.get("M-1021", "hlh-021")["claim_id"] == "HLH-021"


def test_malformed_id_not_looked_up(store):
    """A malformed ID (HLH021, no hyphen) is NOT looked up by the store. The bot has
    to confirm "Did you mean HLH-021?" with the member first. Rule R6b."""
    assert store.get("M-1021", "HLH021") is None


def test_other_members_claim_not_found(store):
    """Aoife (M-1015) cannot see Conor's claim HLH-016, even though it exists. Rule R2."""
    assert store.get("M-1015", "HLH-016") is None


def test_not_found_is_identical_for_other_member_and_missing(store, retriever):
    """Asking for someone else's claim and asking for a claim that doesn't exist give
    exactly the same answer, so the bot can't reveal that a claim exists. Rule R3."""
    t = tool(build_tools("M-1015", store, retriever), "get_claim_status")
    other = t.invoke({"claim_id": "HLH-016"})      # exists, but belongs to another member
    missing = t.invoke({"claim_id": "HLH-099"})    # does not exist
    assert other == missing == json.dumps(NOT_FOUND)


def test_records_hide_internal_fields(store):
    """A claim record shown to the bot leaves out internal fields (member_id, source)."""
    assert {"member_id", "source"}.isdisjoint(store.get("M-1012", "HLH-012"))


def test_list_returns_only_own_claims(store):
    """'List my claims' returns exactly the member's own claims: Laura (M-1012) gets
    her three, and Aoife's list never includes Conor's HLH-016. Rules R2, R5."""
    assert [c["claim_id"] for c in store.list_for("M-1012")] == ["HLH-012", "HLH-036", "HLH-037"]
    assert all(c["claim_id"] != "HLH-016" for c in store.list_for("M-1015"))


def test_tools_take_no_member_argument(store, retriever):
    """No tool has a member argument, so the model has no way to ask for another
    member's data, whatever the member types (for example "I'm member M-1016").
    The member is fixed when the tools are built. Rule R1."""
    for t in build_tools("M-1012", store, retriever):
        assert "member" not in json.dumps(t.args).lower()


def test_every_golden_member_exists(store):
    """Every member used in the golden conversations exists in the claims data, so no
    conversation fails just because of a typo in a member ID."""
    assert {c["member_id"] for c in load_golden()} <= store.members()


# ============================================================================
# 3. Claims system down (rule R22): the fault used by conversation C18
# ============================================================================

def test_faulted_store_raises():
    """With the fault switched on, both claim lookups fail with ClaimsStoreUnavailable,
    the error bot.py turns into a message for the model."""
    s = ClaimsStore(fault="claims_store_unavailable")
    with pytest.raises(ClaimsStoreUnavailable):
        s.get("M-1024", "HLH-024")
    with pytest.raises(ClaimsStoreUnavailable):
        s.list_for("M-1024")


def test_unknown_fault_rejected():
    """A misspelt fault name is an error, not silently ignored, so a typo in the golden
    file can't turn a fault test into a normal run."""
    with pytest.raises(ValueError):
        ClaimsStore(fault="typo")


# ============================================================================
# 4. Policy documents: the M5 document 10 swap (spec section 7)
# ============================================================================

def test_m5_corpus_swaps_document_10():
    """The M5 bot searches ten documents, and document 10 is the M5 version (it says
    the assistant can look up your own claims), not the Day 3 one."""
    docs = load_m5_docs()
    assert len(docs) == 10
    assert "look up the status of your own claims" in " ".join(docs["10_contact_and_privacy"].split())
    assert "cannot see your claims" not in docs["10_contact_and_privacy"]


def test_day3_document_10_unchanged():
    """The Day 3 document 10 on disk still has its original wording, so the Day 3 bot
    and its tests are unaffected by M5."""
    assert "cannot see your claims" in (DOCS_DIR / "10_contact_and_privacy.md").read_text(encoding="utf-8")


def test_search_policy_returns_chunk_ids(store, retriever):
    """search_policy finds the right document for a clear query ('waiting period 182
    days' -> the waiting periods document first) and records the 3 chunk IDs it
    retrieved, which the retrieval checks will use later."""
    t = tool(build_tools("M-1021", store, retriever), "search_policy")
    msg = t.invoke({"type": "tool_call", "id": "x", "name": "search_policy",
                    "args": {"query": "waiting period 182 days"}})
    assert msg.artifact["doc_ids"][0] == "04_waiting_periods"
    assert len(msg.artifact["chunk_ids"]) == 3


# ============================================================================
# 4b. M5 chunking: tables by row, the exclusions list by item (changed 6 November)
# ============================================================================

@pytest.fixture(scope="module")
def m5_chunks():
    """The M5 chunks, keyed by chunk ID."""
    return {c.chunk_id: c.text for c in chunk_m5(load_m5_docs())}


def test_limits_table_is_one_chunk_per_row(m5_chunks):
    """The cover and limits table becomes six row chunks, one per treatment, and each
    row repeats the column headings so it makes sense on its own. The physiotherapy
    row holds the facts C03 and C19 needed: 50 per session, 10 sessions."""
    rows = [k for k in m5_chunks if k.startswith("02_cover_and_limits#2.")]
    assert len(rows) == 6
    physio = m5_chunks["02_cover_and_limits#2.3"]
    assert "Treatment: Physiotherapy" in physio and "50 per session" in physio and "10 sessions" in physio


def test_exclusions_list_is_one_chunk_per_item(m5_chunks):
    """The exclusions list becomes six item chunks. An item that runs over several
    lines in the document (fitness classes) is kept whole, and acupuncture has a
    chunk of its own (the fact C02 needed)."""
    items = {k: v for k, v in m5_chunks.items() if k.startswith("03_exclusions#2.")}
    assert len(items) == 6
    assert any("acupuncture" in v and "Alternative therapies" in v for v in items.values())
    assert any("pilates" in v and "run at a clinic" in v for v in items.values())


def test_only_tables_and_the_exclusions_list_are_split(m5_chunks):
    """Only the two tables and the exclusions list are split; the numbered lists in
    documents 04, 06 and 08 stay as paragraphs, as decided (6 November)."""
    split_docs = {k.split("#")[0] for k in m5_chunks if "." in k.split("#")[1]}
    assert split_docs == {"02_cover_and_limits", "03_exclusions", "05_pre_authorisation"}
    assert SPLIT_LIST_DOCS == {"03_exclusions"}


def test_other_chunks_identical_to_day3():
    """Every chunk that is not a table row or list item is exactly the chunk Day 3's
    paragraph chunker makes, with the same ID: the change is limited to what was decided."""
    docs = load_m5_docs()
    day3 = {c.chunk_id: c.text for c in chunk_docs(docs, mode="paragraph")}
    m5 = {c.chunk_id: c.text for c in chunk_m5(docs)}
    assert all(day3[k] == v for k, v in m5.items() if k in day3)
    assert set(day3) - set(m5) == {"02_cover_and_limits#2", "03_exclusions#2", "05_pre_authorisation#3"}


def test_split_chunks_are_found_by_the_agents_queries(retriever):
    """Queries the agent actually wrote in the first two full runs now return the chunk
    with the answer first: the physiotherapy row (C03, C19) and the acupuncture item (C02)."""
    assert retriever.retrieve("physiotherapy limit per session", 3)[0][0].chunk_id == "02_cover_and_limits#2.3"
    assert retriever.retrieve("acupuncture cover exclusions treatment limits", 3)[0][0].chunk_id == "03_exclusions#2.4"


def test_m5_document_04_states_the_day_0_rule():
    """The M5 version of document 04 says how days are counted (cover start date is
    day 0), with a worked example whose dates differ from the test conversations;
    the Day 3 document 04 on disk is unchanged."""
    m5 = " ".join(load_m5_docs()["04_waiting_periods"].split())
    assert "The date your cover began is day 0" in m5 and "1 March 2026" in m5
    assert "20 May" not in m5 and "7 July" not in m5          # not the dates W01 and W02 use
    assert "day 0" not in (DOCS_DIR / "04_waiting_periods.md").read_text(encoding="utf-8")


# ============================================================================
# 5. LangGraph wiring, with a scripted model in place of the LLM
# ============================================================================

def test_tool_round_trip_and_memory(store, retriever):
    """Two turns through the real graph. Turn 1: the model asks for HLH-021, the tool
    runs and the model replies. Turn 2 ("Why?"): the model is sent the whole
    conversation, including turn 1's tool result. That is the bot's memory, and what
    lets "Why?" refer to HLH-021. Also checks the system prompt is sent first. Rule R7."""
    model = ScriptedModel(script=[
        call("get_claim_status", {"claim_id": "HLH-021"}),
        AIMessage(content="HLH-021 was declined."),
        AIMessage(content="It was declined because of the waiting period."),
    ], seen=[])
    graph = build_graph(model, build_tools("M-1021", store, retriever))
    cfg = {"configurable": {"thread_id": "t1"}}
    graph.invoke({"messages": [HumanMessage("What's happening with HLH-021?")]}, cfg)
    graph.invoke({"messages": [HumanMessage("Why?")]}, cfg)
    last_input = model.seen[-1]                     # what the model was sent on turn 2
    assert any(isinstance(m, ToolMessage) and "WAITING_PERIOD" in m.text for m in last_input)
    assert "System" in type(last_input[0]).__name__


def test_tool_failure_reaches_model_as_error(retriever):
    """When the claims system is down, the bot does not crash: the tool's failure goes
    back to the model as an error message ("not responding"), and the model can still
    reply to the member. Rule R22, conversation C18."""
    model = ScriptedModel(script=[call("get_claim_status", {"claim_id": "HLH-024"}),
                                  AIMessage(content="I can't check claims right now.")], seen=[])
    graph = build_graph(model, build_tools("M-1024", ClaimsStore(fault="claims_store_unavailable"), retriever))
    out = graph.invoke({"messages": [HumanMessage("Has HLH-024 been paid?")]}, {"configurable": {"thread_id": "t2"}})
    err = [m for m in out["messages"] if isinstance(m, ToolMessage)][0]
    assert err.status == "error" and "not responding" in err.text
    assert out["messages"][-1].text == "I can't check claims right now."


def test_run_conversation_trace_record(retriever):
    """Playing golden conversation C14 (David types HLH021, then says yes) produces a
    trace record the checks can read: turn 1 has no tool call and the confirmation
    reply; turn 2 has one get_claim_status call with the tidied ID, its success
    status and whether the claim was found."""
    conv = next(c for c in load_golden() if c["conv_id"] == "C14")
    model = ScriptedModel(script=[AIMessage(content="Did you mean HLH-021?"),
                                  call("get_claim_status", {"claim_id": "HLH-021"}),
                                  AIMessage(content="HLH-021 was declined.")], seen=[])
    rec = run_conversation(conv, llm=model, retriever=retriever, tracing=False, save=False)
    assert rec["error"] is None and len(rec["turns"]) == 2
    assert rec["turns"][0]["tool_calls"] == [] and rec["turns"][0]["reply"] == "Did you mean HLH-021?"
    t2 = rec["turns"][1]["tool_calls"][0]
    assert (t2["name"], t2["args"], t2["status"], t2["artifact"]["found"]) == \
        ("get_claim_status", {"claim_id": "HLH-021"}, "success", True)


def test_bot_module_makes_no_api_call_at_import():
    """Importing bot.py does not create a model client, so these free tests (and
    anything else that imports the bot) never need an API key or cost money."""
    import chatbot.bot as b
    assert "ChatOpenAI(" not in inspect.getsource(b).split("def make_llm")[0]
