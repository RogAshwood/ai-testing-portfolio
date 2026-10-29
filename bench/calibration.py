"""calibration.py: check the judge against Roger's labels (Day 4, as Day 3).

Two blind sheets are built from a generation run, before anyone looks at the
judge's verdicts:
  cases sheet   20 generated cases (2 per story, fixed random seed). Label each:
                verdict (correct / incorrect / not_in_basis), technique
                (positive / negative / boundary), concrete (y / n) and atomic (y / n).
  recall sheet  every expected idea for 3 stories. Label each: covered (y / n)
                and which case IDs cover it. Stories S03, S04 and S07 are used
                because S05, S08 and S09 were already discussed in the error
                analysis, which would bias the labels.
The sheet hides case IDs behind label IDs; the key file maps them back.
Use the error-analysis HTML sheet to read each story's full list of cases.

After scoring, `compare` reports agreement per check, with the confusion table,
and lists every disagreement so each one can be read, not just counted.
False passes (judge says correct or covered, Roger does not) are reported
separately because they are the costly error.

Usage (from the repo root):
    python -m bench.calibration build results/testgen/gen_v1_..._r1_....json
    python -m bench.calibration compare results/testgen/score_..._r1_....json

Change history:
  2026-10-24  v1  first version (Day 4).
  2026-10-28  v2  atomic check (my_atomic column; skipped where blank).
  2026-10-28  v3  agreement() returns the results as data (for notebook 03); --labels selects older labels.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections import Counter
from pathlib import Path

from bench.golden import ROOT, load_golden

CAL_DIR = ROOT / "results" / "testgen" / "calibration"
RECALL_STORIES = ("S03", "S04", "S07")
PER_STORY = 2
SEED = 42

ALIASES = {
    "verdict": {"c": "correct", "correct": "correct", "i": "incorrect", "incorrect": "incorrect",
                "n": "not_in_basis", "nib": "not_in_basis", "not_in_basis": "not_in_basis",
                "not in basis": "not_in_basis"},
    "technique": {"p": "positive", "positive": "positive", "n": "negative", "negative": "negative",
                  "b": "boundary", "boundary": "boundary"},
    "yn": {"y": True, "yes": True, "true": True, "1": True, "n": False, "no": False, "false": False, "0": False},
}


def _run_tag(gen_file: str) -> str:
    stem = Path(gen_file).stem.removeprefix("gen_")
    return stem.rsplit("_", 1)[0]          # drop the timestamp


def build(gen_path: Path) -> None:
    run = json.loads(gen_path.read_text(encoding="utf-8"))
    stories = {s["story_id"]: s for s in load_golden()["stories"]}
    rng = random.Random(SEED)
    tag = _run_tag(gen_path.name)
    CAL_DIR.mkdir(parents=True, exist_ok=True)

    sheet, key = [], []
    for rec in run["records"]:
        cases = (rec.get("parsed") or {}).get("test_cases") or []
        for c in rng.sample(cases, min(PER_STORY, len(cases))):
            label = f"L{len(sheet) + 1:02d}"
            s = stories[rec["story_id"]]
            sheet.append({
                "label_id": label, "story_id": s["story_id"], "story_title": s["title"],
                "acceptance_criteria": " | ".join(f"{a['ac_id']}: {a['text']}" for a in s["acceptance_criteria"]),
                "covers": ", ".join(c.get("covers", [])), "case_title": c.get("title", ""),
                "preconditions": " | ".join(c.get("preconditions", [])),
                "steps": " | ".join(c.get("steps", [])), "expected_result": c.get("expected_result", ""),
                "my_verdict": "", "my_technique": "", "my_concrete": "", "my_atomic": "", "notes": ""})
            key.append({"label_id": label, "story_id": s["story_id"], "case_id": c["case_id"]})

    recall = [{"story_id": sid, "idea_id": i["idea_id"], "technique": i["technique"], "idea": i["idea"],
               "my_covered": "", "my_case_ids": "", "notes": ""}
              for sid in RECALL_STORIES for i in stories[sid]["expected_ideas"]]

    paths = {"cases": CAL_DIR / f"cal_cases_{tag}.csv", "key": CAL_DIR / f"cal_key_{tag}.csv",
             "recall": CAL_DIR / f"cal_recall_{tag}.csv"}
    for name, rows in (("cases", sheet), ("key", key), ("recall", recall)):
        if paths[name].exists():
            raise SystemExit(f"{paths[name].name} already exists; not overwriting your labels")
    for name, rows in (("cases", sheet), ("key", key), ("recall", recall)):
        with paths[name].open("w", encoding="utf-8-sig", newline="") as f:   # utf-8-sig: Excel reads € correctly
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"wrote {paths[name].relative_to(ROOT)}  ({len(rows)} rows)")
    print("\nFill the my_* columns in the cases and recall sheets. Do not open the score file first.")


def _read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _norm(kind: str, value: str):
    return ALIASES[kind].get((value or "").strip().lower())


def _agreement(pairs: list[tuple]) -> dict:
    done = [(h, j) for h, j in pairs if h is not None and j is not None]
    agree = sum(h == j for h, j in done)
    return {"labelled": len(done), "agree": agree,
            "rate": round(agree / len(done), 2) if done else None,
            "confusion": Counter(f"human {h} / judge {j}" for h, j in done)}


def agreement(score_path: Path, label_suffix: str = "") -> dict:
    """Compare a score file's judge verdicts with the label sheets for its run.

    label_suffix selects an older set of labels, e.g. "_labels_round1".
    Returns {"checks": {name: {labelled, agree, rate, confusion}}, "false_passes": {...},
    "disagreements": [...], "judge": {...}} so the notebook can tabulate it."""
    score = json.loads(score_path.read_text(encoding="utf-8"))
    tag = _run_tag(score["gen_file"])
    sheet = _read(CAL_DIR / f"cal_cases_{tag}{label_suffix}.csv")
    key = {r["label_id"]: r for r in _read(CAL_DIR / f"cal_key_{tag}.csv")}
    recall = _read(CAL_DIR / f"cal_recall_{tag}{label_suffix}.csv")

    judged, ideas_judged = {}, {}
    for s in score["stories"]:
        j = s["judgement"] or {}
        for c in ((j.get("cases_call") or {}).get("parsed") or {}).get("cases", []):
            judged[(s["metrics"]["story_id"], c["case_id"])] = c
        for i in ((j.get("recall_call") or {}).get("parsed") or {}).get("ideas", []):
            ideas_judged[i["idea_id"]] = i

    checks = {"verdict": [], "technique": [], "concrete": [], "atomic": []}
    disagreements = []
    for row in sheet:
        k = key[row["label_id"]]
        jc = judged.get((k["story_id"], k["case_id"]), {})
        human = {"verdict": _norm("verdict", row["my_verdict"]),
                 "technique": _norm("technique", row["my_technique"]),
                 "concrete": _norm("yn", row["my_concrete"]),
                 "atomic": _norm("yn", row.get("my_atomic", ""))}
        for field in checks:
            checks[field].append((human[field], jc.get(field)))
            if human[field] is not None and jc.get(field) is not None and human[field] != jc.get(field):
                disagreements.append({"item": f"{row['label_id']} {k['story_id']}-{k['case_id']}", "check": field,
                                      "you": human[field], "judge": jc.get(field), "judge_reason": jc.get("reason", "")})

    recall_pairs = []
    for row in recall:
        ji = ideas_judged.get(row["idea_id"], {})
        h = _norm("yn", row["my_covered"])
        recall_pairs.append((h, ji.get("covered")))
        if h is not None and ji.get("covered") is not None and h != ji.get("covered"):
            disagreements.append({"item": row["idea_id"], "check": "idea covered", "you": h, "judge": ji.get("covered"),
                                  "judge_reason": f"(cases {ji.get('case_ids')}) {ji.get('reason', '')}"})

    return {
        "judge": {"model": score["judge_model"], "cases_fp": score["judge_cases_fp"],
                  "recall_fp": score["judge_recall_fp"], "gen_file": score["gen_file"]},
        "checks": {name: _agreement(pairs) for name, pairs in (*checks.items(), ("idea covered", recall_pairs))},
        "false_passes": {
            "verdict": sum(1 for h, j in checks["verdict"] if j == "correct" and h in ("incorrect", "not_in_basis")),
            "idea covered": sum(1 for h, j in recall_pairs if j is True and h is False)},
        "disagreements": disagreements}


def compare(score_path: Path, label_suffix: str = "") -> None:
    """Print the agreement report (see agreement())."""
    res = agreement(score_path, label_suffix)
    j = res["judge"]
    print(f"Calibration for {j['gen_file']}  (judge {j['model']}, "
          f"cases prompt {j['cases_fp']}, recall prompt {j['recall_fp']})\n")
    for name, a in res["checks"].items():
        print(f"{name:<13} agreement {a['agree']}/{a['labelled']}  ({a['rate']})")
        for cell, n in sorted(a["confusion"].items()):
            print(f"   {cell:<45} {n}")
    fp = res["false_passes"]
    print(f"\nfalse passes: verdict {fp['verdict']} (judge correct, you not); "
          f"idea covered {fp['idea covered']} (judge covered, you not)")
    print(f"\ndisagreements ({len(res['disagreements'])}):")
    for d in res["disagreements"]:
        print(f"  - {d['item']} {d['check']}: you {d['you']}, judge {d['judge']}. Judge: {d['judge_reason']}")


def main() -> None:
    p = argparse.ArgumentParser(description="Day 4 judge calibration")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build").add_argument("gen_file")
    c = sub.add_parser("compare")
    c.add_argument("score_file")
    c.add_argument("--labels", default="", help='label file suffix, e.g. "_labels_round1"')
    a = p.parse_args()
    if a.cmd == "build":
        build(Path(a.gen_file))
    else:
        compare(Path(a.score_file), a.labels)


if __name__ == "__main__":
    main()
