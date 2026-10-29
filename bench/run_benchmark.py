"""run_benchmark.py: the Day 4 test-generation benchmark as one CI step (notebook 03 suite).

    frozen-fingerprint check (free) --> generate (prompt v2, 10 stories) --> score with judge v2
        --> append to results/testgen_history.csv --> quality gates --> pass / fail

Notebook 03 carries the narrative; this script carries the automation. It adds no
scoring logic of its own: it calls bench.generate and bench.score, the same
modules the notebook imports, so CI and notebook always measure the same way.

Gates (bench/ci_thresholds.py):
  HARD  golden set, prompt v2 and both judge prompts match their frozen fingerprints
        (checked before any API call, so a changed file costs nothing)
  HARD  10/10 stories schema-valid
  WARN  mean recall >= 0.68, mean precision >= 0.85, judge replies complete,
        no cases linked to no acceptance criterion (empty covers)

Usage (from the repo root):
    python -m bench.run_benchmark --check-only     # free: fingerprints only
    python -m bench.run_benchmark --run bench-3    # generate + score + history + gates (about $0.32)

Change history:
  2026-10-29  v1  first version (Day 5).
  2026-10-29  v2  WARN gate for cases with empty covers (see testcase_schema.py v2).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from bench import ci_thresholds as T
from bench.ci_report import Gate, report
from bench.golden import load_golden, load_named_prompt, load_prompt
from bench.judge import CASES_PROMPT, RECALL_PROMPT
from bench.testcase_schema import unlinked_cases


def fingerprint_gates() -> list[Gate]:
    now = {
        "golden": load_golden()["_fingerprint"],
        "prompt_v2": load_prompt(T.BENCH_PROMPT)[1],
        "judge_cases": load_named_prompt(CASES_PROMPT)[1],
        "judge_recall": load_named_prompt(RECALL_PROMPT)[1],
    }
    return [Gate(f"Frozen fingerprint: {k}", "HARD", now[k] == want, now[k], want)
            for k, want in T.FROZEN.items()]


def quality_gates(summary: dict, judge_issue_count: int, unlinked: list[str]) -> list[Gate]:
    def fmt(v):
        return "-" if v is None else f"{v:.2f}"
    recall, precision = summary.get("mean_recall"), summary.get("mean_precision")
    return [
        Gate("Stories schema-valid", "HARD", summary["schema_valid"] >= T.MIN_SCHEMA_VALID,
             f"{summary['schema_valid']}/{summary['stories']}", f">= {T.MIN_SCHEMA_VALID}/10"),
        Gate("Mean recall (judge)", "WARN", recall is not None and recall >= T.MIN_RECALL,
             fmt(recall), f">= {T.MIN_RECALL:.2f}"),
        Gate("Mean precision (judge)", "WARN", precision is not None and precision >= T.MIN_PRECISION,
             fmt(precision), f">= {T.MIN_PRECISION:.2f}"),
        Gate("Judge replies complete (no missing or unknown IDs)", "WARN", judge_issue_count == 0,
             str(judge_issue_count), "0"),
        Gate("Cases linked to no acceptance criterion (empty covers)", "WARN",
             len(unlinked) <= T.MAX_UNLINKED_CASES,
             f"{len(unlinked)}" + (f" ({', '.join(unlinked)})" if unlinked else ""),
             f"<= {T.MAX_UNLINKED_CASES}"),
    ]


def main() -> None:
    p = argparse.ArgumentParser(description="CI run of the test-generation benchmark")
    p.add_argument("--run", default="ci", help="run label, e.g. bench-3 (set by benchmark.yml)")
    p.add_argument("--check-only", action="store_true", help="fingerprint gates only; no API call")
    a = p.parse_args()
    suite = "Benchmark: AI test generation (prompt v2)"

    gates = fingerprint_gates()
    if a.check_only or any(not g.passed for g in gates):
        notes = [] if a.check_only else ["Stopped before generation: a frozen file has changed, so this run "
                                         "would not be comparable with the history file."]
        sys.exit(report(suite, gates, notes))

    from bench import generate, score
    gen_path = generate.run(T.BENCH_PROMPT, a.run)
    result = score.score_run(gen_path)
    score_path = score.save(result, write_history=True, rescore=False)

    s = result["summary"]
    issues = sum(len(st["metrics"].get("judge_issues") or []) for st in result["stories"])
    run_records = json.loads(Path(gen_path).read_text(encoding="utf-8"))["records"]
    unlinked = [f"{r['story_id']} {cid}" for r in run_records for cid in unlinked_cases(r.get("parsed"))]
    gates += quality_gates(s, issues, unlinked)
    notes = [f"Cases {s['total_n_cases']}, incorrect {s['total_incorrect']}, not in basis "
             f"{s['total_not_in_basis']}, duplicates {s['total_dup_cases']}",
             f"Cost: generation ${s['total_gen_cost_usd']}, judge ${s['total_judge_cost_usd']} "
             f"(gpt-6-sol price provisional); time: generation {s['total_gen_latency_s']} s, "
             f"judge {s['total_judge_latency_s']} s",
             "Baseline (3 runs, 28 Oct 2026): recall 0.75 [0.70-0.78], precision 0.91"]
    sys.exit(report(suite, gates, notes, {"gen_file": Path(gen_path).name, "score_file": Path(score_path).name}))


if __name__ == "__main__":
    main()
