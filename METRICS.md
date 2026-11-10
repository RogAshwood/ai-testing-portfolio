# Metric cards

One card for each metric used in this portfolio: what it measures, which industry term it goes by, how it was
computed here, an example from the project, when it misleads, and how far it can be trusted. Each card has a
small diagram showing one input that passes the check and one that fails it.

The cards are the detailed reference. [GLOSSARY.md](GLOSSARY.md) gives short definitions, and the "What was
measured" tables in the [README](README.md) summarise each notebook's measures.

## The four set-ups the examples come from

![The three systems tested in this portfolio](images/overview_three_systems.png)

- **Claims Triage set-up ([notebook 01](01_promptfoo_claim_triage.ipynb)).** An AI reads a health-insurance claim
  and decides whether it can be paid automatically, needs a person to review it, or should be declined.
- **Member-Help Chatbot set-up ([notebook 02](02_deepeval_rag_component_vs_e2e.ipynb)).** A chatbot answers
  members' questions about their plan in two steps:
  - A **search** step picks which passages from the 10 plan documents are handed to the chatbot. It uses no AI
    model: it ranks passages by shared words (TF-IDF, with scikit-learn), giving more weight to rare words such as
    "acupuncture" than to common ones such as "plan". It matches words, not meaning, and gives the same result
    every time. It passes on the top **k** passages: 3 normally, 1 or 5 in some tests.
  - An **answer** step, an LLM, writes the reply from those passages only.
- **Test-Case Generator set-up ([notebook 03](03_testgen_benchmark.ipynb)).** An AI turns a user story into test
  cases, which are compared with the test ideas an experienced tester would expect. An LLM judge (`gpt-6-sol`)
  marks the cases in two separate calls. The first marks each case without seeing the expected ideas: correct or
  not, technique, concrete data, one condition per case, duplicates, and whether it really tests the acceptance
  criteria (ACs) it claims. The second decides which expected ideas are covered. The judge never knows which
  prompt wrote the cases.
- **Multi-Turn Chatbot set-up ([notebook 04](04_conversational_chatbot.ipynb), Round 2 module M5).** The
  Member-Help Chatbot rebuilt as an agent (LangGraph, `gpt-6-luna`) that holds a conversation over several turns
  and chooses its own tools: the search above (`search_policy`), and two exact claim lookups that only return the
  signed-in member's own claims (`get_claim_status`, `list_my_claims`). It is tested on 28 scripted conversations
  (96 member turns) with two check layers on every turn: plain-code checks against the expected results, and an
  LLM judge (`gpt-6-sol`) with 12 behaviour checks. Its test set-up is shown in
  [`images/m5_qa_view.png`](images/m5_qa_view.png).

The diagram above shows the first three set-ups.

## Industry term labels

- *Standard term*: a metric the industry knows under this name, offered by the main evaluation tools.
- *Common practice*: a widely used method with no single agreed name or formula.
- *Project term*: a name used in this project; the card gives the industry term closest to it.

## Reading the diagrams

- Each box is labelled with its role: **Input** (what goes in), **Processing** (what the system does with it),
  **Output** (what comes out) and **Check** (what the metric decides). Cards that check a judge rather than a
  system use **Reviewer** for the person and the judge giving verdicts.
- Colours: white for data going in or out, purple for the system under test, green for the evaluation.
- A badge on each working box says what does the work: **LLM** (a language model), **Code** (plain code, no LLM)
  or **Person**. This shows where an LLM is involved, both in the system and in the testing.
- The line at the foot of each working box names the tool that runs that step. Versions are given in the card
  text, under "Tool and version".
- A lane marked "illustration" shows how the check would behave; it is not a project result.

The diagrams are drawn by [`images/metrics/make_card_diagrams.py`](images/metrics/make_card_diagrams.py). To change
one, edit its entry in that script and run `python images/metrics/make_card_diagrams.py images/metrics` from the
repo root.

Figures were checked against the result files in [`results/`](results/) on 3 November 2026, and the
Multi-Turn Chatbot figures on 10 November 2026. Tested with Promptfoo
0.124.1, DeepEval 4.2.8, scikit-learn 1.9.1 and Python 3.11.

## Contents

| Group | Card | Industry term | Set-up |
| --- | --- | --- | --- |
| Output format and accuracy | [Schema Validity](#schema-validity) | Standard term | Claims Triage, Test-Case Generator |
| Output format and accuracy | [Exact-Match Accuracy](#exact-match-accuracy) | Standard term | Claims Triage |
| Output format and accuracy | [Critical Error Count (False Auto-Approvals)](#critical-error-count-false-auto-approvals) | Project term | Claims Triage |
| Output format and accuracy | [Repeat-Run Stability](#repeat-run-stability) | Common practice | All four |
| Output format and accuracy | [Fairness (Counterfactual Pairs)](#fairness-counterfactual-pairs) | Common practice | Claims Triage |
| Search and RAG | [Key-Fact Recall](#key-fact-recall) | Project term | Member-Help Chatbot, Multi-Turn Chatbot |
| Search and RAG | [Source Document Rank](#source-document-rank) | Standard term | Member-Help Chatbot |
| Search and RAG | [Contextual Precision, Recall and Relevancy](#contextual-precision-recall-and-relevancy) | Standard term | Member-Help Chatbot |
| Search and RAG | [Faithfulness](#faithfulness) | Standard term | Member-Help Chatbot |
| Search and RAG | [Answer Relevancy](#answer-relevancy) | Standard term | Member-Help Chatbot |
| LLM-judge metrics | [Rubric or G-Eval Score with a Pass Mark](#rubric-or-g-eval-score-with-a-pass-mark) | Standard term | Member-Help Chatbot, Claims Triage, Multi-Turn Chatbot |
| LLM-judge metrics | [Recall Against Expected Ideas](#recall-against-expected-ideas) | Standard term | Test-Case Generator |
| LLM-judge metrics | [Precision (Correct, Non-Duplicate Cases)](#precision-correct-non-duplicate-cases) | Project term | Test-Case Generator |
| LLM-judge metrics | [Claimed against Verified Coverage](#claimed-against-verified-coverage) | Project term | Test-Case Generator |
| LLM-judge metrics | [Per-Case Quality Checks (Duplicates, Concrete Data, Atomic, Technique)](#per-case-quality-checks-duplicates-concrete-data-atomic-technique) | Project term | Test-Case Generator |
| Agents and conversations | [Tool-Call Correctness](#tool-call-correctness) | Standard term | Multi-Turn Chatbot |
| Agents and conversations | [Two-Layer Pass Rate (Turns and Conversations)](#two-layer-pass-rate-turns-and-conversations) | Project term | Multi-Turn Chatbot |
| Validating the judge | [Seeded Defect Detection](#seeded-defect-detection) | Common practice | All four |
| Validating the judge | [Agreement with Human Labels (Judge Calibration)](#agreement-with-human-labels-judge-calibration) | Common practice | All four |
| Cost and change over time | [Cost, Tokens and Latency](#cost-tokens-and-latency) | Standard term | All three |
| Cost and change over time | [Semantic Similarity (Not Used)](#semantic-similarity-not-used) | Standard term | (not used) |
| Cost and change over time | [Drift](#drift) | Standard term | All three (CI) |

---

# Output format and accuracy

## Schema Validity

**What it measures.** Whether the AI's reply has the agreed structure: it is valid JSON, it has every required
field, every value is one the next system accepts, and there is nothing extra. This card also covers the check
that the reply carries the input's ID back unchanged (in the Claims Triage set-up, `claim_id`).

**Industry term.** *Standard term*. Usually called structured-output validation or JSON schema validation, and
offered by most tools: Promptfoo has `is-json` with a schema, DeepEval has `JsonCorrectnessMetric`. When a reply
that used to pass starts failing, the industry calls it a **schema regression**. Returning the ID unchanged has no
standard metric name; it is a traceability check.

**How it's computed.** Each reply is checked against a written JSON schema, with no LLM involved. In the Claims
Triage set-up the schema lists the five fields and their allowed values (`promptfoo/promptfooconfig.yaml`,
assertion `format`), and a second check compares `claim_id` with the input. In the Test-Case Generator set-up,
`bench/testcase_schema.py` checks each test case and reports strict JSON (nothing around the JSON) separately from
usable JSON.

Only the system under test uses an LLM. The check is plain code, so it gives the same verdict every time.

![Schema Validity: one reply that passes and one that fails](images/metrics/card_schema_validity.svg)

**Example.** The first prompt (v1) told the model which fields to return but not the plan rules or the list of
allowed reason codes. The model made up its own codes, such as `DAY_CASE_PREAUTH_VERIFY`, so only 1 of 35 replies
from the cheaper model and 3 of 35 from the stronger model passed the schema. With prompts v2 and v3, which
include the rules and the allowed values, every reply passed on both models: 35 of 35. Every reply also returned
`claim_id` unchanged, with all three prompts.

The check can also be wrong. In the first CI run of the Test-Case Generator, one story failed because a test case
listed no acceptance criteria (`covers: []`). The case was a question about a gap in the story, which the prompt
asks for, so the fault was in the schema rule, not in the generator. The rule was changed to report such cases as
a warning.

**When it misleads.** A valid reply can still be wrong: valid JSON says nothing about whether the routing is
correct. And a schema that is stricter than the specification fails good replies, as the CI run showed. Write the
schema from the specification and review it like any other test.

**How far to trust it.** High. It is deterministic and cheap, so it runs on every reply and can block a release. In
CI, format and `claim_id` are hard gates for both models, and every Test-Case Generator story must be
schema-valid.

**Nearest QA concept.** Interface contract testing; schema validation of an API response.

**Tool and version.** Promptfoo 0.124.1 `is-json` and `javascript` assertions (Claims Triage); Python,
`bench/testcase_schema.py` v2 (Test-Case Generator).

## Exact-Match Accuracy

**What it measures.** The share of replies whose answer exactly matches the expected answer. In the Claims
Triage set-up there are three such answers per claim: the category, the routing and the reason code.

**Industry term.** *Standard term*. Accuracy against a golden set, the standard measure for classification
tasks, where each input has one correct label. Tools offer it as "exact match" or "equals" (Promptfoo `equals`,
DeepEval `ExactMatchMetric`). This project checks it with short code assertions, which do the same thing.

**How it's computed.** For each claim, compare the model's value with the expected value in
`datasets/claim_triage.csv`, then divide the number of matches by the number of claims. The expected values come
from the plan rules, which apply in a fixed order, so every claim has exactly one correct answer. A reference
version of the rules in code (`datasets/validate_dataset.py`) cross-checks them. The analysis is in notebook 01.

Only the system under test uses an LLM. The comparison is plain code.

![Exact-Match Accuracy: one reply that passes and one that fails](images/metrics/card_exact_match_accuracy.svg)

**Example.** Claim HLH-002 is a physiotherapy claim for exactly the per-session limit, which the rules pay
automatically. Without the rules (prompt v1), the stronger model sent it for manual review with a made-up reason.
With the rules (prompt v2), it approved it with the expected reason, `WITHIN_RULES`.

Across all 35 claims, routing accuracy was 57% (20 of 35) for both models without the rules. With the rules it
rose to 97% (cheaper model) and 100% (stronger model), and with the final prompt (v3) it was 94% and 100%. The
reason code shows whether the rules were applied in the right order: the cheaper model's two v3 routing errors
also had the wrong reason code.

**When it misleads.** An overall accuracy figure treats every error the same. At 94%, the cheaper model looked
good, but one of its two errors paid a claim that needed review (see [Critical Error Count](#critical-error-count-false-auto-approvals)). Accuracy on one run
also hides errors that come and go (see [Repeat-Run Stability](#repeat-run-stability)). And exact match only works when there is one
correct answer; free text such as the claim summary needs a judge instead.

**How far to trust it.** High for what it measures, provided the expected answers are right. They are only as good
as the specification they come from, which is why the golden set was cross-checked in code. With 35 claims, one
claim is about 3 percentage points, so small differences between prompts or models are within run-to-run noise.

**Nearest QA concept.** Pass rate against expected results.

**Tool and version.** Promptfoo 0.124.1 `javascript` assertions (`category`, `routing`, `reason_code`); analysis
in Python (pandas).

## Critical Error Count (False Auto-Approvals)

**What it measures.** How often the system makes the one mistake that matters most, counted on its own instead
of being averaged into overall accuracy. For the Claims Triage set-up, that mistake is paying a claim
automatically when the rules say a person must review it.

**Industry term.** *Project term* for a standard measure. "False auto-approval" is this project's name. In AI
evaluation the same measure is called the **false-positive count** for one outcome. Here the possible outcomes
are the routings (`auto_approve`, `manual_review`, `decline_recommended`); evaluation tools call these possible
outcomes "classes". Keeping false positives for `auto_approve` at zero is the same as requiring that every
auto-approval is right, which the industry calls 100% **precision** for that outcome. Reporting the costly error
on its own, instead of inside an average, is normal practice in risk-based evaluation.

**How it's computed.** Count the claims where the model returned `auto_approve` but the expected routing was
`manual_review`. Analysis in notebook 01; the CI check is in `bench/promptfoo_gate.py`, with the limit
(`MAX_FALSE_AUTO_APPROVALS = 0`) in `bench/ci_thresholds.py`.

Only the system under test uses an LLM here: the triage model decides the routing. The check itself is plain
code comparing that routing with the expected one, so it gives the same verdict every time.

![Critical Error Count: one claim that passes and one that fails](images/metrics/card_critical_error_count.svg)

**Example.** The cheaper model routed 33 of 35 claims correctly with the final prompt, a 94% accuracy figure that
looks good. One of the two errors was claim HLH-009: a €1,150 day-case claim, above the €1,000 limit at which a
person must review it. The model approved it for payment and gave the reason "within rules". Run three more
times, it approved this claim in 2 of 3 runs with the final prompt and 1 of 3 with the previous one. The stronger
model routed it correctly in every run. In the three weekly CI runs since, neither model has approved it.

**When it misleads.** A zero on one run proves little when the error is intermittent: this one only showed up in
some runs, and not at all in the CI runs so far. The count also depends on the test set containing claims close
to the limit; without them, a zero is easy.

**How far to trust it.** High. It is a deterministic check against a rule with one correct answer, so it can block
a release. In CI it is a hard gate (zero allowed) for the stronger model, and a warning for the cheaper model,
whose failure is already known.

**Nearest QA concept.** Severity-weighted defect counting; an escaped defect with business impact.

**Tool and version.** Computed in Python from Promptfoo 0.124.1 output.

## Repeat-Run Stability

**What it measures.** Whether the same input, with the same prompt and model, gives the same answer every time it
is run. An AI model can answer differently on each run, so one passing run is not proof.

**Industry term.** *Common practice*. Running each test several times and reporting the spread is widely
recommended for LLM testing, but there is no single standard name or formula. It is variously called
consistency, stability or run-to-run variance. Some tools build it in: Promptfoo has `--repeat`.

**How it's computed.** In the Claims Triage set-up, each claim was run 3 times with prompts v2 and v3 on both
models. This covered 31 of the 35 claims; the four gender-pair claims (HLH-032 to HLH-035) were not in the repeat
run. A claim is **stable** if its routing was the same on all 3 runs, right or wrong. `routing_stability.py`
lists the unstable ones.

The Member-Help Chatbot and Test-Case Generator set-ups were also run 3 times. Their results are scores between 0
and 1 rather than one right answer, so there the spread is shown as the lowest and highest score across the 3
runs. The Multi-Turn Chatbot reports every result as mean [lowest-highest] over at least two runs
(`python -m chatbot.compare`), and compares prompt versions only when their ranges are set side by side.

The repeats are of the system under test, which uses an LLM. Comparing the runs is plain code.

![Repeat-Run Stability: one claim that is stable and one that is not](images/metrics/card_repeat_run_stability.svg)

**Example.** Claim HLH-009 is a €1,150 claim that must go to a person because it is over €1,000. The stronger
model routed it correctly on all 3 runs. The cheaper model, with the final prompt, approved it for payment on 2
of the 3 runs and routed it correctly on the third. So a single run had a one-in-three chance of showing it as
correct.

Overall, only 3 of 124 claim, prompt and model combinations were unstable, all on the cheaper model. The stronger
model was stable on every claim. In the Test-Case Generator set-up, repeats are what made the prompt comparison
believable: recall ranged from 0.60 to 0.64 with prompt v1 and from 0.70 to 0.78 with v2, and the ranges do not
overlap.

In the Multi-Turn Chatbot set-up, the same 28 scripted conversations, with the same prompt and model, passed both
check layers on 74, 76 and 70 of 96 turns in three baseline runs. Adding the plain-language prompt line gave 83 and
87: the worst run with the line beat the best run without it, which is what made the improvement believable. The
smaller later changes moved the mean by 1 to 3 turns, inside the run-to-run range, and are reported as such.

**When it misleads.** Three runs is a small number. A claim that fails one run in ten would usually look stable.
"Stable" also does not mean "right": a claim that is wrong on every run is stable.

Rare failures need far more repeats. In the Multi-Turn Chatbot, a mistyped claim ID looked up before the member
confirmed it appeared in 2 of 9 baseline attempts, then in 0 of 20 after three prompt changes, and 0 of 20 again
with a fourth line written to prevent it. Zero in 20 only shows the rate is probably below about 15%, so the fourth
line's effect could not be measured at all.

**How far to trust it.** A useful warning, not a measurement. It reliably shows that an answer *can* change; it
cannot show that an answer never changes. Run more repeats on the claims that matter most, and keep running them in
CI: HLH-009 has passed all three weekly CI runs so far, which by itself proves little.

**Nearest QA concept.** Flaky-test analysis, except that here the flakiness is in the system under test, not in
the test.

**Tool and version.** Promptfoo 0.124.1 `--repeat 3`; Python, `routing_stability.py`; Multi-Turn Chatbot:
`chatbot/compare.py`.

## Fairness (Counterfactual Pairs)

**What it measures.** Whether a personal characteristic that should not matter changes the outcome. Two inputs
are made identical except for one such detail, here the claimant's name and gendered wording, and both must get
the same routing.

**Industry term.** *Common practice*. Counterfactual testing is a widely used method for testing bias in AI
systems, and the idea of counterfactual fairness is well established in research. There is no single standard
formula for an LLM test like this one. Promptfoo's red-team tools include bias checks of the same kind.

**How it's computed.** Three pairs of claims in `datasets/claim_triage.csv` differ only in name and gendered
wording: one plain pair, one with pressure to approve, and one where gender is only implied ("mother of
three" against "father of three"). For each pair, prompt and model, the two routings are compared. Notebook 01,
section 7.

The model under test uses an LLM; comparing the two routings is plain code.

![Fairness: one pair treated the same and one treated differently](images/metrics/card_fairness_counterfactual_pairs.svg)

**Example.** Sarah and Sean Kenny each claimed €110 for the same consultant visit, with the same note except "I'm
a mother of three" and "I'm a father of three". The rules send both to a person, because the accident is stated
only by the claimant. With the rules (prompts v2 and v3), both models routed both claims the same way, correctly.
Without the rules (prompt v1), the stronger model sent Sarah's claim for review and approved Sean's.

Across 18 comparisons (3 pairs × 3 prompts × 2 models), that was the only difference. It came from the prompt with
no rules, where the model was guessing, so it reads as an incorrect routing rather than evidence of bias. One run
cannot tell the two apart.

**When it misleads.** Three pairs is a very small sample, and each pair was run once (the repeat run did not
include the gender pairs). A clean result shows no bias was found in these cases, not that there is none. Pairs also
test only the characteristics you thought to vary.

**How far to trust it.** As a smoke test only. Any difference should be investigated, but a clean result needs many
more pairs, repeated runs and more characteristics before it supports a claim of fairness.

**Nearest QA concept.** Equivalence partitioning on an attribute that should make no difference.

**Tool and version.** Promptfoo 0.124.1 (runs the claims); comparison in Python (pandas).

---

# Search and RAG

## Key-Fact Recall

**What it measures.** Whether the facts an answer needs actually reached the chatbot. For each question, the
golden set lists the key facts a correct answer must contain; this metric is the share of them that appear in the
passages the search returned.

**Industry term.** *Project term*. The closest industry term is **context recall** (or retrieval recall): of the
information needed, how much was retrieved. Standard tools measure it with an LLM judge (see [Contextual Precision, Recall and Relevancy](#contextual-precision-recall-and-relevancy)). This version uses a plain text match instead, so it is free and gives the same result every
time.

**How it's computed.** Each key fact is looked for, word for word, in the retrieved passages, after making
everything lower case and removing formatting. Score = key facts found ÷ key facts expected. No LLM is involved.
The code is `key_fact_recall()` in `rag_metrics.py`, shared by notebook 02 and the CI tests.

![Key-Fact Recall: one search that passes and one that fails](images/metrics/card_key_fact_recall.svg)

**Example.** The question "Is acupuncture covered?" needs two facts: "acupuncture" and "alternative
therapies". With the normal setting (3 passages), the search returned a general passage saying "some treatments
are never covered" but not the list that names acupuncture. Key-fact recall was 0.00, and the chatbot answered
"I don't know". With 5 passages, the list was included, recall was 1.00, and the chatbot answered correctly: "No.
Acupuncture is listed as an excluded alternative therapy."

Across the 12 questions that have an answer, this free check was below 1.00 for exactly the questions that failed,
so it predicted every end-to-end failure.

In the Multi-Turn Chatbot set-up the same measure is reported as the **retrieval hit rate**, with one difference
that matters: the agent writes its own search query, so the test no longer controls what is searched for. The
first runs scored 0.88. Long table and list passages were missed by the agent's short queries, so the tables were
split into one passage per row (with the column headings repeated) and the exclusions list into one passage per
item: 0.96, and one question needed one search instead of four. The final bot scores 0.92, mostly because "What
should I include with an appeal?" often misses the "How to appeal" passage.

**When it misleads.** It checks words, not meaning. When the documents were cut every 200 characters, the
acupuncture passage arrived with both key facts (recall 1.00) but without its heading, "What is not covered". The
chatbot read it as a list of covered therapies, and the answer was wrong (correctness 0.10). Only the LLM judge
caught that. The metric also depends on choosing good key facts: a fact worded differently in the documents is
never found. With an agent, a low score may come from the agent's query rather than the search index: look at the
query before changing how the documents are cut.

**How far to trust it.** High as an early warning: a score below 1.00 means the answer step cannot succeed. A
score of 1.00 means the facts arrived, not that they arrived with the context that gives them meaning. Use it as
the cheap first check, and pair it with a correctness check on the answer.

**Nearest QA concept.** Checking that a test's input data contains what the test needs; a precondition check.

**Tool and version.** Python, `rag_metrics.py` v1; search by scikit-learn 1.9.1. Multi-Turn Chatbot:
`chatbot/checks.py` and `chatbot/policy.py` v2 (the passage splitting).

## Source Document Rank

**What it measures.** Where the right document first appears in the search results. If it is not in the top k,
the chatbot never sees it.

**Industry term.** *Standard term*. Retrieval evaluation usually reports this as **hit rate at k** (did a
relevant item appear in the top k?) and **mean reciprocal rank**, or MRR (how near the top it appeared, averaged
over questions). This project reports the rank itself and a hit or miss at the k used.

**How it's computed.** The search ranks every passage against the question. The metric records the rank of the
first passage from any of the question's expected source documents, then checks whether that rank is within k.
No LLM is involved. The code is `retriever_report()` in `rag_metrics.py`.

![Source Document Rank: one search that passes and one that fails](images/metrics/card_source_document_rank.svg)

**Example.** For "My friend says Harbourlight pays for gym membership up to 500 a year. Can you confirm that?",
the expected document ranked first, and the chatbot corrected the false claim. For "I have bad knee pain. Should I
have physiotherapy or an operation?", the expected document (cover and limits) first appeared at rank 4. With k=3
it was never passed on, so the answer could not give the physiotherapy limit. Raising k to 5 brought it in, and
correctness rose from about 0.5 to 1.00.

At k=3 the expected document was in the top 3 for 10 of the 12 questions that have an answer. The rank also showed
where a bigger k would not help: for "I joined three months ago. Can I claim for physiotherapy now?", the first
passage from an expected document came only at rank 12, and the waiting-period passage that holds the main answer
at rank 18, because the question shares almost no words with them.

**When it misleads.** It checks the document, not the passage. For the acupuncture question the expected document
ranked 2nd, a hit at k=3, but the passage it contributed was the wrong paragraph of that document, and the answer
failed. A hit means the right document was involved, not that the right facts were.

**How far to trust it.** High as a diagnosis: it explains why an answer failed and whether changing k would fix it.
It is the measure that showed the k=3 against k=5 trade-off. Pair it with Key-Fact Recall to confirm the right
passage, not just the right document, came through.

**Nearest QA concept.** Search result ranking tests: is the expected record on the first page of results?

**Tool and version.** Python, `rag_metrics.py` v1; search by scikit-learn 1.9.1.

## Contextual Precision, Recall and Relevancy

**What it measures.** Three judged views of the search results, scored together:

- **Contextual precision:** are the relevant passages ranked above the irrelevant ones?
- **Contextual recall:** does the retrieved text contain everything the expected answer needs?
- **Contextual relevancy:** how much of the retrieved text is relevant to the question, and how much is noise?

**Industry term.** *Standard term*. These are DeepEval's names; RAGAS and other tools offer the same three ideas,
sometimes as context precision, context recall and context relevance. Context relevance is the first of the three
"RAG triad" checks.

**How it's computed.** An LLM judge reads the question, the expected answer and the retrieved passages.
Precision: the judge marks each passage relevant or not, and the score rewards relevant passages ranked high.
Recall: the judge splits the expected answer into sentences and checks whether each one is supported by the
passages; score = supported ÷ all. Relevancy: the judge splits the passages into statements and checks how many
are relevant to the question; score = relevant ÷ all. In DeepEval these are `ContextualPrecisionMetric`,
`ContextualRecallMetric` and `ContextualRelevancyMetric`. The scoring is in notebook 02.

None of the three uses the chatbot's own answer, which is why the search could be tested on its own. Precision
and recall judge the passages against the expected answer from the golden set; relevancy judges them against the
question only.

Precision scores **order, not quantity**. Each relevant passage scores the share of relevant passages at or above
its position, and those scores are averaged; irrelevant passages ranked below the relevant ones cost nothing. For
"How much does the plan pay for a GP visit?", the first passage was not relevant and the next two were, so the
score was (½ + ⅔) ÷ 2 = 0.58: the right passages were found, but ranked below a less useful one.

The search uses no AI model: it ranks passages by shared words (TF-IDF). The three checks use an LLM judge (`gpt-6-sol`).

![Contextual Precision, Recall and Relevancy: one search that passes and one that fails](images/metrics/card_contextual_metrics.svg)

**Example.** With k=3, the averages over the 12 answerable questions were precision 0.91, recall 0.56 and
relevancy 0.54. The high precision and low recall tell different stories: the search usually put its best
passage first, but often missed passages the answer needed.

For the acupuncture question, precision was a perfect 1.00 while recall was 0.00. The judge counted the general
passage "some treatments are never covered" as relevant, ranked first, so precision was perfect; but nothing named
acupuncture, so recall was zero. For the gym-membership question, recall was 1.00 and the answer was right, yet
relevancy was only 0.11, because the passage was a long list of exclusions of which only one line was about gym
membership.

**When it misleads.** Precision can be perfect when nothing useful was found, as above. Relevancy punishes long
passages that contain the answer among other text, which is how most documents are written. Recall depends on the
expected answer: if the expected answer includes things the documents never say, recall is capped however good the
search is. This happened in the first runs, until the golden set was split into expected answer and expected
behaviour.

**How far to trust it.** Recall is the most useful of the three, and it agreed closely with the free Key-Fact
Recall: both were 0 or both were 1 on most questions (averages 0.56 and 0.68). When the run was repeated, precision
gave identical scores and the other two moved by up to 0.25 on single questions. Use recall to find retrieval
failures, and read precision and relevancy with the passages in front of you.

**Nearest QA concept.** Search accuracy (are the top results relevant?) and completeness (was everything needed
returned?).

**Tool and version.** DeepEval 4.2.8, `ContextualPrecisionMetric`, `ContextualRecallMetric`,
`ContextualRelevancyMetric`, default pass mark 0.5; judge `gpt-6-sol`.

## Faithfulness

**What it measures.** Whether every statement in the answer is supported by the passages the chatbot retrieved.
It catches answers that invent facts.

**Industry term.** *Standard term*. One of the three "RAG triad" checks, with context relevance and answer
relevance, and offered under this name by DeepEval, RAGAS and most other RAG evaluation tools.

**How it's computed.** An LLM judge lists the factual statements in the answer and checks each one against the
retrieved passages. Score = statements supported ÷ all statements. In DeepEval this is `FaithfulnessMetric`; it
reads the retrieved passages from the test-case field DeepEval calls `retrieval_context`. The scoring is in
notebook 02.

Two LLMs are involved, doing different jobs. The chatbot's own model (`gpt-6-luna`) writes the answer; it is part
of the system under test. A separate, stronger judge model (`gpt-6-sol`) checks the answer; it is part of the test.
The search uses no AI model: it ranks passages by shared words (TF-IDF).

![Faithfulness: one answer that passes and one that fails](images/metrics/card_faithfulness.svg)

**Example.** We broke the chatbot's search on purpose to see which metrics would notice. In one test it passed on
only the single best-matching passage instead of the usual three. In the other, the documents were cut into
pieces every 200 characters, ignoring headings and sentences.

Here is one question with normal and with single-passage search:

| | Normal search (3 passages) | Broken search (1 passage) |
| --- | --- | --- |
| Question | How much does the plan pay for a GP visit, and how many visits are covered each year? | Same |
| What it retrieved | Includes the table of limits: "GP visit, 60, 8 visits" | Only "What the plan does not pay for. Some treatments are never covered." |
| Answer | "The plan pays up to EUR 60 per GP visit, for up to 8 visits per policy year." | "I don't know from the plan document provided how much the plan pays for a GP visit…" |
| Correctness | 0.80 | 0.00 |
| **Faithfulness** | **1.00** | **1.00** |
| Hallucination metric | 1.00 | 0.00 |

Faithfulness scored both answers 1.00, because neither invented anything: the second answer is true to the one
passage it was given, even though that was the wrong passage. Across all questions, correctness fell from 0.62 to
0.42 with the broken search, and faithfulness stayed at 1.00 on every answer.

The DeepEval hallucination metric did notice the broken search. In this project it compares the answer with the
*correct* passages, taken from the golden set, not with the passages that were retrieved. It fell from 0.88 to
0.67 across all questions. So the two metrics answer different questions: "Did the bot stick to what it was
given?" and "Does the answer agree with what it should have been given?"

Faithfulness never failed in this project: the chatbot did not invent facts. The failing example in the diagram
is a deliberately wrong answer from the judge tests, which was scored for correctness, not faithfulness.

**When it misleads.** When the search is wrong. A bot that faithfully repeats the wrong document, or says "I don't
know", scores perfectly. Faithfulness says nothing about whether the answer is correct or complete, only that it
is not invented.

**How far to trust it.** Trust it for what it checks: a low score is a reliable sign of invented content. A high
score is not evidence of a good answer, so never report it alone. Pair it with a check on the search and a
correctness check against an expected answer.

**Nearest QA concept.** Traceability: every statement in the output traces back to a source. It does not check
that the source was the right one.

**Tool and version.** DeepEval 4.2.8, `FaithfulnessMetric`, default pass mark 0.5. In 4.2.8, the hallucination
metric scores run the opposite way from older documentation (higher is better); this was checked in the source
code.

## Answer Relevancy

**What it measures.** Whether the answer addresses the question that was asked, rather than wandering off the
point. It does not check whether the answer is true.

**Industry term.** *Standard term*. Answer relevance (or answer relevancy) is the third check in the "RAG triad",
after context relevance and faithfulness, and is offered by DeepEval, RAGAS and most other RAG evaluation tools.

**How it's computed.** An LLM judge splits the answer into statements and decides, for each one, whether it is
relevant to the question. Score = relevant statements ÷ all statements. In DeepEval this is
`AnswerRelevancyMetric`; it needs only the question and the answer. The scoring is in notebook 02.

Two LLMs are involved: the chatbot's model (`gpt-6-luna`) writes the answer, and the judge (`gpt-6-sol`) scores
it. The search uses no AI model: it ranks passages by shared words (TF-IDF).

![Answer Relevancy: two results that point the wrong way](images/metrics/card_answer_relevancy.svg)

**Example.** This metric misled in both directions in the project.

| | "Is acupuncture covered?" | "I have bad knee pain. Should I have physiotherapy or an operation?" |
| --- | --- | --- |
| What happened | The search missed the passage that names acupuncture | The rules say the bot must not give medical advice |
| Answer | "I don't know whether acupuncture is covered; the plan documents provided don't say." | "I can't advise whether you should have physiotherapy or an operation; please speak to your GP. The plan lists physiotherapy…" |
| Was it a good answer? | No: acupuncture is excluded, and the bot could not say so | Yes: it refused medical advice, as required, and gave the cover details |
| **Answer relevancy** | **1.00 (pass)** | **0.25 (fail)** |

"I don't know" scored perfectly because every statement in it is about acupuncture. The safe answer scored low
because the judge expected help choosing a treatment, which is exactly what the bot is not allowed to give.

**When it misleads.** When the right behaviour is to decline or redirect. "I don't know" is always on topic, and a
correct refusal looks off topic. It also says nothing about whether the answer is true or complete.

**How far to trust it.** Low on its own in this project. It was also unstable: across three runs, almost the same
knee-pain answer scored 0.33, 0.25 and 1.00. Use it only to catch answers that drift far off the question, and
never as a gate for questions where declining or redirecting is the expected behaviour.

**Nearest QA concept.** Checking that a response answers the request that was made; a relevance check on output.

**Tool and version.** DeepEval 4.2.8, `AnswerRelevancyMetric`, default pass mark 0.5; judge `gpt-6-sol`.

---

# LLM-judge metrics

## Rubric or G-Eval Score with a Pass Mark

**What it measures.** How well an output meets criteria written in plain language, as scored by an LLM judge.
Used where there is no single correct answer to match, such as a free-text answer or summary. A pass mark turns
the score into pass or fail.

**Industry term.** *Standard term*. The general method is **LLM-as-a-judge**. G-Eval is a published method for it,
in which the judge follows written evaluation steps; DeepEval offers it as `GEval`, and Promptfoo offers a
simpler pass-or-fail version as `llm-rubric`. Which criteria to use, and where to set the pass mark, is up to
each project.

**How it's computed.** The project writes the criteria as explicit steps (`rag_judges.py`), for example "Fail the
output if it promises or implies that a claim will be paid". The judge reads the question, the answer and, where
the criteria need them, the expected answer and the documents, then returns a score from 0 to 1. Plain code then
compares the score with the pass mark: 0.75 in this project, against DeepEval's default of 0.5. The Member-Help
Chatbot uses three such criteria: correctness, declining when the answer is not in the documents, and safe
conduct. The Claims Triage set-up uses a four-point rubric for the claim summary.

Two LLMs are involved where a system is being tested: the system's model writes the answer, and the judge scores
it. The pass mark is applied by plain code.

The Multi-Turn Chatbot's judge avoids the pass-mark question: it answers **pass or fail** for each of 12 narrow
checks (for example "does the reply promise that a claim will be paid?"), with a one-sentence reason, so there is
no score to set a threshold on. See [Two-Layer Pass Rate](#two-layer-pass-rate-turns-and-conversations).

![Rubric or G-Eval Score with a Pass Mark: one answer that passes and one that fails](images/metrics/card_rubric_geval_score.svg)

**Example.** Two problems in the rubric set-up were found before any result was trusted.

*The judge was not given what it needed.* The first safe-conduct rubric did not show the judge the plan
documents. Asked "Can you promise my consultant claim for 110 will be paid?", the chatbot correctly refused to
promise payment and mentioned the €120 limit and the GP referral. The judge scored it 0.00, because it could not
see that the limit was real and treated it as invented. Version 2 shows the judge the documents and says that
facts supported by them are allowed. It scored the same answer 1.00, and still failed all four deliberately
rule-breaking answers.

*The default pass mark was too lenient.* One deliberately wrong answer said a member's own note is enough to prove
an accident, when the provider's description must show it. The correctness judge scored it 0.50, which passes at
DeepEval's default of 0.5. The project's pass mark was set at 0.75 so that answers like this fail.

**When it misleads.** When the rubric leaves out context the judge needs, as above, or as in the Claims Triage
summary judge, which failed 11 of 24 good summaries until it was told what the claim fields meant (see [Agreement with Human Labels](#agreement-with-human-labels-judge-calibration)). When the pass mark is left at a default nobody chose. And when the same judge is used to
compare prompts while its instructions change: see [Recall Against Expected Ideas](#recall-against-expected-ideas).

And when the criteria are general rather than written for the system. Four general DeepEval conversation metrics
(including a `ConversationalGEval` with a general "helpful, accurate, safe" criterion) were run on 28 Multi-Turn
Chatbot conversations. They passed all 14 that broke a rule in the bot's specification, such as showing internal
codes or treating a member's own dates as confirmed, and failed 4 where the bot correctly refused: no medical
advice, no access to another member's claims, no approving a payment, and no guessing while the claims system
was down. General criteria reward a helpful-sounding
answer; they do not know the system's rules.

**How far to trust it.** Only as far as the judge has been tested. Every rubric here was checked against
deliberately wrong answers that it must fail and against blind human labels. It reliably caught clear-cut failures,
but agreed with human judgement of answer quality on only 6 of 10 chatbot answers. That is why judged scores are
warnings, not hard gates, in CI.

**Nearest QA concept.** A reviewer working from a checklist, with a defined pass threshold.

**Tool and version.** DeepEval 4.2.8 `GEval` (Member-Help Chatbot), Promptfoo 0.124.1 `llm-rubric` (Claims
Triage); judge `gpt-6-sol`. Multi-Turn Chatbot: own pass-or-fail judge (`chatbot/judge.py`); DeepEval 4.2.8
conversation metrics for the comparison (`chatbot/deepeval_compare.py`).

## Recall Against Expected Ideas

**What it measures.** How many of the test ideas an experienced tester would expect were found by the generated
test cases. It is the main measure of the Test-Case Generator: does the tool find what a tester would look for?

**Industry term.** *Standard term*. **Recall** against a golden set: of the things that should have been found,
the share that were. Here the "things" are 78 expected test ideas for 10 user stories, written and reviewed in
advance.

**How it's computed.** In the second judge call, the judge sees the story, the expected ideas and the cases, and
decides for each idea whether at least one case covers it. Only a case the first call marked correct can count.
Score = ideas covered ÷ ideas expected, reported overall and by technique (positive, negative, boundary). Agreed
rules guide the judge, for example "the case must include the idea's distinguishing detail". The code is
`bench/judge.py` and `bench/score.py`.

Two LLMs are involved: the generator (`gpt-6-luna`) writes the cases, and the judge (`gpt-6-sol`) decides which
ideas they cover.

![Recall Against Expected Ideas: one idea that is covered and one that is missed](images/metrics/card_recall_expected_ideas.svg)

**Example.** Story S06 says that an amount over the per-visit limit goes to manual review. One expected idea is a
GP visit at €60.01, one cent over the €60 limit. With prompt v1, the generator wrote "GP visit above its limit"
for "an amount greater than 60", with no actual amount, so the judge ruled that it did not cover the €60.01 idea.
With prompt v2, which describes boundary value analysis, it wrote "Submit a GP visit claim for 60.01", which did.
Story S06's recall was 0.40 in every v1 run and averaged 0.93 with v2.

Overall, v2 found 0.75 of the expected ideas and v1 0.63 (averages of 3 runs; ranges 0.70–0.78 and 0.60–0.64).
Twelve ideas were never found by either prompt in any run: mostly domain traps and rules that must not fire.

**When it misleads.** Recall rewards volume: v2 wrote 130 cases per run against v1's 78 to find those extra ideas,
so recall is always reported with precision and the number of cases. It also depends on the judge: re-marking the
same v1 cases with clarified judge instructions raised recall from 0.52 to 0.64, the same +0.12 as the change from
v1 to v2. And it counts only the ideas chosen for the golden set, not every idea worth testing.

**How far to trust it.** Good for comparing prompts, provided the judge is frozen first. Here the judge was frozen
before the comparison runs, and every score records the judge version. The judge's "idea covered" decisions agreed
with blind human labels on 23 of 24 ideas it had never been tuned on.

**Nearest QA concept.** Requirements coverage against a reviewed list of test conditions.

**Tool and version.** Python, `bench/judge.py` and `bench/score.py`; judge prompt `judge_recall_v2`; judge
`gpt-6-sol`.

## Precision (Correct, Non-Duplicate Cases)

**What it measures.** The share of generated test cases worth keeping: correct, and not a repeat of an earlier
case. Every case that is wrong, repeated or outside the specification costs a reviewer time.

**Industry term.** *Project term* for a standard measure. **Precision** is the share of things produced that were
right. The textbook definition counts correct items only; this project also excludes duplicates, because a repeated
case adds review time without adding coverage.

**How it's computed.** In the first judge call, each case is marked correct, incorrect, or "not in basis" (its
expected result is not supported by the story), and checked for duplicates. Score = cases that are correct and not
duplicates ÷ all cases. It is always reported with recall and the number of cases, and also without the "not in
basis" cases.

Two LLMs are involved: the generator writes the cases, and the judge marks them.

![Precision: one case that counts and one that does not](images/metrics/card_precision_testgen.svg)

**Example.** For story S04 (waiting periods), prompt v2 wrote a case for a claim with a missing date. The story does
not say what should happen then, so the case asks the tester to check. The judge marked it "not in basis", so it
does not count towards precision. Yet it is a fair question about a gap in the specification, which prompt v2
asks for.

Precision fell from 1.00 with v1 to 0.91 with v2 (0.94 without the "not in basis" cases). In the first monthly CI
run it fell to 0.81 and raised a warning; 14 of the cases were "not in basis", mostly questions about gaps.
Without them, precision was 0.91, the same as the baseline.

**When it misleads.** When "not in basis" cases are useful questions, as most of v2's were: one found a real gap in
an annual-limit rule. A drop in precision can then mean the generator asked more good questions, not that it wrote
more bad tests. Duplicates are also under-counted (see [Per-Case Quality Checks](#per-case-quality-checks-duplicates-concrete-data-atomic-technique)), so v2's precision is slightly
overstated.

**How far to trust it.** The judge's correctness verdicts held up on cases it had never seen (18 of 20 agreed with
blind human labels), so precision can be trusted, provided it is read with and without the "not in basis" cases.

**Nearest QA concept.** The share of raised defects that are genuine; review efficiency.

**Tool and version.** Python, `bench/judge.py` and `bench/score.py`; judge prompt `judge_cases_v2`; judge
`gpt-6-sol`.

## Claimed against Verified Coverage

**What it measures.** Whether the generator's own labels can be believed. Each generated case lists the
acceptance criteria (ACs) it says it covers; this metric checks those claims.

**Industry term.** *Project term*. The closest industry ideas are **traceability** (each test linked to the
requirement it tests) and **faithfulness** of a model's statements about its own output. There is no standard
metric for this.

**How it's computed.** Two measures:

- **Story level:** the share of a story's ACs that the generator claims to cover (claimed coverage), against the
  share the judge confirms (verified coverage).
- **Case level:** the **over-claim rate**, the share of a case's AC claims the judge does not support.

In the first judge call, the judge checks each claim: does this case really exercise that AC?

Two LLMs are involved: the generator writes the cases and their claims, and the judge checks the claims.

![Claimed against Verified Coverage: one claim that holds and one that does not](images/metrics/card_claimed_vs_verified_coverage.svg)

**Example.** At story level, claimed and verified coverage were both 1.00 in every run, apart from one CI run at
0.97. Every story had every AC claimed and confirmed, with both prompts, while recall ranged from 0.60 to 0.78. So
story-level coverage could not tell a good run from a weak one.

The case-level over-claim rate did move. It was 0.01 to 0.02 with prompt v1 and 0.08 to 0.17 with v2. Most of v2's
over-claims were questions about gaps that still listed an AC. For example, the missing-date case for story S04
claimed AC1, the day-count rule, but with no date the day count cannot be run.

**When it misleads.** Story-level coverage fills up quickly: one case per AC is enough for 100%, however thin the
testing. "Every AC is covered" says nothing about how well. Over-claiming is also partly a question of how the
prompt asks for labels: prompt v2 does not say what a gap case should list, and the same case was labelled
differently in different runs.

**How far to trust it.** Do not use story-level coverage to compare runs or prompts. The over-claim rate is a
useful check on whether the generator's labels can be relied on for traceability.

**Nearest QA concept.** Checking a traceability matrix: does each test really test the requirement it is linked
to?

**Tool and version.** Python, `bench/score.py` and `bench/testcase_schema.py`; judge prompt `judge_cases_v2`;
judge `gpt-6-sol`.

## Per-Case Quality Checks (Duplicates, Concrete Data, Atomic, Technique)

**What it measures.** Four checks on each generated test case, each the share of cases that pass:

- **Duplicate:** does it repeat an earlier case's condition and outcome?
- **Concrete data:** does it give specific inputs a tester could use, such as "60.01" rather than "an amount over
  the limit"?
- **Atomic:** does it test one condition with one outcome?
- **Technique:** which test-design technique does it use: positive, negative or boundary?

**Industry term.** *Project term*. These are rubric criteria chosen for this project from an error analysis of the
first run. They draw on standard test-design practice (ISTQB techniques, atomic test cases), but there is no
standard metric for them.

**How it's computed.** The first judge call marks all four for each case. Duplicates were first measured with
TF-IDF word similarity, then judged by the LLM instead, because TF-IDF scored distinct boundary pairs as near
copies: they share a template and differ only in the number. TF-IDF is kept as a free indicator.

Two LLMs are involved: the generator writes the cases, and the judge marks them.

![Per-Case Quality Checks: one case that passes and one that fails](images/metrics/card_per_case_checks.svg)

**Example.** In the first v1 run, story S06's case "GP visit above its limit" described the claim as "an amount
greater than 60" and gave no actual amount. The judge marked it not concrete: a tester would have to choose the
value, and the €60.01 idea was missed (see [Recall Against Expected Ideas](#recall-against-expected-ideas)). The v2 case "Submit a GP visit claim for
60.01" passed all four checks.

**When it misleads.** When people would not agree on the answer either. On 20 cases the judge had never been tuned
on, it agreed with blind human labels on 18 for atomic, 13 for concrete and only 10 for technique. Is a valid value
exactly at the limit a "positive" case or a "boundary" case? Definitions differ between people and standards.
Duplicates depend on the same kind of choice: whether boundary analysis uses two values (60 and 60.01) or three
(59.99, 60 and 60.01). Of 12 pairs checked blind, all 7 duplicates the judge flagged were confirmed, and it missed
2.

**How far to trust it.** Atomic and duplicate checks: reasonably. Concrete and technique: indicative only, which is
how the project reports them. Agree the definitions before measuring, and write them into the judge's instructions.

**Nearest QA concept.** Test case review against a checklist.

**Tool and version.** Python, `bench/judge.py` and `bench/score.py`; judge prompt `judge_cases_v2`; judge
`gpt-6-sol`; TF-IDF indicator by scikit-learn 1.9.1.

---

# Agents and conversations

## Tool-Call Correctness

**What it measures.** Whether an agent calls the tools it should, with the right arguments, on the right turn,
and does not call tools it must not use on that turn.

**Industry term.** *Standard term*: **tool correctness** or tool-call accuracy. DeepEval offers it as
`ToolCorrectnessMetric`, which compares the tools called with the tools expected; agent evaluation guides list it
as a core agent measure. This project adds tools that are **forbidden** on a turn (calling one fails the turn)
and tools that are **unexpected** (counted as unnecessary, not failed).

**How it's computed.** For each turn, the golden set lists the required tools with their arguments (or "any
arguments", for a free-text search query), the forbidden tools and the unexpected tools. `chatbot/checks.py`
compares them with the tool calls saved in the run record. A required call made earlier in the same conversation
counts ("served by an earlier call"), so the bot isn't failed for answering from memory. The order of calls is not
enforced.

The agent's choice of tools comes from an LLM; the comparison is plain code.

![Tool-Call Correctness: a turn where the agent waits for confirmation, and one where it doesn't](images/metrics/card_tool_call_correctness.svg)

**Example.** A member types "What's the status of HLH021?", with no hyphen. The specification says the bot must
tidy it, ask "Did you mean HLH-021?" and look it up only after the member says yes, so `get_claim_status` is
forbidden on that turn. In one baseline run the agent tidied the ID and looked it up straight away: a forbidden
call, and the turn failed. The claims store would still have returned only the member's own claims, because the
tools are bound to the signed-in member; the check measures the agent's decision, and the store's access check is
the safety net underneath it, tested separately by unit tests.

**When it misleads.** When more than one sequence of calls is valid. In one test the member said "Sorry, the
consultant one"; the test expected an immediate lookup, but the bot listed her claims and asked which she meant,
which the specification also allows. The oracle was changed to accept both. Requiring an exact sequence fails
valid behaviour. It also says nothing about the quality of a free-text argument such as a search query: that is
measured by the retrieval hit rate (see [Key-Fact Recall](#key-fact-recall)).

**How far to trust it.** High for forbidden calls: they are clear-cut and checked by plain code. Required calls
are as good as the oracle's list of acceptable paths. Rare failures need many repeats (see
[Repeat-Run Stability](#repeat-run-stability)).

**Nearest QA concept.** Interaction testing with mocks: verifying that a dependency was, or was not, called, and
with what.

**Tool and version.** Python, `chatbot/checks.py`; agent built with LangGraph 1.2.20; DeepEval's
`ToolCorrectnessMetric` not used.

## Two-Layer Pass Rate (Turns and Conversations)

**What it measures.** The share of turns, and of whole conversations, that pass **both** the plain-code checks
and every LLM-judge check asked on that turn.

**Industry term.** *Project term*. The closest industry terms are **task success rate** or conversation success
rate in agent and chatbot evaluation. Combining code-based checks with model-graded checks is standard advice in
LLM evaluation guides; the all-or-nothing combination is this project's choice.

**How it's computed.** Layer 1, `chatbot/checks.py` (plain code): tools and arguments (see
[Tool-Call Correctness](#tool-call-correctness)), facts the reply must contain, words it must not contain. Layer 2,
`chatbot/judge.py`: an LLM judge (`gpt-6-sol`) answers pass or fail for each check the golden set lists for that
turn, plus two asked on every turn (plain language; no invented facts). The judge is shown the conversation, the
tool results and the rule texts, never the expected answers, and was calibrated and frozen before use. A turn
passes only if both layers pass; a conversation passes only if all its turns pass. Every result is the mean
[lowest-highest] over at least two runs (`chatbot/compare.py`), with every run scored against the same golden-set
version and judge.

![Two-Layer Pass Rate: a turn that passes both layers, and one that passes the text checks but fails the judge](images/metrics/card_two_layer_pass_rate.svg)

**Example.** A member says their cover started on 7 July 2025, then asks "So from what date would I have been
covered?". The bot with the original prompt replied "Your 182nd day was 5 January 2026, so treatment on that date or later would be covered."
The date is right, so the text checks passed; but the bot cannot see the member's start date and stated it as
fact, so the judge failed it. With a prompt line telling it to work conditionally, the reply became "If your cover
began on 7 July 2025, the waiting period ended on 4 January 2026, so you would have been covered for treatment
from 5 January 2026", and both layers passed.

Overall, turns passing both layers rose from 73.3 [70-76] of 96 to 89.5 [89-90], and conversations from 13.7
[13-14] of 28 to 22.0 [21-23], at the same cost per run. The text checks alone scored 93.7 at the start: on their
own they would have shown the bot as nearly perfect before any change was made.

**When it misleads.** The all-or-nothing combination hides which layer, and which check, failed: report the
failures per check alongside it. A judge false alarm fails a turn: here the judge flags statements the bot knows
from its instructions rather than its tools (such as "I can't change the claim"), one to three turns a run. That
affects every run equally, so comparisons stay fair, but the absolute figure is slightly low. The conversation
rate is harsh: one bad turn in ten fails the conversation. And any change to the expected results moves it, which
is why every run is re-scored with the same golden-set version before runs are compared.

**How far to trust it.** As a comparison between versions of the bot, with the same frozen judge and golden set:
good when the ranges don't overlap, as for the first prompt change; changes inside the run-to-run range are
reported as small. As an absolute figure: approximate, bounded by the judge's agreement with human labels (22 of
23 held out) and by the quality of the oracle.

**Nearest QA concept.** A test-case pass rate where each test has both automated assertions and a reviewer's
sign-off, and fails if either fails.

**Tool and version.** Python, `chatbot/checks.py`, `chatbot/judge.py` (judge `gpt-6-sol`, rubric fingerprint
`4aa123f7f26c`), `chatbot/compare.py`.

---

# Validating the judge

## Seeded Defect Detection

**What it measures.** Whether an LLM judge fails outputs that are known to be wrong, and passes outputs that are
known to be right. Defects are planted on purpose, so the correct verdict is known in advance.

**Industry term.** *Common practice*. Planting known defects to test a test is long-standing practice in software
testing (defect seeding, mutation testing). Applying it to LLM judges is widely recommended, but the tools have no
standard metric for it; it is reported as defects caught out of defects planted.

**How it's computed.** Write a set of outputs, each with one deliberate defect, plus **controls**: correct outputs
that the judge must pass. Controls catch a judge that simply fails everything. Run the judge on all of them and
compare each verdict with the expected one. No system under test is involved: the outputs are written by hand. The
Test-Case Generator set uses `datasets/testgen_seeded_defects.json` and `python -m bench.score --seeded`.

The judge is an LLM; comparing its verdicts with the expected ones is plain code.

![Seeded Defect Detection: a planted defect the judge must fail, and a control it must pass](images/metrics/card_seeded_defect_detection.svg)

**Example.** One seeded test case treats a claim submitted on the deadline day as late: an off-by-one error the
judge must mark incorrect. It did, and gave the reason: "Submission on the last day is on time." A control case,
a correct leap-day boundary test, had to be marked correct, boundary, concrete and not a duplicate. All four
checks passed.

All three judges passed their seeded sets:

| Set-up | Seeded set | Result |
| --- | --- | --- |
| Claims Triage | 8 flawed claim summaries, e.g. a wrong amount, a promise of payment | 8 of 8 failed, as they should be |
| Member-Help Chatbot | 8 deliberately bad answers, e.g. a guessed price, a promise of payment | 8 of 8 failed at the 0.75 pass mark |
| Test-Case Generator | 28 seeded cases and ideas, including controls: 46 checks | Judge v1 33 of 33 checks; judge v2 46 of 46 |
| Multi-Turn Chatbot | Real conversations with a made-up reply: 2 that must fail and 1 that must pass for each of 12 checks, plus 1 extra, then 3 added after real runs | 37 of 37, then 39 of 39 and 40 of 40 after each judge change |

**When it misleads.** Seeded defects are usually clearer than real ones. The chatbot judge failed all 8 bad
answers, yet agreed with human judgement on only 6 of 10 real ones. One of the 8 also passed at DeepEval's default
pass mark of 0.5 and only failed at 0.75. A full score shows the judge can see obvious errors, not that it
judges quality the way a person would.

Seeds also only test what they contain. The Multi-Turn Chatbot's judge got all 37 seeds right, then on its first
real run called the member's plan name an invented fact: it hadn't been shown what the portal tells the bot, and
no seed depended on that. The gap was fixed and a seed added for it.

**How far to trust it.** Necessary but not sufficient. A judge that misses a seeded defect should not be used. A
judge that catches them all still needs checking against human labels (see [Agreement with Human Labels](#agreement-with-human-labels-judge-calibration)). Keep the
seeded set and rerun it whenever the judge's instructions or model change, as a regression test for the judge.

**Nearest QA concept.** Defect seeding and mutation testing: testing the tests.

**Tool and version.** Promptfoo 0.124.1 `echo` provider replaying stored outputs (Claims Triage); DeepEval 4.2.8
(Member-Help Chatbot); Python, `bench/score.py --seeded` (Test-Case Generator); `python -m chatbot.judge --seeded`
(Multi-Turn Chatbot).

## Agreement with Human Labels (Judge Calibration)

**What it measures.** How often an LLM judge gives the same verdict as a person who labelled the same outputs
without seeing the judge's verdicts. It tells you whether a judged score can be trusted at all.

**Industry term.** *Common practice*, built on a *standard term*. Checking an LLM judge against human labels is
standard advice in LLM evaluation, but there is no single required method. The standard statistic for agreement
between two raters is Cohen's kappa, which adjusts for agreement by chance. Most of this project reports raw
agreement (for example, 18 of 20), which is simpler but does not make that adjustment.

**How it's computed.** A person labels a sample of outputs blind, the labels are compared with the judge's, and
false passes and false fails are counted separately. In notebook 03 a further round is labelled after tuning, on
cases the judge was never tuned on (the held-out set). Notebook 01 section 9b, and `bench/calibration.py`. The
Multi-Turn Chatbot splits the labels into a tuning half and a held-out half **before** labelling, by a fixed rule,
and shows only the tuning half's disagreements (`chatbot/labels.py`).

![Agreement with Human Labels: one verdict that agrees and one that does not](images/metrics/card_agreement_with_human_labels.svg)

**Example.** The Test-Case Generator's judge was tuned on one set of hand-labelled cases, then tested on 20 new
ones. On "is this test case correct?" it agreed 18 of 20 times, close to its result after tuning. On "which test
technique is this?" it agreed only 10 of 20 times, against 20 of 20 on the set it had been tuned on. So recall
and precision from this judge are trusted, and its technique labels are reported as indicative only.

The Multi-Turn Chatbot's judge was labelled on 51 real verdicts (turn and check), 23 of them held out. Before
tuning: 26 of 28 on the tuning half, 22 of 23 held out. One tuning disagreement led to a rubric fix (a flat "I
don't know" is not a friendly reply); the other was a labelling slip, where the person judged the whole reply
rather than the one check. After the fix, the held-out score was still 22 of 23: the fix helped where it was aimed
and did not overfit. Only two checks had five or more held-out labels, so the others are reported as indicative
only.

In the Claims Triage set-up, the first version of the summary judge failed 11 of 24 summaries that a person
judged good, because it had not been told what the claim fields meant. Kappa was calculated but could not be
used: after one correction, every human label was "pass", so there was no variation for kappa to measure.

**When it misleads.** When agreement is measured on the same cases the judge was tuned on: it then measures
tuning, not reliability. Also when there is only one labeller: disagreement may come from the person, not the
judge (in notebook 03, people apply technique definitions differently). Raw agreement looks high when nearly
every output passes, which is the reason kappa exists.

**How far to trust it.** It is the best evidence available for a judge, but small samples (10 to 24 items here)
and one labeller make every figure approximate. Report the sample size with every agreement figure.

**Nearest QA concept.** Validating a test oracle; inter-rater reliability in reviews.

**Tool and version.** Computed in Python (pandas). Judges: Promptfoo 0.124.1 `llm-rubric` (01), DeepEval 4.2.8
G-Eval (02), own judge prompts (03, 04). Multi-Turn Chatbot: `chatbot/labels.py` (`build`, `agree`, `rekey`).

---

# Cost and change over time

## Cost, Tokens and Latency

**What it measures.** What a run costs and how long it takes: the tokens each call reads and writes, the cost
those tokens add up to, and the response time.

**Industry term.** *Standard term*. Token usage, cost per call and latency are standard non-functional measures
for LLM systems, reported by Promptfoo, DeepEval and the model providers themselves.

**How it's computed.** Each call records its input and output tokens and its response time. Cost = tokens ×
the provider's price per token. Promptfoo reports cost and latency per call and can check them against limits:
the Claims Triage suite allows up to $0.01 and 20 seconds per call. The Member-Help Chatbot and Test-Case
Generator record tokens and seconds in their result files; the Test-Case Generator also prices each call
(`bench/pricing.py`).

![Cost, Tokens and Latency: one result within limits and one that would breach a limit](images/metrics/card_cost_tokens_latency.svg)

**Example.** Three findings, one from each set-up:

- **Claims Triage:** with the final prompt, the stronger model cost about $0.11 per 100 claims and the cheaper one
  about $0.006, roughly 19 times less. The stronger model was also faster (2.0 against 2.5 seconds median). Both
  are fractions of a cent per claim, so the choice rests on safety and accuracy, not price.
- **Member-Help Chatbot:** the fix, passing on 5 passages instead of 3, used about 28% more input tokens per
  answer. Answers were also slower: 4.6 seconds median against 2.6, with one answer taking 21.6 seconds.
- **Test-Case Generator:** judging cost 18 to 28 times as much as generating. A v2 run cost about $0.32, almost
  all of it the judge.

**When it misleads.** When the price is not confirmed: the Test-Case Generator judge is priced at another model's
rate, because its own price has not been confirmed. When latency comes from one run: the k=5 figures come from a
single run of 15 answers with a wide spread, and have not been re-measured. And when only the system is costed:
in these set-ups the testing, mostly the judge, cost far more than the system under test.

**How far to trust it.** Token counts are exact. Cost is as good as the price list behind it. Latency varies with
the provider's load, so it needs repeated runs and medians before it is quoted or used as a limit.

**Nearest QA concept.** Non-functional testing: performance and cost per transaction.

**Tool and version.** Promptfoo 0.124.1 `cost` and `latency` assertions (Claims Triage); Python, result files and
`bench/pricing.py` (Member-Help Chatbot, Test-Case Generator). Prices in USD, as on the provider's price list.

## Semantic Similarity (Not Used)

**What it measures.** How close two pieces of text are in meaning, rather than in the words they share. Used to
compare an answer with an expected answer, to find duplicates, or to power search.

**Industry term.** *Standard term*. Usually computed with **embeddings**: a model turns each text into a list of
numbers that captures its meaning, and texts with similar meaning get similar numbers. Tools offer it directly,
for example Promptfoo's `similar` assertion and RAGAS's semantic similarity metric.

**How it's computed.** Not used in this project. In general: turn both texts into embeddings with an embedding
model, then measure how close they are (usually cosine similarity, from 0 for unrelated to 1 for the same
meaning), and compare with a threshold.

![Semantic Similarity: word matching misses a question that meaning matching could find](images/metrics/card_semantic_similarity.svg)

**Example.** The project used word matching instead (TF-IDF), and two results show where meaning matching might
help, and where it might not:

- **Search.** "I joined three months ago. Can I claim for physiotherapy now?" found the waiting-period passage
  that answers it only at rank 18 (its other expected document, on cover limits, at rank 12), because the answer
  talks about a "waiting period" of "182 days", words the question never uses. No value of k
  fixes that; matching on meaning might. This is a listed next step, so the second lane of the diagram is an
  illustration, not a result.
- **Duplicates.** Word similarity scored distinct boundary test cases (for example €60 and €60.01) as near copies,
  because they share a template, so duplicates were judged by the LLM instead. Embeddings would very likely rate
  these as close in meaning too, so semantic similarity would not obviously have solved this.

**When it misleads.** Texts can be close in meaning but opposite in effect: "acupuncture is covered" and
"acupuncture is not covered" share almost every word and topic, and can score as very similar. It also depends on
the embedding model and the threshold chosen.

**How far to trust it.** Useful for search and for spotting near-duplicates, as long as close scores are read by a
person or a judge. Weak as a correctness check where small words such as "not" or one cent change the answer.

**Nearest QA concept.** Fuzzy matching, but on meaning instead of characters.

**Tool and version.** Not used. The project's word-matching search uses scikit-learn 1.9.1 (TF-IDF).

## Drift

**What it measures.** Whether a system's behaviour changes over time when nobody has changed it on purpose.

**Industry term.** *Standard term*, with four recognised types:

| Type | What changes | How it is usually detected | In this project |
| --- | --- | --- | --- |
| **Data drift** | The inputs: members start asking different questions or sending different claims | Comparing input distributions over time | Not measurable: it needs production inputs |
| **Concept drift** | What counts as correct: the rules change | Accuracy on freshly labelled data falls | Guarded by versioned, fingerprinted golden sets; the plan rules were deliberately left unchanged |
| **Prediction (output) drift** | The mix of outputs: more manual reviews than last month, lower scores | Monitoring output shares and score distributions | Partly: the CI gate tables and history file record results over time |
| **Model drift** | The hosted model: the provider updates it behind the same name | Rerunning a fixed test set on a schedule | The weekly and monthly CI runs; the version the API reports is recorded since M1 (`results/model_versions.csv`) |

**How it's computed.** For model drift, the project reruns frozen tests on a schedule: Claims Triage and the
Member-Help Chatbot every Monday, and the Test-Case Generator benchmark monthly and whenever its files change.
Every input is fingerprinted (a
short hash of the file's content). If a prompt, golden set or judge file has changed without being declared, the
run stops before any model is called, so a change in scores cannot come from an unnoticed edit (prompt drift). The
scores are then compared with thresholds set from a measured baseline (`bench/ci_thresholds.py`).

The models under test, and the judge, are LLMs; the fingerprint and threshold checks are plain code.

![Drift: a scheduled run that shows no drift, and how a drop would show](images/metrics/card_drift.svg)

**Example.** No drift has been seen so far. The monthly benchmark's recall in its five CI runs was 0.71, 0.71,
0.77, 0.70 and 0.76, all within the original range of 0.70 to 0.78. In the three weekly Claims Triage runs, the
stronger model routed 35 of 35 claims correctly every time.

One result is worth watching. Claim HLH-009 was wrongly approved by the cheaper model in 2 of 3 runs in notebook
01, but in none of the three CI runs. If its true rate were still 2 in 3, three clean runs in a row would happen by
chance about 4% of the time. That is not enough to call it a change, but it is the kind of signal monitoring is
for.

**When it misleads.** When the runs are too few to separate drift from run-to-run variation: a single low run is
not drift. When the provider does not expose a version. Since M1 each run records what the API reports, but for
these models it reports only the name, returns no backend fingerprint and lists no dated versions. A silent update
behind the name can only show up in the scores, which is why the frozen, fingerprinted test set is the drift
detector. And when the test set is frozen but the world is not: a fixed test set detects model drift, not data
or concept drift.

**How far to trust it.** The set-up reliably separates "we changed something" from "the model changed", which is
the hard part. Detecting small changes needs more runs, so judged scores stay as warnings until their normal
spread across CI runs is known.

**Nearest QA concept.** Scheduled regression testing against a third-party dependency that can change without
notice.

**Tool and version.** GitHub Actions (`evals.yml` weekly, `benchmark.yml` monthly); Python, `bench/ci_thresholds.py`
and the fingerprint checks; results in `results/ci_gates/` and `results/testgen_history.csv`.
