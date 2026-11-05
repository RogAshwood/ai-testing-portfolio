"""
chatbot/tools.py: the tools the M5 agent can ask for.

What a "tool" is here
---------------------
A tool is an ordinary Python function that the model is allowed to ask us to
run. The model sees each tool's name, its description (the function's
docstring) and its arguments, and decides when to ask for it. The model never
runs code itself: LangGraph's tools step runs the function and hands the
result back. So the docstrings below are not just comments: they are the
instructions the model reads when choosing a tool.

  search_policy(query)        search the plan documents (the Day 3 retriever)
  get_claim_status(claim_id)  one of the signed-in member's own claims
  list_my_claims()            the signed-in member's claims, short form
  request_callback(...)       stretch (R18 to R20): built later, not offered yet

Why the tools are built per member
----------------------------------
build_tools() is called once per conversation with the signed-in member's ID.
The functions inside it "remember" that ID (a Python closure), so none of the
tools has a member argument. The model therefore has no way to ask for
another member's claims, whatever the member types (rule R1). The access check
itself is in claims.py.

Two outputs per tool
--------------------
Each tool returns a pair (content, artifact). LangChain calls this
response_format="content_and_artifact":
  content   the text the model reads (for example the claim record as JSON)
  artifact  extra detail kept for the trace record but NOT shown to the model
            (for example which chunk IDs were retrieved, and their scores)
The artifact is what lets the checks see exactly what each tool did.

If the claims system is down, the claim tools raise ClaimsStoreUnavailable;
bot.py turns that into an error message for the model (C18, rule R22).

Change history:
  2026-11-05  v1  first version (M5).
  2026-11-05  v1.1  comments expanded; no code change.
"""
from __future__ import annotations

import json

from langchain_core.tools import StructuredTool

from .claims import ClaimsStore
from .policy import DEFAULT_K

# The one "not found" answer, used for a claim that belongs to someone else AND
# for one that doesn't exist, so the two cases can't be told apart (rule R3).
NOT_FOUND = {"found": False,
             "message": "No claim with that ID on this member's account. Claim IDs look like HLH-012."}


def build_tools(member_id: str, store: ClaimsStore, retriever, k: int = DEFAULT_K) -> list:
    """Return the three tools for one member's conversation.

    member_id  the signed-in member, from the session (never from the chat)
    store      the claims store (possibly faulted, for C18)
    retriever  the Day 3 TF-IDF retriever over the M5 corpus
    k          chunks returned per search; 3, as on Day 3
    """

    def search_policy(query: str):
        """Search the Essential Plus plan documents. Use for any question about what
        the plan covers, its limits, rules, exclusions, waiting periods, deadlines,
        how to claim, appeals or contact details. Write a short query with the key
        terms, for example 'waiting period 182 days' or 'physiotherapy limit per session'."""
        # The query is written by the model, not typed by the member (agentic RAG).
        chunks, scores = retriever.retrieve(query, k)
        # content: the chunk texts, each labelled with its ID so the model can tell them apart.
        text = "\n\n".join(f"[{c.chunk_id}]\n{c.text}" for c in chunks)
        # artifact: what was retrieved, for the retrieval checks (hit rate, source rank).
        artifact = {"query": query, "chunk_ids": [c.chunk_id for c in chunks],
                    "doc_ids": [c.doc_id for c in chunks], "scores": [round(s, 4) for s in scores]}
        return text, artifact

    def get_claim_status(claim_id: str):
        """Look up one of the signed-in member's own claims by its ID, in the standard
        form HLH- followed by three digits (for example HLH-012). Returns the claim's
        status, decision code, amount paid, last update and next step, or 'not found'."""
        record = store.get(member_id, claim_id)          # None unless it is this member's claim
        result = {"found": True, "claim": record} if record else NOT_FOUND
        return json.dumps(result), {"claim_id": claim_id, "found": record is not None}

    def list_my_claims():
        """List the signed-in member's own claims (ID, treatment, date, status). Use when
        the member asks about 'my claim' without an ID, or does not know the ID."""
        claims = store.list_for(member_id)
        return json.dumps({"claims": claims}), {"claim_ids": [c["claim_id"] for c in claims]}

    # Wrap each function as a LangChain tool. The name, description and arguments
    # the model sees are taken from the function's name, docstring and parameters.
    return [StructuredTool.from_function(f, response_format="content_and_artifact")
            for f in (search_policy, get_claim_status, list_my_claims)]


TOOL_NAMES = ["search_policy", "get_claim_status", "list_my_claims"]
