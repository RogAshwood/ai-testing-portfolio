"""chatbot: the M5 multi-step member-help bot (Harbourlight Health).

Modules
- claims.py   claims store behind the claim tools; access check and fault injection
- policy.py   the Day 3 retriever over the M5 corpus (documents 01 to 09 + M5 document 10)
- tools.py    search_policy, get_claim_status, list_my_claims, bound to the session's member
- prompt.py   the M5 system prompt (Day 3 conduct rules + spec tool rules)
- bot.py      the LangGraph agent and run_conversation(), which writes the trace record
- run.py      the command line: python -m chatbot.run --conv C01
- checks.py   the deterministic checks: python -m chatbot.checks --latest
- judge.py    the conversation judge (gpt-6-sol) for behaviour checks: python -m chatbot.judge --latest

How the pieces fit: run.py asks bot.py to play a golden conversation; bot.py
builds the LangGraph agent with prompt.py's instructions and tools.py's tools;
the tools use claims.py (exact lookups) and policy.py (the Day 3 retriever).
Every run is saved as a trace record in results/chatbot/, which checks.py reads
and scores against the golden conversations; judge.py then reviews the
behaviour the text checks cannot see, using datasets/judge_rubric.md.

Test basis: datasets/chatbot_spec.md. Oracle: datasets/conversations_golden.json.
"""
