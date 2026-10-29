# Glossary: testing AI, in QA terms

Each term with its plain meaning, the nearest conventional QA concept, and where it appears in this portfolio
(01 claim triage, 02 member-help chatbot, 03 AI test generation, CI continuous evaluation).

## Core concepts

| Term | Meaning | Nearest QA concept | Where |
| --- | --- | --- | --- |
| Eval | A repeatable test of AI output quality against agreed criteria | Test suite | All |
| Test basis | The documents that say what correct behaviour is | Specification, requirements | All |
| Oracle | The source of the expected result for each test | Expected results | All |
| Golden dataset (golden set) | Curated inputs with expected outputs or criteria, agreed and frozen | Test data with expected results | All |
| Assertion / metric | A check on an output; metrics usually return a score from 0 to 1 and pass above a threshold | Assertion with a pass threshold | All |
| Non-determinism | The same input can give different outputs from one run to the next | A flaky test, but by design | 01, 02, 03 |
| Temperature | A model setting that controls how random its output is | Test environment variable | 01 |
| Tokens | The units of text a model reads and writes; they drive cost and speed | Load unit for non-functional testing | All |
| Prompt | The instructions given to the model; changing it changes the system | Configuration under version control | All |
| Hallucination | Confident output not supported by the facts or the context given | Incorrect result | 01, 02, 03 |
| Grounding / faithfulness | Every claim in the answer is supported by the context supplied | Traceability to source | 01, 02 |

## Judging output

| Term | Meaning | Nearest QA concept | Where |
| --- | --- | --- | --- |
| Deterministic check | A check written in code that always gives the same verdict, e.g. exact match or JSON schema | Automated assertion | All |
| LLM-as-a-judge | A model grades another model's output against a rubric | Peer review, automated | 01, 02, 03 |
| Rubric | The written criteria a judge applies | Acceptance criteria for a review | 01, 02, 03 |
| G-Eval | DeepEval's method for custom judged criteria written in plain language | Custom acceptance criterion | 02 |
| Judge calibration | Comparing the judge's verdicts with human labels to see how far it can be trusted | Validating a test oracle | 01, 02, 03 |
| Blind labelling | A human labels outputs without seeing the judge's verdict first | Independent review | 01, 02, 03 |
| Held-out set | Cases kept out of tuning the judge, used only to measure it | Independent test set | 03 |
| Seeded defect | A deliberately wrong output the judge must fail | Defect seeding, mutation testing | 01, 02, 03 |
| False pass / false fail | The judge passes a bad output / fails a good one | False negative / false positive in testing | 01, 02, 03 |
| Cohen's kappa | Agreement between two raters, adjusted for chance | Inter-rater reliability | 01 |
| Semantic similarity | Comparing meaning, usually with embeddings (numeric representations of text). Not used in this portfolio | Fuzzy matching on meaning | (README notes) |
| Lexical similarity (TF-IDF) | Comparing shared words, weighted by how distinctive they are. Compares words, not meaning | Text comparison | 02, 03 |

## Measures

| Term | Meaning | Nearest QA concept | Where |
| --- | --- | --- | --- |
| Accuracy | Share of outputs that match the expected result | Pass rate | 01 |
| Precision | Of the things flagged or produced, the share that were right | Share of raised defects that are genuine | 01, 02, 03 |
| Recall | Of the things that should have been found, the share that were | Defect detection rate, coverage | 01, 02, 03 |
| False auto-approval | A claim approved automatically when the rules required a person to review it; the costly error in 01 | Escaped defect with business impact | 01 |
| Consistency / stability | Whether repeated runs give the same result | Flakiness rate | 01, 02 |
| Fairness (counterfactual pairs) | Two inputs identical except a personal attribute must get the same outcome | Equivalence testing on a protected attribute | 01 |
| Not in basis | A generated test whose expected result the specification does not support; often a fair question about a gap | Specification gap raised during review | 03 |

## Retrieval-augmented generation (RAG)

| Term | Meaning | Nearest QA concept | Where |
| --- | --- | --- | --- |
| RAG | Retrieval-augmented generation: fetch relevant documents, then answer from them | Two components: search plus report | 02 |
| Retriever / generator | The search component / the component that writes the answer | Components tested separately | 02 |
| Chunk | A slice of a document stored for retrieval | Test data partition | 02 |
| Top k | How many chunks are passed to the generator | Result page size | 02 |
| Contextual precision / recall | Whether the retriever ranks relevant chunks high / finds all the chunks needed | Search result accuracy and completeness | 02 |
| RAG triad | Context relevance, grounding and answer relevance, scored together | Component and end-to-end checks | 02 |
| Retrieval failure | The right information never reaches the generator | Upstream defect | 02 |
| Fault injection | Breaking a component on purpose to see which checks notice | Fault injection, mutation testing | 02 |

## Security and safety

| Term | Meaning | Nearest QA concept | Where |
| --- | --- | --- | --- |
| Prompt injection (direct / indirect) | Instructions hidden in user input or retrieved content that hijack the model | Injection attack, as in SQL injection | 01, 02 |
| Jailbreak | Input crafted to bypass safety rules | Security bypass | (not tested separately) |
| Red teaming | Adversarial testing for security and safety failures | Penetration testing | 01 |
| OWASP Top 10 for LLM Applications | The standard list of security risks for LLM-based systems | OWASP Top 10 | 01, primer |
| Guardrail | A runtime filter or rule on inputs or outputs | Input validation, output sanitisation | 01, 02 |

## Change over time and CI

| Term | Meaning | Nearest QA concept | Where |
| --- | --- | --- | --- |
| Prompt regression | Re-running the same tests after a prompt change and comparing with the baseline | Regression testing | 01, 03 |
| Schema regression | Output that no longer meets its agreed structure | Interface contract break | 01, 03, CI |
| Model drift | The hosted model behaves differently over time without any change on your side | Unannounced change in a third-party dependency | CI |
| Prompt drift | Unnoticed or unrecorded changes to a prompt | Configuration drift | 03, CI |
| Fingerprint | A short hash of a file's content, recorded with every result so any change is visible | Version identifier, checksum | 03, CI |
| Baseline | The measured results that later runs are compared against | Baseline | All |
| Quality gate | A threshold a CI run must meet; a hard gate fails the run, a warning is only reported | Release criteria, exit criteria | CI |
| Error analysis | Reviewing real outputs to categorise failure modes before writing evals | Defect root-cause analysis | 03 |
| Eval-driven development | Writing evals before changing prompts or models | Test-driven development | All |

## Agents

| Term | Meaning | Nearest QA concept | Where |
| --- | --- | --- | --- |
| Agent | An LLM that plans and calls tools across several steps. Notebook 03 tests a single prompt, not an agent | Workflow orchestrator | (not used) |
| Tool call | An agent invoking a function or API | Integration call | (not used) |
| Trace / span | The recorded steps of one request through an AI system | Log and distributed trace | (stretch goal) |
