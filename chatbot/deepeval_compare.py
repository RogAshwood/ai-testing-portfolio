"""
chatbot/deepeval_compare.py: general DeepEval conversation metrics, compared with our targeted checks.

The question
------------
Our evaluation of the chatbot is targeted: deterministic checks written from the
spec, plus a judge with 12 behaviour checks calibrated against human labels.
Would off-the-shelf conversational metrics have found the same problems? This
module runs four DeepEval 4.2.8 metrics on saved runs and lines their verdicts up
with ours, conversation by conversation.

  DeepEval metric                     what it scores                     closest of ours
  KnowledgeRetentionMetric            remembers what the member said     memory turns (C01, C07, L01-L03)
  ConversationCompletenessMetric      the member's needs were met        expected_outcome of each conversation
  TurnFaithfulnessMetric              replies grounded in tool results   no_invented_fact
  ConversationalGEval "Overall        a general quality score            all 12 judge checks together
    quality" (one general criterion)

Set-up, chosen so the comparison is fair
----------------------------------------
  - Same judge model as ours (gpt-6-sol), so differences come from the metric,
    not the model. Prices from bench/pricing.py (provisional for gpt-6-sol).
  - Each saved conversation becomes a DeepEval ConversationalTestCase: the member
    and bot turns, with each bot turn's tool results as its retrieval_context and
    tools_called. scenario and expected_outcome come from the golden set.
  - The general criterion deliberately does not list our rules: the point is to
    see what a general metric finds without them.
  - DeepEval's default threshold (0.5): a conversation passes a metric at 0.5 or above.

Our verdict for a conversation is "both layers": every turn passed the
deterministic checks and every judge check (checks.json + judge.json).

Outputs, in results/chatbot_deepeval/:
  <label>.json   every score and reason, our verdict and failing checks, cost
  <label>.csv    one row per conversation, for a spreadsheet

Usage (from the repo root)
--------------------------
  python -m chatbot.deepeval_compare results/chatbot/<run>+results/chatbot/<run2> --limit 2   (a cheap try)
  python -m chatbot.deepeval_compare results/chatbot/<run>+results/chatbot/<run2> --label baseline_A

This module calls the API (through DeepEval). Cost is printed.

Change history:
  2026-11-09  v1  first version (M5 step 4g).
  2026-11-09  v1.1  Overall quality: ConversationalGEval can't read chatbot_role in 4.2.8
                    (it errored on every conversation in the first trial), so the role
                    moved into the criteria text and the metric reads the turns and
                    their tool results instead.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")      # no usage data sent to DeepEval

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "results" / "chatbot_deepeval"
GOLDEN_PATH = ROOT / "datasets" / "conversations_golden.json"
JUDGE_MODEL = "gpt-6-sol"
THRESHOLD = 0.5
CHATBOT_ROLE = ("The online help assistant of Harbourlight Health, a fictional health insurer. It talks to a "
                "member who is signed in to the member portal, about their plan and their own claims.")
GENERAL_CRITERIA = ("The assistant is the online help assistant of a health insurer, talking to a signed-in "
                    "member about their plan and their own claims. Judge its replies as a whole: they should "
                    "be helpful, accurate (supported by the retrieval context), safe and professional.")
MEMORY_CONVERSATIONS = {"C01", "C07", "C08", "L01", "L02", "L03"}


def GEVAL_PARAMS_LIST(MultiTurnParams) -> list:
    """What the general GEval metric reads: the turns and each turn's tool results.
    (ConversationalGEval in 4.2.8 can't read chatbot_role, so the role is in the criteria.)"""
    return [MultiTurnParams.CONTENT, MultiTurnParams.ROLE, MultiTurnParams.RETRIEVAL_CONTEXT]


# ---------------------------------------------------------------------------
# Building the DeepEval test cases (no API calls)
# ---------------------------------------------------------------------------

def load_records(spec: str) -> list[dict]:
    """Conversation records from one or more run folders joined with '+'."""
    out = []
    for folder in spec.split("+"):
        for p in sorted(Path(folder).glob("*.json")):
            d = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(d, dict) and "conv_id" in d and "turns" in d:
                out.append(d)
    return out


def our_verdicts(spec: str) -> dict[str, dict]:
    """Our verdict per conversation (both layers) and the checks it failed."""
    det, judge = {}, {}
    for folder in spec.split("+"):
        d = Path(folder)
        for c in json.loads((d / "checks.json").read_text(encoding="utf-8"))["conversations"]:
            for t in c["turns"]:
                det[(c["conv_id"], t["turn"])] = (t["passed"], t.get("failures", []))
        for t in json.loads((d / "judge.json").read_text(encoding="utf-8"))["turns"]:
            judge[(t["conv_id"], t["turn"])] = [c for c, v in t["verdicts"].items() if v["verdict"] != "pass"]
    out = {}
    for (cid, n), (ok, failures) in det.items():
        o = out.setdefault(cid, {"passed": True, "failed": []})
        jf = judge.get((cid, n), ["not judged"])
        if not ok:
            o["failed"].append(f"t{n} text checks")
        o["failed"] += [f"t{n} {c}" for c in jf]
        o["passed"] = o["passed"] and ok and not jf
    return out


def tool_lines(turn: dict) -> list[str]:
    """What the bot's tools returned on one turn, one string per call."""
    return [f"{c['name']}({json.dumps(c.get('args') or {})}) -> {c.get('status')}: {c.get('result')}"
            for c in turn.get("tool_calls", [])]


def to_test_case(record: dict, golden_conv: dict):
    """One saved conversation as a DeepEval ConversationalTestCase."""
    from deepeval.test_case import ConversationalTestCase, ToolCall, Turn
    turns = []
    for t in record["turns"]:
        turns.append(Turn(role="user", content=t["user"]))
        calls = [ToolCall(name=c["name"], input_parameters=c.get("args") or {}, output=c.get("result"))
                 for c in t.get("tool_calls", [])]
        turns.append(Turn(role="assistant", content=t["reply"] or "(no reply)",
                          retrieval_context=tool_lines(t) or None, tools_called=calls or None))
    return ConversationalTestCase(name=record["conv_id"], turns=turns, chatbot_role=CHATBOT_ROLE,
                                  scenario=golden_conv["scenario"], expected_outcome=golden_conv["expected_outcome"])


def make_metrics(model=None) -> list:
    """The four DeepEval metrics, all with the same judge model."""
    from deepeval.metrics import (ConversationalGEval, ConversationCompletenessMetric, KnowledgeRetentionMetric,
                                  TurnFaithfulnessMetric)
    from deepeval.test_case import MultiTurnParams
    if model is None:
        from dotenv import load_dotenv
        from deepeval.models import OpenAIModel
        from bench.pricing import PRICES_PER_M
        load_dotenv(ROOT / ".env")
        p_in, p_out = PRICES_PER_M[JUDGE_MODEL]
        model = OpenAIModel(model=JUDGE_MODEL, cost_per_input_token=p_in / 1e6, cost_per_output_token=p_out / 1e6)
    return [KnowledgeRetentionMetric(model=model, threshold=THRESHOLD),
            ConversationCompletenessMetric(model=model, threshold=THRESHOLD),
            TurnFaithfulnessMetric(model=model, threshold=THRESHOLD),
            ConversationalGEval(name="Overall quality", criteria=GENERAL_CRITERIA, model=model, threshold=THRESHOLD,
                                evaluation_params=GEVAL_PARAMS_LIST(MultiTurnParams))]


def metric_name(m) -> str:
    return getattr(m, "name", None) if m.__class__.__name__ == "ConversationalGEval" else m.__class__.__name__


# ---------------------------------------------------------------------------
# Running and comparing
# ---------------------------------------------------------------------------

def run(spec: str, limit: int | None = None, metrics_factory=make_metrics) -> dict:
    """Score every conversation in the run with the four metrics and attach our verdict."""
    golden = {c["conv_id"]: c for c in json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))["conversations"]}
    ours = our_verdicts(spec)
    records = [r for r in load_records(spec) if r["conv_id"] in golden and r["conv_id"] in ours]
    records.sort(key=lambda r: r["conv_id"])
    if limit:
        records = records[:limit]
    rows, total_cost, start = [], 0.0, time.perf_counter()
    for rec in records:
        tc = to_test_case(rec, golden[rec["conv_id"]])
        row = {"conv_id": rec["conv_id"], "ours_passed": ours[rec["conv_id"]]["passed"],
               "ours_failed": ours[rec["conv_id"]]["failed"], "metrics": {}}
        for m in metrics_factory():                                  # fresh metric objects per conversation
            name = metric_name(m)
            try:
                m.measure(tc)
                cost = float(m.evaluation_cost or 0)
                row["metrics"][name] = {"score": round(m.score, 3), "passed": m.score >= THRESHOLD,
                                        "reason": m.reason, "cost_usd": round(cost, 5)}
                total_cost += cost
            except Exception as e:                                   # one failure must not stop the run
                row["metrics"][name] = {"score": None, "passed": None, "reason": f"error: {e}", "cost_usd": 0}
        rows.append(row)
        print(f"  {rec['conv_id']}: ours {'PASS' if row['ours_passed'] else 'FAIL'}  |  " +
              "  ".join(f"{n} {v['score']}" for n, v in row["metrics"].items()), flush=True)
    return {"meta": {"runs": spec, "judge_model": JUDGE_MODEL, "threshold": THRESHOLD,
                     "general_criteria": GENERAL_CRITERIA, "deepeval_version": _version(),
                     "time_s": round(time.perf_counter() - start, 1), "cost_usd": round(total_cost, 4)},
            "conversations": rows, "comparison": compare(rows)}


def _version() -> str:
    try:
        import deepeval
        return deepeval.__version__
    except Exception:
        return "unknown"


def compare(rows: list[dict]) -> dict:
    """For each metric: mean score, passes, and agreement with our verdict.

    missed  = DeepEval passed a conversation we failed (a problem the general metric didn't see)
    extra   = DeepEval failed a conversation we passed (worth reading: our gap, or its false alarm)"""
    out = {}
    names = sorted({n for r in rows for n in r["metrics"]})
    for n in names:
        scored = [r for r in rows if r["metrics"].get(n, {}).get("score") is not None]
        if not scored:
            out[n] = {"scored": 0}
            continue
        agree = [r for r in scored if r["metrics"][n]["passed"] == r["ours_passed"]]
        out[n] = {"scored": len(scored),
                  "mean_score": round(sum(r["metrics"][n]["score"] for r in scored) / len(scored), 3),
                  "passed": sum(r["metrics"][n]["passed"] for r in scored),
                  "agree_with_ours": len(agree),
                  "missed": [r["conv_id"] for r in scored if r["metrics"][n]["passed"] and not r["ours_passed"]],
                  "extra": [r["conv_id"] for r in scored if not r["metrics"][n]["passed"] and r["ours_passed"]],
                  "errors": len(rows) - len(scored)}
    return out


def print_report(res: dict) -> None:
    rows, comp = res["conversations"], res["comparison"]
    ours_pass = sum(r["ours_passed"] for r in rows)
    print(f"\nDeepEval {res['meta']['deepeval_version']} with {res['meta']['judge_model']} on {res['meta']['runs']}")
    print(f"  {len(rows)} conversations; ours (both layers): {ours_pass} pass, {len(rows) - ours_pass} fail")
    print(f"  cost ${res['meta']['cost_usd']} (gpt-6-sol price provisional)  |  time {res['meta']['time_s']} s\n")
    print(f"  {'metric':34} {'mean':>6} {'pass':>6} {'agree':>7}   missed (DeepEval pass, ours fail)")
    for n, c in comp.items():
        if not c.get("scored"):
            print(f"  {n:34} no scores (all errors)")
            continue
        print(f"  {n:34} {c['mean_score']:>6} {c['passed']:>3}/{c['scored']:<2} {c['agree_with_ours']:>4}/{c['scored']:<2}"
              f"   {', '.join(c['missed']) or '-'}")
        if c["extra"]:
            print(f"  {'':34} {'':>6} {'':>6} {'':>7}   extra (DeepEval fail, ours pass): {', '.join(c['extra'])}")
        if c["errors"]:
            print(f"  {'':34} {c['errors']} error(s): see the JSON")
    print("\n  Conversations we failed, with what each DeepEval metric said:")
    for r in rows:
        if not r["ours_passed"]:
            scores = "  ".join(f"{n.replace('Metric', '')} {v['score']}" for n, v in r["metrics"].items())
            print(f"    {r['conv_id']}: ours failed on {', '.join(r['ours_failed'][:4])}"
                  f"{' …' if len(r['ours_failed']) > 4 else ''}\n      DeepEval: {scores}")


def write_outputs(res: dict, label: str) -> list[Path]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    j, c = OUT_DIR / f"{label}.json", OUT_DIR / f"{label}.csv"
    j.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    names = sorted({n for r in res["conversations"] for n in r["metrics"]})
    with c.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["conv_id", "ours_passed", "ours_failed"] + [f"{n} score" for n in names] +
                   [f"{n} reason" for n in names])
        for r in res["conversations"]:
            w.writerow([r["conv_id"], r["ours_passed"], "; ".join(r["ours_failed"])] +
                       [r["metrics"].get(n, {}).get("score") for n in names] +
                       [r["metrics"].get(n, {}).get("reason") for n in names])
    return [j, c]


def main(argv=None) -> int:
    """Entry point for `python -m chatbot.deepeval_compare`."""
    ap = argparse.ArgumentParser(description="DeepEval conversational metrics vs our targeted checks.")
    ap.add_argument("run", help="run folder(s), joined with + (must have checks.json and judge.json)")
    ap.add_argument("--limit", type=int, help="only the first N conversations (a cheap try)")
    ap.add_argument("--label", help="output name in results/chatbot_deepeval/ (default: first run id)")
    a = ap.parse_args(argv)
    res = run(a.run, limit=a.limit)
    print_report(res)
    label = a.label or Path(a.run.split("+")[0]).name + (f"_limit{a.limit}" if a.limit else "")
    for f in write_outputs(res, label):
        print(f"Wrote {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
