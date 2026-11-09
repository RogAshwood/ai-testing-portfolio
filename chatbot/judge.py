"""
chatbot/judge.py: the M5 conversation judge. Scores behaviour the text checks cannot see.

What it does
------------
The deterministic checks (checks.py) cover facts and mechanics: tools, arguments,
key facts, absent terms. Some rules are about meaning instead: did the reply
promise payment, leak another member's claim, invent a fact, use plain language?
For those, a stronger model (gpt-6-sol, the same judge model as Days 3 and 4)
reviews each turn and answers pass or fail per check, with a one-sentence reason.

How one turn is judged
----------------------
  1. Build a packet of evidence for the turn (build_packet):
       - the conversation so far and the reply being judged
       - everything the bot's tools returned on this and earlier turns (claim
         records, lists, policy text), because the bot may answer from memory
       - the spec rules behind the checks, word for word (chatbot_spec.md)
       - for date turns, the correct answer worked out in code (date_check)
       - the golden set's note for the turn, if any
  2. Send the judge the rubric (datasets/judge_rubric.md): its general
     instructions plus the sections for the checks asked on this turn.
  3. Read the answer, which must be JSON with one pass/fail per check asked
     (parse_verdicts). A malformed answer is retried once, then recorded as
     judge_error. A judge_error is never counted as a pass.

The checks asked on a turn are the golden set's judge_checks for that turn plus
judge_checks_every_turn (plain_language, no_invented_fact). One call per turn
covers all of them; if calibration shows checks influencing each other, switch
to one call per check.

The judge does no arithmetic and never sees the golden set's expected answers
(key facts, absent terms): only the evidence the bot had, the rules, and for
dates the correct answer. It is not told what the deterministic checks found.

Outputs (in the run folder, next to checks.json)
------------------------------------------------
  judge.json         every verdict with its reason, plus tokens, cost and time
  judge_turns.csv    one row per turn and check, for a spreadsheet
  The summary combines both layers: a turn passes only if it passes the
  deterministic checks AND every judge check.

Calibration
-----------
  --seeded   judges datasets/judge_seeded_turns.json: real conversation contexts
             with a made-up reply whose verdict is known. Every one must be right.
Every result records the fingerprints of the rubric, the spec and the judge's
system prompt, so results from different judge versions are never mixed up.

Usage (from the repo root)
--------------------------
  python -m chatbot.judge --latest                       judge the newest run
  python -m chatbot.judge results/chatbot/<run_id>       judge one run
  python -m chatbot.judge --latest --limit 5             first 5 turns only (a cheap try)
  python -m chatbot.judge --seeded                       the seeded replies

This module calls the API (only judge_turn does). Cost is printed.

Change history:
  2026-11-06  v1  first version (M5 step 4).
  2026-11-09  v1.1  the packet gains a SESSION line (signed-in member and plan): the
                    first full run showed the judge calling "Essential Plus" an invented
                    fact because it could not see what the bot is told by the portal.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from bench.pricing import cost_usd

from .bot import RESULTS_DIR, ROOT, load_golden

JUDGE_MODEL = "gpt-6-sol"                     # same judge model as Days 3 and 4
RUBRIC_PATH = ROOT / "datasets" / "judge_rubric.md"
SPEC_PATH = ROOT / "datasets" / "chatbot_spec.md"
SEEDED_PATH = ROOT / "datasets" / "judge_seeded_turns.json"
GOLDEN_PATH = ROOT / "datasets" / "conversations_golden.json"
PLAN_NAME = "Essential Plus"    # the plan the bot is told about in chatbot/prompt.py (a test keeps them in step)


def fingerprint(text: str) -> str:
    """First 12 characters of the SHA-256 of a text, as used across the project."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# The rubric and the spec, read as data
# ---------------------------------------------------------------------------

def load_rubric(path: Path = RUBRIC_PATH) -> tuple[str, dict[str, str], str]:
    """Read the rubric file. Returns (instructions, {check id: section text}, fingerprint).

    The instructions are the section headed '## Instructions to the judge'.
    Each check is a section headed '### `check_id` ...' under '## Checks'; its
    whole text (question, pass if, fail if, examples) is what the judge is shown.
    """
    text = path.read_text(encoding="utf-8")
    m = re.search(r"^## Instructions to the judge\n(.*?)(?=^## )", text, flags=re.MULTILINE | re.DOTALL)
    if not m:
        raise ValueError("rubric has no '## Instructions to the judge' section")
    instructions = m.group(1).strip()
    checks_part = text.split("## Checks", 1)[1].split("\n## ", 1)[0]
    sections = re.split(r"^### ", checks_part, flags=re.MULTILINE)[1:]
    checks = {}
    for sec in sections:
        cid = re.match(r"`([a-z_]+)`", sec)
        if not cid:
            raise ValueError(f"rubric check heading without a `check_id`: {sec[:40]!r}")
        checks[cid.group(1)] = "### " + sec.strip()
    return instructions, checks, fingerprint(text)


def rule_ids(section: str) -> list[str]:
    """The spec rules named in a check's heading, for example '(R1, R2, R3)'."""
    heading = section.splitlines()[0]
    return re.findall(r"R\d+[a-c]?", heading)


def spec_rules(path: Path = SPEC_PATH) -> dict[str, str]:
    """{rule id: rule text} for every '- **Rn.** ...' bullet in the spec."""
    text = path.read_text(encoding="utf-8")
    rules = {}
    for m in re.finditer(r"^- \*\*(R\d+[a-c]?)\.\*\* (.*?)(?=^- \*\*R|^\S|\Z)", text, flags=re.MULTILINE | re.DOTALL):
        rules[m.group(1)] = " ".join(m.group(2).split())
    return rules


# ---------------------------------------------------------------------------
# The packet of evidence for one turn
# ---------------------------------------------------------------------------

def checks_for_turn(golden: dict, golden_turn: dict) -> list[str]:
    """The checks asked on a turn: its own judge_checks, then the every-turn checks."""
    every = golden.get("judge_checks_every_turn", [])
    return list(dict.fromkeys(golden_turn["judge_checks"] + every))      # keeps order, no repeats


def evidence(record_turns: list[dict], upto: int) -> list[str]:
    """Everything the bot's tools returned on turns 1..upto, one line per tool call."""
    lines = []
    for t in record_turns[:upto]:
        for c in t["tool_calls"]:
            lines.append(f"[turn {t['turn']}] {c['name']}({json.dumps(c['args'])}) -> {c['status']}: {c['result']}")
    return lines


def build_packet(golden_turn: dict, history: list[dict], reply: str, tool_lines: list[str],
                 checks: list[str], rubric_checks: dict[str, str], rules: dict[str, str],
                 member_id: str | None = None) -> dict:
    """Everything the judge needs for one turn, as a dict (see render_packet for the text).

    history     earlier turns: [{"member": ..., "assistant": ...}]
    reply       the reply being judged
    tool_lines  evidence() for this and earlier turns
    member_id   the signed-in member (from the portal session), shown with the plan name
                so the judge knows what the bot knows without a tool call
    """
    ids = sorted({r for c in checks for r in rule_ids(rubric_checks[c])},
                 key=lambda r: (int(re.sub(r"\D", "", r)), r))
    session = {"member_id": member_id, "plan": PLAN_NAME} if member_id else None
    return {"session": session, "history": history, "member": golden_turn["user"], "reply": reply,
            "evidence": tool_lines,
            "rules": {r: rules[r] for r in ids if r in rules}, "date_check": golden_turn.get("date_check"),
            "note": golden_turn.get("behaviour") or "", "checks": checks}


def render_packet(p: dict) -> str:
    """The packet as the text the judge reads."""
    out = []
    if p.get("session"):
        s = p["session"]
        out += ["SESSION (known to the assistant from the member portal, not from the member)",
                f"Signed-in member: {s['member_id']}; plan: {s['plan']}", ""]
    out += ["CONVERSATION SO FAR"]
    if not p["history"]:
        out.append("(this is the first turn)")
    for i, h in enumerate(p["history"], start=1):
        out += [f"Member (turn {i}): {h['member']}", f"Assistant (turn {i}): {h['assistant']}"]
    out += ["", "THIS TURN", f"Member: {p['member']}", f"Assistant (the reply to judge): {p['reply']}", "",
            "EVIDENCE: what the assistant's tools returned in this conversation"]
    out += p["evidence"] or ["(no tool was called in this conversation so far)"]
    out += ["", "RULES FROM THE SPECIFICATION"] + [f"{r}: {t}" for r, t in p["rules"].items()]
    if p["date_check"]:
        dc = p["date_check"]
        out += ["", "CORRECT ANSWER FOR THE DATES (worked out in code; the cover start date is day 0)",
                f"Cover start date the member gave: {dc['cover_start']}"]
        if dc.get("date"):
            where = "inside" if dc["inside_waiting_period"] else "outside"
            out.append(f"{dc['date']} is day {dc['day']}, {where} the waiting period")
        out.append(f"Covered from: {dc['covered_from']}")
    if p["note"]:
        out += ["", f"NOTE ON THIS TURN: {p['note']}"]
    out += ["", "CHECKS TO ANSWER: " + ", ".join(p["checks"])]
    return "\n".join(out)


def system_prompt(instructions: str, rubric_checks: dict[str, str], checks: list[str]) -> str:
    """The judge's instructions plus the rubric sections for the checks asked."""
    return instructions + "\n\n" + "\n\n".join(rubric_checks[c] for c in checks)


# ---------------------------------------------------------------------------
# Calling the judge and reading its answer
# ---------------------------------------------------------------------------

class JudgeAnswerError(ValueError):
    """The judge's answer was not in the required form."""


def parse_verdicts(text: str, checks: list[str]) -> dict[str, dict]:
    """Read the judge's JSON. Returns {check: {"verdict": "pass"|"fail", "reason": ...}}.

    Raises JudgeAnswerError if the text is not JSON, a check is missing or extra,
    or a verdict is anything other than pass or fail."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)                  # tolerate a code fence
    try:
        data = json.loads(t)
    except json.JSONDecodeError as e:
        raise JudgeAnswerError(f"not JSON: {e}") from None
    items = data.get("verdicts") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise JudgeAnswerError("no 'verdicts' list")
    out = {}
    for v in items:
        c, verdict = v.get("check"), str(v.get("verdict", "")).lower()
        if c not in checks:
            raise JudgeAnswerError(f"unexpected check {c!r}")
        if verdict not in ("pass", "fail"):
            raise JudgeAnswerError(f"{c}: verdict {v.get('verdict')!r} is not pass or fail")
        out[c] = {"verdict": verdict, "reason": str(v.get("reason", "")).strip()}
    missing = [c for c in checks if c not in out]
    if missing:
        raise JudgeAnswerError(f"missing checks {missing}")
    return out


def make_judge_llm(model: str = JUDGE_MODEL):
    """The judge model client. Same set-up as the bot's (Responses API, default temperature)."""
    from dotenv import load_dotenv
    from langchain_openai import ChatOpenAI
    load_dotenv(ROOT / ".env")
    return ChatOpenAI(model=model, use_responses_api=True, max_retries=2, timeout=90)


def judge_turn(llm, system: str, packet_text: str, checks: list[str], model: str = JUDGE_MODEL) -> dict:
    """Ask the judge about one turn. Tries twice; on a second bad answer every check
    is recorded as judge_error. Returns verdicts plus tokens, cost, time and the
    model version served."""
    tokens_in = tokens_out = 0
    served, error, verdicts = None, None, None
    start = time.perf_counter()
    for attempt in (1, 2):
        msg = llm.invoke([SystemMessage(system), HumanMessage(packet_text)])
        usage = msg.usage_metadata or {}
        tokens_in += usage.get("input_tokens", 0)
        tokens_out += usage.get("output_tokens", 0)
        served = (msg.response_metadata or {}).get("model_name") or served
        try:
            verdicts = parse_verdicts(msg.text, checks)
            error = None
            break
        except JudgeAnswerError as e:
            error = f"attempt {attempt}: {e}"
    if verdicts is None:
        verdicts = {c: {"verdict": "judge_error", "reason": error} for c in checks}
    return {"verdicts": verdicts, "error": error, "input_tokens": tokens_in, "output_tokens": tokens_out,
            "cost_usd": cost_usd(model, tokens_in, tokens_out), "latency_s": round(time.perf_counter() - start, 2),
            "model_served": served}


# ---------------------------------------------------------------------------
# Judging a run
# ---------------------------------------------------------------------------

def judge_run(run_dir: Path, llm=None, limit: int | None = None) -> dict:
    """Judge every reached turn of every conversation record in a run folder."""
    llm = llm or make_judge_llm()
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    convs = {c["conv_id"]: c for c in golden["conversations"]}
    instructions, rubric_checks, rubric_fp = load_rubric()
    rules = spec_rules()
    records = [json.loads(p.read_text(encoding="utf-8"))
               for p in sorted(run_dir.glob("*.json")) if p.stem in convs]
    results, n = [], 0
    for rec in records:
        conv = convs[rec["conv_id"]]
        for i, gt in enumerate(conv["turns"][:len(rec["turns"])]):
            if limit is not None and n >= limit:
                break
            n += 1
            checks = checks_for_turn(golden, gt)
            history = [{"member": t["user"], "assistant": t["reply"]} for t in rec["turns"][:i]]
            p = build_packet(gt, history, rec["turns"][i]["reply"], evidence(rec["turns"], i + 1),
                             checks, rubric_checks, rules, member_id=conv["member_id"])
            system = system_prompt(instructions, rubric_checks, checks)
            r = judge_turn(llm, system, render_packet(p), checks)
            results.append({"conv_id": rec["conv_id"], "turn": i + 1, "checks": checks, **r,
                            "system_prompt_fp": fingerprint(system)})
    meta = {"run": run_dir.name, "judge_model": JUDGE_MODEL, "rubric_fp": rubric_fp,
            "spec_fp": fingerprint(SPEC_PATH.read_text(encoding="utf-8")),
            "golden_fp": fingerprint(GOLDEN_PATH.read_text(encoding="utf-8")),
            "judged_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "limit": limit}
    return {"meta": meta, "turns": results, "summary": summarise(results, run_dir)}


def summarise(results: list[dict], run_dir: Path) -> dict:
    """Pass/fail counts per check, judge errors, cost, and the combined score with checks.json."""
    per_check: dict[str, dict] = {}
    for r in results:
        for c, v in r["verdicts"].items():
            per_check.setdefault(c, {"pass": 0, "fail": 0, "judge_error": 0})[v["verdict"]] += 1
    combined = None
    ck = run_dir / "checks.json"
    if ck.exists():
        det = {(c["conv_id"], t["turn"]): t["passed"]
               for c in json.loads(ck.read_text(encoding="utf-8"))["conversations"] for t in c["turns"]}
        judged = {(r["conv_id"], r["turn"]): all(v["verdict"] == "pass" for v in r["verdicts"].values())
                  for r in results}
        both = {k: det.get(k, False) and ok for k, ok in judged.items()}
        convs = sorted({k[0] for k in both})
        combined = {"turns_judged": len(both), "turns_passing_both": sum(both.values()),
                    "conversations": len(convs),
                    "conversations_passing_both": sum(all(v for k, v in both.items() if k[0] == c) for c in convs)}
    return {"per_check": per_check, "judge_errors": sum(1 for r in results if r["error"]),
            "cost_usd": round(sum(r["cost_usd"] or 0 for r in results), 4),
            "latency_s": round(sum(r["latency_s"] for r in results), 1), "combined": combined}


def write_outputs(result: dict, run_dir: Path) -> None:
    """Save judge.json and judge_turns.csv in the run folder."""
    (run_dir / "judge.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    with (run_dir / "judge_turns.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["conv_id", "turn", "check", "verdict", "reason"])
        for r in result["turns"]:
            for c, v in r["verdicts"].items():
                w.writerow([r["conv_id"], r["turn"], c, v["verdict"], v["reason"]])


def print_report(result: dict) -> None:
    s, m = result["summary"], result["meta"]
    print(f"Judge {m['judge_model']} on run {m['run']}  (rubric {m['rubric_fp']})")
    if s["combined"]:
        c = s["combined"]
        print(f"  both layers: {c['conversations_passing_both']}/{c['conversations']} conversations, "
              f"{c['turns_passing_both']}/{c['turns_judged']} turns pass")
    print(f"  judge errors {s['judge_errors']}  |  cost ${s['cost_usd']}  |  time {s['latency_s']} s\n")
    print(f"  {'check':36} pass  fail  error")
    for c, n in sorted(s["per_check"].items()):
        print(f"  {c:36} {n['pass']:>4}  {n['fail']:>4}  {n['judge_error']:>5}")
    print()
    for r in result["turns"]:
        for c, v in r["verdicts"].items():
            if v["verdict"] != "pass":
                print(f"  {v['verdict'].upper():5} {r['conv_id']} t{r['turn']} {c}: {v['reason']}")


# ---------------------------------------------------------------------------
# Seeded replies (calibration: every verdict is known in advance)
# ---------------------------------------------------------------------------

def judge_seeded(path: Path = SEEDED_PATH, llm=None) -> dict:
    """Judge every seeded reply and compare with its known verdict.

    Each seed is a real conversation context (history and tool evidence from a
    saved run) with a made-up reply. The judge is asked all of that turn's checks,
    as in a normal run, but only the seeded check is scored."""
    llm = llm or make_judge_llm()
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    convs = {c["conv_id"]: c for c in golden["conversations"]}
    instructions, rubric_checks, rubric_fp = load_rubric()
    rules = spec_rules()
    seeds = json.loads(path.read_text(encoding="utf-8"))["seeds"]
    out = []
    for s in seeds:
        gt = convs[s["conv_id"]]["turns"][s["turn"] - 1]
        checks = list(dict.fromkeys(checks_for_turn(golden, gt) + [s["check"]]))
        p = build_packet(gt, s["history"], s["reply"], s["evidence"], checks, rubric_checks, rules,
                         member_id=convs[s["conv_id"]]["member_id"])
        r = judge_turn(llm, system_prompt(instructions, rubric_checks, checks), render_packet(p), checks)
        got = r["verdicts"][s["check"]]
        out.append({"seed_id": s["seed_id"], "check": s["check"], "expected": s["expected"],
                    "got": got["verdict"], "reason": got["reason"], "correct": got["verdict"] == s["expected"],
                    "cost_usd": r["cost_usd"]})
    return {"meta": {"judge_model": JUDGE_MODEL, "rubric_fp": rubric_fp, "seeds_fp":
                     fingerprint(path.read_text(encoding="utf-8")),
                     "judged_at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
            "seeds": out, "correct": sum(o["correct"] for o in out), "total": len(out),
            "cost_usd": round(sum(o["cost_usd"] or 0 for o in out), 4)}


def main(argv=None) -> int:
    """Entry point for `python -m chatbot.judge`."""
    ap = argparse.ArgumentParser(description="Judge a saved M5 run, or the seeded replies.")
    ap.add_argument("run_dir", nargs="?", help="results/chatbot/<run_id>")
    ap.add_argument("--latest", action="store_true", help="judge the newest run folder")
    ap.add_argument("--limit", type=int, help="judge only the first N turns (a cheap try)")
    ap.add_argument("--seeded", action="store_true", help="judge datasets/judge_seeded_turns.json")
    a = ap.parse_args(argv)

    if a.seeded:
        res = judge_seeded()
        out = RESULTS_DIR.parent / "chatbot_judge_seeded"          # outside results/chatbot, so --latest never picks it
        out.mkdir(parents=True, exist_ok=True)
        f = out / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json")
        f.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Seeded replies: {res['correct']}/{res['total']} judged correctly  |  cost ${res['cost_usd']}  "
              f"(rubric {res['meta']['rubric_fp']})")
        for o in res["seeds"]:
            if not o["correct"]:
                print(f"  WRONG {o['seed_id']} {o['check']}: expected {o['expected']}, got {o['got']}: {o['reason']}")
        print(f"\nWrote {f}")
        return 0 if res["correct"] == res["total"] else 1

    if a.latest:
        runs = sorted(p for p in RESULTS_DIR.iterdir() if p.is_dir() and p.name[:1].isdigit())
        if not runs:
            ap.error(f"no runs in {RESULTS_DIR}")
        run_dir = runs[-1]
    elif a.run_dir:
        run_dir = Path(a.run_dir)
    else:
        ap.error("give a run folder, --latest or --seeded")
    res = judge_run(run_dir, limit=a.limit)
    write_outputs(res, run_dir)
    print_report(res)
    print(f"\nWrote {run_dir / 'judge.json'} and {run_dir / 'judge_turns.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
