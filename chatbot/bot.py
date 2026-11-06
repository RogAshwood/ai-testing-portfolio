"""
chatbot/bot.py: the M5 member-help bot (the system under test) and the code that
plays a golden conversation through it.

How the bot works
-----------------
The bot is a small LangGraph "graph": two steps (nodes) that hand over to each
other until the bot has a reply for the member.

    member message
         |
         v
    +---------+   the model asked for a tool?   +---------+
    |  agent  | -------------- yes -----------> |  tools  |
    | (model) | <------ tool results ---------- | (code)  |
    +---------+                                 +---------+
         |
         no: the model wrote a reply
         v
    reply to the member (end of the turn)

  agent  One call to the model (gpt-6-luna). It is given the system prompt, the
         whole conversation so far and the list of tools, and it either asks for
         one or more tool calls or writes the reply.
  tools  Runs the tools the model asked for (search the policy documents, look
         up a claim, list the member's claims) and passes the results back to
         the agent, which then decides again.

Memory: a "checkpointer" stores the conversation's messages under a thread ID,
one thread per conversation. On the next turn the agent is given everything
said so far, which is how "Why was it declined?" can refer to HLH-021.

What this file contains
-----------------------
  make_llm()           creates the model client (the only part that costs money)
  build_graph()        wires the agent and tools steps into the graph above
  run_conversation()   plays one golden conversation's scripted member turns
                       through a fresh bot and returns a trace record
  load_golden()        reads the golden conversations file
  _tool_error()        what the model is told when the claims system is down
  _langfuse_handler()  optional connection to Langfuse, for viewing traces
  _turn_record()       turns one turn's raw messages into a readable summary

The trace record
----------------
run_conversation() writes results/chatbot/<run_id>/<conv_id>.json. For every
turn it holds the member's message, each tool the bot called (with arguments,
whether it worked, and what came back), the bot's reply, tokens, cost and time.

Cached tokens: OpenAI automatically reuses its processing of a long opening
part of a request that it has seen recently (here the system prompt and the
tool descriptions). This is "prompt caching". It makes calls faster and the
cached input tokens cheaper, but the reply is still generated fresh every time,
so it cannot make two runs give the same answer. The record counts the cached
input tokens (cached_input_tokens) so this can be seen. cost_usd is worked out
at the full input price, so it slightly overstates the real cost.
The checks read this file. They never read Langfuse, so the tests work the
same with or without a Langfuse account.

Nothing in this file calls the API when it is imported. Only make_llm() creates
a client, and only run_conversation() uses it.

Change history:
  2026-11-05  v1  first version (M5).
  2026-11-05  v1.1  comments and docstrings expanded; some variable names made clearer.
                    Behaviour unchanged (same 27 tests pass).
  2026-11-06  v1.2  trace record counts cached input tokens per turn and in the totals.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from bench.pricing import cost_usd

from .claims import ClaimsStore, ClaimsStoreUnavailable
from .policy import build_m5_retriever
from .prompt import SYSTEM_PROMPT
from .tools import build_tools

ROOT = Path(__file__).resolve().parent.parent          # the repo folder
RESULTS_DIR = ROOT / "results" / "chatbot"            # where trace records are saved
AGENT_MODEL = "gpt-6-luna"     # same cheap model as Days 2 to 4
RECURSION_LIMIT = 12           # safety stop: at most 12 agent/tools steps in one turn
                               # (about 5 rounds of tool calls), so a confused model
                               # cannot loop forever and run up cost


# ---------------------------------------------------------------------------
# The model
# ---------------------------------------------------------------------------

def make_llm(model: str = AGENT_MODEL):
    """Create the client for the agent model.

    - Reads OPENAI_API_KEY from .env.
    - Uses OpenAI's Responses API, the same API the Day 3 bot uses.
    - Temperature is not set, so the provider default applies (as agreed for M5).
    - max_retries and timeout stop one slow or failed call from hanging a run.

    Creating the client costs nothing; cost starts when the graph calls it.
    The imports are inside the function so that importing this file (for
    example in the free tests) needs no API key.
    """
    from dotenv import load_dotenv
    from langchain_openai import ChatOpenAI
    load_dotenv(ROOT / ".env")
    return ChatOpenAI(model=model, use_responses_api=True, max_retries=2, timeout=60)


# ---------------------------------------------------------------------------
# The graph (the bot itself)
# ---------------------------------------------------------------------------

def _tool_error(e: ClaimsStoreUnavailable) -> str:
    """What the model is told when the claims system is down (golden conversation C18).

    LangGraph's tools step calls this when a tool raises ClaimsStoreUnavailable.
    The text below goes back to the model as the tool's result, marked as an
    error, just as a real outage would look. The model should then tell the
    member it can't check claims right now (rule R22).

    The type hint on `e` matters: LangGraph only catches the exception type
    named here. Any other error inside a tool is a bug in our code, so it is
    not hidden from the model; it stops the run and shows up in the trace.
    """
    return "Error: the claims system is not responding. No claim information is available right now."


def build_graph(llm, tools, checkpointer=None):
    """Wire the agent step and the tools step into a graph and return it, ready to run.

    llm           the model client from make_llm(), or a scripted stand-in in the tests
    tools         the member's tools from build_tools()
    checkpointer  where conversation memory is kept; a new in-memory store if omitted

    Each call to graph.invoke() is one member turn: the graph loops agent ->
    tools -> agent until the model replies without asking for a tool.
    """
    # Tell the model which tools exist and what arguments they take, so it can
    # ask for them. The model never runs a tool itself; it only asks.
    llm_with_tools = llm.bind_tools(tools)

    def agent(state: MessagesState):
        # One model call. The system prompt is put in front of the conversation
        # every time rather than stored in memory, so it is always first and
        # always the current version from prompt.py.
        response = llm_with_tools.invoke([SystemMessage(SYSTEM_PROMPT)] + state["messages"])
        # The reply (or tool request) is added to the conversation's messages.
        return {"messages": [response]}

    g = StateGraph(MessagesState)          # the graph's state is the list of messages
    g.add_node("agent", agent)
    g.add_node("tools", ToolNode(tools, handle_tool_errors=_tool_error))   # runs requested tools
    g.add_edge(START, "agent")                      # each turn starts with the model
    g.add_conditional_edges("agent", tools_condition)   # tool requested -> "tools", else end the turn
    g.add_edge("tools", "agent")                    # after the tools, back to the model
    return g.compile(checkpointer=checkpointer or InMemorySaver())


# ---------------------------------------------------------------------------
# Optional Langfuse tracing
# ---------------------------------------------------------------------------

def _langfuse_handler(enabled: bool):
    """Return a Langfuse "callback handler" if tracing is wanted and possible, otherwise None.

    What it is: a callback handler is an object LangChain/LangGraph notifies at
    every step (model call started, tool called, result returned). Langfuse's
    handler forwards those notifications to your Langfuse project, where you
    can view each conversation as a timeline. It only observes; it does not
    change what the bot does.

    When it returns None (no tracing, and the run carries on normally):
      - enabled is False (the run was started with --no-tracing), or
      - LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY is not set in .env.

    Langfuse also reads LANGFUSE_BASE_URL from .env; if that is missing it
    uses https://cloud.langfuse.com, which is the EU region.

    The checks never use Langfuse. They read the local trace record, so a run
    without Langfuse is scored exactly the same as a run with it.
    """
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    if not (enabled and os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")):
        return None
    from langfuse.langchain import CallbackHandler     # imported only when needed
    return CallbackHandler()


# ---------------------------------------------------------------------------
# Running a golden conversation
# ---------------------------------------------------------------------------

def _turn_record(n: int, user: str, new_msgs: list, latency: float, model: str) -> dict:
    """Summarise one turn for the trace record.

    new_msgs is everything the graph added during this turn, in order. It holds
    two kinds of message:
      - AIMessage: one per model call. Either a request for tools (tool_calls)
        or the final reply (no tool_calls). Also carries token counts and the
        model version the API served.
      - ToolMessage: one per tool result, linked to its request by tool_call_id.
        status is "success" or "error"; artifact holds the extra detail the tool
        saved for us (for search_policy, the chunk IDs and scores retrieved).

    Returns a dict with the member's message, every tool call (name, arguments,
    status, artifact and the start of the result text), the reply, the search
    queries the model wrote, and tokens (including cached input tokens), cost
    and time for the turn.
    """
    # Index the tool results by the ID of the request they answer.
    results = {m.tool_call_id: m for m in new_msgs if isinstance(m, ToolMessage)}

    calls, reply = [], ""
    llm_calls, tokens_in, tokens_out, tokens_cached, served = 0, 0, 0, 0, None
    for m in new_msgs:
        if not isinstance(m, AIMessage):
            continue
        # One model call: add up its tokens and note which model version answered.
        llm_calls += 1
        usage = m.usage_metadata or {}
        tokens_in += usage.get("input_tokens", 0)
        tokens_out += usage.get("output_tokens", 0)
        # Input tokens the provider served from its prompt cache (see the top of the file).
        # LangChain reports them as "cache_read", or with a service-tier prefix such as
        # "priority_cache_read", so any key ending in cache_read is counted.
        details = usage.get("input_token_details") or {}
        tokens_cached += sum(v or 0 for k, v in details.items() if k.endswith("cache_read"))
        meta = m.response_metadata or {}
        served = meta.get("model_name") or meta.get("model") or served
        # Pair each tool request with its result.
        for tc in m.tool_calls:
            r = results.get(tc["id"])
            calls.append({"name": tc["name"], "args": tc["args"],
                          "status": r.status if r else "missing",      # "missing" = no result came back
                          "artifact": r.artifact if r else None,
                          "result": (r.text if r else "")[:2000]})    # first 2,000 characters
        # A model call with no tool requests is the reply to the member.
        if not m.tool_calls:
            reply = m.text

    return {"turn": n, "user": user, "reply": reply, "tool_calls": calls,
            "search_queries": [c["args"].get("query") for c in calls if c["name"] == "search_policy"],
            "llm_calls": llm_calls, "input_tokens": tokens_in, "output_tokens": tokens_out,
            "cached_input_tokens": tokens_cached,
            "cost_usd": cost_usd(model, tokens_in, tokens_out),      # None if the model has no price
            "latency_s": round(latency, 3), "model_served": served}


def run_conversation(conv: dict, llm=None, retriever=None, model: str = AGENT_MODEL,
                     tracing: bool = True, run_id: str | None = None, save: bool = True) -> dict:
    """Play one golden conversation through a fresh bot and return its trace record.

    In plain terms: this is the test driver. It acts as the member, sending the
    scripted messages from the golden file one at a time, and records what the
    bot did on each turn. It does not judge the bot; the checks do that later
    by reading the record this function returns (and saves).

    conv       one conversation from conversations_golden.json (member, fault, turns)
    llm        the model client; created with make_llm() if not given. The free
               tests pass a scripted stand-in here, so no API is called
    retriever  the policy-document retriever; built if not given (reused across
               conversations by run.py, because building it takes a moment)
    tracing    also send the run to Langfuse, if keys are set
    run_id     groups the conversations of one run in the same results folder
    save       write the record to results/chatbot/<run_id>/<conv_id>.json

    Steps:
      1. Build a fresh bot for this member: a claims store (faulted if the
         conversation says so), the member's tools, and the graph.
      2. Give the conversation its own thread ID, so its memory is separate
         from every other conversation.
      3. For each scripted member message: send it, wait for the reply, and
         keep only the messages added in this turn for the trace.
      4. If anything fails, record the error and stop this conversation, so
         one broken conversation doesn't stop a run of 20.
      5. Add totals (calls, tokens, cost, time), save the record, return it.
    """
    # 1. A fresh bot for this member.
    llm = llm or make_llm(model)
    retriever = retriever or build_m5_retriever()
    store = ClaimsStore(fault=conv.get("fault"))                # fault=None normally; C18 is faulted
    tools = build_tools(conv["member_id"], store, retriever)    # member bound in here (rule R1)
    graph = build_graph(llm, tools)

    # 2. A unique thread ID: run time + conversation + a random suffix.
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    thread = f"{run_id}-{conv['conv_id']}-{uuid.uuid4().hex[:6]}"
    handler = _langfuse_handler(tracing)
    config = {
        "configurable": {"thread_id": thread},          # which memory to use
        "recursion_limit": RECURSION_LIMIT,              # safety stop per turn
        "callbacks": [handler] if handler else [],       # Langfuse, if on
        "metadata": {"langfuse_session_id": thread,      # groups the turns as one Langfuse session
                     "langfuse_tags": ["m5", conv["conv_id"]]},
        "run_name": f"M5 {conv['conv_id']}",             # label shown in Langfuse
    }

    # 3. Play the scripted member turns.
    turns, error = [], None
    for n, t in enumerate(conv["turns"], start=1):
        # How many messages memory held before this turn, so we can pick out the new ones.
        before = len(graph.get_state(config).values.get("messages", []))
        start = time.perf_counter()
        try:
            state = graph.invoke({"messages": [HumanMessage(t["user"])]}, config)
        except Exception as e:
            # 4. Record the error and stop this conversation (later turns depend on this one).
            error = f"turn {n}: {type(e).__name__}: {e}"
            break
        # before + 1 skips the member's own message, which is already in t["user"].
        turns.append(_turn_record(n, t["user"], state["messages"][before + 1:],
                                  time.perf_counter() - start, model))

    if handler:
        # Langfuse sends in the background; flush makes sure everything is sent before we finish.
        from langfuse import get_client
        get_client().flush()

    # 5. The record the checks will read.
    record = {
        "conv_id": conv["conv_id"], "member_id": conv["member_id"], "fault": conv.get("fault"),
        "stretch": conv.get("stretch", False), "run_id": run_id, "thread_id": thread,
        "model": model,
        "model_served": next((x["model_served"] for x in turns if x["model_served"]), None),   # as in M1
        "langfuse": bool(handler), "error": error, "turns": turns,
        "totals": {k: round(sum((x[k] or 0) for x in turns), 6)
                   for k in ("llm_calls", "input_tokens", "cached_input_tokens", "output_tokens",
                             "cost_usd", "latency_s")},
    }
    if save:
        out = RESULTS_DIR / run_id
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{conv['conv_id']}.json").write_text(json.dumps(record, indent=2, ensure_ascii=False),
                                                     encoding="utf-8")
    return record


def load_golden(path: Path = ROOT / "datasets" / "conversations_golden.json") -> list[dict]:
    """The golden conversations (scored and stretch), as a list of dicts."""
    return json.loads(path.read_text(encoding="utf-8"))["conversations"]
