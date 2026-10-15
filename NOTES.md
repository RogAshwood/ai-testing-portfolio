# Working notes

The working log behind the README: decisions, problems found in the test setup, and open items.
The README presents the results; this file records how I got there, including the mistakes.

---

## Day 1: theory and environment

- Reading: Anthropic's guide to success criteria and evaluations, Hamel Husain's "Your AI Product Needs Evals"
  and the LLM Evals FAQ, and the OWASP Top 10 for LLM Applications.
- Environment: conda (conda-forge) env `ai-testing` with Python 3.11, Node.js 22.22+, JupyterLab, pandas,
  matplotlib, python-dotenv; DeepEval installed with pip. Promptfoo runs through `npx`.

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

_Not started._

## Day 4: Test-generation agent benchmark

_Not started._

## Day 5: CI, README, LinkedIn

_Not started._
