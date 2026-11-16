"""measure_lints.py: how often each lint flags, and how often it is right, on the Day 4 cases.

Why: a lint that flags wrongly a lot teaches people to ignore it. The scope note
(decision 3) says a lint that is wrong more than about 1 time in 3 is dropped or
reworded. This script gives the evidence. It is free: no model calls.

What it compares (all Day 4 data already in the repo)
-----------------------------------------------------
1. Flag rate per lint on each Day 4 run (how many cases each lint flags).
2. missing_test_data against
     - Roger's "concrete" labels (40 cases: 20 from v1 run 1, 20 from v2 run 1), and
     - the judge's "concrete" marks (every case in each run with a score file).
   The lint flags "no concrete value"; it agrees when the label says not concrete.
3. near_duplicate against
     - Roger's 12 labelled pairs (results/testgen/calibration/cal_duplicates_v2_...csv), and
     - the judge's duplicate marks, for three settings of the values rule.
4. A review sheet of every flag from the lints that have no labels yet
   (generic_title, vague_steps, vague_expected, placeholders, boundary_hint),
   with an empty my_agree column for Roger (y = a fair warning, n = a false alarm).

Usage (from the repo root): python -m harness.measure_lints
Writes results/harness/lint_measurement_<UTC time>/: flag_rates.csv, agreement.md, review_sheet.csv

Change history:
  2026-11-12  v1  first version (M7 step 1).
  2026-11-12  v2  repeated_expected added to the review sheet; step objects supported.
  2026-11-12  v3  info-level reminders (boundary_hint durations) are not counted as flags.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from bench.golden import ROOT
from harness.contract import actions, case_key, input_text, load_cases, load_stories
from harness.lints import LINT_NAMES, LINTS, load_rules, similar_pairs, values_in

GOLDEN = ROOT / "datasets" / "testgen_golden.json"
TESTGEN = ROOT / "results" / "testgen"
CAL = TESTGEN / "calibration"
RUNS = {                                   # run name: (generation file, score file or None)
    "v1 run 1": ("gen_v1_gpt-6-luna_g1.0_r1_20261023T145401Z.json", None),
    "v2 run 1": ("gen_v2_gpt-6-luna_g1.0_r1_20261028T124635Z.json",
                 "score_v2_gpt-6-luna_g1.0_r1_20261028T124635Z_jff34c1fc3ab1_20261028T142725Z.json"),
    "v2 bench-6": ("gen_v2_gpt-6-luna_g1.0_rbench-6_20261110T204630Z.json",
                   "score_v2_gpt-6-luna_g1.0_rbench-6_20261110T204630Z_jff34c1fc3ab1_20261110T205447Z.json"),
}
HUMAN_CONCRETE = {                         # run name: (labels file, key file) - the latest labels per run
    "v1 run 1": ("cal_cases_v1_gpt-6-luna_g1.0_r1.csv", "cal_key_v1_gpt-6-luna_g1.0_r1.csv"),
    "v2 run 1": ("cal_cases_v2_gpt-6-luna_g1.0_r1.csv", "cal_key_v2_gpt-6-luna_g1.0_r1.csv"),
}
HUMAN_DUPLICATES = ("v2 run 1", "cal_duplicates_v2_gpt-6-luna_g1.0_r1.csv")
UNLABELLED = ("generic_title", "vague_steps", "vague_expected", "repeated_expected", "placeholders", "boundary_hint")


def _csv(path: Path) -> list[dict]:
    """Read a CSV file (Excel's byte-order mark allowed) into a list of dicts."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def judge_marks(score_file: str | None) -> dict[tuple[str, str], dict]:
    """{(story_id, case_id): judge's mark} from a Day 4 score file, or {} if there is none."""
    if not score_file:
        return {}
    data = json.loads((TESTGEN / score_file).read_text(encoding="utf-8"))
    marks = {}
    for st in data["stories"]:
        sid = st["metrics"]["story_id"]
        parsed = (st.get("judgement") or {}).get("cases_call", {}).get("parsed") or {}
        for c in parsed.get("cases", []):
            marks[(sid, c["case_id"])] = c
    return marks


def human_concrete(run: str) -> dict[tuple[str, str], bool]:
    """{(story_id, case_id): Roger's concrete label as True/False} for one run, via the key file."""
    if run not in HUMAN_CONCRETE:
        return {}
    labels_file, key_file = HUMAN_CONCRETE[run]
    key = {r["label_id"]: (r["story_id"], r["case_id"]) for r in _csv(CAL / key_file)}
    return {key[r["label_id"]]: r["my_concrete"].strip().lower() == "y"
            for r in _csv(CAL / labels_file) if r["my_concrete"].strip()}


def agreement_table(pairs: list[tuple[bool, bool]], name_flag: str, name_label: str) -> dict:
    """Count a 2x2 table: lint flag (True/False) against the label (True = the label agrees a flag is due)."""
    t = {"both": 0, "flag_only": 0, "label_only": 0, "neither": 0}
    for flag, due in pairs:
        t["both" if flag and due else "flag_only" if flag else "label_only" if due else "neither"] += 1
    flags = t["both"] + t["flag_only"]
    t["n"] = len(pairs)
    t["agree"] = t["both"] + t["neither"]
    t["false_flag_rate"] = round(t["flag_only"] / flags, 2) if flags else None
    t["text"] = (f"{t['agree']}/{t['n']} agree; {flags} flagged, of which {t['flag_only']} false "
                 f"({name_label} disagrees); {t['label_only']} missed ({name_label} says a flag was due)")
    return t


def pair_verdicts(stories, groups, threshold, require_same, when_no_values) -> dict[tuple[str, str, str], bool]:
    """{(story, earlier case, later case): would the lint call this pair a duplicate?} for every pair."""
    out = {}
    for sid, cases in groups.items():
        sims = {(a, b): s for a, b, s in similar_pairs(cases, 0.0)}    # threshold 0: score every pair
        for (a, b), s in sims.items():
            va, vb = values_in(input_text(cases[a])), values_in(input_text(cases[b]))
            ok = s >= threshold                                         # similar enough in wording?
            if ok and require_same:                                     # the same-values rule, as in lints.py
                ok = va == vb and (bool(va) or when_no_values)
            out[(sid, case_key(cases[a], a + 1), case_key(cases[b], b + 1))] = ok
    return out


def review_row(run: str, name: str, finding, story: dict, cases: list[dict]) -> dict:
    """One review-sheet row for a lint warning: the warning, the case (or the AC for a
    story-level boundary hint) and empty my_agree / notes columns for Roger."""
    case = next((c for n, c in enumerate(cases, 1) if case_key(c, n) == finding.case_id), {})
    ac_id = finding.message.split(" ", 1)[0] if name == "boundary_hint" else ""
    ac_text = next((a["text"] for a in story["acceptance_criteria"] if a["ac_id"] == ac_id), "")
    return {"run": run, "lint": name, "story_id": finding.story_id, "case_id": finding.case_id,
            "title": case.get("title", ""), "message": finding.message,
            "acceptance_criterion": f"{ac_id}: {ac_text}" if ac_text else "",
            "steps": " | ".join(actions(case)), "expected_result": case.get("expected_result", ""),
            "my_agree": "", "notes": ""}


def run_all_lints(stories: dict, rules: dict) -> tuple[dict, dict, list[dict]]:
    """Run every lint (switched on or not) over every Day 4 run.
    Returns (cases per run, warnings per run and lint, review-sheet rows for the unlabelled lints)."""
    groups_by_run, flags_by_run, review_rows = {}, {}, []
    for run, (gen, _) in RUNS.items():
        groups, _ = load_cases(TESTGEN / gen)
        groups_by_run[run] = groups
        flags_by_run[run] = {}
        for name in LINT_NAMES:
            found = [f for sid, st in stories.items() if groups.get(sid)
                     for f in LINTS[name](st, groups[sid], rules[name]) if f.level == "warn"]   # info is not a flag
            flags_by_run[run][name] = found
            if name in UNLABELLED:
                review_rows += [review_row(run, name, f, stories[f.story_id], groups[f.story_id]) for f in found]
    return groups_by_run, flags_by_run, review_rows


def section_flag_rates(groups_by_run: dict, flags_by_run: dict) -> tuple[list[str], list[dict]]:
    """Section 1: how many cases each lint flags in each run (markdown lines and CSV rows)."""
    md = ["## 1. Flag rate per lint (cases flagged / cases)", "",
          "| Lint | " + " | ".join(RUNS) + " |", "|---|" + "---|" * len(RUNS)]
    rows = []
    n_cases = {run: sum(len(c) for c in g.values()) for run, g in groups_by_run.items()}
    for name in LINT_NAMES:
        cells = []
        for run in RUNS:
            k = len(flags_by_run[run][name])
            # boundary_hint counts AC numbers with a gap, not cases, so it has no percentage
            cells.append(f"{k} ACs/numbers" if name == "boundary_hint" else f"{k}/{n_cases[run]} ({k / n_cases[run]:.0%})")
            rows.append({"lint": name, "run": run, "flags": k, "cases": n_cases[run]})
        md.append(f"| {name} | " + " | ".join(cells) + " |")
    return md, rows


def section_missing_test_data(flags_by_run: dict) -> list[str]:
    """Section 2: missing_test_data warnings against Roger's and the judge's 'concrete' marks.
    A warning is right when the label says the case is NOT concrete."""
    md = ["", "## 2. missing_test_data against concrete labels", "",
          "The lint flags a case with no number, date or quoted text in its preconditions or steps. "
          "It should agree with a 'not concrete' label.", ""]
    human_pairs, judge_lines = [], []
    for run, (_, score) in RUNS.items():
        flagged = {(f.story_id, f.case_id) for f in flags_by_run[run]["missing_test_data"]}
        for key, concrete in human_concrete(run).items():
            human_pairs.append((key in flagged, not concrete))
        marks = judge_marks(score)
        if marks:
            t = agreement_table([(k in flagged, not m["concrete"]) for k, m in marks.items()], "lint", "judge")
            judge_lines.append(f"- Judge, {run}: {t['text']}; false-flag rate {t['false_flag_rate']}")
    t = agreement_table(human_pairs, "lint", "Roger")
    return md + [f"- Roger's labels (40 cases): {t['text']}; false-flag rate {t['false_flag_rate']}", *judge_lines]


def section_near_duplicate(stories: dict, groups_by_run: dict, rules: dict) -> list[str]:
    """Section 3: near_duplicate against Roger's 12 labelled pairs and the judge's duplicate marks,
    for three settings of the same-values rule, then each labelled pair with its similarity."""
    run, dup_file = HUMAN_DUPLICATES
    labelled = _csv(CAL / dup_file)
    marks = judge_marks(RUNS[run][1])
    judge_dup = {(sid, m["duplicate_of"], cid) for (sid, cid), m in marks.items() if m.get("duplicate_of")}
    threshold = rules["near_duplicate"]["threshold"]
    md = ["", f"## 3. near_duplicate against Roger's 12 labelled pairs and the judge ({run})", "",
          f"Similarity threshold {threshold} (TF-IDF). "
          "Judge column: pairs the judge marked as duplicates, how many the lint also flags.", "",
          "| Setting | Agree with Roger | False flags | Missed | Judge pairs also flagged | Lint flags the judge did not |",
          "|---|---|---|---|---|---|"]
    settings = [("similarity only", False, False),
                ("same values, pairs with no values not flagged (default)", True, False),
                ("same values, pairs with no values flagged", True, True)]
    for label, require_same, when_no_values in settings:
        verdicts = pair_verdicts(stories, groups_by_run[run], threshold, require_same, when_no_values)
        t = agreement_table([(verdicts.get((r["story_id"], r["earlier_case"], r["later_case"]), False),
                              r["my_duplicate"].strip().lower() == "y") for r in labelled], "lint", "Roger")
        lint_pairs = {k for k, v in verdicts.items() if v}
        md.append(f"| {label} | {t['agree']}/{t['n']} | {t['flag_only']} | {t['label_only']} | "
                  f"{len(judge_dup & lint_pairs)}/{len(judge_dup)} | {len(lint_pairs - judge_dup)} |")
    md += ["", "Roger's pairs, with the lint's similarity:", "",
           "| Pair | Story | Cases | Similarity | Same values? | Roger | Roger's reason |", "|---|---|---|---|---|---|---|"]
    for r in labelled:
        cases = groups_by_run[run][r["story_id"]]
        idx = {case_key(c, n): n - 1 for n, c in enumerate(cases, 1)}       # case ID -> position
        a, b = idx[r["earlier_case"]], idx[r["later_case"]]
        sim = next((s for x, y, s in similar_pairs(cases, 0.0) if (x, y) == (a, b)), None)
        same = values_in(input_text(cases[a])) == values_in(input_text(cases[b]))
        md.append(f"| {r['pair_id']} | {r['story_id']} | {r['earlier_case']}–{r['later_case']} | {sim} | "
                  f"{'yes' if same else 'no'} | {r['my_duplicate']} | {r['my_reason']} |")
    return md


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    """Write rows to a CSV file that opens cleanly in Excel (UTF-8 with byte-order mark)."""
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    """Run the measurement: lints over every Day 4 run, the three comparison sections,
    then write flag_rates.csv, review_sheet.csv and agreement.md and print the report."""
    stories = load_stories(GOLDEN)
    rules = load_rules()
    out_dir = ROOT / "results" / "harness" / f"lint_measurement_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    out_dir.mkdir(parents=True, exist_ok=True)

    groups_by_run, flags_by_run, review_rows = run_all_lints(stories, rules)
    rates_md, rate_rows = section_flag_rates(groups_by_run, flags_by_run)
    md = ["# Lint measurement on the Day 4 cases", "",
          f"Settings: harness/lint_rules.toml as of {datetime.now(timezone.utc):%Y-%m-%d}. Free; no model calls.", "",
          *rates_md,
          *section_missing_test_data(flags_by_run),
          *section_near_duplicate(stories, groups_by_run, rules),
          "", "## 4. Lints with no labels yet", "",
          f"Every flag from {', '.join(UNLABELLED)} is in review_sheet.csv ({len(review_rows)} rows). "
          "Mark my_agree y (a fair warning) or n (a false alarm)."]

    write_csv(out_dir / "flag_rates.csv", ["lint", "run", "flags", "cases"], rate_rows)
    write_csv(out_dir / "review_sheet.csv", ["run", "lint", "story_id", "case_id", "title", "message",
                                             "acceptance_criterion", "steps", "expected_result", "my_agree", "notes"],
              review_rows)
    (out_dir / "agreement.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    print(f"\nsaved {out_dir}")


if __name__ == "__main__":
    main()
