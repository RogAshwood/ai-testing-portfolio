"""check.py: the harness command. Checks a cases file against a stories file.

Usage (from the repo root, in the ai-testing env; one line each):
    python -m harness.check --stories datasets/testgen_golden.json --cases results/testgen/gen_v2_gpt-6-luna_g1.0_r1_20261028T124635Z.json
    python -m harness.check --stories <file> --cases <file> --no-judge
    python -m harness.check --stories <file> --cases <file> --reuse-judge results/testgen/score_<...>.json
    python -m harness.check --stories <file> --cases <file> --no-title --lints vague_steps,placeholders

What it does
    1. reads both files and checks the input contract                 (contract.py)
    2. runs the code checks: titles, AC links, ACs with no tests      (checks.py)        free
    3. runs the enabled lints                                          (lints.py)         free
    4. runs the judge, stories in parallel (--workers, default 4), per story:            paid
         case judge (verdict, atomic, duplicate, AC claims, concrete)  (judge.py)
         title judge (does the title say what the test checks?)       (judge.py)
         checklist pass A: story review, story and ACs only (AC gaps) (checklist.py) saved and reused
         checklist pass B: test coverage of the ideas the ACs define  (checklist.py)
         --no-judge      skip step 4 (free checks only)
         --reuse-judge   read the case-judge marks from a Day 4 score file instead (free; for regression)
         --no-title      skip the title judge
         --no-checklist  skip the checklist judge;  --checklist <file> use another checklist
         --case-detail   high-level (default) or low-level: low-level adds the step_detail lint
         --no-cache      re-run every story review instead of reusing saved ones
    Stories only, before any test cases exist (checklist pass A):
         python -m harness.check --stories <file> --stories-only
    5. writes results/harness/<UTC time>/ with:
         cases.csv     one row per case, one column per check ("fail", "warn" or blank), plus the
                       judge's technique label and every message
         findings.csv  every finding with its plain-English message
         summary.md    totals per story and overall, duplicate groups, judge cost and time
         checklist.csv one row per story and checklist item: check setting, status, quote, ACs,
                       cases, cross-check
         judge.json    the judge's raw replies and token counts (only when the judge ran live)

Exit code: 0 if no case fails, 1 if any case fails, 2 if a file cannot be read.

Change history:
  2026-11-12  v1  first version (M7 step 1).
  2026-11-12  v2  M7 step 3: judge checks (case judge + title judge), reuse mode, cost and time.
  2026-11-13  v3  M7 step 4b: checklist judge (suggestions and questions for the product owner).
  2026-11-13  v4  checklist in two passes (story review, reused; test coverage); stories in parallel;
                  --stories-only, --workers, --no-cache.
  2026-11-13  v5  checklist "check" setting (when_raised / every_story / off): the summary lists the
                  settings and the excluded items, and groups a suggestion or question repeated across
                  stories into one line. (A --context project rules file was tried and dropped.)
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from bench.golden import ROOT
from bench.judge import JUDGE_MODEL
from bench.pricing import PROVISIONAL
from harness.checks import run_code_checks
from harness.contract import Finding, InputError, case_key, load_cases, load_stories
from harness.checklist import (CACHE_DIR, CHECKLIST_PATH, check_coverage, checklist_fingerprint,
                               checklist_results, load_checklist, review_story)
from harness.judge import call_cost, duplicate_groups, judge_findings, judge_story, marks_from_score_file
from harness.lints import LINT_NAMES, load_rules, run_lints

OUT_DIR = ROOT / "results" / "harness"
CODE_CHECKS = ("schema", "title", "unknown_ac", "no_ac_linked")
JUDGE_CHECKS = ("verdict", "atomic", "duplicate", "over_claim", "concrete", "title_clear", "judge_missing")


def _judge_one(story: dict, cases: list[dict], client, model: str, titles: bool, items: list[dict],
               cache_dir: Path | None) -> dict:
    """All judge calls for one story: case judge, title judge, then checklist pass A (story review,
    reused from the cache when nothing changed) and pass B (test coverage)."""
    rec = judge_story(story, cases, client, model, titles)
    if items:
        rec["review_call"] = review_story(story, client, items, model, cache_dir)
        rec["coverage_call"] = check_coverage(story, cases, rec["review_call"], client, items, model)
    return rec


def _record_cost(rec: dict, model: str) -> float:
    """Cost of one story's judge calls; a story review reused from the cache costs nothing."""
    calls = [rec.get(k) for k in ("cases_call", "title_call", "coverage_call")]
    review = rec.get("review_call")
    if review and not review.get("cached"):
        calls.append(review)
    return sum(call_cost(c, model) for c in calls if c)


def _checklist_meta(path: Path | None, items: list[dict]) -> dict | None:
    """What the report says about the checklist used: file, fingerprint and each item's setting."""
    if not path or not items:
        return None
    return {"path": str(path), "fingerprint": checklist_fingerprint(path),
            "settings": {i["id"]: (i["name"], i["check"]) for i in items}}


def run_judge(stories: dict, groups: dict, client=None, reuse: Path | None = None,
              titles: bool = True, model: str = JUDGE_MODEL, checklist: Path | None = CHECKLIST_PATH,
              workers: int = 4, cache_dir: Path | None = CACHE_DIR) -> dict:
    """Judge every story that has cases, `workers` stories at a time (each story's own calls run in
    order). Returns {'findings', 'techniques', 'records', 'checklist_rows', 'cost_usd', 'seconds', ...}.
    With `reuse`, the case-judge marks come from a Day 4 score file and no model is called (no title
    or checklist judge then). checklist=None skips the checklist; cache_dir=None re-runs every story review."""
    records = marks_from_score_file(reuse) if reuse else {}
    if not reuse and client is None:
        from bench.generate import make_client          # reads OPENAI_API_KEY from .env
        client = make_client()
    items = load_checklist(checklist) if checklist and not reuse else []
    todo = {sid: [c for c in groups.get(sid, []) if isinstance(c, dict)] for sid in stories}
    todo = {sid: cases for sid, cases in todo.items() if cases}
    start = time.perf_counter()
    if not reuse:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = {sid: pool.submit(_judge_one, stories[sid], cases, client, model, titles, items, cache_dir)
                       for sid, cases in todo.items()}
            records = {sid: f.result() for sid, f in futures.items()}       # story order kept
    findings, techniques, checklist_rows = [], {}, []
    cost = sum(_record_cost(r, model) for r in records.values()) if not reuse else 0.0
    for sid, cases in todo.items():
        if sid not in records:
            findings.append(Finding(sid, "", "judge_missing", "warn", "no judge marks for this story in the reuse file"))
            continue
        f, t = judge_findings(stories[sid], cases, records[sid])
        findings += f
        techniques.update({(sid, cid): tech for cid, tech in t.items()})
        if items:
            f, rows = checklist_results(stories[sid], records[sid].get("review_call"),
                                        records[sid].get("coverage_call"), items, cases)
            findings += f
            checklist_rows += rows
    return {"findings": findings, "techniques": techniques, "records": records, "checklist_rows": checklist_rows,
            "cost_usd": round(cost, 4), "seconds": round(time.perf_counter() - start, 1),
            "mode": "reuse" if reuse else "live", "model": model, "checklist": _checklist_meta(checklist, items)}


def review_stories_only(stories: dict, client=None, checklist: Path = CHECKLIST_PATH, model: str = JUDGE_MODEL,
                        workers: int = 4, cache_dir: Path | None = CACHE_DIR) -> dict:
    """Checklist pass A on its own: review the stories before any test cases exist. Same result
    shape as run_judge, with no case findings."""
    if client is None:
        from bench.generate import make_client
        client = make_client()
    items = load_checklist(checklist)
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {sid: pool.submit(review_story, st, client, items, model, cache_dir) for sid, st in stories.items()}
        records = {sid: {"review_call": f.result()} for sid, f in futures.items()}
    findings, rows = [], []
    for sid, rec in records.items():
        f, r = checklist_results(stories[sid], rec["review_call"], None, items)
        findings += f
        rows += r
    return {"findings": findings, "techniques": {}, "records": records, "checklist_rows": rows,
            "cost_usd": round(sum(_record_cost(r, model) for r in records.values()), 4),
            "seconds": round(time.perf_counter() - start, 1), "mode": "live", "model": model,
            "checklist": _checklist_meta(checklist, items)}


def run_checks(stories_path: Path, cases_path: Path | None, lints: list[str] | None = None, judge: bool = True,
               client=None, reuse: Path | None = None, titles: bool = True,
               checklist: Path | None = CHECKLIST_PATH, case_detail: str | None = None,
               workers: int = 4, cache_dir: Path | None = CACHE_DIR) -> dict:
    """Run every check and return {'stories', 'groups', 'findings', 'rules', 'judge' (None if skipped)}.
    cases_path None = stories only: the checklist story review (pass A) and nothing else.
    case_detail ("high-level" or "low-level") overrides the level in lint_rules.toml."""
    stories = load_stories(stories_path)
    if checklist:
        load_checklist(checklist)                          # a broken checklist stops the run before any model call
    rules = load_rules(only=lints)
    if case_detail:
        rules.setdefault("case_detail", {})["level"] = case_detail
    if cases_path is None:
        judged = review_stories_only(stories, client, checklist or CHECKLIST_PATH, workers=workers,
                                     cache_dir=cache_dir)
        return {"stories": stories, "groups": {}, "findings": judged["findings"], "rules": rules, "judge": judged}
    groups, findings = load_cases(cases_path)
    findings += run_code_checks(stories, groups)
    findings += run_lints(stories, groups, rules)
    judged = (run_judge(stories, groups, client, reuse, titles, checklist=checklist, workers=workers,
                        cache_dir=cache_dir) if judge else None)
    if judged:
        findings += judged["findings"]
    return {"stories": stories, "groups": groups, "findings": findings, "rules": rules, "judge": judged}


def case_rows(result: dict) -> tuple[list[str], list[dict]]:
    """One row per case with a column per case-level check: 'fail', 'warn' or blank."""
    # Columns: the case-level code checks, each lint that is switched on, then the judge checks
    # if the judge ran. boundary_hint and ac_unverified are about a whole story, not one case,
    # so they appear in summary.md and findings.csv only.
    enabled = [n for n in LINT_NAMES if result["rules"].get(n, {}).get("enabled", True) and n != "boundary_hint"]
    judge_cols = list(JUDGE_CHECKS) if result.get("judge") else []
    columns = list(CODE_CHECKS) + enabled + judge_cols
    techniques = (result.get("judge") or {}).get("techniques", {})
    by_case: dict[tuple[str, str], list[Finding]] = {}       # findings grouped per (story, case)
    for f in result["findings"]:
        if f.case_id:
            by_case.setdefault((f.story_id, f.case_id), []).append(f)

    rows = []
    for sid, cases in result["groups"].items():
        for n, case in enumerate(cases, start=1):
            cid = case_key(case, n)
            found = by_case.get((sid, cid), [])
            row = {"story_id": sid, "case_id": cid,
                   "title": case.get("title", "") if isinstance(case, dict) else "",
                   "fails": sum(f.level == "fail" for f in found),
                   "warnings": sum(f.level == "warn" for f in found)}
            for col in columns:                               # "fail" outranks "warn" in a cell
                levels = {f.level for f in found if f.check == col}
                row[col] = "fail" if "fail" in levels else ("warn" if levels else "")
            if judge_cols:
                row["judge_technique"] = techniques.get((sid, cid), "")
            row["messages"] = " | ".join(f"{f.check}: {f.message}" for f in found)
            rows.append(row)
    extra = ["judge_technique"] if judge_cols else []
    return ["story_id", "case_id", "title", "fails", "warnings"] + columns + extra + ["messages"], rows


def _grouped(findings: list[Finding], level: str, names: dict[str, str]) -> list[str]:
    """Checklist findings of one level as summary lines; an item found in two or more stories is
    one line naming the stories (Roger, 13 Nov), with each story's own note underneath."""
    by_item: dict[str, list[Finding]] = {}
    for f in findings:
        if f.check == "checklist" and f.level == level:
            by_item.setdefault(f.message.split(" ", 1)[0], []).append(f)
    lines = []
    for item_id, fs in sorted(by_item.items()):
        if len(fs) == 1:
            lines.append(f"- {fs[0].story_id}: {fs[0].message}")
            continue
        lines.append(f"- {item_id} {names.get(item_id, '')}: in {len(fs)} stories ({', '.join(f.story_id for f in fs)})")
        prefix = f"{item_id} {names.get(item_id, '')}"             # strip the item ID and name (names may hold ':')
        lines += [f"    - {f.story_id}: {f.message[len(prefix):].lstrip(' :') if f.message.startswith(prefix) else f.message}"
                  for f in fs]
    return lines or ["- none"]


def checklist_markdown(rows: list[dict], findings: list[Finding], meta: dict | None) -> list[str]:
    """The checklist part of summary.md: the settings used (with every excluded item named), pass A
    (story review) and pass B (test coverage), with repeated findings grouped."""
    status = Counter(r["status"] for r in rows)
    stories_n = len({r["story_id"] for r in rows})
    cached = len({r["story_id"] for r in rows if r["review_cached"]})
    settings = (meta or {}).get("settings") or {r["item_id"]: (r["name"], r["check"]) for r in rows}
    named = {v: [f"{k} {n}" for k, (n, c) in settings.items() if c == v] for v in ("off", "every_story")}
    lines = ["", "## Checklist settings for this run", ""]
    if meta:
        lines.append(f"Checklist file: {Path(meta['path']).name} (fingerprint {meta['fingerprint']}).")
    lines += [f"- Excluded (check = off), NOT checked in any story: {', '.join(named['off']) or 'none'}",
              f"- Checked in every story's test cases (check = every_story): {', '.join(named['every_story']) or 'none'}",
              "- All other items: checked when the story raises them (check = when_raised)", "",
              "## Checklist pass A: story review (story and ACs only)", "",
              f"Ideas the stories raise: {status['ac_gap'] + sum(1 for r in rows if r['check'] == 'when_raised' and r['status'] in ('defined', 'covered', 'not_covered', 'missing'))} "
              f"(AC gaps: {status['ac_gap']}); not raised by the story: {status['not_raised']} "
              f"(no claim made either way). Story reviews reused from earlier runs: {cached} of {stories_n}.",
              "", "Questions for the product owner (AC gaps):", ""]
    names = {k: n for k, (n, _) in settings.items()}
    lines += _grouped(findings, "question", names)
    tested = Counter(r["status"] for r in rows if r["status"] in ("covered", "not_covered", "missing"))
    if tested:
        lines += ["", "## Checklist pass B: test coverage", "",
                  f"Covered: {tested['covered']}; not covered: {tested['not_covered']}"
                  + (f"; not answered: {tested['missing']}" if tested["missing"] else "") + ".",
                  "", "Suggestions for the test cases (not covered):", ""]
        lines += _grouped(findings, "suggestion", names)
    asked = [r for r in rows if r["check"] == "when_raised"]
    disagree = [r for r in asked if r["disagree"]]
    lines += ["", f"Cross-check: trigger words and the story review disagree on whether the story raises an idea in "
                  f"{len(disagree)} of {len(asked)} story-idea pairs (checklist.csv, column disagree; a tuning aid)."]
    return lines


def summary_markdown(result: dict, header: str) -> str:
    """Totals per story and overall, duplicate groups and judge cost, as a short markdown page."""
    findings, judged = result["findings"], result.get("judge")
    mode = ("no judge" if not judged else "judge marks reused from a Day 4 score file" if judged["mode"] == "reuse"
            else f"judge {judged['model']}")
    lines = [f"# Harness check: {header}", "",
             f"Checks: code checks, lints, {mode}. fail = breaks the input contract or a hard rule; "
             "warn = worth a human look; info = a reminder of something the code cannot check.", "",
             "| Story | Cases | Cases with a fail | Cases with a warning | ACs with no test | "
             "ACs with no verified test | Boundary hints | Checklist suggestions | Questions for the PO |",
             "|---|---|---|---|---|---|---|---|---|"]
    for sid in sorted(set(result["stories"]) | set(result["groups"])):
        cases = result["groups"].get(sid, [])
        fs = [f for f in findings if f.story_id == sid]
        failed = {f.case_id for f in fs if f.case_id and f.level == "fail"}
        warned = {f.case_id for f in fs if f.case_id and f.level == "warn"}
        unverified = sum(f.check == "ac_unverified" for f in fs) if judged else "–"
        has_list = bool(judged and judged.get("checklist_rows"))
        sugg = sum(f.level == "suggestion" for f in fs) if has_list else "–"
        ques = sum(f.level == "question" for f in fs) if has_list else "–"
        lines.append(f"| {sid} | {len(cases)} | {len(failed)} | {len(warned)} | "
                     f"{sum(f.check == 'ac_no_tests' for f in fs)} | {unverified} | "
                     f"{sum(f.check == 'boundary_hint' and f.level == 'warn' for f in fs)} | {sugg} | {ques} |")
    counts = Counter((f.check, f.level) for f in findings)
    lines += ["", "## Findings by check", "", "| Check | Level | Count |", "|---|---|---|"]
    lines += [f"| {c} | {lvl} | {n} |" for (c, lvl), n in sorted(counts.items())]
    if judged:
        groups = duplicate_groups(findings)
        lines += ["", "## Duplicate groups (judge)", ""]
        lines += [f"- {sid}: " + "; ".join(" = ".join(g) for g in gs) for sid, gs in groups.items()] or ["- none"]
        price_note = " (price provisional)" if judged["model"] in PROVISIONAL else ""
        lines += ["", "## Judge cost and time", "",
                  f"- Mode: {judged['mode']}; model {judged['model']}",
                  f"- Cost: ${judged['cost_usd']:.4f}{price_note}; time {judged['seconds']} s"]
    rows = (judged or {}).get("checklist_rows") or []
    if rows:
        lines += checklist_markdown(rows, findings, judged.get("checklist"))
    story_level = [f for f in findings if not f.case_id and f.check != "checklist"]
    if story_level:
        lines += ["", "## Story-level findings", ""]
        lines += [f"- {f.story_id} ({f.level}, {f.check}): {f.message}" for f in story_level]
    return "\n".join(lines) + "\n"


def write_outputs(result: dict, out_dir: Path, header: str) -> None:
    """Write cases.csv, findings.csv, summary.md and (if the judge ran) judge.json into out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    columns, rows = case_rows(result)
    with open(out_dir / "cases.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)
    with open(out_dir / "findings.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["story_id", "case_id", "check", "level", "message"])
        w.writerows([[x.story_id, x.case_id, x.check, x.level, x.message] for x in result["findings"]])
    (out_dir / "summary.md").write_text(summary_markdown(result, header), encoding="utf-8")
    judged = result.get("judge")
    if judged and judged.get("checklist_rows"):
        with open(out_dir / "checklist.csv", "w", newline="", encoding="utf-8-sig") as f:
            # my_agree / notes are empty columns for a reviewer to mark each answer right (y) or wrong (n)
            w = csv.DictWriter(f, fieldnames=list(judged["checklist_rows"][0]) + ["my_agree", "notes"])
            w.writeheader()
            w.writerows([{**{k: (", ".join(v) if isinstance(v, list) else v) for k, v in r.items()},
                          "my_agree": "", "notes": ""} for r in judged["checklist_rows"]])
    if judged and judged["mode"] == "live":
        meta = {k: judged[k] for k in ("mode", "model", "cost_usd", "seconds")}
        (out_dir / "judge.json").write_text(json.dumps({"meta": meta, "stories": judged["records"]},
                                                       indent=1, ensure_ascii=False), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Parse the command line, run the checks, write the outputs, print a short summary."""
    p = argparse.ArgumentParser(description="Check AI-generated test cases against their user stories.")
    p.add_argument("--stories", required=True, type=Path, help="stories JSON file")
    p.add_argument("--cases", type=Path, help="cases JSON file (leave out with --stories-only)")
    p.add_argument("--stories-only", action="store_true",
                   help="review the stories against the checklist before any test cases exist (pass A only)")
    p.add_argument("--workers", type=int, default=4, help="stories judged at the same time (default 4)")
    p.add_argument("--no-cache", action="store_true", help="re-run every story review instead of reusing saved ones")
    p.add_argument("--lints", help="comma-separated lints to run (overrides lint_rules.toml), or 'none'")
    p.add_argument("--no-judge", action="store_true", help="free checks only: no model calls")
    p.add_argument("--reuse-judge", type=Path, help="read case-judge marks from a Day 4 score file (free)")
    p.add_argument("--no-title", action="store_true", help="skip the title judge")
    p.add_argument("--no-checklist", action="store_true", help="skip the checklist judge")
    p.add_argument("--case-detail", choices=["high-level", "low-level"],
                   help="the level the cases are written at (default from lint_rules.toml: high-level)")
    p.add_argument("--checklist", type=Path, default=CHECKLIST_PATH, help="checklist file (default harness/checklist.toml)")
    p.add_argument("--out", type=Path, help="output folder (default results/harness/<UTC time>)")
    args = p.parse_args(argv)

    lints = None if args.lints is None else ([] if args.lints.strip() == "none" else
                                             [x.strip() for x in args.lints.split(",") if x.strip()])
    if not args.stories_only and args.cases is None:
        print("cannot run: give --cases <file>, or --stories-only to review the stories alone")
        return 2
    try:
        result = run_checks(args.stories, None if args.stories_only else args.cases, lints, judge=not args.no_judge,
                            reuse=args.reuse_judge, titles=not (args.no_title or args.reuse_judge),
                            checklist=None if args.no_checklist else args.checklist, case_detail=args.case_detail,
                            workers=args.workers, cache_dir=None if args.no_cache else CACHE_DIR)
    except (InputError, ValueError, OSError) as e:
        print(f"cannot run: {e}")
        return 2

    out_dir = args.out or OUT_DIR / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    header = (f"story review of {args.stories.name}" if args.stories_only
              else f"{args.cases.name} against {args.stories.name}")
    write_outputs(result, out_dir, header)
    n_cases = sum(len(c) for c in result["groups"].values())
    judged = result.get("judge")
    print(f"{n_cases} cases in {len(result['groups'])} stories; "
          + (f"judge {judged['mode']}, ${judged['cost_usd']:.4f}, {judged['seconds']} s" if judged else "no judge"))
    for (check, level), n in sorted(Counter((f.check, f.level) for f in result["findings"]).items()):
        print(f"  {check:<18} {level:<5} {n}")
    print(f"saved {out_dir}")
    failed = {(f.story_id, f.case_id) for f in result["findings"] if f.level == "fail"}
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
