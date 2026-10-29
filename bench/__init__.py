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

The notebook 03_testgen_benchmark.ipynb and the Day 5 CI job both import these
modules, so the benchmark logic exists in one place only.
"""
