"""ci_thresholds.py: the quality gates for the CI workflows (evals.yml weekly, benchmark.yml monthly
and on change), in one place.

Agreed with Roger on 2026-10-29 (project note claude/day5_ci_scope.md). Each
number is set from a measured baseline, given here next to it.

  HARD gate  a failure fails the CI run (red badge).
  WARN       a failure is reported in the run summary but does not fail the run.
             Judged metrics start as warnings because the judges disagreed with
             human labels on some items (notebooks 01-03); promote them to hard
             gates once a few weekly runs show how much they vary.

Change history:
  2026-10-29  v1  first version (Day 5).
"""

# ---------------------------------------------------------------------------
# Promptfoo: claim triage, prompt v3 only, both models (notebook 01)
# ---------------------------------------------------------------------------
PROMPTFOO_PROMPT = "v3-rules-dates"
RELEASE_MODEL = "sol-strong"           # the release candidate: hard gates apply to it
REPORT_MODELS = ["luna-cheap"]         # measured and reported, warnings only
N_CLAIMS = 35

# HARD, every model: format, schema and traceability must be 100%.
# Baseline: 35/35 on both models with v3.
FORMAT_METRICS = ["format", "claim_id"]

# HARD, release model: zero false auto-approvals (the costly error).
# Baseline: sol-strong 0 with v3. luna-cheap auto-approves HLH-009 in 2 of 3
# runs (known defect), so for luna this is a warning.
MAX_FALSE_AUTO_APPROVALS = 0

# HARD, release model: routing accuracy. Baseline sol-strong 35/35 with v3;
# one miss allowed so a single flip on a borderline claim does not fail the run.
MIN_ROUTING_CORRECT = 34               # of 35

# WARN, every model: summary quality (llm-rubric, judge rubric v2).
# Baseline: rubric v2 still failed 4 of 24 good summaries in judge validation.
MIN_SUMMARY_PASS_RATE = 0.80

# ---------------------------------------------------------------------------
# DeepEval: tests/test_rag.py (notebook 02)
# ---------------------------------------------------------------------------
# HARD: all 5 tests pass (pass mark 0.75, rag_judges.PASS_MARK). The test
# runner's own exit code is the gate, so nothing is configured here.

# ---------------------------------------------------------------------------
# Benchmark: AI test generation, prompt v2, one run (notebook 03)
# ---------------------------------------------------------------------------
BENCH_PROMPT = "v2"

# HARD: frozen fingerprints. If any differs, the run is not comparable with the
# history file, so it is stopped before any API call.
FROZEN = {
    "golden": "228e95aab97e",          # datasets/testgen_golden.json v1.0
    "prompt_v2": "26bcc3fb6a1c",       # bench/prompts/testgen_v2.txt
    "judge_cases": "ff34c1fc3ab1",     # bench/prompts/judge_cases_v2.txt
    "judge_recall": "00e27350cffd",    # bench/prompts/judge_recall_v2.txt
}

# HARD: every story returns schema-valid JSON. Baseline 10/10 in all six runs.
MIN_SCHEMA_VALID = 10                  # of 10 stories

# WARN: judged quality. Baseline over 3 runs of v2: mean recall 0.75 [0.70-0.78],
# mean precision 0.91. Thresholds sit just below the observed range.
MIN_RECALL = 0.68
MIN_PRECISION = 0.85
