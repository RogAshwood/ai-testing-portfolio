"""bench: the Day 4 AI test-generation benchmark.

Modules
- golden.py          load the frozen golden set, build the story card the generator sees
- testcase_schema.py parse and check the generator's JSON (free, deterministic)
- generate.py        call the generator once per story and save every output
- judge.py           the LLM judge: Call A (cases) and Call B (recall) per story
- score.py           free metrics + judge metrics per story, history file, seeded check
- calibration.py     blind label sheets and judge-vs-human agreement
- review_sheet.py    error-analysis review sheet (cases next to expected ideas) per run
- pricing.py         token prices (USD per million) for cost reporting
- run_benchmark.py   Day 5 CI step: fingerprint check, one v2 run, score, history, gates
- promptfoo_gate.py  Day 5 CI gates for the Promptfoo claim-triage results
- ci_thresholds.py   every CI threshold, with the baseline it was set from
- ci_report.py       gate results to console, GitHub run summary and results/ci_gates/

The notebook 03_testgen_benchmark.ipynb and the Day 5 CI job both import these
modules, so the benchmark logic exists in one place only.
"""
