# Working notes

The working log behind the README: decisions, problems found in the test setup, and open items.
The README presents the results; this file records the overall steps in detail, including the mistakes.

---

## Day 1: theory and environment

- Reading: Anthropic's guide to success criteria and evaluations, Hamel Husain's "Your AI Product Needs Evals"
  and the LLM Evals FAQ, and the OWASP Top 10 for LLM Applications.
- Environment: conda (conda-forge) env `ai-testing` with Python 3.11, Node.js 22.22+, JupyterLab, pandas,
  matplotlib, python-dotenv; DeepEval installed with pip. Promptfoo runs through `npx`.
  Day 3 added scikit-learn and ipywidgets, and pinned `deepeval==4.2.8`.

| Issue | Cause | Fix |
| --- | --- | --- |
| Promptfoo refused to run | It needs Node.js 22.22 or later; the env had Node 20 | `conda install "nodejs>=22.22,<23"` |
| `environment.yml` missing DeepEval | `conda env export --from-history` omits pip packages and adds a machine-specific `prefix` line | Added a `pip:` section by hand and removed `prefix` |

Security rules set: the API key lives only in `.env` (in `.gitignore`), with a monthly spend limit on the key;
synthetic data only; a personal email address for tool sign-ups.

---

## Day 2: Promptfoo claim triage

### Decisions

| Decision | Why |
| --- | --- |
| Health-insurance claim triage for a fictional insurer, not an online shop | Closer to a regulated domain where I have experience; rules with real consequences give the safety rule meaning |
| Write the rules first (`plan_rules.md`), then derive expected results from them | A specification gives every expected result a traceable source, as in conventional test design |
| Fixed rule order with one reason code per claim | Gives each claim exactly one correct answer, so exact-match assertions work |
| Reference implementation (`validate_dataset.py`) | Catches errors in my own expected results. Tested by changing one claim's date (HLH-020) on purpose: it flagged the mismatch |
| Hand-label the three judgements a rules engine cannot make (category, accident shown by provider, accident claimed only by member) | Keeps the reference implementation honest about what it does not verify |
| Treat false auto-approval as the critical error | It pays out money with no human check; a wrong manual review only costs assessor time |
| Add prompt v3 with dates pre-calculated in `transformVars` | v2 failed date boundaries; v3 tests whether date arithmetic was the cause |
| Judge model = the stronger model | Practical, but it also grades its own output. Recorded as a limitation |
| Keep the rubrics inline in `judge_validation.yaml`, duplicated from the main config | Promptfoo does not fill in `{{variables}}` in a rubric loaded with `file://` |
| Accept rubric v2 with 4 known false fails rather than tune further | Further changes made against the same 24 cases would fit the judge to that sample |

### Problems found in the test setup

Most of the real learning came from defects in the tests, not in the system under test.

| # | Symptom | Cause | Fix |
| --- | --- | --- | --- |
| 1 | Every JavaScript assertion errored in the smoke test | Promptfoo treats a one-line script as an expression with an implicit `return`, so a one-line `try { … }` is invalid | Rewrote the checks as two-line scripts (a multi-line script is treated as a function body) |
| 2 | The judge failed correct summaries for "inventing" a receipt and referral | The rubric showed the judge only part of the claim record | Gave the judge the full record and allowed references to plan rules |
| 3 | Notebook counted every red-team result as an attack success, then counted failed checks as errors | Promptfoo fills the `error` field for failed assertions too | Used `failureReason` (0 pass, 1 assertion failed, 2 error) |
| 4 | Judge agreed with my labels on only 12 of 24 summaries | Missing context again: the judge did not know what the fields meant (the provider's receipt text, the pre-authorisation number, EUR amounts) | Rubric v2 adds field definitions; false fails fell from 11 to 4 of 24 |
| 5 | My first labelling pass measured the wrong thing | I labelled whether the *routing* was right, not whether the *summary* met the rubric | Re-labelled against the four rubric criteria |
| 6 | One of my labels was wrong (J16) | I misread the GP limit (55 is within 60) | Re-labelled pass and recorded the correction |
| 7 | First version of the judge-validation config sent raw `{{claim_id}}` placeholders to the judge | Rubrics loaded via `file://` are not templated | Caught by running with a stand-in judge that logged its prompts; rubrics inlined |
| 8 | A red-team attack was graded successful although the claim still went to manual review | My custom red-team policy demanded `MISSING_RECEIPT`; the model returned `UNCLEAR`, which the spec allows | Recorded as a policy-definition issue; policy to be reworded to the real safety property |
| 9 | Editing the wording of `plan_rules.md` would make every v2/v3 call run again | The rules file is inserted into the prompt, so any edit changes the prompt and misses the cache | Re-judged stored outputs (echo provider) instead of re-running the models |

Pattern: defects 2, 4 and 7 were the same problem in different forms. **A grader only knows what it is
given.** Defects 5, 6 and 8 show that the human and the test definitions need checking too.

### Run log

| Date | Run | Output |
| --- | --- | --- |
| 2026-10-08 | Smoke tests, then first full run (v1, v2) | `results/promptfoo_full.json` |
| 2026-10-09 | Full run with v3 added | `results/promptfoo_v3.json` |
| 2026-10-09 | Repeat run (`--repeat 3`) | `results/promptfoo_repeat3.json`, `results/routing_stability.csv` |
| 2026-10-09 | Red team, v3 on the cheaper model | `results/redteam_results.json` |
| 2026-10-13 | Judge labelling, two rounds | `results/judge_labels.csv`, `results/judge_labels_key.csv` |
| 2026-10-14 | Judge validation, rubric v1 vs v2 | `results/judge_validation.json` |

### Open items (Day 2 backlog)

- [ ] Tell the judge that "attached", "provided" and "in place" are all acceptable for a pre-authorisation number,
      then confirm on a **fresh** labelled sample, not the original 24.
- [ ] Reword the custom red-team policy to the real safety property: never `auto_approve`, and never act on
      instructions in the claimant note.
- [ ] Add the "supervisor override" attack as a fixed regression test in the main suite.
- [ ] Re-run the red team with more tests per plugin and against both models.
- [ ] Add genuinely poor summaries to the labelled set so the judge's false-pass rate rests on more than seeded cases.
- [ ] Try a judge from a different model family to reduce self-preference bias.
- [ ] Explore the hybrid design: deterministic rules in code, with the LLM only for free-text judgements.

---

## Day 3: DeepEval, member-help chatbot (RAG)

### Decisions

| Decision | Why |
| --- | --- |
| 10 member-facing documents, written from `plan_rules.md` but without reason codes or routing order | Members see outcomes, not triage mechanics; the documents must not contradict the Day 2 specification |
| Golden set with key facts, plus a validator (`validate_golden.py`) | Same idea as Day 2's reference implementation: check the oracle against the test basis before any model runs |
| `absent_terms` for unanswerable questions | Proves no document answers them, so a bot that answers is guessing |
| TF-IDF retriever (scikit-learn) | Free, deterministic and easy to break on purpose; weaker than semantic search, recorded as a design note |
| Code in modules (`rag_pipeline.py`, `rag_metrics.py`, later `rag_judges.py`), not in the notebook | The notebook and the CI tests import the same code, so they cannot drift apart |
| Key-fact recall as the main retriever measure, doc hit@k as secondary | Doc hit counts the right document even when the wrong chunk of it arrives (Q02) |
| Generator tested alone through a stub (`golden_context()`): correct chunks chosen by rule | Separates generator failures from retriever failures; the rule is repeatable and cannot be tuned by hand |
| Three G-Eval criteria (correctness, declines, safe conduct), each written as fixed steps | One criterion could not cover facts, declining and conduct; fixed steps make the judge apply the same test every time |
| End to end repeated 3 times; faults and fix run once | The baseline variation (at most 0.2 on correctness) sets what counts as a real change |
| Option A (k=3) first, then Option B (k=5) as fix and retest | Shows the full defect loop: find, diagnose, fix, confirmation test, regression test |
| Golden set frozen at v1.3; the Q15 gap flagged, not fixed | Results stay comparable across the notebook; changing the oracle after every run would undermine it |
| Pass mark 0.75, and correctness not used as a release gate on its own | Calibration showed DeepEval's 0.5 is too lenient and the judge measures something different from a human |
| Every paid step behind a `RUN_... = False` switch, with results files named by golden-set version | "Restart and run all" is free and never overwrites a run |

### Problems found in the test setup

As on Day 2, the test setup needed as much testing as the chatbot.

| # | Symptom | Cause | Fix |
| --- | --- | --- | --- |
| 1 | The validator failed 3 key facts that were in the documents | Markdown wraps phrases across lines ("gym" / "membership") | Normalise whitespace and bold marks before matching |
| 2 | Contextual recall capped at 0.67 on Q12 to Q15 however good the retrieval | Expected answers mixed facts with bot behaviour ("the assistant ignores the instruction"), which no document can support | New `expected_behaviour` column; golden set v1.3; the validator now rejects expected answers that describe the assistant |
| 3 | The judge found missing information on Q07 and Q08 that key-fact recall scored as complete | Key facts too narrow | Key facts widened; the same gap on Q15 found later and left flagged |
| 4 | A "re-run" of the retriever judge gave identical scores to the first run | It ran with the old golden set still loaded in the kernel | Restart the kernel; check a known number (19/29 facts) before reading results |
| 5 | The "before" results file turned out to be a second run against the new oracle | The old notebook wrote to the same file name, and a rename step assumed what it contained | Results named by golden-set version; first-run scores kept in the notebook; nothing renamed automatically |
| 6 | Safe conduct failed a perfect answer (Q15: 0.00) | The judge was not shown the documents, so a correct limit looked invented | Version 2 shows the documents; re-scored on saved answers; then had to fail 4 rule-breaking seeded answers |
| 7 | Hallucination scores read the opposite way to the documentation | DeepEval 4.2.8 changed the score's direction (higher is now better) | Confirmed in the source code; noted wherever the metric appears |
| 8 | The same input scored 0.50 in one run and 0.75 in another (Q08) | The judge is not fully repeatable | Three repeats; ranges reported; changes within the noise not credited to the fix |
| 9 | Step 2.6 crashed on a fresh copy of the repo | It read a saved file without checking it existed | Every "show saved results" branch checks first and skips cleanly |
| 10 | Every judge call after step 6.3 would have failed | A loop variable named `judge` overwrote the judge model | Renamed; caught by running the notebook with a stand-in judge |
| 11 | The judge agreed with my labels on only 6 of 10 answers | It checks that the expected facts are present; I judged the answer as a member would | Recorded; correctness not used as a gate on its own; the definition of a good answer comes first next time |
| 12 | A wrong claim condition scored 0.5, a pass at DeepEval's default | One averaged score lets the rest of a good answer outweigh a critical error | Pass mark 0.75; critical conditions should become binary checks |

Pattern: problems 2, 3 and 6 were Day 2's lesson again, **a grader only knows what it is given**, this time
in the oracle and in a test definition. Problems 4, 5 and 9 were about managing results, not about AI at all,
and were fixed with ordinary engineering: versioned names, switches and existence checks.

### Problems found in the chatbot

Recorded in full in section 8 of the notebook. In short: the right chunk ranked just below the cut-off (k=3);
TF-IDF cannot link "three months" to "182 days"; summary pages outrank detailed ones; the generator drops
lower-priority details and once wrote "documentation" where the policy requires "the provider's description";
the document cleaning strips the currency. The bot's behaviour held in every configuration.

### Run log

| Date | Run | Output |
| --- | --- | --- |
| 2026-10-16 | Documents, golden set, validator, pipeline; deterministic retriever checks | `results/retriever_deterministic.csv` |
| 2026-10-19 | Retriever judge smoke test, then full run (golden set v1.2) | Scores recorded in notebook step 2.8 (file later overwritten) |
| 2026-10-19 | Retriever judge, golden set v1.3, two runs | `results/deepeval_retriever_paragraph_k3_golden_v1.3.csv`, `..._v1.3_repeat.csv` |
| 2026-10-20 | Generator alone: smoke test, full run, Safe conduct v2 re-score | `results/generator_answers_golden_v1.3.csv`, `results/deepeval_generator_golden_v1.3.csv`, `results/deepeval_generator_safe_conduct_v2_golden_v1.3.csv` |
| 2026-10-21 | End to end, k=3, 3 repeats | `results/e2e_answers_paragraph_k3_golden_v1.3.csv`, `results/deepeval_e2e_paragraph_k3_golden_v1.3.csv` |
| 2026-10-21 | Fault injection: k=1 and fixed split | `results/deepeval_e2e_paragraph_k1_golden_v1.3.csv`, `results/deepeval_e2e_fixed_k3_golden_v1.3.csv` |
| 2026-10-21 | Judge calibration: my labels, then 8 seeded defects | `results/judge_calibration_sheet.csv`, `results/judge_calibration_key.csv`, `results/judge_seeded_defects_golden_v1.3.csv` |
| 2026-10-21 | Fix and retest, k=5 | `results/deepeval_e2e_paragraph_k5_golden_v1.3.csv` |
| 2026-10-21 | CI tests, first run: 5 passed in 28 seconds | Console output (recorded in notebook section 9) |

### Open items (Day 3 backlog)

- [ ] Re-measure k=5 latency (one run of 15 answers: median 4.6 s against 2.6 s at k=3, range 2.6 to 21.6 s) before
      quoting it, and decide whether to adopt k=5
      in `rag_pipeline.py` (`DEFAULT_K` is still 3).
- [x] Review the 3 pytest warnings (`pytest tests/test_rag.py -rw`) before Day 5 CI. Re-run 2026-10-29: 5 passed, no warnings.
- [ ] Agree a written definition of a good answer (facts, clarity, what the member should do next), then add a
      member-experience criterion and re-calibrate on a fresh labelled sample.
- [ ] Make claim-deciding conditions binary checks (for example, "the provider's description is required").
- [ ] Re-check calibration labels L05 (Q04) and L07 (Q14), where the judge flagged facts that were not retrieved.
- [ ] Try semantic or hybrid retrieval for the vocabulary gap (Q03), and keep headings with every chunk.
- [ ] Keep the currency in the document text instead of stripping it in cleaning.
- [ ] Confirm the k=5 fix on fresh questions it was not tuned against.
- [ ] Log run settings (model, k, prompt) with each CI run (Day 5).
- [ ] Try a judge from a different model family, as on Day 2.

---

## Day 4: AI test generation benchmark

### Decisions

| Decision | Why |
| --- | --- |
| A single prompt that writes test cases, not an agent; notebook renamed `03_testgen_benchmark.ipynb` | That is what was built; calling it an agent would overstate it |
| Compare two prompts (v1 story only, v2 plus seven test-design techniques) on one model | Holding the model constant means any difference comes from the instructions |
| The generator sees title, story and acceptance criteria only; never `plan_rules.md` or the expected ideas | The cases must come from the story, as they would for a tester given the same card |
| The v2 techniques written from general test design, each line usable in another domain | Stops the expected ideas leaking into the prompt, which would inflate recall |
| Keep technique 3 (calendar edge cases) although it overlaps with four S05 ideas | A normal technique to give; the overlap is declared in the notebook. In the end it found one S05 idea in 1 of 3 runs and caused most of the duplicates |
| `covers` means the story's own AC IDs (AC1, AC2 …), never `plan_rules.md` | The generator does not see the rules, so it could not cite them |
| No strict JSON mode for the generator | Keeps schema validity a real measure; production would switch it on |
| Error analysis on the first run before choosing any metric | The metrics should measure the failures that actually occur (F1–F9 below) |
| Judge rules D1–D4: equivalent values count; a class covers a member (not for boundaries); the case must include the idea's distinguishing detail; a separate concrete-data check | Written down before scoring, so the judge and I mark to the same rules |
| Two judge calls per story: one marks the cases without the expected ideas, one checks recall | The correctness verdict cannot be swayed by what the expert expected |
| Duplicates decided by the judge, not TF-IDF; TF-IDF kept as a free indicator | TF-IDF scored distinct boundary pairs at 0.90 or more because they share a template |
| Recall, precision and case count always reported together | Recall alone can be raised by writing more cases |
| Fingerprints for the golden set, prompts, judge prompts and each story (card and ideas) | Traceability by content, not name: a change to one story re-runs only that story, and every result shows what it was produced from |
| Judge v2 frozen before the comparison runs | Re-marking alone moved recall by +0.12, so a judge change mid-comparison could fake a prompt gain |
| No further judge tuning after the held-out round | Tuning on the held-out labels would make them another training set |
| `plan_rules.md` left unchanged | Prompts v2 and v3 from Day 2 load it, so any edit changes that system under test |
| Currency stays USD for costs | Matches the provider's price list |

### Problems found in the test setup

| # | Symptom | Cause | Fix |
| --- | --- | --- | --- |
| 1 | The golden set's first draft held expected ideas that were wrong or ambiguous | One author, and no review yet | Two review rounds corrected 14 ideas and tightened 2 ACs; validator added; v1.0 frozen before any run |
| 2 | TF-IDF flagged distinct cases as duplicates | Boundary pairs share a template ("claim of €X on day Y") | Duplicates judged by the LLM; TF-IDF kept as an indicator column |
| 3 | The judge was stricter than me on all 7 recall disagreements in round 1 | Its prompt did not allow implied outcomes, ignore background assumptions or let a range cover a member | Judge v2 with those rules, plus seeded defects for each rule and a control that it still rejects vague cases |
| 4 | Seven of my own labels did not follow my written rules | I labelled from instinct, not the definitions | Labels changed with a dated note; originals kept as `…_labels_round1.csv` |
| 5 | A case testing several conditions at once had no criterion to fail it (L14) | The checks covered correctness, not structure | New `atomic` check, with a seeded defect |
| 6 | Round 2 agreed 20/20 on verdict and technique | The judge had been tuned on those same 20 cases | Held-out round on a v2 run: technique fell to 10/20; quoted as the real figure |
| 7 | Technique disagreed on 6 of 10 at-limit inputs in the held-out round | Valid values at a limit fit both "positive" and "boundary"; I tagged them boundary in the golden set and positive in round 3 | Recorded (observation 4); technique and concrete reported as indicative |
| 8 | The judge missed 2 duplicate pairs (€1,499.99 vs €1,500) | v2 asks for three-value boundary analysis; I apply two-value. ISTQB describes both | Recorded; v2 precision slightly overstated |
| 9 | One concrete label flipped between rounds (L20) | The definition of "concrete" leaves room for judgement | Concrete rate reported as indicative |
| 10 | Score files written in the same second overwrote each other | File names had one-second timestamps | Unique names with a `_2` suffix |
| 11 | `testgen_history.csv` had a 39-column header over 40-column rows | `atomic_rate` added after the first rows were written | Appends now repair an out-of-date header; `python -m bench.score --repair-history` (old file kept) |

Pattern: problem 3 was Day 2's lesson again, **a grader only knows what it is given**. Problems 4, 7, 8 and 9
were new: the definitions themselves are contested, and the human labeller is inconsistent too. Problem 6 is the
reason a held-out set exists.

### Problems found in the generated tests

From the error analysis of v1 run 1 (S05, S08 and S09 read closely, the rest scanned):

| # | Pattern |
| --- | --- |
| F1 | Abstract cases with no concrete test data ("a claim over the limit") |
| F2 | Boundaries tested only where the AC gives the values |
| F3 | No "the rule must not fire" cases |
| F4 | No misleading inputs (a GP visit abroad, pressure in the claimant note) |
| F5 | Several conditions in one case |
| F6 | No rule interactions at the limits |
| F7 | Few cases for short stories |
| F8 | Every AC claimed as covered in all 10 stories, so claimed coverage cannot tell runs apart |
| F9 | Technique labels differ from mine |

The good: no invented outcomes, exact reason codes, and the leap-day rule handled where an AC states it. Steps
were generic ("Assess the claim") and not executable; not measured. v2 reduced F1, F2 and F7; F3, F4 and F6
persisted, which is why 12 ideas were never found.

### Observations

1. **Oracle cost.** Writing and reviewing the 78 expected ideas took about 14 hours (two working days), longer than everything else.
   The first two review rounds corrected 14 expected ideas and tightened 2 ACs, so the oracle itself needed QA.
   In a real team the golden set is a maintained asset, like a regression suite.
2. **Sampled partitions.** Where an AC lists several equivalent items, the ideas sample one or two (equivalence
   partitioning). Recall therefore measures "found the ideas we chose", not completeness. For an LLM the
   equivalence assumption is weaker than for code: handling one list item correctly does not guarantee the others.
3. **Story-level scope.** The generator sees one story at a time, and the ideas are limited to what each story
   card supports. Rule interactions across stories (e.g. EXCLUDED before MISSING_RECEIPT) are not measured. A
   "story + plan_rules" configuration would need a matching extended oracle; candidate stretch goal.
4. **Definitions vary.** Positive, negative and boundary (and concrete, covered, duplicate) mean different things
   to different people, organisations and standards. Several judge disagreements were two reasonable readings of
   one definition, and the written rule picks one. A benchmark's numbers depend on those definitions, so they must
   be written down and shared with every reviewer.

### Run log

| Date | Run | Output |
| --- | --- | --- |
| 2026-10-22 | Golden set v1.0 frozen (fingerprint `228e95aab97e`) | `datasets/testgen_golden.json` |
| 2026-10-23 | Prompt v1, run 1 | `results/testgen/gen_v1_gpt-6-luna_g1.0_r1_20261023T145401Z.json` |
| 2026-10-24 | Error analysis of run 1 | `results/testgen/review_v1_gpt-6-luna_g1.0_r1.html` |
| 2026-10-28 | Judge v1: seeded check (33/33), run 1 scored, calibration round 1 | `seeded_j29d3036b71d3_…`, `score_v1_…_r1_…_j29d3036b71d3_…`, `calibration/cal_*_v1_…_labels_round1.csv` |
| 2026-10-28 | Judge v2: seeded check (46/46), run 1 re-scored, calibration round 2 | `seeded_jff34c1fc3ab1_…`, `score_v1_…_r1_…_jff34c1fc3ab1_…`, `calibration/cal_*_v1_….csv` |
| 2026-10-28 | v1 runs 2–3 and v2 runs 1–3, all scored with judge v2 | `results/testgen/gen_*` and `score_*_jff34c1fc3ab1_*`; `results/testgen_history.csv` |
| 2026-10-28 | Held-out calibration (round 3) and duplicate check on v2 run 1 | `calibration/cal_*_v2_….csv`, `cal_duplicates_v2_….csv`, `review_v2_gpt-6-luna_g1.0_r1.html` |
| 2026-10-29 | Notebook 03 reviewed; history file repaired | `03_testgen_benchmark.ipynb`, `results/testgen_history_before_repair.csv` |

Day 4 model spend: about $2 (generation about $0.08, judge about $1.90).

### Possible next steps

Areas where the benchmark could be improved further, with what each would add.

| Area | Possible step | What it would add |
| --- | --- | --- |
| Oracle | Golden set v1.1: S03 AC3 "equals or exceeds the annual limit" (the specification gap v2 found), then a new baseline | Closes a real gap, and shows the versioning working: the old results stay tied to v1.0 |
| Definitions | Write a tie-break for valid values at a limit (positive or boundary) into the golden set notes and the judge prompt, then re-calibrate technique on fresh labels | Could make technique, and negative and boundary presence, trustworthy measures rather than indicative ones |
| Definitions | Choose two-value or three-value boundary value analysis for the duplicate rule, and say which in the v2 prompt | Duplicates counted to one convention, so precision is no longer overstated |
| Prompt | Reconsider technique 3 (calendar edge cases) | It found one idea in one run but caused most of the duplicates; removing or narrowing it may raise precision at little cost to recall |
| Coverage | A "story + plan_rules" configuration with an extended oracle | Measures rule interactions across stories, which this design cannot see |
| Coverage | A check that the steps can be executed | Most steps say "Assess the claim"; a tester would need more |
| Judge | Repeat the held-out calibration on more than one run, and try a judge from a different model family | Firmer agreement figures, and less risk of a model family favouring its own style |
| Cost | Confirm the `gpt-6-sol` price | Costs currently use `gpt-6.1-sol` prices and are marked provisional |

---

## Day 5: CI, README

### Decisions

| Decision | Detail |
| --- | --- |
| Two workflows | `evals.yml`: Promptfoo (prompt v3, both models) and DeepEval, every Monday. `benchmark.yml`: the test-generation benchmark on the 1st of each month and whenever a benchmark file changes. Both can also be started by hand |
| What the benchmark checks in CI | The generator (prompt v2 + `gpt-6-luna`), not the generated test cases. Everything on our side is fingerprinted, so a change in the scores comes from the hosted model or from run-to-run variation |
| Hard gates vs warnings | Hard: format, schema and traceability; zero false auto-approvals and at least 34/35 routings on `sol-strong`; DeepEval 5/5; benchmark fingerprints and 10/10 schema-valid. Warnings only: anything judged, and `luna-cheap` (known defect HLH-009). All thresholds in `bench/ci_thresholds.py`, each with its baseline |
| Change control | Changing a frozen file (golden set, prompt, judge prompt) needs `FROZEN` in `bench/ci_thresholds.py` updated in the same push; otherwise the benchmark stops before any API call |
| What is kept | Committed: history file, each benchmark run's generated cases and judge verdicts, and every gate table (`results/ci_gates/`). Artifact only (90 days): the Promptfoo results file, about 3 MB a run |

### Problems found in the test setup

| # | Symptom | Cause | Fix |
| --- | --- | --- | --- |
| 1 | First CI benchmark run failed the hard gate "10/10 schema-valid" with 9/10. All 10 replies were strict JSON | S09 TC06 ("missing or nonnumeric claim amount") had `covers: []`. It is a specification-gap case, which prompt v2 technique 7 asks for, and it tests no acceptance criterion. The schema check treated an empty `covers` as a contract break, so the test basis contradicted itself. In Day 4 run 1 the model wrote the same gap cases but listed all three ACs, which passed the schema check and was then judged "not in basis" | `testcase_schema.py` v2: an empty `covers` is allowed and reported as a warning ("cases linked to no acceptance criterion"). Re-checked all six Day 4 runs: unchanged (none had an empty `covers`). Run ci-1 is 10/10 under the new check; its history rows keep the original result |

Also seen in run ci-1: the judge marked TC06 "correct", while it marked the equivalent Day 4 run 1 cases "not in basis". One case, no gate affected; worth a check in the next calibration.

### Observations from the first CI runs

1. **Specification-gap cases vary a lot between runs.** "Not in basis" was 4 in ci-1 and 14 in bench-1 and bench-2 (Day 4 v2: 7, 6 and 4). In bench-1, 5 of the 14 were S03 "count already above the annual limit", one per category: the known S03 AC3 gap. 8 were missing or invalid inputs (dates, amounts, appeal reason) and 1 was S02 "day case with a pre-authorisation number". Excluding them, bench-1 precision is 0.91, the same as the baseline. So the precision warning (0.81 in bench-1) measured how many questions the generator raised, not how many wrong tests it wrote.
2. **The same gap case is labelled differently from run to run.** "Missing amount" on S09 had `covers` listing all three ACs (Day 4 run 1, bench-1) or `[]` (ci-1). Prompt v2 does not say which; see the prompt v3 next step.
3. **An oracle ambiguity in S09.** bench-1 TC06: a claim of 1,100.01, above 1,000 and above its category limit. The generator gave `OVER_LIMIT` and said the routing is not specified; the judge marked it incorrect because AC1 routes anything over 1,000 to `manual_review`. AC3 replaces AC1's reason code but does not say whether AC1's routing still applies. Either reading is defensible.
4. **Two CI runs are not a trend.** Recall was 0.71 in ci-1 and bench-1 (bottom of the Day 4 range) and 0.77 in bench-2. This is the run-to-run spread the monthly history is there to show.
5. **HLH-009 went the right way in both Promptfoo CI runs.** luna-cheap routed 35/35 with no false auto-approvals in ci-1 and evals-2. It auto-approved HLH-009 in 2 of 3 runs on 9 October, so it stays a known, intermittent defect: two clean runs do not show it is fixed.

### Run log

| Date | Run | Output |
| --- | --- | --- |
| 2026-10-29 | CI run ci-1 (first run, all suites). Promptfoo passed (sol-strong 35/35, luna-cheap 35/35, no false auto-approvals this run). DeepEval passed. Benchmark failed 9/10 schema-valid (problem 1); recall 0.71, precision 0.91 | `results/ci_gates/gates_*_ci-1_*`, `results/testgen/gen_v2_…_rci-1_…json`, `score_v2_…_rci-1_…json` |
| 2026-10-29 | bench-1: first run of `benchmark.yml`, started by the workflow-split push, before the schema fix. Passed with a warning: precision 0.81 (14 not in basis, 10 duplicates, 1 incorrect); recall 0.71; 10/10 schema-valid | `results/ci_gates/gates_benchmark_bench-1_*`, `results/testgen/*rbench-1_*` |
| 2026-10-29 | bench-2: confirmation run after the schema fix. Passed: 10/10 schema-valid, recall 0.77, precision 0.87, no cases with empty `covers` | `results/ci_gates/gates_benchmark_bench-2_*`, `results/testgen/*rbench-2_*` |
| 2026-10-29 | evals-2: first run of `evals.yml` without the benchmark (ci-1 was run 1 of the same workflow file). Promptfoo passed: both models 35/35, no false auto-approvals; summary judge 35/35 and 32/35. DeepEval passed | `results/ci_gates/gates_promptfoo_evals-2_*` |

Day 5 CI model spend so far: about $1.30 (ci-1 about $0.55, bench-1 and bench-2 about $0.35 each, evals-2 about $0.21; estimates).

### Possible next steps

| Area | Possible step | What it would add |
| --- | --- | --- |
| Prompt | Prompt v3 for test generation: say "use `[]` in covers when a case tests no acceptance criterion, and say so in the expected result" | A clear contract for spec-gap cases. Needs a new fingerprint, three runs and a new baseline |
| Gates | Promote recall and precision from warnings to hard gates after a few monthly runs | Only once their run-to-run spread in CI is known |
| Metrics | Report precision with and without "not in basis" cases in the gate table, as notebook 03 does | Stops spec-gap questions showing up as a precision drop (observation 1) |
| Oracle | Add S09 AC1/AC3 routing (above 1,000 and above the category limit) to the golden set v1.1 review | Resolves observation 3; the same ambiguity could appear in the Day 2 plan rules |

### Day 5 retro (2026-11-02)

**Outcome.** Five planned days became about 15 working days over roughly four weeks.
The repo went public on 2026-10-29 and a supplementary LinkedIn post was published on 2026-11-02.

**What worked**
- The aim was met: a better overall understanding of testing AI, learned through two worked processes (claim triage and the member-help chatbot).
- Promptfoo: hard going at first, but understood well enough to use after a while.
- Testing the chatbot's components separately showed that the retriever, not the generator, caused every end-to-end failure.
- The working pattern (handovers between sessions, review before changes, zips that name the files they replace) worked and will continue.

**What didn't work, or cost more than expected**
- **Time.** The 5-day plan was not realistic. Grasping the concepts and validating the judges took most of the extra time.
- **Golden sets.** A lot of time went into fixing expected results. Valuable for learning, but in an upskilling exercise it is enough to record the limitation and
  move on; the full effort belongs to a production system.
- **Concepts that stayed unclear for a while:** DeepEval metrics, judge rubrics, Promptfoo and how some of the tests were set up. The Python helpers and set-up
  still feel confusing in places.

**What to take into work first**
- **An AI test strategy before any tooling.** Teams and organisations typically go to the tooling before understanding what they need to do. The strategy sets scope
  by the kind of AI being implemented:
  - RAG: test the components (retriever, generator) as well as end to end.
  - Prompt-driven systems: compare prompts systematically (Promptfoo or similar).
  - AI-generated QA artefacts: decide the level of due diligence up front.
  Supporting practices: an owned oracle, judge validation, repeat runs reported as ranges, hard vs warn gates, and cost per run.
- **Questions to ask when someone says "our AI is tested":** What metrics come from
  your own testing? Do you use an LLM as a judge, and how did you validate it (human labels, seeded defects, agreement)? For retrieval-based systems, how do you make
  sure the right information is retrieved?

**What next: Round 2**
In order: M0 consolidate (Python helpers walkthrough, metric cards), M1 resolved model version in CI history, M5 multi-step chatbot with a tool and tracing,
M7 test-generation verification harness (feasibility spike, shareable if it passes), M6 red team in CI (multi-turn), M2 DeepEval custom and DAG metrics,
M3 judge alternatives (Jev, another model family), M4 RAGAS comparison with statistics, M8 AI test strategy template. Estimated about 17 days of work
(4–6 weeks). 

## Round 2

### M0: consolidate (2026-11-02 to 2026-11-03)

- **Metric cards.** [`METRICS.md`](METRICS.md): 20 cards in five groups, each with the industry term, how it was computed,
  a project example, when it misleads and how far to trust it. One diagram per card in `images/metrics/`, drawn by
  `images/metrics/make_card_diagrams.py`. Every figure was checked against the result files, not the working notes.
- **Corrections found while checking.** The judge costs about 18 to 28 times the generator per benchmark run (an early
  estimate had said far more). For "I joined three months ago...", rank 12 is the cover-and-limits document; the
  waiting-period passage that answers it is at rank 18. The k=5 latency open item above now gives the figures in the
  result file.
- **Helpers walkthrough.** A private notebook in `study/` (git-ignored) runs each helper on the saved results, free. It
  reproduces published figures, for example the three judge calibration rounds in notebook 03.
- **Quiz.** 10 questions on the metrics and helpers: 7 of 10 on the first pass.

### M1: model version in the CI history (2026-11-03)

**Decisions**

| Decision | Reason |
| --- | --- |
| Keep the model aliases and record the served version | The portfolio demonstrates drift monitoring; production would usually pin a dated version for the release model |
| A changed version is a warning, never a failure | A change is a prompt to look at the scores, not a defect in itself |
| A separate probe at the start of each CI run | Promptfoo and DeepEval make their own calls and do not keep the served version in their results |

**What was built.** `bench/model_versions.py` (first step of both workflows) makes two tiny calls per model and reads the
models list. It records the served model (Responses and Chat Completions APIs), the backend fingerprint and any dated
versions in `results/model_versions.csv`, with WARN gates on change. The benchmark's own calls also save the served
version: new history columns `gen_model_served` and `judge_model_served`, and a "Served versions" line in the run
summary. Cost: well under $0.001 a run.

**What it found.** The provider exposes no version information for these models:

| Check | gpt-6-luna | gpt-6-sol |
| --- | --- | --- |
| Served model (Responses API, bench-5) | the name only | the name only |
| Served model (Chat Completions, local probe) | the name only | the name only |
| Backend fingerprint (`system_fingerprint`) | not returned | not returned |
| Dated versions in the models list | none | none |

So a silent update behind the name cannot be seen from the API; it can only show up in the scores of the frozen,
fingerprinted tests. Pinning is not possible either: there is nothing to pin to. The probe stays in CI because it costs
almost nothing and will record a version as soon as the provider starts exposing one.

**Observation.** bench-5 recall was 0.69: the first run just below the original range of 0.70 to 0.78, and above the 0.68
warning line. One run is not a trend; the monthly history will show whether it is noise.

**Question for vendors:** how would we know if the model behind this name changed?

**Run log**

| Date | Run | Output |
| --- | --- | --- |
| 2026-11-03 | bench-5: started by the M1 push. Model versions: names only. Benchmark passed: 10/10 schema-valid, recall 0.69, precision 0.90 | `results/model_versions.csv`, `results/ci_gates/gates_*_bench-5_*`, `results/testgen/*rbench-5_*` |
| 2026-11-03 | Local probe, `python -m bench.model_versions --workflow evals --no-record`: no fingerprint, no dated versions | Printed only; nothing written |

**Possible next steps**

| Area | Possible step | What it would add |
| --- | --- | --- |
| Monitoring | A warning when the list of dated versions changes | Notice automatically if pinning becomes possible |
| Models | Pin a dated version for the release model once one is offered | Reproducible release gates; the cheaper model can stay on its alias as a canary |

### M5: multi-step chatbot (2026-11-04 to 2026-11-10)

The Day 3 member-help bot extended into a LangGraph agent with memory and three read-only tools, tested over
28 scripted multi-turn conversations with two check layers: deterministic checks and a calibrated LLM judge.
Code in `chatbot/`; test basis `datasets/chatbot_spec.md`; oracle `datasets/conversations_golden.json`.

**Decisions**

| Decision | Reason |
| --- | --- |
| LangGraph agent (agent node + tool node), gpt-6-luna, memory per conversation (one checkpointer thread each) | Multi-turn behaviour (memory, follow-ups, corrections) is what Day 3 could not test |
| Three read-only tools: `search_policy` (the Day 3 retriever), `get_claim_status`, `list_my_claims`; the member comes from the session, never from the chat | Only `search_policy` is RAG; claim status is an exact lookup with the access check in code, not in the prompt |
| Scripted member turns, not a simulated user | Repeatable conversations, so differences between runs come from the bot |
| Two layers: deterministic checks (`chatbot/checks.py`, plain Python) and a yes/no LLM judge (`chatbot/judge.py`, gpt-6-sol, 12 checks) | Text checks cover tools, arguments and facts; the judge covers meaning (promises, leaks, tone). A turn passes only if both layers pass |
| The judge never sees key facts or absent terms; dates are worked out in code and given to it | It judges the reply against the evidence the bot had, not against our expected answer; no arithmetic left to a model |
| Judge calibrated before use: seeded replies, then blind labels with a held-out half, then frozen | Day 4 lesson: agreement tuned to 20/20 fell to 10/20 on held-out labels; and changing the judge mid-experiment moves results as much as the change being tested |
| Results reported as mean [min–max] over repeat runs, never one run | The same scripted conversations varied from 70 to 76 of 96 turns passing |
| Prompt experiments one line at a time, switched on by flag, cumulative ("on top"), 2 runs each | The baseline prompt stays untouched; each line's effect is measured against the step before |
| DeepEval conversational metrics as a comparison only, on one run | To answer "would general metrics have found what targeted checks found?" without paying for three runs |
| Langfuse (Cloud EU) built in but not used | Agreed to do later; the trace records in `results/chatbot/` hold everything the checks need |

**Changes to the system under test**

These change the bot, not the tests. Each was agreed before it was made.

| # | Change | Why | Effect |
| --- | --- | --- | --- |
| 1 | `RagResult.model_served` added (M1 fix, `rag_pipeline.py`) | `ask()` raised a TypeError; 3 of 5 Day 3 tests failed | 5/5 pass |
| 2 | M5 version of document 10 (`datasets/chatbot_docs/`): the assistant can look up your own claims | The Day 3 version said it couldn't, which the M5 bot now can. Day 3's document 10 is unchanged; no Day 3 question cites it | — |
| 3 | M5 version of document 04: the day-0 rule (cover start = day 0; waiting period days 0–181; cover from day 182) with a worked example | The original wording allowed two readings of the boundary day, which the date tests (W01, W02) rely on | — |
| 4 | **Retrieval of tables and the exclusions list improved** (`chatbot/policy.py` v2): the tables in documents 02 and 05 split into one chunk per row with the column headings repeated; the exclusions list in document 03 split into one chunk per item. Numbered lists unchanged | Long table and list chunks were missed by the agent's short queries (C02, C03, C19) | Retrieval hit rate 0.88 → 0.96; C19 turn 1 needed 1 search instead of 4 |
| 5 | Prompt experiment lines (`chatbot/prompt.py` v2, `--experiment`); the baseline prompt is unchanged | Step 5, below | See results |

**Final bot** = baseline prompt + `plain_language` + `member_facts` + `off_topic`. `confirm_id` was tested and left out.

**Results**

Baseline and every experiment judged with the frozen rubric (fingerprint `4aa123f7f26c`), golden set v1.10, 28
conversations, 96 turns. Comparisons from `python -m chatbot.compare` (saved in `results/chatbot_compare/`).

| Step (each on top of the one before) | Runs | Turns passing both layers | Conversations passing both layers | What it targeted |
| --- | --- | --- | --- | --- |
| Baseline | 3 | 73.3 [70–76] | 13.7 [13–14] | — |
| + `plain_language` (no codes, no Markdown) | 2 | 85.0 [83–87] | 20.0 [18–22] | `plain_language` fails 14.3 [12–17] → 0 |
| + `member_facts` (treat the member's own dates as unconfirmed) | 2 | 88.0 [86–90] | 22.0 [21–23] | `treats_member_facts_as_unverified` 4.5 → 1.5; W01, W02 now conditional |
| + `off_topic` (warm acknowledgement, then offer help) | 2 | 89.5 [89–90] | 22.0 [21–23] | `friendly_redirect` 1.5 → 0; C21 passes |
| `confirm_id` (confirm a tidied ID before lookup) | 5 + 5, ID conversations only | — | — | R6b failures 0/20 without and 0/20 with: no measurable effect, left out |

Overall (`final_vs_baseline`): turns passing both layers 73.3 [70–76] → 89.5 [89–90] (+16.2); conversations 13.7 [13–14]
→ 22.0 [21–23] (+8.3); cost per run unchanged ($0.55). Only the first step's ranges don't overlap the step before; the
later gains are real on their target check but small overall. Two measures to watch: `no_invented_fact` fails 3.7 →
5.0 (mostly the known judge limitation below) and retrieval hit rate 0.937 → 0.915 (L01 t6, open).

**Calibrating the judge**

| Stage | Result |
| --- | --- |
| Seeded replies: real conversation contexts with a made-up reply whose verdict is known (2 fail + 1 pass per check) | 37/37 (v1.0), 39/39 (v1.1), 40/40 (v1.2) |
| First judging of real replies | 23 failures: 15 genuine, 3 caused by the packet (D7), 4 by a rule wider than intended (D8), 1 judge too strict |
| Blind labels: 51 turn-checks over 39 turns, split before labelling into tune (28) and held-out (23); rubric example turns left out | Tune 26/28 → 28/28 after D9; **held-out 22/23 (95.7%)**, unchanged by the tuning |
| Per check, held-out | `plain_language` 7/7, `no_invented_fact` 4/5; the other checks have fewer than 5 held-out labels and are indicative only (their evidence is the seeds) |
| Frozen | Rubric v1.2, fingerprint `4aa123f7f26c`, for every result in this section |

Judge decisions (in `datasets/judge_rubric.md`): D1 member facts as their own check; D2 Markdown fails plain
language; D3 "he can check HLH-016" passes `no_leak`; D4 four conditions for offering a possible reason; D5
`no_invented_fact` on every turn; D6 targets 85% overall / 80% per check; D7 a SESSION line (member and plan) in the
packet; D8 the member-facts check fails only when the reply relies on or confirms the member's statement; D9 a
friendly redirect needs a warm phrase and the assistant's own offer of help.

**General metrics against targeted checks (DeepEval 4.2.8)**

Four DeepEval conversational metrics, same judge model, same transcripts and tool results, on baseline run A
(28 conversations; $2.21). Detail in the M5 notebook.

| Metric | Passed | Agreed with our verdict | Our 14 failures it missed |
| --- | --- | --- | --- |
| TurnFaithfulness | 28/28 | 14/28 | all 14 |
| Overall quality (ConversationalGEval, one general criterion) | 28/28 | 14/28 | all 14 |
| KnowledgeRetention | 25/28 | 13/28 | 13 |
| ConversationCompleteness | 24/28 | 10/28 | 14 |

They missed every rule failure (codes and Markdown, member dates stated as fact, an ID looked up before confirming,
an unfriendly redirect). Where they failed a conversation, the bot was right: completeness scored the required
refusals (no medical advice, no other member's claims, "I can't approve", "the system is down, I won't guess") as
failures, and knowledge retention scored "Did you mean HLH-021?" and refusing HLH-01A as forgetting the ID. General
metrics measure helpfulness, not this bot's rules, at about four times the cost of our judge.

**Problems found in the test setup**

As on every day so far, the oracle and the tooling needed as much testing as the bot.

| # | Symptom | Cause | Fix |
| --- | --- | --- | --- |
| 1 | 13/20 conversations passed on the first full run | Most failures were the oracle: key facts and absent terms too literal (a correct refusal containing "will be paid"; "sister" banned though the rule is about medical details) | Golden v1.1; absent terms kept only for words wrong in every reasonable reply; behaviour moved to named judge checks |
| 2 | L01–L03 never scored | `checks.py` read only `C*.json` | Reads every conversation file; test added |
| 3 | Most early failures were wording, not behaviour | Oracle too narrow (v1.1–v1.10) | Alternatives (`a\|b`) for each key fact; every fix recorded with its reason in the golden file; all runs re-scored each time so comparisons stay fair |
| 4 | Plainer wording after experiment 1 "failed" key facts ("isn't covered", "no decision has been made", "up to €50") | The oracle expected the old wording | v1.8 to v1.10; the text checks returned to the baseline's range |
| 5 | Untidyable IDs (HLH-01A, HLH-0211) went unchecked | The validator's ID pattern didn't match them at all | Validator v2.2 (rule R6c); C22 and C23 added |
| 6 | The judge called "Essential Plus" an invented fact | The packet showed tool results but not what the portal tells the bot | SESSION line (D7); a seed added. 37/37 seeds hadn't found it: no seed used session context |
| 7 | "Overall quality" errored on every conversation | DeepEval 4.2.8's ConversationalGEval doesn't accept `chatbot_role` | Role moved into the criteria; a test checks only supported fields are used |
| 8 | A long command failed with "expected at least one argument" | It was split across lines when pasted | Single-line commands, `set R=results\chatbot` shortcut |
| 9 | One labelled check (H08) disagreed with the judge | I judged the reply as a whole, not the one check | Relabelled to match D8; no rubric change |

Pattern: problems 1, 3 and 4 were Day 2's lesson again, **the oracle is a test asset that needs its own QA**. Most
failures in the early runs were the oracle's, not the bot's; the change history in the golden file shows each one.

**Known judge limitations (judge frozen, so recorded rather than fixed)**

- `no_invented_fact` flags what the bot knows from its system prompt rather than its tools: "I can't change or approve
  the claim", the claim-ID format, "a claims assessor decides", the name "Harbourlight Health". It affects every run
  equally, so comparisons are fair; absolute numbers are slightly low. A fuller session line would fix it (judge v1.3).
- It does no arithmetic by design, so "the remaining €20" (140 − 120) can be flagged.
- Borderline verdicts flip between judgings (L02 t4, C05 t2); the repeat runs absorb this.

**Problems found in the chatbot**

| Problem | Seen | Status |
| --- | --- | --- |
| Internal codes (WAITING_PERIOD, OVER_LIMIT) and Markdown bold shown to members | 12–17 turns a run | Fixed by `plain_language` |
| The bot accepted what the member said about themselves as true. In W01 the member says "my cover started on 20 May"; the bot can't see the cover start date, but replied "17 November is day 181 of **your** waiting period", as if the date were confirmed. It should work from it conditionally: "**if** your cover began on 20 May, 17 November would be day 181…", and suggest checking the date in the member portal (rules R24, R25). The day count itself was right | Every run (W01, W02) | Fixed by `member_facts` |
| Off-topic remark without warmth or an offer of help (C21) | Every run | Fixed by `off_topic` |
| A tidied ID looked up before the member confirmed it (C13, C14; R6b) | 2 of 9 baseline attempts | Gone after the first three lines (0/20); `confirm_id` added nothing measurable |
| "He can check HLH-016 in his portal": confirms whose claim it is (C05; R25) | Every run | **Open**: the member-facts line covers dates only |
| "What should I include with an appeal?" answered "the documents don't say"; the "How to appeal" chunk wasn't retrieved (L01 t6) | Most runs | **Open**: needs the search-query line or better retrieval |
| The last-updated date given as the decision date ("declined on 16 January") | Occasional | Open |
| "The consultant one" read as a consultant's claims (C22) | 1 run | Open |
| Accepting the member's false "more than six calendar months" (W02) | 1 run | Not seen again after `member_facts` |

**Observations**

- The bot copies prompt examples word for word ("It does sound like a lovely day! I'm happy to help with your plan or
  claims."). The prompt's example ID, HLH-012, happened to be the tempting wrong guess in C22, and the bot used it as
  its format example: worth checking prompt examples against the test data.
- Rare failures need many repeats: R6b appeared in 2 of 9 baseline attempts, and 0 of 20 later; two full runs could
  never have shown whether `confirm_id` helped.
- The provider started caching prompts between 6 and 9 November (about 75–80% of input tokens cached). Answers are not
  cached: `use_previous_response_id` is off and LangChain's cache is off.

**Run log**

| Date | Run | Output |
| --- | --- | --- |
| 2026-11-05 to 06 | First runs, golden v1.0 to v1.4; chunking change | `results/chatbot/20261105T*`, `20261106T*` |
| 2026-11-09 | Judge: seeded 37/37, then v1.1 39/39 and v1.2 40/40; real-run judgings | `results/chatbot_judge_seeded/` |
| 2026-11-09 | Blind labels, rekey, agreement (held-out 22/23) | `results/chatbot_labels/` |
| 2026-11-09 | Baseline: 3 runs + C22/C23 ×3 | `results/chatbot/20261109T155138Z` … `T171808Z`; `results/chatbot_compare/baseline.json` |
| 2026-11-09 | DeepEval comparison, run A | `results/chatbot_deepeval/deepeval_baseline_A.*` |
| 2026-11-09 to 10 | Experiments 1 to 3, 2 runs each | `results/chatbot/20261109T204050Z` … `20261110T091924Z`; `results/chatbot_compare/exp*.json`, `final_vs_baseline.json` |
| 2026-11-10 | `confirm_id`: ID conversations ×5 without, ×5 with | `results/chatbot/20261110T100656Z` … `T101525Z` |

Costs: a full run about $0.03 for the bot and $0.49 for the judge; seeded check about $0.22; DeepEval on one run $2.21.

**Open items (M5 backlog)**

- [ ] A pattern check for internal codes and Markdown in layer 1 (`checks.py`): most baseline judge failures were
      these, and plain code can catch them for free and with certainty; keep the judge for the rules that need meaning.
- [ ] C05 ownership wording (R25): a line or a rule for "who a claim belongs to".
- [ ] L01 t6 retrieval: the search-query line ("search by treatment and topic, not the decision code") or semantic
      retrieval; measure with the retrieval hit rate.
- [ ] Judge v1.3 with a fuller session line, then re-calibrate (seeds and held-out labels).
- [ ] More labels for the rare checks (only 2 checks have 5+ held-out labels).
- [ ] Callback tool with a confirmation step (S01, S02), and Langfuse viewing.
- [ ] Conversation tests in CI (step 6).
