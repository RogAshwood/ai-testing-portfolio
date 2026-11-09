"""
chatbot/compare.py: compare groups of runs, for example the baseline against a prompt experiment.

Why this exists
---------------
The same scripted conversations give different results from run to run (the
baseline ranged from 70 to 76 of 96 turns passing). So a change to the bot is
judged on groups of runs, reported as mean [min-max], never on one run.

What it reads
-------------
For each run folder: checks.json (the deterministic checks) and judge.json (the
judge). Nothing is re-run and no API is called. A turn passes "both layers" only
if it passed the checks and every judge check, as in judge.py.

One logical run can be spread over several folders, joined with "+": the
baseline's C22 and C23 were run separately from the other 26 conversations,
so run A is  results/chatbot/20261109T155138Z+results/chatbot/20261109T171528Z

Safety checks
-------------
  - every run must be judged with the same rubric (the frozen judge), otherwise
    the comparison would mix two judges; it stops and says which run differs
  - every run in a group must cover the same conversations; a difference between
    the groups is reported, because the totals would not be comparable
  - the prompt each run used (baseline, or which experiments) is read from the
    trace records and printed; one logical run must use one prompt throughout

Usage (from the repo root)
--------------------------
  python -m chatbot.compare --baseline A1+A2 B1+B2 C1+C2 --experiment X Y
  python -m chatbot.compare --baseline A1+A2 B1+B2 C1+C2          (baseline only)
Writes results/chatbot_compare/<label>.json when --label is given.

No API calls.

Change history:
  2026-11-09  v1  first version (M5 step 4g, for the step 5 prompt experiments).
  2026-11-09  v1.1  shows which prompt experiments each run used (from the trace records)
                    and stops if one logical run mixes prompts.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "results" / "chatbot_compare"


def load_run(spec: str) -> dict:
    """One logical run from one or more folders joined with '+'.

    Returns turn-level results keyed by (conv_id, turn): deterministic pass,
    judge verdicts, plus the run totals needed for the table."""
    det, verdicts, rubric_fps, prompts = {}, {}, set(), set()
    cost, ret_hits, ret_turns, conv_det = 0.0, 0.0, 0, {}
    for folder in spec.split("+"):
        d = Path(folder)
        ck = json.loads((d / "checks.json").read_text(encoding="utf-8"))
        jd = json.loads((d / "judge.json").read_text(encoding="utf-8"))
        rubric_fps.add(jd["meta"]["rubric_fp"])
        s = ck["summary"]
        cost += (s.get("cost_usd") or 0) + (jd["summary"].get("cost_usd") or 0)
        if s.get("retrieval_turns"):
            ret_hits += s["retrieval_hit_rate"] * s["retrieval_turns"]
            ret_turns += s["retrieval_turns"]
        for c in ck["conversations"]:
            for t in c["turns"]:
                det[(c["conv_id"], t["turn"])] = t["passed"]
            rec_path = d / f"{c['conv_id']}.json"
            if rec_path.exists():                    # records before v1.3 of bot.py have no field: baseline
                rec = json.loads(rec_path.read_text(encoding="utf-8"))
                prompts.add(tuple(rec.get("experiments", [])))
        for t in jd["turns"]:
            verdicts[(t["conv_id"], t["turn"])] = {k: v["verdict"] for k, v in t["verdicts"].items()}
    if len(rubric_fps) != 1:
        raise SystemExit(f"{spec}: folders judged with different rubrics {sorted(rubric_fps)}")
    if len(prompts) > 1:
        raise SystemExit(f"{spec}: conversations were run with different prompts {sorted(prompts)}")
    prompt = (prompts.pop() if prompts else ())
    return {"name": spec, "prompt": "baseline" if not prompt else "baseline + " + ", ".join(prompt), "det": det, "verdicts": verdicts, "rubric_fp": rubric_fps.pop(), "cost": cost,
            "retrieval": (ret_hits / ret_turns) if ret_turns else None}


def measures(run: dict) -> dict:
    """The numbers reported for one run."""
    keys = sorted(run["det"])
    judge_ok = {k: all(v == "pass" for v in run["verdicts"].get(k, {"missing": "fail"}).values()) for k in keys}
    both = {k: run["det"][k] and judge_ok[k] for k in keys}
    convs = sorted({k[0] for k in keys})
    fails = {}
    for k in keys:
        for check, v in run["verdicts"].get(k, {}).items():
            if v != "pass":
                fails[check] = fails.get(check, 0) + 1
    return {"turns": len(keys), "conversations": len(convs), "prompt": run["prompt"],
            "turns_text": sum(run["det"][k] for k in keys),
            "turns_judge": sum(judge_ok.values()),
            "turns_both": sum(both.values()),
            "convs_text": sum(all(run["det"][k] for k in keys if k[0] == c) for c in convs),
            "convs_both": sum(all(both[k] for k in keys if k[0] == c) for c in convs),
            "judge_fails": fails, "retrieval": run["retrieval"], "cost": run["cost"],
            "conv_ids": convs}


def summarise(group: list[dict]) -> dict:
    """mean, min and max of each measure over a group of runs."""
    out = {}
    for m in ("turns_text", "turns_judge", "turns_both", "convs_text", "convs_both", "retrieval", "cost"):
        vals = [g[m] for g in group if g[m] is not None]
        out[m] = {"mean": round(statistics.mean(vals), 3), "min": min(vals), "max": max(vals)} if vals else None
    checks = sorted({c for g in group for c in g["judge_fails"]})
    out["judge_fails"] = {c: {"mean": round(statistics.mean(g["judge_fails"].get(c, 0) for g in group), 2),
                              "min": min(g["judge_fails"].get(c, 0) for g in group),
                              "max": max(g["judge_fails"].get(c, 0) for g in group)} for c in checks}
    return out


def fmt(s: dict | None, digits: int = 1) -> str:
    if s is None:
        return "-"
    return f"{s['mean']:.{digits}f} [{s['min']:.{digits}f}-{s['max']:.{digits}f}]" if digits else \
        f"{s['mean']:.1f} [{s['min']}-{s['max']}]"


def report(groups: dict[str, list[dict]]) -> dict:
    """Print the comparison table and return it as data."""
    names = list(groups)
    sums = {n: summarise(g) for n, g in groups.items()}
    sizes = {n: (groups[n][0]["turns"], groups[n][0]["conversations"]) for n in names}
    print("Runs:")
    for n in names:
        prompts = sorted({g["prompt"] for g in groups[n]})
        print(f"  {n}: {len(groups[n])} run(s), {sizes[n][1]} conversations, {sizes[n][0]} turns; "
              f"prompt: {' / '.join(prompts)}")
        if len(prompts) > 1:
            print(f"  NOTE: the {n} runs used different prompts")
    if len({tuple(groups[n][0]["conv_ids"]) for n in names}) > 1:
        print("  NOTE: the groups cover different conversations, so totals are not directly comparable")
    rows = [("Turns passing the text checks", "turns_text", 0), ("Turns passing the judge", "turns_judge", 0),
            ("Turns passing both layers", "turns_both", 0), ("Conversations passing the text checks", "convs_text", 0),
            ("Conversations passing both layers", "convs_both", 0), ("Retrieval hit rate", "retrieval", 3),
            ("Cost per run (bot + judge), $", "cost", 2)]
    head = f"\n  {'measure':40}" + "".join(f"{n:>24}" for n in names)
    if len(names) == 2:
        head += f"{'change in mean':>16}"
    print(head)
    for label, m, d in rows:
        line = f"  {label:40}" + "".join(f"{fmt(sums[n][m], d):>24}" for n in names)
        if len(names) == 2 and sums[names[0]][m] and sums[names[1]][m]:
            line += f"{sums[names[1]][m]['mean'] - sums[names[0]][m]['mean']:>+16.{d or 1}f}"
        print(line)
    print("\n  judge fails per check (mean [min-max] per run)")
    checks = sorted({c for n in names for c in sums[n]["judge_fails"]})
    for c in checks:
        zero = {"mean": 0, "min": 0, "max": 0}
        vals = [sums[n]["judge_fails"].get(c, zero) for n in names]
        line = f"    {c:38}" + "".join(f"{fmt(v, 0):>24}" for v in vals)
        if len(names) == 2:
            line += f"{vals[1]['mean'] - vals[0]['mean']:>+16.1f}"
        print(line)
    return {"groups": {n: [{k: v for k, v in g.items() if k != "conv_ids"} | {"name": g.get("name")}
                           for g in groups[n]] for n in names}, "summary": sums}


def main(argv=None) -> int:
    """Entry point for `python -m chatbot.compare`."""
    ap = argparse.ArgumentParser(description="Compare groups of M5 runs (mean [min-max]).")
    ap.add_argument("--baseline", nargs="+", required=True, help="run folders; join split runs with +")
    ap.add_argument("--experiment", nargs="+", help="run folders of the experiment")
    ap.add_argument("--label", help="save the comparison as results/chatbot_compare/<label>.json")
    a = ap.parse_args(argv)
    runs = {"baseline": [load_run(s) for s in a.baseline]}
    if a.experiment:
        runs["experiment"] = [load_run(s) for s in a.experiment]
    fps = {r["rubric_fp"] for g in runs.values() for r in g}
    if len(fps) != 1:
        bad = [(r["name"], r["rubric_fp"]) for g in runs.values() for r in g]
        raise SystemExit(f"runs were judged with different rubrics, so they can't be compared: {bad}")
    print(f"Judge rubric {fps.pop()} (same for every run)")
    groups = {n: [measures(r) | {"name": r["name"]} for r in g] for n, g in runs.items()}
    res = report(groups)
    if a.label:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUT_DIR / f"{a.label}.json").write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
        print(f"\nWrote {OUT_DIR / (a.label + '.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
