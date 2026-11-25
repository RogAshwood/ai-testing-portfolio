"""harness: M7 test-case checking harness.

Checks test cases written by any AI tool against the user stories they were
written for, without an answer key ("oracle-free"). It reports, case by case,
what is wrong, so a reviewer looks at the worst cases first.

Modules
- contract.py      read the stories file and the cases file; the input contract (schema)
- checks.py        free code checks: titles, AC links, ACs with no tests (fail or warning)
- lints.py         free style lints, each switchable: vague wording, missing test data,
                   placeholders, near duplicates, boundary hints (warnings only)
- lint_rules.toml  the lint settings and word lists a team can edit
- judge.py         the AI checks: the frozen Day 4 case judge (verdict, atomic, duplicate,
                   AC claims, concrete) and a new title judge, turned into findings
- checklist.py     checklist-based testing in two passes: story review (story and ACs only; AC gaps
                   -> questions for the product owner; saved and reused) and test coverage of the
                   ideas the ACs define (gaps -> suggestions for the test cases)
- checklist.toml   the generic test ideas (C01-C18), team-editable
- prompts/         judge prompts (judge_title_v1, judge_story_review_v1, judge_test_coverage_v1)
                   and the bare generator prompt (testgen_bare.txt)
- check.py         the command: python -m harness.check --stories <file> --cases <file>
- regression.py    proves the judge checks match the Day 4 benchmark (exact, free) and
                   compares a live run with the Day 4 marks
- seeded.py        runs the harness on cases with known defects (datasets/harness_seeded_cases.json
                   and the Day 4 seeds) and reports caught / missed / false alarms
- generate_bare.py generates cases with a bare "write test cases" prompt (prompts/testgen_bare.txt),
                   a weaker, everyday generator style to check
- report.py        one HTML page per run (report.html): flagged cases first, coverage map per AC,
                   checklist, duplicate groups, steps per case; can rebuild a page for an earlier run
- generate.py      generates cases for ANY stories file with the Day 4 v1/v2 prompts or the bare
                   prompt (M7 step 5: datasets/aml_kyc_stories.json)
- measure_lints.py how often each lint flags, and how often it agrees with Roger's
                   Day 4 labels and the Day 4 judge (run once to tune the lints)

The harness only imports from bench/ (the Day 4 benchmark); it never edits it,
so changing harness files does not start the benchmark CI workflow.

Change history:
  2026-11-12  v1  first version (M7 step 1: input contract, code checks, lints; no judge yet).
  2026-11-12  v2  M7 step 3: judge.py, prompts/, regression.py.
  2026-11-12  v3  M7 step 4: seeded.py, generate_bare.py, calendar caution in judge.py.
  2026-11-13  v4  M7 step 4b: checklist.py, checklist.toml; two-value BVA; case_detail setting.
  2026-11-13  v5  two-pass checklist, parallel stories, --stories-only.
  2026-11-24  v6  M7 step 5: generate.py (any stories file); checklist "check" setting (v5 of checklist.py).
  2026-11-24  v7  M7 step 6: report.py (report.html).
"""
