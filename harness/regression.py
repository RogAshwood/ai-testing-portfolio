"""regression.py: prove the harness's judge checks match the Day 4 benchmark.

Two checks, both run from the repo root:

1. Exact, free (no model call):
       python -m harness.regression
   For every Day 4 run that has a score file, the harness reads the SAME judge marks
   (reuse mode) and the counts it reports per story must equal bench/score.py's metrics:
   incorrect, not in basis, duplicates, ACs with a verified test, cases not atomic,
   cases not concrete. Any difference is a bug in how the harness reads the marks.

2. Live agreement (after one paid harness run; about $0.15-0.25):
       python -m harness.regression --live results/harness/<run>/judge.json
   Compares the marks the judge gave in the harness run with the Day 4 marks for the
   same cases, field by field. The model does not answer identically every time, so
   this reports agreement rates rather than expecting a perfect match; the same judge
   prompt and model should agree on the large majority.

Change history:
  2026-11-12  v1  first version (M7 step 3).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bench.golden import ROOT
from harness.check import run_checks

GOLDEN = ROOT / "datasets" / "testgen_golden.json"
TESTGEN = ROOT / "results" / "testgen"
RUNS = {                                    # Day 4 runs with a judge v2 score file: (generation, score)
    "v2 run 1": ("gen_v2_gpt-6-luna_g1.0_r1_20261028T124635Z.json",
                 "score_v2_gpt-6-luna_g1.0_r1_20261028T124635Z_jff34c1fc3ab1_20261028T142725Z.json"),
    "v2 bench-6": ("gen_v2_gpt-6-luna_g1.0_rbench-6_20261110T204630Z.json",
                   "score_v2_gpt-6-luna_g1.0_rbench-6_20261110T204630Z_jff34c1fc3ab1_20261110T205447Z.json"),
}
FIELDS = ("verdict", "technique", "concrete", "atomic", "duplicate", "claims")


def bench_counts(score_file: Path) -> dict[str, dict]:
    """Per story, the counts bench/score.py recorded, in the units the harness reports."""
    data = json.loads(score_file.read_text(encoding="utf-8"))
    out = {}
    for st in data["stories"]:
        m = st["metrics"]
        n = m["n_cases"]
        out[m["story_id"]] = {
            "incorrect": m["incorrect"], "not_in_basis": m["not_in_basis"], "duplicates": m["dup_cases"],
            "verified_ac_cov": m["verified_ac_cov"],
            "not_atomic": round(n * (1 - m["atomic_rate"])) if m.get("atomic_rate") is not None else None,
            "not_concrete": round(n * (1 - m["concrete_rate"])) if m.get("concrete_rate") is not None else None}
    return out


def harness_counts(result: dict) -> dict[str, dict]:
    """Per story, the same counts read from the harness's findings."""
    out = {}
    for sid, story in result["stories"].items():
        fs = [f for f in result["findings"] if f.story_id == sid]
        n_acs = len(story["acceptance_criteria"])
        out[sid] = {
            "incorrect": sum(f.check == "verdict" and "contradicts" in f.message for f in fs),
            "not_in_basis": sum(f.check == "verdict" and "not in basis" in f.message for f in fs),
            "duplicates": sum(f.check == "duplicate" for f in fs),
            "verified_ac_cov": round((n_acs - sum(f.check == "ac_unverified" for f in fs)) / n_acs, 3),
            "not_atomic": sum(f.check == "atomic" for f in fs),
            "not_concrete": sum(f.check == "concrete" for f in fs)}
    return out


def exact_regression() -> bool:
    """Check 1: reuse the Day 4 marks and compare every count with bench/score.py. True if all match."""
    all_ok = True
    for run, (gen, score) in RUNS.items():
        result = run_checks(GOLDEN, TESTGEN / gen, lints=[], judge=True, reuse=TESTGEN / score, titles=False)
        want, got = bench_counts(TESTGEN / score), harness_counts(result)
        diffs = [(sid, k, want[sid][k], got[sid][k]) for sid in want for k in got[sid]
                 if want[sid].get(k) is not None and want[sid][k] != got[sid][k]]
        all_ok &= not diffs
        print(f"{run}: {len(want)} stories, {len(got[next(iter(got))])} counts each: "
              + ("all match bench/score.py" if not diffs else f"{len(diffs)} DIFFERENCES"))
        for sid, k, w, g in diffs:
            print(f"   {sid} {k}: bench {w}, harness {g}")
    return all_ok


def _marks(cases_call: dict) -> dict[str, dict]:
    """{case_id: mark} from one judge call record."""
    return {m["case_id"]: m for m in ((cases_call or {}).get("parsed") or {}).get("cases", [])}


def _field(mark: dict, field: str):
    """One comparable value from a mark: duplicate as yes/no, claims as the set of unsupported ACs."""
    if field == "duplicate":
        return bool(mark.get("duplicate_of"))
    if field == "claims":
        return sorted(c["ac_id"] for c in mark.get("claims", []) if not c.get("supported"))
    return mark.get(field)


def live_agreement(judge_json: Path, score_file: Path) -> dict[str, tuple[int, int]]:
    """Check 2: {field: (agree, compared)} between a harness live run and the Day 4 marks."""
    live = json.loads(Path(judge_json).read_text(encoding="utf-8"))["stories"]
    day4 = json.loads(Path(score_file).read_text(encoding="utf-8"))["stories"]
    old = {st["metrics"]["story_id"]: _marks(st["judgement"]["cases_call"]) for st in day4}
    tally = {f: [0, 0] for f in FIELDS}
    for sid, rec in live.items():
        new = _marks(rec["cases_call"])
        for cid, m in new.items():
            if cid in old.get(sid, {}):
                for f in FIELDS:
                    tally[f][1] += 1
                    tally[f][0] += _field(m, f) == _field(old[sid][cid], f)
    return {f: (a, n) for f, (a, n) in tally.items()}


def main(argv: list[str] | None = None) -> int:
    """Run check 1, or check 2 when --live is given. Exit 1 if check 1 finds a difference."""
    p = argparse.ArgumentParser(description="Regression of the harness judge checks against Day 4.")
    p.add_argument("--live", type=Path, help="judge.json from a live harness run on v2 run 1")
    p.add_argument("--day4", default="v2 run 1", choices=list(RUNS), help="Day 4 run to compare with")
    args = p.parse_args(argv)
    if args.live:
        res = live_agreement(args.live, TESTGEN / RUNS[args.day4][1])
        print(f"Live harness judge vs Day 4 judge marks ({args.day4}), same prompt and model:")
        for f, (a, n) in res.items():
            print(f"  {f:<10} {a}/{n} agree ({a / n:.0%})" if n else f"  {f:<10} no cases compared")
        return 0
    return 0 if exact_regression() else 1


if __name__ == "__main__":
    raise SystemExit(main())
