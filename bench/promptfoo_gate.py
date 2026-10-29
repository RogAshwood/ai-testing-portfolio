"""promptfoo_gate.py: apply the CI quality gates to a Promptfoo results file (notebook 01 suite).

    npx promptfoo eval ... -o results/ci/promptfoo_ci.json  -->  this script  -->  pass / fail

Promptfoo's own exit code fails on any failed assertion, including the known
luna-cheap defect and judged summary scores. CI therefore runs Promptfoo with
PROMPTFOO_FAILED_TEST_EXIT_CODE=0 and lets this script decide, using the
agreed gates in bench/ci_thresholds.py:

  HARD  every model: format (JSON + schema) and claim_id 35/35
  HARD  sol-strong:  zero false auto-approvals; routing correct >= 34/35
  WARN  luna-cheap:  false auto-approvals and routing accuracy (reported only)
  WARN  every model: summary quality pass rate (LLM judge)

An API error on a test counts as a failed check, never as a pass.

Usage (from the repo root):
    python -m bench.promptfoo_gate results/ci/promptfoo_ci.json
    python -m bench.promptfoo_gate results/promptfoo_v3.json      # free: re-check a saved run

Change history:
  2026-10-29  v1  first version (Day 5).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from bench import ci_thresholds as T
from bench.ci_report import Gate, report


def load_rows(path: Path, prompt_label: str = T.PROMPTFOO_PROMPT) -> list[dict]:
    """One row per (model, claim) for the chosen prompt, with each assertion's pass/fail."""
    data = json.loads(path.read_text(encoding="utf-8"))
    res = data["results"]
    labels = [p.get("label", "") for p in res.get("prompts", [])]
    rows = []
    for r in res["results"]:
        label = labels[r["promptIdx"]] if r.get("promptIdx") is not None and r["promptIdx"] < len(labels) else ""
        if not label.startswith(prompt_label):
            continue
        checks = {}
        for c in (r.get("gradingResult") or {}).get("componentResults") or []:
            metric = c.get("assertion", {}).get("metric")
            if metric and metric != "nft":
                checks[metric] = bool(c.get("pass"))
        rows.append({"model": r["provider"].get("label") or r["provider"]["id"],
                     "claim_id": r["vars"].get("claim_id"),
                     "error": r.get("error") if not r.get("gradingResult") else None,
                     "checks": checks})
    return rows


def model_stats(rows: list[dict]) -> dict:
    stats = defaultdict(lambda: {"n": 0, "format": 0, "claim_id": 0, "routing": 0,
                                 "false_auto": [], "summary": 0, "errors": 0})
    for r in rows:
        s = stats[r["model"]]
        c = r["checks"]
        s["n"] += 1
        s["errors"] += bool(r["error"])
        s["format"] += c.get("format", False)
        s["claim_id"] += c.get("claim_id", False)
        s["routing"] += c.get("routing", False)
        s["summary"] += c.get("summary_quality", False)
        if c.get("safety_no_false_auto_approve") is False:
            s["false_auto"].append(r["claim_id"])
    return dict(stats)


def build_gates(stats: dict) -> list[Gate]:
    gates = []
    models = [T.RELEASE_MODEL] + T.REPORT_MODELS
    missing = [m for m in models if m not in stats or stats[m]["n"] != T.N_CLAIMS]
    gates.append(Gate("All 35 claims ran on both models", "HARD", not missing,
                      ", ".join(f"{m} {stats.get(m, {}).get('n', 0)}" for m in models), f"{T.N_CLAIMS} each"))
    for m in models:
        s = stats.get(m)
        if not s:
            continue
        for metric in T.FORMAT_METRICS:
            gates.append(Gate(f"{m}: {metric} correct", "HARD", s[metric] == s["n"],
                              f"{s[metric]}/{s['n']}", f"{s['n']}/{s['n']}"))
        level = "HARD" if m == T.RELEASE_MODEL else "WARN"
        fa = s["false_auto"]
        gates.append(Gate(f"{m}: false auto-approvals", level, len(fa) <= T.MAX_FALSE_AUTO_APPROVALS,
                          f"{len(fa)}" + (f" ({', '.join(fa)})" if fa else ""), f"<= {T.MAX_FALSE_AUTO_APPROVALS}"))
        gates.append(Gate(f"{m}: routing correct", level, s["routing"] >= T.MIN_ROUTING_CORRECT,
                          f"{s['routing']}/{s['n']}", f">= {T.MIN_ROUTING_CORRECT}/{T.N_CLAIMS}"))
        rate = s["summary"] / s["n"] if s["n"] else 0
        gates.append(Gate(f"{m}: summary quality (judge)", "WARN", rate >= T.MIN_SUMMARY_PASS_RATE,
                          f"{s['summary']}/{s['n']} ({rate:.0%})", f">= {T.MIN_SUMMARY_PASS_RATE:.0%}"))
    return gates


def main() -> None:
    p = argparse.ArgumentParser(description="CI gates for the Promptfoo claim-triage suite")
    p.add_argument("results", help="Promptfoo JSON output (-o file.json)")
    a = p.parse_args()
    stats = model_stats(load_rows(Path(a.results)))
    notes = [f"{m}: {s['errors']} test(s) ended in an API error" for m, s in stats.items() if s["errors"]]
    notes.append("Known defect: luna-cheap may auto-approve HLH-009 (EUR 1,150, above the EUR 1,000 "
                 "manual-review threshold). Reported, not gated.")
    sys.exit(report("Promptfoo: claim triage (prompt v3)", build_gates(stats), notes,
                    {"results_file": Path(a.results).name}))


if __name__ == "__main__":
    main()
