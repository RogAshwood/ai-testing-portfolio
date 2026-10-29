"""score.py: score a saved generation run and append the result to the history file.

    results/testgen/gen_*.json --> free checks + judge (bench/judge.py) --> metrics per story
                               --> results/testgen/score_*.json + results/testgen_history.csv

Metrics per story (one row per story per run in the history file)
  Free, deterministic
    schema_valid        reply parsed and met the output contract (from generate.py)
    n_cases             number of generated cases
    claimed_ac_cov      share of the story's ACs listed in at least one case's covers
    tfidf_dup_cases     cases whose wording nearly repeats an earlier case (TF-IDF cosine >=
                        DUP_THRESHOLD). Indicator only: run 1 showed TF-IDF scores distinct
                        boundary pairs at 0.90+ because they share a template.
  From the judge
    correct_rate        share of cases judged correct
    incorrect, not_in_basis   counts
    dup_cases           cases the judge marks as a duplicate of an earlier case
    precision           share of cases that are correct and not duplicates
    verified_ac_cov     share of ACs with at least one supported claim on a correct case
    over_claim_rate     share of claimed ACs the judge did not find supported
    recall              share of expected ideas covered by at least one correct case
    recall_positive / _negative / _boundary   the same, by the idea's technique tag
    neg_bnd_pass        at least one correct negative and one correct boundary case
                        (judge's technique labels; boundary waived if boundary_exempt_reason)
    concrete_rate       share of cases with concrete test data (D4)
    atomic_rate         share of cases that test one condition with one outcome (F5; judge v2)
  Cost and time
    gen and judge tokens, cost in USD (bench/pricing.py; USD kept by decision,
    2026-10-27), generation latency and judge latency (both calls) in seconds

Design notes
- Recall counts an idea only if a case the judge marked correct covers it, so a
  case with a wrong expected result never earns recall.
- Run-level summaries give the mean of the per-story figures (each story counts
  equally) and, for recall, the pooled figure over all 78 ideas as well.
- Judge prompts and model are fingerprinted like everything else. A run already
  scored with the same judge fingerprints is not appended to the history again
  unless --rescore is given; the scores file is always new (timestamped).
- Runs without an API key with --no-judge: free metrics only.

Usage (from the repo root, in the ai-testing env):
    python -m bench.score results/testgen/gen_v1_..._r1_....json               # judge + history
    python -m bench.score results/testgen/gen_v1_..._r1_....json --stories S05 --no-history
    python -m bench.score results/testgen/gen_v1_..._r1_....json --no-judge     # free only
    python -m bench.score --seeded                                              # judge self-test
    python -m bench.score --repair-history                                      # fix old history header

Change history:
  2026-10-24  v1  first version (Day 4).
  2026-10-27  v2  judge_latency_s column; latency totals in the summary.
  2026-10-28  v3  atomic_rate (judge v2). History rows from judge v1 keep atomic_rate empty.
  2026-10-28  v4  fix: appending after a column was added left a header with fewer columns than
                  the new rows. Appends now rewrite the file first if its header is out of date;
                  --repair-history fixes an existing file (original kept as *_before_repair.csv).
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from bench.golden import ROOT, load_golden, load_named_prompt
from bench.judge import CASES_PROMPT, JUDGE_MODEL, RECALL_PROMPT, judge_story
from bench.pricing import PROVISIONAL, cost_usd

RESULTS_DIR = ROOT / "results" / "testgen"
HISTORY = ROOT / "results" / "testgen_history.csv"
SEEDED = ROOT / "datasets" / "testgen_seeded_defects.json"
DUP_THRESHOLD = 0.85        # to be calibrated on a few labelled pairs (see duplicate_pairs)

HISTORY_COLUMNS = [
    "scored_utc", "gen_file", "gen_started_utc", "model", "prompt_version", "prompt_fp",
    "golden_version", "golden_fp", "story_id", "card_fp", "ideas_fp",
    "judge_model", "judge_cases_fp", "judge_recall_fp",
    "schema_valid", "n_cases", "claimed_ac_cov", "verified_ac_cov", "over_claim_rate",
    "correct_rate", "incorrect", "not_in_basis", "dup_cases", "tfidf_dup_cases", "precision",
    "recall", "recall_positive", "recall_negative", "recall_boundary",
    "neg_bnd_pass", "concrete_rate", "atomic_rate",
    "gen_input_tokens", "gen_output_tokens", "gen_cost_usd",
    "judge_input_tokens", "judge_output_tokens", "judge_cost_usd", "gen_latency_s", "judge_latency_s",
]


def _share(n: int, d: int) -> float | None:
    return round(n / d, 3) if d else None


def case_text(c: dict) -> str:
    return " ".join([c.get("title", ""), *c.get("preconditions", []), *c.get("steps", []),
                     c.get("expected_result", "")])


def duplicate_pairs(cases: list[dict], threshold: float = DUP_THRESHOLD) -> list[tuple[str, str, float]]:
    """(earlier case, later case, cosine) for every pair at or above threshold. Free."""
    if len(cases) < 2:
        return []
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    m = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True).fit_transform([case_text(c) for c in cases])
    sims = cosine_similarity(m)
    return [(cases[i]["case_id"], cases[j]["case_id"], round(float(sims[i, j]), 3))
            for i in range(len(cases)) for j in range(i + 1, len(cases)) if sims[i, j] >= threshold]


def free_metrics(story: dict, record: dict) -> dict:
    cases = (record.get("parsed") or {}).get("test_cases") or []
    ac_ids = [a["ac_id"] for a in story["acceptance_criteria"]]
    claimed = {a for c in cases for a in c.get("covers", [])}
    pairs = duplicate_pairs(cases)
    return {"schema_valid": record["schema_valid"], "n_cases": len(cases),
            "claimed_ac_cov": _share(len(claimed & set(ac_ids)), len(ac_ids)),
            "tfidf_dup_cases": len({later for _, later, _ in pairs}), "tfidf_pairs": pairs}


def judged_metrics(story: dict, cases: list[dict], judged: dict, free: dict) -> dict:
    a = {c["case_id"]: c for c in (judged["cases_call"]["parsed"] or {}).get("cases", [])}
    b = (judged["recall_call"]["parsed"] or {}).get("ideas", [])
    ids = [c["case_id"] for c in cases]
    correct = {i for i in ids if a.get(i, {}).get("verdict") == "correct"}
    dups = {i for i in ids if a.get(i, {}).get("duplicate_of") in ids[:ids.index(i)]}
    ac_ids = [x["ac_id"] for x in story["acceptance_criteria"]]

    claims = [(i, cl["ac_id"], cl["supported"]) for i in ids for cl in a.get(i, {}).get("claims", [])]
    verified = {ac for i, ac, ok in claims if ok and i in correct}

    covered = {}
    for item in b:
        covered[item["idea_id"]] = bool(item.get("covered")) and any(c in correct for c in item.get("case_ids", []))
    by_tech = {}
    for idea in story["expected_ideas"]:
        by_tech.setdefault(idea["technique"], []).append(covered.get(idea["idea_id"], False))

    tech_correct = {a[i]["technique"] for i in correct}
    needs_bnd = not story.get("boundary_exempt_reason")
    return {
        "correct_rate": _share(len(correct), len(ids)),
        "incorrect": sum(a.get(i, {}).get("verdict") == "incorrect" for i in ids),
        "not_in_basis": sum(a.get(i, {}).get("verdict") == "not_in_basis" for i in ids),
        "dup_cases": len(dups),
        "precision": _share(len(correct - dups), len(ids)),
        "verified_ac_cov": _share(len(verified & set(ac_ids)), len(ac_ids)),
        "over_claim_rate": _share(sum(not ok for _, _, ok in claims), len(claims)),
        "recall": _share(sum(covered.get(i["idea_id"], False) for i in story["expected_ideas"]),
                         len(story["expected_ideas"])),
        **{f"recall_{t}": _share(sum(v), len(v)) for t, v in
           ((t, by_tech.get(t, [])) for t in ("positive", "negative", "boundary"))},
        "neg_bnd_pass": "negative" in tech_correct and ("boundary" in tech_correct or not needs_bnd),
        "concrete_rate": _share(sum(bool(a.get(i, {}).get("concrete")) for i in ids), len(ids)),
        "atomic_rate": _share(sum(bool(a.get(i, {}).get("atomic")) for i in ids), len(ids))
                       if any("atomic" in a.get(i, {}) for i in ids) else None,
        "covered_ideas": sorted(k for k, v in covered.items() if v),
    }


def _tokens(call: dict) -> tuple[int, int]:
    u = call["usage"]
    return u["input_tokens"] or 0, u["output_tokens"] or 0


def score_run(gen_path: Path, story_ids: list[str] | None = None, use_judge: bool = True,
              client=None, judge_model: str = JUDGE_MODEL) -> dict:
    run = json.loads(gen_path.read_text(encoding="utf-8"))
    meta = run["meta"]
    golden = load_golden()
    if meta["golden_fingerprint"] != golden["_fingerprint"]:
        print(f"WARNING: run used golden {meta['golden_fingerprint']}, current file is "
              f"{golden['_fingerprint']}. Stories whose fingerprints differ are skipped.")
    stories = {s["story_id"]: s for s in golden["stories"]}
    if use_judge and client is None:
        from bench.generate import make_client
        client = make_client()

    from bench.golden import story_fingerprints
    out_stories = []
    for rec in run["records"]:
        sid = rec["story_id"]
        if story_ids and sid not in story_ids:
            continue
        story = stories[sid]
        now_fp = story_fingerprints(story)
        if rec["story_fingerprints"] != now_fp:
            print(f"{sid}: skipped, story changed since generation "
                  f"(card {rec['story_fingerprints']['card']} -> {now_fp['card']}, "
                  f"ideas {rec['story_fingerprints']['ideas']} -> {now_fp['ideas']})")
            continue
        cases = (rec.get("parsed") or {}).get("test_cases") or []
        row = {"story_id": sid, **free_metrics(story, rec)}
        judged = None
        if use_judge and cases:
            judged = judge_story(story, cases, client, judge_model)
            row.update(judged_metrics(story, cases, judged, row))
            ti = sum(_tokens(judged[k])[0] for k in ("cases_call", "recall_call"))
            to = sum(_tokens(judged[k])[1] for k in ("cases_call", "recall_call"))
            row.update(judge_input_tokens=ti, judge_output_tokens=to,
                       judge_cost_usd=cost_usd(judge_model, ti, to),
                       judge_latency_s=round(sum(judged[k]["usage"]["latency_s"]
                                                 for k in ("cases_call", "recall_call")), 2),
                       judge_issues=judged["cases_call"]["issues"] + judged["recall_call"]["issues"])
        u = rec["usage"]
        row.update(gen_input_tokens=u["input_tokens"], gen_output_tokens=u["output_tokens"],
                   gen_cost_usd=cost_usd(meta["model"], u["input_tokens"], u["output_tokens"]),
                   gen_latency_s=u["latency_s"], card_fp=now_fp["card"], ideas_fp=now_fp["ideas"])
        out_stories.append({"metrics": row, "judgement": judged})
        _print_row(row, use_judge)

    cases_fp = load_named_prompt(CASES_PROMPT)[1]
    recall_fp = load_named_prompt(RECALL_PROMPT)[1]
    result = {"scored_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "gen_file": gen_path.name, "gen_meta": meta, "judged": use_judge,
              "judge_model": judge_model if use_judge else None,
              "judge_cases_fp": cases_fp if use_judge else None,
              "judge_recall_fp": recall_fp if use_judge else None,
              "stories": out_stories, "summary": summarise([s["metrics"] for s in out_stories])}
    _print_summary(result, use_judge)
    return result


def summarise(rows: list[dict]) -> dict:
    keys = ["n_cases", "claimed_ac_cov", "verified_ac_cov", "over_claim_rate", "correct_rate",
            "precision", "recall", "recall_positive", "recall_negative", "recall_boundary",
            "concrete_rate", "atomic_rate"]
    s = {}
    for k in keys:
        vals = [r[k] for r in rows if r.get(k) is not None]
        s[f"mean_{k}"] = round(sum(vals) / len(vals), 3) if vals else None
    for k in ("n_cases", "incorrect", "not_in_basis", "dup_cases", "tfidf_dup_cases", "gen_input_tokens",
              "gen_output_tokens", "judge_input_tokens", "judge_output_tokens"):
        s[f"total_{k}"] = sum(r.get(k) or 0 for r in rows)
    for k in ("gen_latency_s", "judge_latency_s"):
        vals = [r.get(k) for r in rows if r.get(k) is not None]
        s[f"total_{k}"] = round(sum(vals), 1) if vals else None
    for k in ("gen_cost_usd", "judge_cost_usd"):
        vals = [r.get(k) for r in rows]
        s[f"total_{k}"] = round(sum(vals), 4) if vals and None not in vals else None
    s["neg_bnd_pass"] = sum(bool(r.get("neg_bnd_pass")) for r in rows)
    s["schema_valid"] = sum(bool(r["schema_valid"]) for r in rows)
    s["stories"] = len(rows)
    covered = sum(len(r.get("covered_ideas", [])) for r in rows)
    s["pooled_recall_ideas_covered"] = covered
    return s


def _fmt(v):
    return "  -  " if v is None else (f"{v:.2f}" if isinstance(v, float) else str(v))


def _print_row(r: dict, judged: bool) -> None:
    line = f"{r['story_id']}  cases {r['n_cases']:>3}  tfidf-dup {r['tfidf_dup_cases']}  claimed {_fmt(r['claimed_ac_cov'])}"
    if judged and "recall" in r:
        line += (f"  dup {r['dup_cases']}  verified {_fmt(r['verified_ac_cov'])}  correct {_fmt(r['correct_rate'])}"
                 f"  precision {_fmt(r['precision'])}  recall {_fmt(r['recall'])}"
                 f"  concrete {_fmt(r['concrete_rate'])}  atomic {_fmt(r.get('atomic_rate'))}"
                 f"  neg+bnd {'yes' if r['neg_bnd_pass'] else 'no '}")
        if r.get("judge_issues"):
            line += f"  JUDGE ISSUES {len(r['judge_issues'])}"
    print(line)


def _print_summary(res: dict, judged: bool) -> None:
    s = res["summary"]
    print(f"\n{s['stories']} stories, {s['total_n_cases']} cases, TF-IDF near-duplicates {s['total_tfidf_dup_cases']}")
    if judged:
        prov = " (provisional price)" if res["judge_model"] in PROVISIONAL else ""
        print(f"mean recall {_fmt(s['mean_recall'])} (boundary {_fmt(s['mean_recall_boundary'])}, "
              f"negative {_fmt(s['mean_recall_negative'])}), mean precision {_fmt(s['mean_precision'])}, "
              f"mean concrete {_fmt(s['mean_concrete_rate'])}, mean atomic {_fmt(s['mean_atomic_rate'])}")
        print(f"claimed AC coverage {_fmt(s['mean_claimed_ac_cov'])} vs verified {_fmt(s['mean_verified_ac_cov'])}, "
              f"neg+bnd pass {s['neg_bnd_pass']}/{s['stories']}, duplicates {s['total_dup_cases']}, incorrect {s['total_incorrect']}, "
              f"not in basis {s['total_not_in_basis']}")
        print(f"cost: generation ${_fmt(s['total_gen_cost_usd'])}, judge ${_fmt(s['total_judge_cost_usd'])}{prov}; "
              f"time: generation {_fmt(s['total_gen_latency_s'])} s, judge {_fmt(s['total_judge_latency_s'])} s")


def save(result: dict, write_history: bool, rescore: bool) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = result["scored_utc"].replace("-", "").replace(":", "").replace("+0000", "Z")
    tag = f"j{result['judge_cases_fp']}" if result["judged"] else "free"
    out = RESULTS_DIR / f"score_{Path(result['gen_file']).stem.removeprefix('gen_')}_{tag}_{stamp}.json"
    base, n = out.stem, 2
    while out.exists():                          # never overwrite: add a suffix
        out = out.with_name(f"{base}_{n}.json")
        n += 1
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"saved {out.relative_to(ROOT)}")
    if write_history and result["judged"]:
        _append_history(result, rescore)
    return out


def read_history(path: Path = HISTORY) -> tuple[list[str], list[dict]]:
    """Read the history file as (header, rows). Copes with a file whose later rows
    carry more columns than its header (written before v4): a row is mapped by its
    own length to the old header or to the current HISTORY_COLUMNS."""
    if not path.exists():
        return [], []
    with path.open(encoding="utf-8", newline="") as f:
        raw = list(csv.reader(f))
    header, rows = raw[0], []
    for r in raw[1:]:
        if len(r) == len(header):
            rows.append(dict(zip(header, r)))
        elif len(r) == len(HISTORY_COLUMNS):
            rows.append(dict(zip(HISTORY_COLUMNS, r)))
        else:
            raise SystemExit(f"{path.name}: a row has {len(r)} fields; expected {len(header)} or "
                             f"{len(HISTORY_COLUMNS)}. Not changed.")
    return header, rows


def repair_history(path: Path = HISTORY) -> None:
    """Rewrite the history file with the current columns, keeping every row.
    Columns a row did not have (e.g. atomic_rate for judge v1 rows) stay empty."""
    header, rows = read_history(path)
    if header == HISTORY_COLUMNS and all(len(r) == len(HISTORY_COLUMNS) for r in rows):
        print(f"{path.name}: already consistent, {len(rows)} rows")
        return
    backup = path.with_name(path.stem + "_before_repair.csv")
    backup.write_bytes(path.read_bytes())
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HISTORY_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"{path.name}: rewritten with {len(HISTORY_COLUMNS)} columns, {len(rows)} rows "
          f"(original kept as {backup.name})")


def _append_history(res: dict, rescore: bool) -> None:
    header, existing = read_history()
    if header and header != HISTORY_COLUMNS:          # columns added since the file was started
        repair_history()
    key = (res["gen_file"], res["judge_cases_fp"], res["judge_recall_fp"])
    if not rescore and any((r["gen_file"], r["judge_cases_fp"], r["judge_recall_fp"]) == key for r in existing):
        print("history: this run is already scored with these judge prompts; not appended (use --rescore)")
        return
    m = res["gen_meta"]
    new = not HISTORY.exists()
    with HISTORY.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HISTORY_COLUMNS, extrasaction="ignore")
        if new:
            w.writeheader()
        for s in res["stories"]:
            w.writerow({**s["metrics"], "scored_utc": res["scored_utc"], "gen_file": res["gen_file"],
                        "gen_started_utc": m["started_utc"], "model": m["model"],
                        "prompt_version": m["prompt_version"], "prompt_fp": m["prompt_fingerprint"],
                        "golden_version": m["golden_version"], "golden_fp": m["golden_fingerprint"],
                        "judge_model": res["judge_model"], "judge_cases_fp": res["judge_cases_fp"],
                        "judge_recall_fp": res["judge_recall_fp"]})
    print(f"history: {len(res['stories'])} rows appended to {HISTORY.relative_to(ROOT)}")


# ---------------------------------------------------------------------------
# Seeded defects: does the judge catch what it should?
# ---------------------------------------------------------------------------

def run_seeded(client=None, judge_model: str = JUDGE_MODEL) -> dict:
    """Judge the hand-made cases in datasets/testgen_seeded_defects.json and compare
    each verdict with the expected one."""
    seeds = json.loads(SEEDED.read_text(encoding="utf-8"))
    stories = {s["story_id"]: s for s in load_golden()["stories"]}
    client = client or __import__("bench.generate", fromlist=["make_client"]).make_client()
    results = []

    for group in seeds["case_seeds"]:
        story = stories[group["story_id"]]
        cases = [s["case"] for s in group["seeds"]]
        from bench.judge import CASES_SCHEMA, call_judge, cases_input
        call = call_judge(CASES_PROMPT, cases_input(story, cases), CASES_SCHEMA, client, judge_model)
        got = {c["case_id"]: c for c in (call["parsed"] or {}).get("cases", [])}
        for s in group["seeds"]:
            g = got.get(s["case"]["case_id"], {})
            for field, want in s["expect"].items():
                if field == "unsupported":
                    have = sorted(cl["ac_id"] for cl in g.get("claims", []) if not cl["supported"])
                else:
                    have = g.get(field)
                results.append({"seed": s["seed_id"], "check": field, "expected": want, "judge": have,
                                "pass": have == want, "defect": s["defect"], "reason": g.get("reason", "")})

    for group in seeds["recall_seeds"]:
        story = stories[group["story_id"]]
        from bench.judge import RECALL_SCHEMA, call_judge, recall_input
        call = call_judge(RECALL_PROMPT, recall_input(story, group["cases"]), RECALL_SCHEMA, client, judge_model)
        got = {i["idea_id"]: i for i in (call["parsed"] or {}).get("ideas", [])}
        for exp in group["expect"]:
            have = got.get(exp["idea_id"], {}).get("covered")
            results.append({"seed": exp["seed_id"], "check": "covered", "expected": exp["covered"],
                            "judge": have, "pass": have == exp["covered"], "defect": exp["defect"],
                            "reason": got.get(exp["idea_id"], {}).get("reason", "")})

    passed = sum(r["pass"] for r in results)
    print(f"{'seed':<6} {'check':<12} {'expected':<14} {'got':<14} result")
    for r in results:
        show = lambda v: '""' if v == "" else str(v)
        print(f"{r['seed']:<6} {r['check']:<12} {show(r['expected']):<14} {show(r['judge']):<14} "
              f"{'pass' if r['pass'] else 'FAIL  ' + r['reason']}")
    print(f"\nseeded checks passed {passed}/{len(results)}")
    out = RESULTS_DIR / f"seeded_j{load_named_prompt(CASES_PROMPT)[1]}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"judge_model": judge_model, "results": results}, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    print(f"saved {out.relative_to(ROOT)}")
    return {"passed": passed, "total": len(results), "results": results}


def main() -> None:
    p = argparse.ArgumentParser(description="Score a Day 4 generation run")
    p.add_argument("gen_file", nargs="?", help="results/testgen/gen_*.json")
    p.add_argument("--stories", help="comma-separated story IDs (default: all)")
    p.add_argument("--no-judge", action="store_true", help="free metrics only, no API call")
    p.add_argument("--no-history", action="store_true", help="do not append to the history file")
    p.add_argument("--rescore", action="store_true", help="append even if already scored")
    p.add_argument("--seeded", action="store_true", help="run the judge on the seeded defects")
    p.add_argument("--repair-history", action="store_true", help="rewrite the history file with the current columns")
    a = p.parse_args()
    if a.repair_history:
        repair_history()
        return
    if a.seeded:
        run_seeded()
        return
    if not a.gen_file:
        p.error("give a gen_*.json file, or --seeded")
    res = score_run(Path(a.gen_file), a.stories.split(",") if a.stories else None, not a.no_judge)
    save(res, write_history=not (a.no_history or a.stories), rescore=a.rescore)


if __name__ == "__main__":
    main()
