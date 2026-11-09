"""
chatbot/run.py: play golden conversations through the M5 bot and save the trace records.

Usage (from the repo root, ai-testing env active):
  python -m chatbot.run --conv C01            one conversation (repeat --conv for more)
  python -m chatbot.run --all                 all 20 scored conversations (stretch excluded)
  python -m chatbot.run --conv C01 --no-tracing   skip Langfuse even if keys are set
  python -m chatbot.run --all --no-tracing --experiment plain_language
                                              a prompt experiment (step 5); repeat for more

Each run writes results/chatbot/<run_id>/<conv_id>.json and prints every turn:
the member's message, the tools called with their arguments, and the reply.
This script calls the API; cost is printed per conversation.

What it does, in order:
  1. Reads the command-line options and picks the conversations to play.
  2. Creates the model client and the retriever once, shared by every
     conversation in the run (building the retriever takes a moment).
  3. For each conversation, calls bot.run_conversation(), which plays the
     scripted member turns and saves the trace record.
  4. Prints each turn in a readable form, then the cost and time.
It does not score anything; the checks (step 3) read the saved records.

Change history:
  2026-11-05  v1  first version (M5).
  2026-11-05  v1.1  comments expanded; no code change.
  2026-11-06  v1.2  prints cached input tokens.
  2026-11-09  v1.3  --experiment switches on a prompt experiment (prompt.EXPERIMENT_LINES).
"""
from __future__ import annotations

import argparse
import sys
import textwrap
from datetime import datetime, timezone

from .bot import RESULTS_DIR, load_golden, make_llm, run_conversation
from .prompt import EXPERIMENT_LINES
from .policy import build_m5_retriever


def main(argv=None) -> int:
    """Entry point for `python -m chatbot.run`. argv is for the tests; normally None."""
    # 1. Options and which conversations to play.
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--conv", action="append", default=[], help="conversation ID, e.g. C01")
    ap.add_argument("--all", action="store_true", help="all scored conversations")
    ap.add_argument("--no-tracing", action="store_true", help="do not send to Langfuse")
    ap.add_argument("--experiment", action="append", default=[], choices=sorted(EXPERIMENT_LINES),
                    help="switch on a prompt experiment (repeat for more); default: the baseline prompt")
    a = ap.parse_args(argv)

    golden = {c["conv_id"]: c for c in load_golden()}
    ids = [c for c in golden if not golden[c]["stretch"]] if a.all else a.conv
    unknown = [c for c in ids if c not in golden]
    if not ids or unknown:
        ap.error(f"give --all or --conv with known IDs (unknown: {unknown})")
    if any(golden[c]["stretch"] for c in ids):
        ap.error("stretch conversations need request_callback, which is not built yet")

    # 2. One run ID (UTC time) for the results folder, one model client, one retriever.
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    llm, retriever = make_llm(), build_m5_retriever()
    total = 0.0
    # 3 and 4. Play each conversation, then print what happened.
    for cid in ids:
        rec = run_conversation(golden[cid], llm=llm, retriever=retriever,
                               tracing=not a.no_tracing, run_id=run_id, experiments=a.experiment)
        print(f"\n=== {cid}  member {rec['member_id']}  fault={rec['fault']}  "
              f"served={rec['model_served']}  langfuse={rec['langfuse']}")
        for t in rec["turns"]:
            print(f"\n  [{t['turn']}] Member: {t['user']}")
            for c in t["tool_calls"]:
                print(f"      tool {c['name']}({c['args']}) -> {c['status']}")
            print("      Bot: " + textwrap.fill(t["reply"], 90, subsequent_indent=" " * 11))
        if rec["error"]:
            print(f"\n  ERROR {rec['error']}")
        tot = rec["totals"]
        total += tot["cost_usd"] or 0
        print(f"\n  {tot['llm_calls']} model calls, {tot['input_tokens']} in "
              f"({tot.get('cached_input_tokens', 0)} cached) / {tot['output_tokens']} out tokens, "
              f"${tot['cost_usd']:.4f}, {tot['latency_s']:.1f} s")
    print(f"\nPrompt: {'baseline' if not a.experiment else 'baseline + ' + ', '.join(a.experiment)}"
          f"  (fingerprint {rec['system_prompt_fp']})")
    print(f"Saved to {RESULTS_DIR / run_id}  |  total ${total:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
