"""seeded.py: run the harness on cases with known defects and score what it catches.

Go/no-go criterion 3 is "all seeded defects are caught". This script gives the evidence.
Three sets of seeds:

  harness  datasets/harness_seeded_cases.json (M7, 12 Nov): 23 hand-written cases in the style
           real teams produce (vague steps, "works as expected", placeholders, generic titles,
           copied per-step expected results, wrong AC links, a missing expected result, wrong or
           invented outcomes, bundled checks, a reworded duplicate, an unclear title), 7 clean
           controls, a calendar-edge variant, and 2 story-level seeds. Insurance stories.
  aml      datasets/aml_seeded_cases.json (M7 step 5, 24 Nov): 18 hand-written cases on the AML/KYC
           stories (datasets/aml_kyc_stories.json), 6 clean controls, 2 story-level seeds: the same
           kinds of defect in a second domain.
  day4     datasets/testgen_seeded_defects.json case seeds (Day 4, judge v2 passed 46/46 on the
           judge's own marks). Here they test the harness's reading of those marks: each expected
           judge value becomes a finding that must (or must not) appear.

How each seed is scored
  caught        every check in must_fire appeared on the case (or the story, for story-level seeds)
  missed        a must_fire check did not appear
  false alarm   on a control (or for a must_not_fire check), a finding appeared that should not have
  not run       the check needs the judge and --no-judge was given
  ok            a control (or conditional seed) raised nothing it should not
Usage (repo root):
    python -m harness.seeded                 # harness and day4 sets, judge on (paid: about $0.15-0.25)
    python -m harness.seeded --no-judge      # free checks only
    python -m harness.seeded --set harness   # one set (harness, day4 or aml)
    python -m harness.seeded --set aml       # the AML/KYC seeds (paid: about $0.10)
    python -m harness.seeded --set all       # all three
Writes results/harness/seeded_<UTC time>/: report.md, seeds.csv, and the harness outputs per set.
Exit code 0 if every seeded defect was caught (judge checks included when run), else 1.

Change history:
  2026-11-12  v1  first version (M7 step 4).
  2026-11-24  v2  aml set (AML/KYC seeds on a second domain); --set all.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from bench.golden import ROOT
from harness.check import JUDGE_CHECKS, run_checks, write_outputs

GOLDEN = ROOT / "datasets" / "testgen_golden.json"
AML_STORIES = ROOT / "datasets" / "aml_kyc_stories.json"
HARNESS_SEEDS = ROOT / "datasets" / "harness_seeded_cases.json"
AML_SEEDS = ROOT / "datasets" / "aml_seeded_cases.json"
DAY4_SEEDS = ROOT / "datasets" / "testgen_seeded_defects.json"
JUDGE_ONLY = set(JUDGE_CHECKS) | {"ac_unverified"}


# --- building the inputs ----------------------------------------------------------
def harness_set(path: Path = HARNESS_SEEDS) -> tuple[list[dict], list[dict], list[dict]]:
    """An M7 seed file (harness or aml) as (story groups of cases, case expectations, story-level expectations)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["stories"], data["expectations"]["cases"], data["expectations"]["story_level"]


def day4_set() -> tuple[list[dict], list[dict], list[dict]]:
    """The Day 4 case seeds turned into harness expectations. Each expected judge value maps to a
    finding: verdict incorrect / not_in_basis -> 'verdict'; atomic false -> 'atomic'; concrete
    false -> 'concrete'; unsupported ACs -> 'over_claim'; duplicate_of -> 'duplicate'. A value
    that says 'no problem' (verdict correct, atomic true, ...) becomes a must_not_fire check.
    The technique label is not a finding, so it is not scored here."""
    data = json.loads(DAY4_SEEDS.read_text(encoding="utf-8"))
    groups, expectations = [], []
    for g in data["case_seeds"]:
        groups.append({"story_id": g["story_id"], "test_cases": [s["case"] for s in g["seeds"]]})
        for s in g["seeds"]:
            want = s["expect"]
            must, must_not = [], []
            rules = {"verdict": want.get("verdict") in ("incorrect", "not_in_basis") if "verdict" in want else None,
                     "atomic": (want["atomic"] is False) if "atomic" in want else None,
                     "concrete": (want["concrete"] is False) if "concrete" in want else None,
                     "over_claim": bool(want["unsupported"]) if "unsupported" in want else None,
                     "duplicate": bool(want["duplicate_of"]) if "duplicate_of" in want else None}
            for check, fires in rules.items():
                if fires is True:
                    must.append(check)
                elif fires is False:
                    must_not.append(check)
            expectations.append({"seed_id": s["seed_id"], "story_id": g["story_id"], "case_id": s["case"]["case_id"],
                                 "defect": s["defect"], "must_fire": must, "must_not_fire": must_not, "control": False})
    return groups, expectations, []


def write_inputs(groups: list[dict], folder: Path, stories_file: Path = GOLDEN) -> tuple[Path, Path]:
    """Write a stories file holding only the stories these seeds use (so stories without
    cases do not add noise) and the cases file, in folder. Returns (stories path, cases path)."""
    golden = json.loads(stories_file.read_text(encoding="utf-8"))
    used = {g["story_id"] for g in groups}
    folder.mkdir(parents=True, exist_ok=True)
    stories_path, cases_path = folder / "stories.json", folder / "cases.json"
    stories_path.write_text(json.dumps({"stories": [s for s in golden["stories"] if s["story_id"] in used]},
                                       ensure_ascii=False), encoding="utf-8")
    cases_path.write_text(json.dumps({"stories": groups}, ensure_ascii=False), encoding="utf-8")
    return stories_path, cases_path


# --- scoring ----------------------------------------------------------------------
def score_case(exp: dict, findings: list, judge_ran: bool) -> dict:
    """Score one case expectation against the findings on that case (info-level reminders ignored)."""
    on_case = [f for f in findings if f.story_id == exp["story_id"] and f.case_id == exp["case_id"]
               and f.level in ("fail", "warn")]
    fired = {f.check for f in on_case}
    not_run = [c for c in exp["must_fire"] + exp.get("must_not_fire", []) if c in JUDGE_ONLY and not judge_ran]
    missed = [c for c in exp["must_fire"] if c not in fired and c not in not_run]
    false = sorted(c for c in exp.get("must_not_fire", []) if c in fired)
    if exp.get("control"):
        false = sorted(fired - set(exp.get("tolerate", [])))
    if exp.get("if_duplicate_then_caution"):
        dup = [f for f in on_case if f.check == "duplicate"]
        if dup and "Caution" not in dup[0].message:
            missed.append("calendar caution")
    # kind: a defect seed (something must fire), a control (nothing, or named checks, must not fire),
    # or a conditional seed (only the calendar-caution rule applies)
    kind = ("defect" if exp["must_fire"] else
            "control" if exp.get("control") or exp.get("must_not_fire") else "conditional")
    if missed:
        result = "missed"
    elif false:
        result = "false alarm"
    elif not_run:
        result = "not run"
    else:
        result = "caught" if kind == "defect" else "ok"
    expected = (", ".join(exp["must_fire"]) if kind == "defect" else
                "none (control)" if exp.get("control") else
                f"must not fire: {', '.join(exp['must_not_fire'])}" if exp.get("must_not_fire") else
                "caution if a duplicate")
    return {"seed_id": exp["seed_id"], "story_id": exp["story_id"], "case_id": exp["case_id"], "kind": kind,
            "defect": exp["defect"], "expected": expected,
            "found": ", ".join(sorted(fired)) or "none", "missed": ", ".join(missed), "false_alarm": ", ".join(false),
            "result": result}


def score_story(exp: dict, findings: list, judge_ran: bool) -> dict:
    """Score one story-level expectation: a finding of that check on that story containing the text."""
    hit = any(f.story_id == exp["story_id"] and not f.case_id and f.check == exp["check"]
              and exp.get("contains", "") in f.message for f in findings)
    not_run = exp["check"] in JUDGE_ONLY and not judge_ran
    return {"seed_id": exp["seed_id"], "story_id": exp["story_id"], "case_id": "(story)", "kind": "defect",
            "defect": exp["defect"],
            "expected": f"{exp['check']} ({exp.get('contains', '')})", "found": "yes" if hit else "no",
            "missed": "" if hit or not_run else exp["check"], "false_alarm": "",
            "result": "caught" if hit else ("not run" if not_run else "missed")}


def run_set(name: str, out_dir: Path, judge: bool) -> tuple[list[dict], dict]:
    """Run the harness on one seed set and score it. Returns (rows, the harness result)."""
    groups, case_exp, story_exp = (harness_set() if name == "harness" else
                                   harness_set(AML_SEEDS) if name == "aml" else day4_set())
    stories_path, cases_path = write_inputs(groups, out_dir / name, AML_STORIES if name == "aml" else GOLDEN)
    result = run_checks(stories_path, cases_path, lints=None, judge=judge)
    write_outputs(result, out_dir / name, f"seeded set '{name}'")
    rows = [score_case(e, result["findings"], judge) for e in case_exp]
    rows += [score_story(e, result["findings"], judge) for e in story_exp]
    for r in rows:
        r["set"] = name
    return rows, result


def report(rows: list[dict], costs: dict, judge: bool) -> str:
    """The markdown report: totals per set, then every seed with what was expected and found."""
    lines = ["# Seeded defects through the harness", "",
             f"Judge: {'on' if judge else 'off (free checks only)'}. "
             + " ".join(f"{k}: ${v['cost_usd']:.4f}, {v['seconds']} s." for k, v in costs.items()), "",
             "| Set | Defect seeds caught | Missed | Not run | Controls clean | False alarms |", "|---|---|---|---|---|---|"]
    for name in sorted({r["set"] for r in rows}):
        rs = [r for r in rows if r["set"] == name]
        seeds = [r for r in rs if r["kind"] == "defect"]
        controls = [r for r in rs if r["kind"] == "control"]
        lines.append(f"| {name} | {sum(r['result'] == 'caught' for r in seeds)}/{len(seeds)} | "
                     f"{sum(r['result'] == 'missed' for r in rs)} | {sum(r['result'] == 'not run' for r in rs)} | "
                     f"{sum(r['result'] == 'ok' for r in controls)}/{len(controls)} | "
                     f"{sum(r['result'] == 'false alarm' for r in rs)} |")
    lines += ["", "| Set | Seed | Case | Defect | Expected | Found | Result |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        extra = f" (missed: {r['missed']})" if r["missed"] else (f" (false alarm: {r['false_alarm']})" if r["false_alarm"] else "")
        lines.append(f"| {r['set']} | {r['seed_id']} | {r['story_id']} {r['case_id']} | {r['defect']} | "
                     f"{r['expected']} | {r['found']} | {r['result']}{extra} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Run the chosen seed sets, write report.md and seeds.csv, print the totals."""
    p = argparse.ArgumentParser(description="Score the harness on seeded defects.")
    p.add_argument("--set", choices=["harness", "day4", "aml", "both", "all"], default="both",
                   help="both = harness and day4 (insurance); all = harness, day4 and aml")
    p.add_argument("--no-judge", action="store_true", help="free checks only")
    args = p.parse_args(argv)
    judge = not args.no_judge
    out_dir = ROOT / "results" / "harness" / f"seeded_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    names = (["harness", "day4"] if args.set == "both" else ["harness", "day4", "aml"] if args.set == "all"
             else [args.set])
    rows, costs = [], {}
    for name in names:
        r, result = run_set(name, out_dir, judge)
        rows += r
        if result["judge"]:
            costs[name] = result["judge"]
    text = report(rows, costs, judge)
    (out_dir / "report.md").write_text(text, encoding="utf-8")
    with open(out_dir / "seeds.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["set", "seed_id", "story_id", "case_id", "kind", "defect", "expected", "found",
                                          "missed", "false_alarm", "result"])
        w.writeheader()
        w.writerows(rows)
    print("\n".join(text.splitlines()[:6 + len(names)]))
    print(f"saved {out_dir}")
    return 1 if any(r["result"] == "missed" for r in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
