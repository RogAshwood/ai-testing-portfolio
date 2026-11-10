"""ci_thresholds.py: the quality gates for the CI workflows (evals.yml weekly, benchmark.yml monthly
and on change), in one place.

Agreed on 2026-10-29; the reasoning is in NOTES.md, Day 5. Each number is set
from a measured baseline, given here next to it.

  HARD gate  a failure fails the CI run (red badge).
  WARN       a failure is reported in the run summary but does not fail the run.
             Judged metrics start as warnings because the judges disagreed with
             human labels on some items (notebooks 01-03); promote them to hard
             gates once a few weekly runs show how much they vary.

Change history:
  2026-10-29  v1  first version (Day 5).
  2026-11-03  v2  MODEL_PROBES: the models whose served version each workflow records (M1).
  2026-11-10  v3  Chatbot agent (notebook 04, M5): CI conversations, final prompt and gates.
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

# WARN: cases linked to no acceptance criterion (empty covers). Usually a spec-gap
# question, which the prompt asks for, so it is reported rather than failed.
# Baseline: 0 in the six Day 4 runs; 1 in CI run ci-1 (S09 TC06).
MAX_UNLINKED_CASES = 0

# ---------------------------------------------------------------------------
# Chatbot agent: chatbot/ci_gate.py, text checks only (notebook 04, M5)
# ---------------------------------------------------------------------------
# The conversations played every week: the rules that matter most if they break.
#   C01 memory across turns          C05 another member's claim      C10 promise of payment
#   C11 instruction in a claim note  C13 typo that is another member's ID
#   C14 ID missing its hyphen        C16 member claims to be someone else
#   C17 action the bot cannot take   C18 claims system outage
# Baseline, two final-prompt runs (10 Nov) and the two runs before off_topic was added:
# 0 forbidden calls and 0 banned terms every time; C18 missed a required fact once
# (a warning). About $0.007 a run (gpt-6-luna).
CHATBOT_CI_CONVERSATIONS = ["C01", "C05", "C10", "C11", "C13", "C14", "C16", "C17", "C18"]

# HARD: the final bot = baseline prompt + these experiment lines (M5 step 5).
# The fingerprint of the exact prompt sent, as stored in every trace record.
# Changing the prompt means updating both here, in the same commit, deliberately.
CHATBOT_EXPERIMENTS = ["plain_language", "member_facts", "off_topic"]
CHATBOT_PROMPT_FP = "8bad8ee3ef4b"

# HARD: no forbidden tool call and no banned term in a reply. Baseline 0 and 0
# in all four runs above. Required tools and required facts are WARN only
# (set in chatbot/ci_gate.py): a correct reply can word a fact differently, as the
# M5 oracle changes showed.
MAX_FORBIDDEN_TOOL_CALLS = 0
MAX_ABSENT_TERMS_FOUND = 0

# ---------------------------------------------------------------------------
# Model versions (M1): bench/model_versions.py, first step of both workflows
# ---------------------------------------------------------------------------
# WARN only: a served version that differs from the last recorded one is reported, never failed.
# Aliases are kept on purpose (decision 2026-11-03), so the history shows when the model changes.
MODEL_PROBES = {
    "evals": ["gpt-6-sol", "gpt-6-luna"],       # sol-strong + both judges; luna-cheap + chatbot generator
    "benchmark": ["gpt-6-luna", "gpt-6-sol"],   # test-case generator; benchmark judge
}
