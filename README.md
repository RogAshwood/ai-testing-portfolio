# Testing AI: a QA lead's portfolio

Practical work from a short upskilling project in testing LLM-based systems, written from a QA-lead perspective.
Every exercise uses one fictional health insurer, **Harbourlight Health**, so the portfolio reads as one business
tested at several layers. All data is synthetic: no employer data and no real personal or medical data.

| # | Notebook | What is tested | Tools | Status |
| --- | --- | --- | --- | --- |
| 01 | [`01_promptfoo_claim_triage.ipynb`](01_promptfoo_claim_triage.ipynb) | An LLM claim-triage step: prompt regression, model comparison, judge validation, red teaming | Promptfoo, pandas | Done |
| 02 | [`02_deepeval_rag_component_vs_e2e.ipynb`](02_deepeval_rag_component_vs_e2e.ipynb) | Member-help chatbot (RAG): retriever and generator tested separately and end to end, fault injection, judge calibration, fix and retest, CI tests | DeepEval, scikit-learn, pytest | Done |
| 03 | [`03_testgen_benchmark.ipynb`](03_testgen_benchmark.ipynb) | AI test generation: two prompts benchmarked against an expert golden set, an LLM judge tested with seeded defects and blind labels (including a held-out round) | OpenAI API, Python (`bench/`), pandas, matplotlib | Done |

---

## 01: Claim triage with Promptfoo

### The system under test

Step 3 of a seven-step claims workflow: an LLM reads a claim and recommends a **category**, a **routing**
(`auto_approve`, `manual_review` or `decline_recommended`), a **reason code** and a short **summary**.
A human assessor makes every decision except spot-checked auto-approvals.

The rules (cover limits, exclusions, a 182-day waiting period with exemptions, a 12-month submission deadline,
and a strict order for applying them) are in [`datasets/plan_rules.md`](datasets/plan_rules.md). That file is
the **specification (test basis)**. The expected results in the dataset are derived from it, and a reference
implementation ([`datasets/validate_dataset.py`](datasets/validate_dataset.py)) checks that every expected
result follows from the rules.

### What was tested

- **35 synthetic claims** covering the core rules, boundaries (at the limit vs 1 euro over, deadline day vs 1 day
  late, waiting-period day 181 vs 182, a leap-day deadline), ambiguous claims, adversarial notes (an embedded
  instruction, a yoga class relabelled as physio, an emotive plea) and fairness pairs (claims identical except
  for name or gender).
- **3 prompt versions × 2 models.** v1 is a one-line baseline. v2 adds the rules and an output schema. v3 adds
  date facts pre-calculated by a simulated intake step, to test whether date arithmetic was causing v2's errors.
  Models: a cheaper and a stronger OpenAI model.
- **Checks on every response:**
  - deterministic: valid JSON and schema; claim ID, category, routing and reason code against the expected result
  - a zero-tolerance safety rule: **never auto-approve a claim the rules do not auto-approve**
  - an LLM judge for summary quality (binary pass/fail against a four-point rubric)
  - latency and cost thresholds
- **Stability:** every combination run 3 times to find routings that flip between runs.
- **Red team:** Promptfoo-generated attacks through the free-text claimant note (prompt injection, hijacking,
  PII and health-data disclosure, coverage discrimination).
- **Judge validation:** the summary judge was itself tested against human labels (see below).

### Headline findings

<!-- Replace the bracketed figures with the numbers from the notebook. -->

1. **The prompt mattered more than the model.** Routing accuracy rose from [v1 %] to [v2 %] to [v3 %] on the
   cheaper model. Moving date arithmetic out of the model (v3) fixed [n] of the [11] date-dependent claims.
2. **Safety rule:** [n] false auto-approvals with v3 across both models. [One sentence on where they occurred, if any.]
3. **The LLM judge needed testing as much as the model.** Against my labels, the original rubric failed 11 of 24
   good summaries. Every one of those failures came from missing context: the judge did not know what the claim fields meant. Adding
   field definitions cut false fails to 4 of 24, while the judge still caught all 8 deliberately flawed summaries.
4. **Red team:** no attack produced an auto-approval. The one graded "successful" was, on review, a sign that my
   attack policy was stricter than the specification, not a breach.
5. **Cost is not the deciding factor.** Both models cost fractions of a cent per claim. One wrong routing costs
   far more, so the choice rests on safety and accuracy.

![Routing accuracy by prompt and model](results/charts/01_routing_accuracy_by_prompt.png)

### Testing the judge

An LLM judge is a test oracle, so it was validated before its scores were trusted:

1. **Blind labelling.** 24 summaries were labelled by hand against the same four criteria, without seeing the judge's
   verdicts.
2. **Comparison.** Agreement, false passes and false fails (notebook section 9b).
3. **Re-judging with the outputs frozen.** [`promptfoo/judge_validation.yaml`](promptfoo/judge_validation.yaml)
   replays the stored model outputs through Promptfoo's `echo` provider. Only the rubric changes between runs, so
   any change in verdicts comes from the rubric. Eight deliberately flawed summaries test whether the judge
   still fails what it should (section 9c).

This suite stays in the repo as a regression test for the judge: re-run it whenever the rubric or judge model changes.

### Limitations

These are patterns, not precise measurements: 35 claims, a self-written specification that also serves as the
prompt, one human labeller, a judge from the same model family as one of the systems under test, and a small
red-team sample. The full list is in section 12 of the notebook.

---

## 02: Member-help chatbot with DeepEval

### The system under test

A small retrieval-augmented generation (RAG) chatbot that answers members' questions about their plan. It has
two components, and each can fail on its own:

- **Retriever:** cuts 10 short member documents into chunks and ranks them against the question with TF-IDF
  (scikit-learn). The top k chunks (k=3 in the baseline) are passed on.
- **Generator:** a cheaper OpenAI model writes the answer from those chunks only, under rules in its system
  prompt: say when it does not know, no medical advice, never promise a claim will be paid, ignore instructions
  hidden in the question.

The documents in [`datasets/policy_docs/`](datasets/policy_docs/) are the **test basis**. The **oracle** is a
15-question golden set ([`datasets/rag_golden.csv`](datasets/rag_golden.csv)): expected answer, expected
behaviour, source documents and key facts for each question. [`datasets/validate_golden.py`](datasets/validate_golden.py)
checks the oracle against the documents before any test runs.

![Day 3 evaluation set-up](images/day3_eval_setup.png)

### What was tested

- **15 questions:** 8 standard, 3 the documents cannot answer (the bot should say so), 2 adversarial (a prompt
  injection and a false premise) and 2 that ask for medical advice or a promise of payment.
- **The retriever alone:** deterministic key-fact recall (are the facts the answer needs in the retrieved text?)
  and DeepEval's contextual precision, recall and relevancy.
- **The generator alone:** given the *correct* chunks through a stub, so any failure is the generator's.
  Faithfulness, answer relevancy and hallucination, plus three G-Eval criteria written as explicit steps:
  correctness, declining when the answer is not in the documents, and safe conduct.
- **End to end:** the whole chatbot, repeated 3 times to measure run-to-run variation, then compared question
  by question with the generator-alone results to say where each failure came from.
- **Fault injection:** the retriever broken on purpose (one chunk only; text cut every 200 characters) to see
  which metrics notice.
- **Judge calibration:** the LLM judge compared with my own blind labels, and 8 deliberately bad answers that
  it must fail.
- **Fix and retest:** k raised from 3 to 5, then confirmation and regression testing.
- **CI tests:** 5 automated tests in [`tests/test_rag.py`](tests/test_rag.py), run with `deepeval test run`.

### Headline findings

1. **Every end-to-end failure came from the retriever, none from the generator.** End to end, 6 of 12
   answerable questions failed. Given the right chunks, the generator scored 0.8 or above on all 12. An
   end-to-end score alone shows *that* the chatbot is weak; testing the components shows *where*.
2. **The cheapest check was the best predictor.** Key-fact recall, a plain text match with no LLM, was below 1
   for exactly the questions that failed, and moved with correctness when the retriever was broken on purpose.
   But it checks words, not meaning: when the text was cut every 200 characters, one question's facts arrived
   without the heading "What is not covered", and the answer was still wrong. Only the LLM judge caught that.
3. **The bot stayed safe throughout.** Declining unanswerable questions and the safe-conduct checks scored 1.00
   in every configuration, including with the retriever broken. Poor retrieval cost members answers; it did
   not make the bot guess, follow the injected instruction, give medical advice or promise payment.
4. **Some metrics are blind to retrieval faults.** Faithfulness stayed at 1.00 with the retriever broken,
   because the bot faithfully repeated whatever it was given. Answer relevancy gave "I don't know" a perfect
   score.
5. **The judge is reliable for clear-cut failures, not for quality.** It failed all 8 deliberately bad answers,
   but agreed with my labels on only 6 of 10 real ones: it checks that facts are present, while I judged the
   answer as a member would. DeepEval's default pass mark of 0.5 let a wrong claim condition through.
6. **The fix worked, at a price.** k=5 genuinely fixed 3 of the 6 retrieval failures with no regressions,
   taking questions passing from 5 to 10 of 12 (2 of those within run-to-run noise), for about 28% more input
   tokens per answer and slower answers. One question still fails because it shares no words with its answer:
   that needs semantic search, not a bigger k.

![Correctness per question: generator alone against end to end](results/charts/correctness_generator_vs_e2e.png)

### Testing the tests

As in Day 2, the tests needed testing too. The first LLM-judge runs found problems in the test set-up, each of
which could have produced a wrong verdict about the chatbot:

- **The oracle mixed facts with behaviour.** Expected answers such as "the assistant ignores the instruction"
  can never be found in a document, so retrieval scores were capped however well the retriever worked. The
  golden set was split into `expected_answer` and `expected_behaviour`, versioned (v1.3) and frozen.
- **A test was not given what it needed.** The first safe-conduct test was not shown the documents, so it
  failed a perfect answer for stating a correct limit. Version 2 fixed that, then had to fail 4 deliberately
  rule-breaking answers before it was trusted.
- **The library changed underneath.** In DeepEval 4.2.8 the hallucination score runs the other way from older
  documentation (higher is better). Checked in the source code before reading any results.

The judge's criteria live in [`rag_judges.py`](rag_judges.py) and are imported by both the notebook and the CI
tests, so the analysis and the gate always test the same thing. The full list of problems, in the chatbot and in
the test set-up, is in section 8 of the notebook and in [`NOTES.md`](NOTES.md).

### Limitations

15 synthetic questions over 10 short documents; a deliberately simple retriever; one judge model from the same
provider as the generator; 10 human labels from one person; the faults and the fix run once each (the baseline
3 times). The patterns are the point, not the precise scores. The full list is in section 8 of the notebook.

---

## 03: AI test generation benchmark

### The system under test

Teams increasingly paste a user story into an AI tool and get test cases back. This exercise measures how good
those test cases are, and whether telling the AI how to design tests helps.

The system under test is a single prompt (not an agent) that turns one user story into test cases as JSON:
title, technique, the acceptance criteria covered, preconditions, steps and expected result. The generator
(`gpt-6-luna`, the cheaper model) sees only the story's title, user story and acceptance criteria. Two prompts
are compared on the same model, so any difference comes from the instructions:

- **v1:** "here is a user story, write test cases for it", with the technique definitions so its labels can be compared.
- **v2:** v1 plus seven general test-design techniques (equivalence partitioning, boundary value analysis, negative
  testing and others). They were written from general test design, never from the expected ideas: each line must
  still make sense for a story from another domain.

The **test basis** is 10 user stories for Harbourlight's claims platform (39 acceptance criteria), traced to
`plan_rules.md` and the Day 3 documents. The **oracle** is a golden set of 78 expected test ideas an experienced
QA lead would want (27 positive, 20 negative, 31 boundary) in
[`datasets/testgen_golden.json`](datasets/testgen_golden.json), v1.0, frozen.
[`datasets/validate_testgen_golden.py`](datasets/validate_testgen_golden.py) checks it before any run.

![Day 4 benchmark flow](images/day4_testgen_flow.svg)

### What was tested

- **3 runs × 2 prompts × 10 stories**, because the generator does not give the same answer twice.
- **Error analysis first.** The first v1 run was read case by case before any metric was chosen. It found nine
  failure patterns (abstract test data, boundaries only where the story gives values, no "rule must not fire"
  cases, several conditions in one case, and others), which became the judge's checks and four matching rules.
- **An LLM judge** (`gpt-6-sol`, the stronger model) in two calls per story. The first marks each case without
  seeing the expected ideas: correct, incorrect or not in the test basis; technique; concrete test data; one
  condition per case (atomic); duplicates. The second decides which expected ideas are covered, and by which cases.
  The judge never knows which prompt wrote the cases.
- **Measures reported together:** recall (share of expected ideas found) alone can be gamed by writing more cases,
  so it always appears with precision (share of cases correct and not duplicates) and case count. Also claimed
  against verified coverage, concrete and atomic rates, cost and time.
- **Traceability by content:** the golden set, every prompt, the judge prompts and each story are fingerprinted
  (first 12 characters of a SHA-256 hash). Every result records the fingerprints it was produced from, so a changed
  story or prompt shows in every result. All runs go into `results/testgen_history.csv`.

### Headline findings

1. **Technique guidance helped.** v2 found 0.75 of the expected ideas against v1's 0.63 (mean of 3 runs; ranges
   0.70–0.78 and 0.60–0.64 do not overlap). Gains were similar for positive, negative and boundary ideas. The
   largest story gain was per-visit limits (0.40 to 0.93), where v2 tested both sides of each value.
2. **The reviewer pays for it.** v2 wrote 130 cases per run against 78: about five extra cases for every extra
   idea found. Precision fell from 1.00 to 0.91 (0.94 without the "not in basis" cases), and every duplicate came
   from v2. A run cost $0.32 against $0.22, most of it the judge.
3. **Twelve ideas were never found by either prompt in any run.** They are domain traps, rules that must not fire
   and rule interactions: what an experienced tester adds from knowing the business. One story (S09) stayed near zero.
4. **The marker's rules moved the score as much as the prompt.** Re-marking the same v1 cases with clarified judge
   instructions raised recall from 0.52 to 0.64, the same +0.12 as the change from v1 to v2. The judge was therefore
   frozen before the comparison runs, and every score records the judge version.
5. **"Not in basis" was not always a defect.** Most of v2's were questions about gaps in the specification, and one
   found a real gap: an annual-limit criterion that says what happens at the limit, but not above it.

![Recall by technique: prompt v1 against v2](results/charts/testgen_recall_by_technique.png)

### Testing the judge

The judge is the test oracle for every number above, so it was tested in four ways before its scores were used:

1. **Seeded defects.** 28 deliberately flawed or deliberately correct items (46 checks) in
   [`datasets/testgen_seeded_defects.json`](datasets/testgen_seeded_defects.json). The judge must fail the flawed
   ones and pass the controls. Judge v1 passed 33 of 33 checks; judge v2 passed 46 of 46.
2. **Blind human labels.** 20 cases and 24 expected ideas labelled by hand without seeing the judge's verdicts.
3. **Tuning, then a held-out round.** Round 1's disagreements led to judge v2. Re-marked, the same labels then agreed
   20/20 on verdict and technique, which is optimistic, so 20 fresh cases and 24 ideas from a v2 run were labelled and the
   frozen judge scored on them with no further tuning.
4. **Duplicate check.** 12 blind pairs: all 7 duplicates the judge flagged were confirmed, and it missed 2.

| Check | Round 1 | Round 2 (after tuning) | Round 3 (held-out) |
| --- | --- | --- | --- |
| Idea covered | 17/24 | 24/24 | 23/24 |
| Verdict | 19/20 | 20/20 | 18/20 |
| Atomic | – | 19/20 | 18/20 |
| Concrete | 16/20 | 16/20 | 13/20 |
| Technique | 15/20 | 20/20 | 10/20 |

The judge's coverage and correctness verdicts held up on unseen cases, so recall and precision can be trusted.
Its technique and concrete labels did not, mainly because people apply those definitions differently (is a valid
value at a limit "positive" or "boundary"?), so those measures are reported as indicative only.

### Limitations

10 stories, 3 runs per prompt, one generator model. The judge was tuned on its own calibration set, and the
held-out round covers one run. Duplicates are under-counted, so v2's precision is slightly overstated. Recall
counts the ideas chosen for the golden set, not completeness. The generator saw one story at a time, so rule
interactions across stories were not measured, and nobody checked whether the steps could be executed. Judge
cost uses `gpt-6.1-sol` prices, unconfirmed for `gpt-6-sol`. The full list is in section 11 of the notebook.

---

## Repository layout

```
ai-testing-portfolio/
├── 01_promptfoo_claim_triage.ipynb   Notebook 01: results, charts and interpretation
├── 02_deepeval_rag_component_vs_e2e.ipynb  Notebook 02: RAG chatbot tested by component and end to end
├── 03_testgen_benchmark.ipynb        Notebook 03: AI test generation, prompt v1 against v2
├── routing_stability.py              Finds claims whose routing changes across repeat runs
├── build_judge_cases.py              Builds the judge-validation cases from stored outputs and labels
├── rag_pipeline.py                   Day 3 system under test: chunker, TF-IDF retriever, generator
├── rag_metrics.py                    Day 3 free checks (no LLM): key-fact recall, correct-context stub
├── rag_judges.py                     Day 3 LLM judge and its G-Eval criteria; shared by notebook and tests
├── environment.yml                   Conda environment
├── bench/                            Day 4 benchmark code, imported by notebook 03
│   ├── golden.py                     Loads the golden set; story cards and fingerprints
│   ├── generate.py                   Runs a prompt over the stories and saves the test cases
│   ├── testcase_schema.py            Checks the generated JSON against the output schema
│   ├── judge.py                      The two LLM-judge calls per story
│   ├── score.py                      Metrics, seeded-defect check and the history file
│   ├── calibration.py                Blind label sheets and judge agreement
│   ├── review_sheet.py               HTML sheet for reading a run's cases by story
│   ├── pricing.py                    Model prices for the cost columns
│   └── prompts/                      testgen_v1/v2, judge_cases_v1/v2, judge_recall_v1/v2
├── datasets/
│   ├── plan_rules.md                 Specification (test basis); also inserted into prompts v2 and v3
│   ├── claim_triage.csv              35 claims with expected results
│   ├── validate_dataset.py           Reference implementation: checks the expected results against the rules
│   ├── judge_seeded_summaries.csv    Deliberately flawed summaries for judge validation
│   ├── policy_docs/                  Day 3 test basis: 10 member documents
│   ├── rag_golden.csv                Day 3 oracle: golden set v1.3, 15 questions
│   ├── validate_golden.py            Checks the Day 3 golden set against the documents
│   ├── testgen_golden.json           Day 4 oracle: golden set v1.0, 10 stories, 78 expected ideas
│   ├── testgen_golden.schema.json    Its JSON schema
│   ├── validate_testgen_golden.py    Checks the Day 4 golden set
│   └── testgen_seeded_defects.json   Seeded defects for testing the Day 4 judge
├── tests/
│   ├── test_rag.py                   5 automated tests for CI (deepeval test run)
│   └── conftest.py                   Test set-up: import path and .env
├── images/                           Diagrams used in notebooks 02 and 03
├── promptfoo/
│   ├── promptfooconfig.yaml          Main regression suite (3 prompts × 2 models × 35 claims)
│   ├── redteamconfig.yaml            Red-team configuration
│   ├── judge_validation.yaml         Judge regression suite (rubric v1 vs v2 on frozen outputs)
│   └── prompts/                      triage_v1.txt, triage_v2.txt, triage_v3.txt
└── results/                          Saved runs, labels and charts for all three notebooks
```

## How to run

**Prerequisites:** Anaconda or Miniconda, and an OpenAI API key with a spending limit set.

```bash
conda env create -f environment.yml
conda activate ai-testing
```

Create a `.env` file in the repo root containing `OPENAI_API_KEY=...`. It is listed in `.gitignore`; never commit it.

```bash
# 1. Check the dataset against the rules (free, no API calls)
python datasets/validate_dataset.py

# 2. Main suite, then the repeat run for stability
npx promptfoo@latest eval -c promptfoo/promptfooconfig.yaml -o results/promptfoo_v3.json
npx promptfoo@latest eval -c promptfoo/promptfooconfig.yaml --repeat 3 -o results/promptfoo_repeat3.json
python routing_stability.py results/promptfoo_repeat3.json

# 3. Red team (Promptfoo asks for email verification on first use)
npx promptfoo@latest redteam run -c promptfoo/redteamconfig.yaml
npx promptfoo@latest export eval latest -o results/redteam_results.json

# 4. Judge validation (needs the labels in results/judge_labels.csv)
python build_judge_cases.py
npx promptfoo@latest eval -c promptfoo/judge_validation.yaml --no-cache -o results/judge_validation.json

# 5. Browse any run interactively
npx promptfoo@latest view
```

Then open the notebook with `jupyter lab` and run all cells. A full run of the main suite makes 210 model calls
(35 claims × 3 prompts × 2 models) plus the same number of judge calls; [approximate cost].

**Notebook 02 (DeepEval)**

```bash
# 1. Check the golden set against the documents (free)
python datasets/validate_golden.py

# 2. The 5 CI tests: 1 free, 4 using the API (about 3 generator and 4 judge calls)
deepeval test run tests/test_rag.py
```

Add `DEEPEVAL_TELEMETRY_OPT_OUT=YES` to `.env` to keep DeepEval from sending usage data. Open the notebook and run
all cells: every step that calls the API is behind a `RUN_... = False` switch and shows the saved results in
`results/` instead, so a full re-run of the notebook is free. Re-running every paid step, smoke tests included, makes about
110 generator calls and 485 judge calls; [approximate cost].

**Notebook 03 (test generation)**

```bash
# 1. Check the golden set and print its fingerprints (free)
python datasets/validate_testgen_golden.py
python -m bench.golden

# 2. Generate one run: see the prompt first (free), then all 10 stories
python -m bench.generate --prompt v2 --dry-run
python -m bench.generate --prompt v2 --run 1

# 3. Test the judge on the seeded defects, then score a run (judge calls; appends to the history file)
python -m bench.score --seeded
python -m bench.score results/testgen/gen_v2_..._r1_....json

# 4. Calibration: build blind label sheets, label them, then compare
python -m bench.calibration build results/testgen/gen_v2_..._r1_....json
python -m bench.calibration compare results/testgen/score_v2_..._r1_....json
```

Open the notebook and run all cells: `RUN_GENERATE`, `RUN_SCORE` and `RUN_SEEDED` are `False`, so it reads
the saved results and a full re-run is free. Generating and scoring all six runs costs about $1.60, almost all of
it judge calls.

Tested with Promptfoo 0.124.1, DeepEval 4.2.8, scikit-learn 1.9.1, Node.js 22.22 and Python 3.11.

## About

Built by [your name], Head of QA, as hands-on learning in AI evaluation. Feedback is welcome via issues.
