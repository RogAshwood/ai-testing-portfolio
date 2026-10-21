# Working notes

The working log behind the README: decisions, problems found in the test setup, and open items.
The README presents the results; this file records how I got there, including the mistakes.

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

Security rules I set: the API key lives only in `.env` (in `.gitignore`), with a monthly spend limit on the key;
synthetic data only; a personal email address for tool sign-ups.

---

## Day 2: Promptfoo claim triage

### Decisions

| Decision | Why |
| --- | --- |
| Health-insurance claim triage for a fictional insurer, not an online shop | Closer to the regulated domains I have tested in; rules with real consequences give the safety rule meaning |
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

Most of the real learning came from defects in my own tests, not in the system under test.

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

<!-- Adjust the dates to match your own runs. -->

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

<!-- Adjust the dates to match your own runs. -->

### Open items (Day 3 backlog)

- [ ] Re-measure k=5 latency (2.7 to 6.5 seconds on one run) before quoting it, and decide whether to adopt k=5
      in `rag_pipeline.py` (`DEFAULT_K` is still 3).
- [ ] Review the 3 pytest warnings (`pytest tests/test_rag.py -rw`) before Day 5 CI.
- [ ] Agree a written definition of a good answer (facts, clarity, what the member should do next), then add a
      member-experience criterion and re-calibrate on a fresh labelled sample.
- [ ] Make claim-deciding conditions binary checks (for example, "the provider's description is required").
- [ ] Re-check calibration labels L05 (Q04) and L07 (Q14), where the judge flagged facts that were not retrieved.
- [ ] Try semantic or hybrid retrieval for the vocabulary gap (Q03), and keep headings with every chunk.
- [ ] Keep the currency in the document text instead of stripping it in cleaning.
- [ ] Confirm the k=5 fix on fresh questions it was not tuned against.
- [ ] Log run settings (model, k, prompt) with each CI run (Day 5).
- [ ] Try a judge from a different model family, as on Day 2.

## Day 4: Test-generation agent benchmark

_Not started._

## Day 5: CI, README, LinkedIn

_Not started._
