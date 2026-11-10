"""
chatbot/ci_gate.py: the weekly CI check of the chatbot agent (run by .github/workflows/evals.yml).

What it does
------------
Plays a small set of the scripted conversations through the final bot, then
marks them with the text checks only (layer 1, plain code: tools, arguments,
facts and banned terms). The LLM judge (layer 2) is not run in CI, so CI does not
check tone, plain language or invented facts; it checks that the bot still does
the right things with its tools and never says what it must not.

The conversations were chosen for the rules that matter most if they break:
another member's data, a promise of payment, an instruction hidden in a claim note,
mistyped claim IDs, an action the bot cannot take, a claims system outage, and
memory across turns. Nine conversations cost about $0.01 a run.

The gates (thresholds in bench/ci_thresholds.py)
-------------------------------------------------
  HARD  every CI conversation played to the end, with no run error
  HARD  the final prompt was used (checked by fingerprint), so the results are
        comparable with the M5 results
  HARD  no forbidden tool call (for example a lookup of a mistyped ID that
        belongs to another member)
  HARD  no banned term in any reply (another member's name or claim, a promise,
        an internal code)
  WARN  required tools called with the right arguments
  WARN  required facts present in every reply
The last two are warnings because the bot is not deterministic: a reply can
word a fact differently or reuse an earlier lookup, which the M5 runs showed is
sometimes still a correct reply. Promote them once a few weekly runs are in.

Usage (from the repo root)
--------------------------
  python -m chatbot.ci_gate play     play the CI conversations with the final prompt (API calls, about $0.01)
  python -m chatbot.ci_gate check    mark the newest run with the text checks and apply the gates (free)

`check` exits with 1 if a HARD gate fails, so the CI run goes red. The gate table
is saved in results/ci_gates/ (committed by CI) and added to the run summary.

Change history:
  2026-11-10  v1  first version (M5 write-up: CI option (b), agreed by Roger).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from bench.ci_report import Gate, report
from bench.ci_thresholds import (CHATBOT_CI_CONVERSATIONS, CHATBOT_EXPERIMENTS, CHATBOT_PROMPT_FP,
                                 MAX_ABSENT_TERMS_FOUND, MAX_FORBIDDEN_TOOL_CALLS)
from bench.golden import ROOT

from . import run
from .bot import RESULTS_DIR
from .checks import check_run, write_outputs

GOLDEN = ROOT / "datasets" / "conversations_golden.json"


def play_args() -> list[str]:
    """The command-line options for chatbot.run: the CI conversations, the final
    prompt's experiment lines, and no Langfuse tracing."""
    args = ["--no-tracing"]
    for cid in CHATBOT_CI_CONVERSATIONS:
        args += ["--conv", cid]
    for exp in CHATBOT_EXPERIMENTS:
        args += ["--experiment", exp]
    return args


def newest_run() -> Path:
    """The newest run folder in results/chatbot/ (run folders are named by UTC time)."""
    runs = sorted(p for p in RESULTS_DIR.iterdir() if p.is_dir())
    if not runs:
        raise SystemExit(f"no runs in {RESULTS_DIR}")
    return runs[-1]


def gates(result: dict, records: list[dict]) -> list[Gate]:
    """The CI gates for one marked run.

    result   what checks.check_run() returned for the run
    records  the trace records of the run (one per conversation played)
    """
    s = result["summary"]
    played = {r["conv_id"] for r in records}
    expected = set(CHATBOT_CI_CONVERSATIONS)
    errors = [r["conv_id"] for r in records if r.get("error")]
    fps = sorted({r.get("system_prompt_fp") for r in records})
    req = s["required_tools"]
    tool_misses = req.get("missing", 0) + req.get("wrong_args", 0) + req.get("met_earlier", 0)
    return [
        Gate("Chatbot: every CI conversation played, no run errors", "HARD",
             played == expected and not errors,
             f"{len(played & expected)} of {len(expected)} played" + (f", errors in {', '.join(errors)}" if errors else "")
             + (f", missing {', '.join(sorted(expected - played))}" if expected - played else ""),
             f"{len(expected)} of {len(expected)}, no errors"),
        Gate("Chatbot: final prompt in use (fingerprint)", "HARD", fps == [CHATBOT_PROMPT_FP],
             ", ".join(str(f) for f in fps), CHATBOT_PROMPT_FP),
        Gate("Chatbot: no forbidden tool call", "HARD", s["forbidden_tool_calls"] <= MAX_FORBIDDEN_TOOL_CALLS,
             str(s["forbidden_tool_calls"]), f"<= {MAX_FORBIDDEN_TOOL_CALLS}"),
        Gate("Chatbot: no banned term in a reply", "HARD", s["absent_terms_found"] <= MAX_ABSENT_TERMS_FOUND,
             str(s["absent_terms_found"]), f"<= {MAX_ABSENT_TERMS_FOUND}"),
        Gate("Chatbot: required tools called with the right arguments", "WARN", tool_misses == 0,
             f"{tool_misses} missed or wrong", "0"),
        Gate("Chatbot: required facts in every reply", "WARN", s["key_facts_missing"] == 0,
             f"{s['key_facts_missing']} missing", "0"),
    ]


def notes(result: dict) -> list[str]:
    """Plain-English lines for the run summary: the totals, then each failed turn."""
    s = result["summary"]
    try:
        version = json.loads(GOLDEN.read_text(encoding="utf-8")).get("version", "?")
    except (OSError, json.JSONDecodeError):
        version = "?"
    lines = [f"Text checks: {s['conversations_passed']} of {s['conversations']} conversations and "
             f"{s['turns_passed']} of {s['turns']} turns pass (oracle v{version}; the judge is not run in CI)",
             f"Cost about ${s['cost_usd']:.4f}; run folder {s['run']}"]
    for c in result["conversations"]:
        for t in c["turns"]:
            for msg in t["failures"]:
                lines.append(f"{c['conv_id']} turn {t['turn']}: {msg}")
    return lines


def check(run_dir: Path) -> int:
    """Mark one run with the text checks, apply the gates and report them. Returns the exit code."""
    result = check_run(run_dir)
    write_outputs(result, run_dir)
    records = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(run_dir.glob("*.json"))
               if p.stem in CHATBOT_CI_CONVERSATIONS]
    return report("Chatbot agent: text checks", gates(result, records), notes(result),
                  extra={"summary": result["summary"]})


def main(argv=None) -> int:
    """Entry point for `python -m chatbot.ci_gate play|check`."""
    ap = argparse.ArgumentParser(description="Weekly CI check of the M5 chatbot agent.")
    ap.add_argument("step", choices=["play", "check"])
    ap.add_argument("run_dir", nargs="?", help="check: a run folder (default: the newest)")
    a = ap.parse_args(argv)
    if a.step == "play":
        code = run.main(play_args())
        env_file = os.environ.get("GITHUB_ENV")        # tells later CI steps which folder this run wrote
        if env_file and code == 0:
            with open(env_file, "a", encoding="utf-8") as f:
                f.write(f"CHATBOT_RUN_DIR={newest_run().relative_to(ROOT).as_posix()}\n")
        return code
    return check(Path(a.run_dir) if a.run_dir else newest_run())


if __name__ == "__main__":
    sys.exit(main())
