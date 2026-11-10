"""
chatbot/diagram.py: draws a UML sequence diagram of one saved conversation (Mermaid text).

Why this exists
---------------
To show how the bot and the tests actually behave on a real conversation: who
talks to whom on each turn, which tools were called with which arguments, what
came back, when the bot answered from memory, and what the two check layers
said about each reply. It is built from a saved trace record, so the picture is
what happened in that run, not an idealised flow.

Lifelines
---------
  Member            the scripted member turns from the golden set
  Portal session    the signed-in member (the tools are bound to them, rule R1)
  Agent             the LangGraph agent node: gpt-6-luna with the system prompt
  Memory            the conversation's checkpointer thread (earlier turns)
  Tool node         runs the tools the agent asks for
  Claims store      exact lookups, with the access check (own claims only)
  Policy retriever  the Day 3 TF-IDF retriever over the policy documents (RAG)
  Checks            after the run: the deterministic checks and the judge

Usage (from the repo root)
--------------------------
  python -m chatbot.diagram results/chatbot/<run_id> C01            prints the Mermaid text
  python -m chatbot.diagram results/chatbot/<run_id> C01 --out images/m5_sequence_C01.mmd

Render the .mmd with the Mermaid CLI (mmdc), the Mermaid Live Editor, or any
Markdown viewer that supports Mermaid (GitHub does). The report's version used the
project colours and evenly spaced lifelines from images/m5_sequence_mermaid_config.json:

  mmdc -i images/m5_sequence_W02.mmd -o images/m5_sequence_W02.svg -c images/m5_sequence_mermaid_config.json -b "#FCFCFB"

No API calls.

Change history:
  2026-11-10  v1  first version (M5 write-up, task T2). Lifeline names in capitals.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def clean(text: str, limit: int = 70, wrap: int = 45) -> str:
    """Text safe for a Mermaid message: no characters Mermaid treats specially, cut
    to a readable length and wrapped onto lines of about `wrap` characters. Messages
    between neighbouring lifelines are wrapped short, so the lifelines stay evenly spaced."""
    t = re.sub(r"[;#]", ",", " ".join(str(text).split())).replace('"', "'")
    t = t.replace("€", "EUR ").replace("—", "-").replace("–", "-")
    if len(t) > limit:
        t = t[:limit].rsplit(" ", 1)[0] + " ..."
    words, lines, line = t.split(), [], ""
    for w in words:
        if len(line) + len(w) > wrap and line:
            lines.append(line)
            line = w
        else:
            line = f"{line} {w}".strip()
    lines.append(line)
    return "<br/>".join(lines)


def tool_result_summary(call: dict) -> str:
    """A short description of what a tool returned."""
    res = str(call.get("result") or "")
    if call.get("status") != "success":
        return "error: " + res[:40]
    if call["name"] == "search_policy":
        chunks = re.findall(r"\[(\w+)#([\d.]+)\]", res)
        return "top chunks: " + ", ".join(f"{d.split('_', 1)[0]} part {n}" for d, n in chunks[:3]) if chunks else "no chunks"
    try:
        data = json.loads(res)
    except (json.JSONDecodeError, TypeError):
        return res[:40]
    if call["name"] == "get_claim_status":
        if not data.get("found"):
            return "not found (or not this member's)"
        c = data["claim"]
        return f"{c['claim_id']}: {c['status']}, paid {c['amount_paid']}, {c['decision_code']}"
    if call["name"] == "list_my_claims":
        claims = data.get("claims", [])
        return f"{len(claims)} claim(s): " + ", ".join(c.get("claim_id", "?") for c in claims)
    return res[:40]


def verdicts(run_dir: Path, conv_id: str) -> dict[int, str]:
    """For each turn, a one-line summary of the two check layers, if the run was scored."""
    out: dict[int, str] = {}
    ck, jd = run_dir / "checks.json", run_dir / "judge.json"
    text_ok = {}
    if ck.exists():
        for c in json.loads(ck.read_text(encoding="utf-8"))["conversations"]:
            if c["conv_id"] == conv_id:
                text_ok = {t["turn"]: t["passed"] for t in c["turns"]}
    judge = {}
    if jd.exists():
        for t in json.loads(jd.read_text(encoding="utf-8"))["turns"]:
            if t["conv_id"] == conv_id:
                judge[t["turn"]] = t["verdicts"]
    for n in set(text_ok) | set(judge):
        parts = []
        if n in text_ok:
            parts.append("text checks " + ("pass" if text_ok[n] else "FAIL"))
        if n in judge:
            fails = [c for c, v in judge[n].items() if v["verdict"] != "pass"]
            parts.append(f"judge: {len(judge[n]) - len(fails)} of {len(judge[n])} checks pass" +
                         (f" (fail: {', '.join(fails)})" if fails else ""))
        out[n] = "<br/>".join(parts)
    return out


def to_mermaid(record: dict, checks: dict[int, str] | None = None) -> str:
    """The Mermaid sequence diagram for one trace record."""
    checks = checks or {}
    member = record["member_id"]
    lines = ["sequenceDiagram", "    autonumber",
             "    actor M as MEMBER",
             "    participant S as PORTAL SESSION",
             "    participant A as AGENT (GPT-6-LUNA)",
             "    participant Mem as MEMORY",
             "    participant T as TOOL NODE",
             "    participant C as CLAIMS STORE",
             "    participant R as POLICY RETRIEVER",
             "    participant Q as CHECKS (AFTER THE RUN)",
             f"    S->>A: {clean(f'signed-in member {member}, tools bound to them', 80, 24)}"]
    for n, t in enumerate(record["turns"], start=1):
        lines.append(f"    Note over M,Q: TURN {n}")
        lines.append(f"    M->>A: {clean(t['user'], 200)}")
        if n > 1:
            lines.append(f"    Mem-->>A: {clean(f'turns 1 to {n - 1}, with their tool results', 80, 22)}")
        calls = t.get("tool_calls", [])
        if calls:
            lines.append("    loop until the model replies without asking for a tool")
            for c in calls:
                args = ", ".join(f"{v}" for v in (c.get("args") or {}).values())
                lines.append(f"        A->>T: {clean(c['name'] + '(' + args + ')', 90, 30)}")
                if c["name"] == "search_policy":
                    lines.append("        T->>R: search the policy chunks")
                    lines.append(f"        R-->>T: {clean(tool_result_summary(c), 80, 30)}")
                else:
                    lines.append(f"        T->>C: {clean(f'lookup for {member} only (access check)', 80, 22)}")
                    lines.append(f"        C-->>T: {clean(tool_result_summary(c), 80, 22)}")
                lines.append("        T-->>A: tool result")
            lines.append("    end")
        else:
            lines.append("    Note over A,Mem: no tool call: answers from memory")
        lines.append(f"    A->>M: {clean(t['reply'], 210)}")
        lines.append("    A->>Mem: save this turn")
        if n in checks:
            lines.append(f"    Note over R,Q: {checks[n]}")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    """Entry point for `python -m chatbot.diagram`."""
    ap = argparse.ArgumentParser(description="Mermaid sequence diagram of one saved M5 conversation.")
    ap.add_argument("run_dir", help="results/chatbot/<run_id>")
    ap.add_argument("conv_id", help="for example C01")
    ap.add_argument("--out", help="write the Mermaid text to this file instead of printing it")
    a = ap.parse_args(argv)
    run_dir = Path(a.run_dir)
    record = json.loads((run_dir / f"{a.conv_id}.json").read_text(encoding="utf-8"))
    text = to_mermaid(record, verdicts(run_dir, a.conv_id))
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
        print(f"Wrote {a.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
