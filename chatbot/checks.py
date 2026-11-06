"""
chatbot/checks.py: the deterministic checks for M5. Scores a saved run against the golden set.

What it does
------------
After `python -m chatbot.run` has saved trace records (one JSON file per
conversation in results/chatbot/<run_id>/), this module compares each turn of
each record with what conversations_golden.json expects for that turn. Every
check here is plain code: no model is called, so it is free and gives the same
answer every time it is run on the same record.

The checks, per turn
--------------------
  required tools    each required tool was called on this turn, with the
                    expected arguments (args null in the golden set = any)
  forbidden tools   none of the forbidden tools was called (a hard fail)
  unexpected tools  any of these that was called is counted, not failed
                    (for example a policy search when only a status was asked)
  key facts         each key fact appears in the reply ('a|b' = either one)
  absent terms      none of the absent terms appears in the reply
  tool errors       no tool failed, except where the conversation's fault
                    makes the failure the point of the test (C18)
  retrieval         where some of the turn's key facts come from a policy
                    document and the bot searched, did the text it got back
                    contain those facts? (reported for information: the agentic
                    RAG measure; see "Retrieval hits" below)

Results for a required tool
---------------------------
  pass          called on this turn with the expected arguments
  pass_earlier  search_policy only: not called on this turn, but an earlier
                search in the conversation already returned this turn's facts,
                so the answer can be grounded in what the bot has in memory
                (C01 turn 2 in the first full run). Counts as a pass, noted.
  met_earlier   called the same way on an earlier turn but not this one, and
                that does not count: for the claim tools (claim data should be
                looked up fresh), or for a search whose earlier results did not
                contain this turn's facts. A fail.
  wrong_args    called on this turn, but with different arguments
  missing       not called at all so far

Retrieval hits
--------------
A turn's "document facts" are its key facts that appear in one of its expected
policy documents. A search on the turn is a hit if the text it returned
contains every document fact (any one alternative of each). This is stricter
than "a chunk of the right document came back": in C03 turn 2 of the first full
run, two chunks of document 02 came back but not the table with the 50 per
session limit, so it is a miss.

Behaviour checks named in judge_checks (no_promise, no_leak, ...) are listed in
the output but not scored here: the conversation judge does those in step 4.

Matching text
-------------
Key facts and absent terms are matched as case-insensitive substrings after
normalising both sides: curly quotes made straight, hyphens and dashes treated
as spaces ("waiting-period" matches "waiting period"), the euro sign removed and
whitespace collapsed.

Usage (from the repo root)
--------------------------
  python -m chatbot.checks results/chatbot/20261105T132117Z     score one run
  python -m chatbot.checks --latest                             score the newest run

Writes checks.json (everything) and checks_turns.csv (one row per turn) into
the run's folder, and prints a summary with the failures.

Change history:
  2026-11-05  v1  first version (M5 step 3).
  2026-11-06  v1.1  after the first full run's error analysis: pass_earlier for
                    search_policy when an earlier search returned this turn's
                    facts (met_earlier is now always a fail); retrieval hits
                    measured on the facts in the returned text, not document IDs.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

from .bot import RESULTS_DIR, load_golden
from .policy import load_m5_docs


# ---------------------------------------------------------------------------
# Text matching
# ---------------------------------------------------------------------------

def norm(text: str) -> str:
    """Normalise text for matching: lower case, straight quotes, hyphens and dashes
    as spaces, no euro sign, single spaces. Applied to both the reply and the
    term being looked for."""
    t = text.lower()
    t = t.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    t = re.sub(r"[-‐‑‒–—]", " ", t)     # hyphen and the dash family
    t = t.replace("€", "").replace("**", "")                # euro sign, Markdown bold
    return " ".join(t.split())


def contains(reply: str, term: str) -> bool:
    """True if any alternative in term ('a|b|c') appears in the reply."""
    r = norm(reply)
    return any(norm(alt) in r for alt in term.split("|"))


# ---------------------------------------------------------------------------
# Tool calls
# ---------------------------------------------------------------------------

def _args_match(expected: dict | None, actual: dict) -> bool:
    """Do the actual tool arguments match the expected ones?
    None means any arguments are fine. A claim_id is compared after trimming
    and upper-casing, the same as the claims store does (rule R6a)."""
    if expected is None:
        return True
    norm_args = lambda a: {k: (v.strip().upper() if k == "claim_id" and isinstance(v, str) else v)
                           for k, v in a.items()}
    return norm_args(expected) == norm_args(actual)


def check_required(req: dict, this_turn: list[dict], earlier: list[dict],
                   doc_facts: list[str] | None = None) -> str:
    """Result for one required tool: pass, pass_earlier, met_earlier, wrong_args or
    missing (see top of file).

    doc_facts are this turn's key facts that come from a policy document. They
    decide whether an earlier search grounds this turn (pass_earlier) or not."""
    same_name = [c for c in this_turn if c["name"] == req["name"]]
    if any(_args_match(req["args"], c["args"]) for c in same_name):
        return "pass"
    if same_name:
        return "wrong_args"
    earlier_same = [c for c in earlier if c["name"] == req["name"] and _args_match(req["args"], c["args"])]
    if not earlier_same:
        return "missing"
    if req["name"] == "search_policy" and doc_facts and facts_in_text(doc_facts, _results_text(earlier_same)):
        return "pass_earlier"
    return "met_earlier"


def _results_text(calls: list[dict]) -> str:
    """The text the given tool calls returned to the model, joined together."""
    return " ".join(c.get("result", "") for c in calls)


def facts_in_text(facts: list[str], text: str) -> bool:
    """True if every fact ('a|b' = either) appears in the text."""
    return all(contains(text, f) for f in facts)


_DOCS: dict[str, str] | None = None


def doc_facts_for(exp: dict) -> list[str]:
    """The turn's key facts that appear in one of its expected policy documents
    (fact_sources entries 'doc:...'). Facts from the claim record or the spec are
    left out, because a policy search could never return them."""
    global _DOCS
    if _DOCS is None:
        _DOCS = load_m5_docs()                      # the M5 corpus, loaded once
    docs = [s.split(":", 1)[1] for s in exp["fact_sources"] if s.startswith("doc:")]
    text = " ".join(_DOCS.get(d, "") for d in docs)
    return [f for f in exp["key_facts"] if contains(text, f)]


# ---------------------------------------------------------------------------
# Scoring one turn and one conversation
# ---------------------------------------------------------------------------

def check_turn(exp: dict, got: dict | None, earlier_calls: list[dict], fault: str | None) -> dict:
    """Compare one turn of the trace record (got) with the golden turn (exp).

    Returns a dict with each check's result and a list of `failures` (the hard
    fails, in plain words). `passed` is True when there are no hard fails.
    met_earlier is not a hard fail; it is listed under `notes` instead.
    """
    if got is None:                                  # the conversation stopped before this turn
        return {"passed": False, "failures": ["turn not reached (run error)"], "notes": [],
                "required": {}, "forbidden_called": [], "unexpected_called": [],
                "missing_facts": [], "absent_found": [], "tool_errors": [], "retrieval_hit": None,
                "judge_checks": exp["judge_checks"]}

    calls = got["tool_calls"]
    names = [c["name"] for c in calls]
    failures, notes = [], []

    doc_facts = doc_facts_for(exp)

    # Required tools
    required = {}
    for req in exp["required_tools"]:
        label = req["name"] + (f"({req['args']})" if req["args"] else "")
        result = check_required(req, calls, earlier_calls, doc_facts)
        required[label] = result
        if result == "pass_earlier":
            notes.append(f"{label} not called this turn; an earlier search already returned this turn's facts")
        elif result != "pass":
            failures.append(f"required {label}: {result}")

    # Forbidden and unexpected tools
    forbidden_called = sorted(set(names) & set(exp["forbidden_tools"]))
    failures += [f"forbidden tool called: {n}" for n in forbidden_called]
    unexpected_called = sorted(set(names) & set(exp["unexpected_tools"]))
    notes += [f"unexpected tool called (counted, not failed): {n}" for n in unexpected_called]

    # Reply text
    missing_facts = [k for k in exp["key_facts"] if not contains(got["reply"], k)]
    failures += [f"key fact missing: {k!r}" for k in missing_facts]
    absent_found = [a for a in exp["absent_terms"] if contains(got["reply"], a)]
    failures += [f"absent term present: {a!r}" for a in absent_found]

    # Tool errors: expected only when the conversation is a fault test
    tool_errors = [c["name"] for c in calls if c["status"] != "success"]
    if tool_errors and not fault:
        failures += [f"tool error: {n}" for n in tool_errors]

    # Retrieval (information only): did this turn's searches return the document facts?
    searches = [c for c in calls if c["name"] == "search_policy" and c["status"] == "success"]
    retrieval_hit = None
    if doc_facts and searches:
        retrieval_hit = facts_in_text(doc_facts, _results_text(searches))

    return {"passed": not failures, "failures": failures, "notes": notes, "required": required,
            "forbidden_called": forbidden_called, "unexpected_called": unexpected_called,
            "missing_facts": missing_facts, "absent_found": absent_found, "tool_errors": tool_errors,
            "retrieval_hit": retrieval_hit, "judge_checks": exp["judge_checks"]}


def check_conversation(golden_conv: dict, record: dict) -> dict:
    """Score every turn of one conversation. The conversation passes only if every
    turn passes and the run finished without an error."""
    turns, earlier = [], []
    for i, exp in enumerate(golden_conv["turns"]):
        got = record["turns"][i] if i < len(record["turns"]) else None
        result = check_turn(exp, got, earlier, record.get("fault"))
        result.update(turn=i + 1, user=exp["user"], reply=got["reply"] if got else "")
        turns.append(result)
        if got:
            earlier += got["tool_calls"]              # tool calls so far, for met_earlier
    return {"conv_id": golden_conv["conv_id"], "category": golden_conv["category"],
            "passed": all(t["passed"] for t in turns) and not record.get("error"),
            "error": record.get("error"), "turns": turns, "totals": record.get("totals", {})}


# ---------------------------------------------------------------------------
# Scoring a whole run
# ---------------------------------------------------------------------------

def check_run(run_dir: Path) -> dict:
    """Score every trace record in a run folder and build the summary."""
    golden = {c["conv_id"]: c for c in load_golden()}
    records = [json.loads(p.read_text(encoding="utf-8"))
               for p in sorted(run_dir.glob("C*.json")) if p.stem in golden]
    if not records:
        raise SystemExit(f"no trace records found in {run_dir}")
    convs = [check_conversation(golden[r["conv_id"]], r) for r in records]
    all_turns = [t for c in convs for t in c["turns"]]
    req = [v for t in all_turns for v in t["required"].values()]
    hits = [t["retrieval_hit"] for t in all_turns if t["retrieval_hit"] is not None]
    summary = {
        "run": run_dir.name,
        "conversations": len(convs), "conversations_passed": sum(c["passed"] for c in convs),
        "turns": len(all_turns), "turns_passed": sum(t["passed"] for t in all_turns),
        "required_tools": {k: req.count(k) for k in ("pass", "pass_earlier", "met_earlier", "wrong_args", "missing")},
        "forbidden_tool_calls": sum(len(t["forbidden_called"]) for t in all_turns),
        "unexpected_tool_calls": sum(len(t["unexpected_called"]) for t in all_turns),
        "key_facts_missing": sum(len(t["missing_facts"]) for t in all_turns),
        "absent_terms_found": sum(len(t["absent_found"]) for t in all_turns),
        "retrieval_hit_rate": round(sum(hits) / len(hits), 3) if hits else None,
        "retrieval_turns": len(hits),
        "judge_checks_pending": sum(len(t["judge_checks"]) for t in all_turns),
        "cost_usd": round(sum(c["totals"].get("cost_usd") or 0 for c in convs), 4),
        "latency_s": round(sum(c["totals"].get("latency_s") or 0 for c in convs), 1),
    }
    return {"summary": summary, "conversations": convs}


def write_outputs(result: dict, run_dir: Path) -> None:
    """Save checks.json (everything) and checks_turns.csv (one row per turn, for a spreadsheet)."""
    (run_dir / "checks.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    with (run_dir / "checks_turns.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["conv_id", "category", "turn", "passed", "failures", "notes",
                    "retrieval_hit", "judge_checks", "user", "reply"])
        for c in result["conversations"]:
            for t in c["turns"]:
                w.writerow([c["conv_id"], c["category"], t["turn"], t["passed"], "; ".join(t["failures"]),
                            "; ".join(t["notes"]), t["retrieval_hit"], ",".join(t["judge_checks"]),
                            t["user"], t["reply"]])


def print_report(result: dict) -> None:
    """Print the summary, then each conversation with its failed turns and notes."""
    s = result["summary"]
    print(f"Run {s['run']}: {s['conversations_passed']}/{s['conversations']} conversations and "
          f"{s['turns_passed']}/{s['turns']} turns pass the deterministic checks")
    print(f"  required tools {s['required_tools']}  |  forbidden calls {s['forbidden_tool_calls']}  |  "
          f"unexpected calls {s['unexpected_tool_calls']}")
    print(f"  key facts missing {s['key_facts_missing']}  |  absent terms found {s['absent_terms_found']}  |  "
          f"retrieval hit rate {s['retrieval_hit_rate']} over {s['retrieval_turns']} turns")
    print(f"  judge checks pending (step 4) {s['judge_checks_pending']}  |  cost ${s['cost_usd']}  |  "
          f"time {s['latency_s']} s\n")
    for c in result["conversations"]:
        mark = "PASS" if c["passed"] else "FAIL"
        print(f"{mark}  {c['conv_id']}  {c['category']}" + (f"  ERROR {c['error']}" if c["error"] else ""))
        for t in c["turns"]:
            for msg in t["failures"]:
                print(f"        turn {t['turn']}: {msg}")
            for msg in t["notes"]:
                print(f"        turn {t['turn']}: note: {msg}")


def main(argv=None) -> int:
    """Entry point for `python -m chatbot.checks`. Returns 0 if every conversation passes, else 1."""
    ap = argparse.ArgumentParser(description="Score a saved M5 run against the golden conversations.")
    ap.add_argument("run_dir", nargs="?", help="results/chatbot/<run_id>")
    ap.add_argument("--latest", action="store_true", help="score the newest run folder")
    a = ap.parse_args(argv)
    if a.latest:
        runs = sorted(p for p in RESULTS_DIR.iterdir() if p.is_dir())
        if not runs:
            ap.error(f"no runs in {RESULTS_DIR}")
        run_dir = runs[-1]
    elif a.run_dir:
        run_dir = Path(a.run_dir)
    else:
        ap.error("give a run folder or --latest")
    result = check_run(run_dir)
    write_outputs(result, run_dir)
    print_report(result)
    print(f"\nWrote {run_dir / 'checks.json'} and {run_dir / 'checks_turns.csv'}")
    return 0 if result["summary"]["conversations_passed"] == result["summary"]["conversations"] else 1


if __name__ == "__main__":
    sys.exit(main())
