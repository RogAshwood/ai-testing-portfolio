"""skill_review.py: run the team's test-case REVIEW skill on the seeded sets and score it like the harness.

Why (M7 step 7, question B): a QA team could skip the harness and write a review skill instead:
plain-English review checks an AI assistant follows. Is that enough? The seeded sets give an
answer key, so the skill can be scored exactly as the harness was (harness/seeded.py):
defects caught, clean controls left alone, false alarms. Running it twice shows how consistent it is.

What runs
  The skill harness/skills/testcase-reviewer/SKILL.md (its content, without the front matter) is
  the instructions; the input is one story card plus that story's cases exactly as written. One call
  per story, the same model as the harness judge (gpt-6-sol), structured JSON reply. This tests the
  skill's CONTENT through the API, not an assistant's skill runtime (loading on demand, tools).

How its answers are scored
  Each problem name in the skill maps to the harness check that looks for the same thing
  (PROBLEM_TO_CHECK below), so the seeded expectations score both the same way: a seed is caught
  when the skill reports the problem on that case (or story), a control is clean when it reports
  nothing.

Usage (repo root, ai-testing env; paid, about $0.10-0.20 per run of all three sets):
    python -m harness.skill_review                     # all three seed sets, twice
    python -m harness.skill_review --set aml --repeat 1
Writes results/harness/skill_review_<UTC time>/: report.md (scores per run and set, consistency
between runs, every seed), seeds.csv, replies.json.

Real cases (no planted defects; about $0.20 for 222 cases): review any cases file, compare the
skill with a harness run on the same file check by check, and score both against a reviewer's labels:
    python -m harness.skill_review --stories datasets/aml_kyc_stories.json --cases <cases file>
        --compare results/harness/<harness run folder>
        --labels results/testgen/calibration/m7_aml_blind_labels.csv results/testgen/calibration/m7_aml_sample_r1.csv
Writes results/harness/skill_review_<UTC time>/: findings.csv (the skill's findings), agreement.md.

Change history:
  2026-11-25  v1  first version (M7 step 7).
  2026-11-25  v2  real cases: --stories/--cases, --compare (harness run), --labels (Roger's marks).
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from bench.golden import ROOT, fingerprint_text, story_card
from bench.judge import JUDGE_MODEL
from bench.pricing import cost_usd
from bench.testcase_schema import parse_reply
from harness import seeded
from harness.contract import Finding, case_key, load_cases, load_stories
from harness.generate import load_skill

SKILL = "testcase-reviewer"
# skill problem name -> (harness check name, level)
PROBLEM_TO_CHECK = {
    "incorrect": ("verdict", "fail"), "not_in_basis": ("verdict", "fail"),
    "bundled": ("atomic", "warn"), "vague_data": ("concrete", "warn"), "duplicate": ("duplicate", "warn"),
    "over_claim": ("over_claim", "warn"), "unclear_title": ("title_clear", "warn"),
    "generic_title": ("generic_title", "warn"), "leftover_placeholder": ("placeholders", "warn"),
    "vague_step": ("vague_steps", "warn"), "vague_expected_result": ("vague_expected", "warn"),
    "copied_expected": ("repeated_expected", "warn"), "no_expected_result": ("schema", "fail"),
    "unknown_ac": ("unknown_ac", "fail"), "no_ac_linked": ("no_ac_linked", "warn")}
STORY_PROBLEM_TO_CHECK = {"ac_without_tests": "ac_no_tests", "untested_limit": "boundary_hint"}
_s = {"type": "string"}
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["story_id", "cases", "story_problems"],
          "properties": {
              "story_id": _s,
              "cases": {"type": "array", "items": {
                  "type": "object", "additionalProperties": False, "required": ["case_id", "problems"],
                  "properties": {"case_id": _s, "problems": {"type": "array", "items": {
                      "type": "object", "additionalProperties": False,
                      "required": ["name", "reason", "duplicate_of", "acs"],
                      "properties": {"name": {"type": "string", "enum": sorted(PROBLEM_TO_CHECK)}, "reason": _s,
                                     "duplicate_of": _s, "acs": {"type": "array", "items": _s}}}}}}},
              "story_problems": {"type": "array", "items": {
                  "type": "object", "additionalProperties": False, "required": ["name", "ac_id", "limit", "reason"],
                  "properties": {"name": {"type": "string", "enum": sorted(STORY_PROBLEM_TO_CHECK)}, "ac_id": _s,
                                 "limit": _s, "reason": _s}}}}}


# --- one story ----------------------------------------------------------------------
def review_story(story: dict, cases: list[dict], client, model: str = JUDGE_MODEL) -> dict:
    """One call: the skill as instructions, the story card and the cases exactly as written as input.
    Returns {'story_id', 'parsed', 'raw', 'usage'}; retries an API error once."""
    instructions = load_skill(SKILL)
    payload = f"User story:\n{story_card(story)}\n\nTest cases:\n" + json.dumps(cases, indent=1, ensure_ascii=False)
    fmt = {"format": {"type": "json_schema", "name": "testcase_review", "schema": SCHEMA, "strict": True}}
    start = time.perf_counter()
    for attempt in (1, 2):
        try:
            resp = client.responses.create(model=model, instructions=instructions, input=payload, text=fmt)
            break
        except Exception:
            if attempt == 2:
                raise
            time.sleep(5)
    raw = resp.output_text.strip()
    parsed, _ = parse_reply(raw)
    usage = getattr(resp, "usage", None)
    return {"story_id": story["story_id"], "parsed": parsed, "raw": raw if parsed is None else None,
            "usage": {"input_tokens": getattr(usage, "input_tokens", None),
                      "output_tokens": getattr(usage, "output_tokens", None),
                      "latency_s": round(time.perf_counter() - start, 2)}}


def findings_from_reply(story: dict, cases: list[dict], rec: dict) -> list[Finding]:
    """The skill's answer as harness findings, so the seeded scorer reads both the same way.
    A case the skill did not mention at all counts as clean (and is noted as missing)."""
    sid = story["story_id"]
    ids = {case_key(c, n) for n, c in enumerate(cases, start=1)}
    out = []
    for c in (rec.get("parsed") or {}).get("cases", []):
        cid = c.get("case_id")
        if cid not in ids:
            continue
        for p in c.get("problems", []):
            check, level = PROBLEM_TO_CHECK.get(p.get("name"), (None, None))
            if check:
                extra = (f" (repeats {p['duplicate_of']})" if p.get("duplicate_of") else "") + \
                        (f" (ACs {', '.join(p['acs'])})" if p.get("acs") else "")
                out.append(Finding(sid, cid, check, level, f"{p['name']}{extra}: {p.get('reason', '')}"))
    for p in (rec.get("parsed") or {}).get("story_problems", []):
        check = STORY_PROBLEM_TO_CHECK.get(p.get("name"))
        if check:
            limit = f" mentions {p['limit']}" if p.get("limit") else ""
            out.append(Finding(sid, "", check, "warn", f"{p.get('ac_id', '')}{limit}: {p.get('reason', '')}"))
    if rec.get("parsed") is None:
        out.append(Finding(sid, "", "skill_reply", "warn", "the review skill returned no readable reply"))
    return out


# --- one seed set, one run ------------------------------------------------------------
def run_set(name: str, folder: Path, client, model: str = JUDGE_MODEL, workers: int = 4) -> tuple[list[dict], list[dict], float]:
    """Review one seed set with the skill and score it. Returns (score rows, raw replies, cost in USD)."""
    groups, case_exp, story_exp = (seeded.harness_set() if name == "harness" else
                                   seeded.harness_set(seeded.AML_SEEDS) if name == "aml" else seeded.day4_set())
    stories_path, cases_path = seeded.write_inputs(groups, folder / name,
                                                   seeded.AML_STORIES if name == "aml" else seeded.GOLDEN)
    stories = load_stories(stories_path)
    cases, _ = load_cases(cases_path)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        recs = list(pool.map(lambda sid: review_story(stories[sid], cases[sid], client, model), list(cases)))
    findings = [f for rec in recs for f in findings_from_reply(stories[rec["story_id"]], cases[rec["story_id"]], rec)]
    rows = [seeded.score_case(e, findings, True) for e in case_exp] + [seeded.score_story(e, findings, True) for e in story_exp]
    for r in rows:
        r["set"] = name
    cost = sum(cost_usd(model, r["usage"]["input_tokens"], r["usage"]["output_tokens"]) or 0 for r in recs)
    return rows, recs, cost


# --- real cases: review a cases file and compare -----------------------------------------
COMPARED = ("verdict", "atomic", "concrete", "title_clear", "duplicate", "over_claim")


def review_file(stories_path: Path, cases_path: Path, client, model: str = JUDGE_MODEL, workers: int = 4) -> tuple[list[Finding], list[dict], float]:
    """Review every story of a cases file with the skill. Returns (findings, raw replies, cost in USD)."""
    stories = load_stories(stories_path)
    groups, _ = load_cases(cases_path)
    todo = [sid for sid in groups if sid in stories]
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        recs = list(pool.map(lambda sid: review_story(stories[sid], groups[sid], client, model), todo))
    findings = [f for rec in recs for f in findings_from_reply(stories[rec["story_id"]], groups[rec["story_id"]], rec)]
    cost = sum(cost_usd(model, r["usage"]["input_tokens"], r["usage"]["output_tokens"]) or 0 for r in recs)
    return findings, recs, cost


def flagged(findings: list[Finding]) -> dict[str, set]:
    """{check: {(story, case), ...}}: which cases each compared check flagged."""
    out = {c: set() for c in COMPARED}
    for f in findings:
        if f.case_id and f.check in out:
            out[f.check].add((f.story_id, f.case_id))
    return out


def agreement(skill: dict[str, set], harness: dict[str, set], all_cases: set) -> list[dict]:
    """Per check: cases both flagged, only the harness, only the skill, neither; % agreement and
    Cohen's kappa (agreement beyond what chance alone would give; 1 = perfect, 0 = chance)."""
    rows = []
    n = len(all_cases) or 1
    for c in COMPARED:
        a, b = skill[c] & all_cases, harness[c] & all_cases
        both, h_only, s_only = len(a & b), len(b - a), len(a - b)
        neither = n - both - h_only - s_only
        po = (both + neither) / n
        pe = ((len(a) / n) * (len(b) / n)) + ((1 - len(a) / n) * (1 - len(b) / n))
        kappa = (po - pe) / (1 - pe) if pe < 1 else 1.0
        rows.append({"check": c, "both": both, "harness_only": h_only, "skill_only": s_only, "neither": neither,
                     "agree_pct": round(100 * po, 1), "kappa": round(kappa, 2)})
    return rows


def load_labels(paths: list[Path]) -> dict[tuple, dict]:
    """A reviewer's labels as {(story, case): {'verdict_faulty': bool, 'atomic': bool, 'title_clear': bool}}
    (only the keys the file gives). Reads the blind sheet (Q1_correct / Q2_single_purpose / Q3_title_clear)
    and the marking sample (rows of kind 'case verdict fail' agreed y = the case really is faulty)."""
    out: dict[tuple, dict] = {}
    for p in paths:
        with open(p, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                if "Q1_correct" in r:
                    key = (r["story"], r["case_id"])
                    lab = out.setdefault(key, {})
                    if r["Q1_correct"].strip():
                        lab["verdict_faulty"] = r["Q1_correct"].strip().lower() != "correct"
                    if r["Q2_single_purpose"].strip():
                        lab["atomic"] = r["Q2_single_purpose"].strip().lower().startswith("y")
                    if r["Q3_title_clear"].strip():
                        lab["title_clear"] = r["Q3_title_clear"].strip().lower().startswith("y")
                elif r.get("kind") == "case verdict fail" and r.get("my_agree", "").strip().lower().startswith("y"):
                    cid = r["cases_or_judge_note"].split(":", 1)[0].strip()
                    out.setdefault((r["story"], cid), {})["verdict_faulty"] = True
    return out


def score_against_labels(labels: dict, flags: dict[str, set]) -> dict[str, tuple[int, int]]:
    """How many labelled cases a checker got right, per question: {name: (right, labelled)}."""
    tests = {"verdict": ("verdict_faulty", lambda k: k in flags["verdict"]),
             "atomic": ("atomic", lambda k: k not in flags["atomic"]),
             "title_clear": ("title_clear", lambda k: k not in flags["title_clear"])}
    out = {}
    for name, (field, says) in tests.items():
        keyed = [(k, v[field]) for k, v in labels.items() if field in v]
        out[name] = (sum(says(k) == truth for k, truth in keyed), len(keyed))
    return out


def agreement_report(header: str, rows: list[dict], n_cases: int, cost: float, seconds: float,
                     human: dict | None) -> str:
    """agreement.md: skill vs harness per check, then both against the reviewer's labels."""
    lines = [f"# Review skill vs harness on real cases: {header}", "",
             f"{n_cases} cases. Review skill cost ${cost:.4f}, {seconds:.1f} s.", "",
             "## Skill vs harness, case by case", "",
             "| Check | Both flag | Harness only | Skill only | Neither | Agreement | Kappa |", "|---|---|---|---|---|---|---|"]
    lines += [f"| {r['check']} | {r['both']} | {r['harness_only']} | {r['skill_only']} | {r['neither']} | "
              f"{r['agree_pct']}% | {r['kappa']} |" for r in rows]
    lines += ["", "Kappa: agreement beyond chance (1 = always agree, 0 = no better than chance, below 0 = worse). "
                  "It matters most for rare checks, where two checkers that flag nothing still 'agree' on most cases."]
    if human:
        lines += ["", "## Both against the reviewer's labels", "",
                  "| Question | Harness right | Skill right |", "|---|---|---|"]
        for q in ("verdict", "atomic", "title_clear"):
            h, s_ = human["harness"].get(q, (0, 0)), human["skill"].get(q, (0, 0))
            lines.append(f"| {q} | {h[0]}/{h[1]} | {s_[0]}/{s_[1]} |")
        lines += ["", "Labels: blind sheet as first marked (before the reviewer saw the judge's reasons) plus the "
                      "sample rows where the reviewer confirmed a case was faulty."]
    return "\n".join(lines) + "\n"


# --- comparing runs ------------------------------------------------------------------
def consistency(runs: list[list[dict]]) -> tuple[int, int]:
    """How many seeds got the same result (caught / missed / ok / false alarm) and the same findings
    in every run, out of all seeds."""
    keyed = [{(r["set"], r["seed_id"]): (r["result"], r["found"]) for r in rows} for rows in runs]
    same = sum(all(k[s] == keyed[0][s] for k in keyed) for s in keyed[0])
    return same, len(keyed[0])


def totals(rows: list[dict]) -> dict:
    """Defect seeds caught, controls clean and false alarms for one set of score rows."""
    seeds = [r for r in rows if r["kind"] == "defect"]
    controls = [r for r in rows if r["kind"] == "control"]
    return {"caught": sum(r["result"] == "caught" for r in seeds), "seeds": len(seeds),
            "clean": sum(r["result"] == "ok" for r in controls), "controls": len(controls),
            "false_alarms": sum(r["result"] == "false alarm" for r in rows)}


def report(runs: list[list[dict]], costs: list[float], seconds: list[float], model: str, fp: str) -> str:
    """report.md: scores per run and set, consistency, then every seed with its result in each run."""
    lines = ["# Review skill on the seeded sets", "",
             f"Skill: harness/skills/{SKILL} (content fingerprint {fp}); model {model}; {len(runs)} run(s).", "",
             "| Run | Set | Defect seeds caught | Controls clean | False alarms | Cost | Time |", "|---|---|---|---|---|---|---|"]
    for i, rows in enumerate(runs, start=1):
        for name in sorted({r["set"] for r in rows}):
            t = totals([r for r in rows if r["set"] == name])
            lines.append(f"| {i} | {name} | {t['caught']}/{t['seeds']} | {t['clean']}/{t['controls']} | "
                         f"{t['false_alarms']} | | |")
        lines.append(f"| {i} | all | | | | ${costs[i - 1]:.4f} | {seconds[i - 1]:.1f} s |")
    if len(runs) > 1:
        same, n = consistency(runs)
        lines += ["", f"Consistency: {same} of {n} seeds got the same result and the same findings in every run."]
    lines += ["", "| Set | Seed | Case | Defect | Expected | " + " | ".join(f"Run {i}" for i in range(1, len(runs) + 1)) + " |",
              "|---|---|---|---|---|" + "---|" * len(runs)]
    for k, r in enumerate(runs[0]):
        cells = " | ".join(f"{rows[k]['result']} ({rows[k]['found']})" for rows in runs)
        lines.append(f"| {r['set']} | {r['seed_id']} | {r['story_id']} {r['case_id']} | {r['defect']} | {r['expected']} | {cells} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Run the review skill on the chosen seed sets, the chosen number of times, and write the report."""
    p = argparse.ArgumentParser(description="Score the team's review skill on the seeded sets.")
    p.add_argument("--set", choices=["harness", "day4", "aml", "all"], default="all")
    p.add_argument("--repeat", type=int, default=2, help="how many times to run it (consistency; default 2)")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--stories", type=Path, help="real cases mode: the stories file")
    p.add_argument("--cases", type=Path, help="real cases mode: the cases file to review")
    p.add_argument("--compare", type=Path, help="real cases mode: a harness run folder on the same cases file")
    p.add_argument("--labels", type=Path, nargs="*", default=[], help="real cases mode: reviewer label sheets")
    args = p.parse_args(argv)
    from bench.generate import make_client                 # reads OPENAI_API_KEY from .env
    client = make_client()
    if args.cases:
        return real_cases(args, client)
    names = ["harness", "day4", "aml"] if args.set == "all" else [args.set]
    out = ROOT / "results" / "harness" / f"skill_review_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    runs, costs, seconds, replies = [], [], [], {}
    for i in range(1, max(1, args.repeat) + 1):
        start, rows, cost = time.perf_counter(), [], 0.0
        for name in names:
            r, recs, c = run_set(name, out / f"run{i}", client, workers=args.workers)
            rows += r
            cost += c
            replies[f"run{i}/{name}"] = recs
        runs.append(rows)
        costs.append(cost)
        seconds.append(time.perf_counter() - start)
    fp = fingerprint_text(load_skill(SKILL))
    text = report(runs, costs, seconds, JUDGE_MODEL, fp)
    (out / "report.md").write_text(text, encoding="utf-8")
    (out / "replies.json").write_text(json.dumps(replies, indent=1, ensure_ascii=False), encoding="utf-8")
    with open(out / "seeds.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["run", "set", "seed_id", "story_id", "case_id", "kind", "defect", "expected",
                                          "found", "missed", "false_alarm", "result"])
        w.writeheader()
        for i, rows in enumerate(runs, start=1):
            w.writerows([{"run": i, **r} for r in rows])
    print("\n".join(text.splitlines()[:6 + len(names) * len(runs) + len(runs) + 2]))
    print(f"saved {out}")
    return 0


def real_cases(args, client) -> int:
    """Real cases mode: review the file, write findings.csv and agreement.md, print the tables."""
    out = ROOT / "results" / "harness" / f"skill_review_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    out.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    findings, recs, cost = review_file(args.stories, args.cases, client, workers=args.workers)
    seconds = time.perf_counter() - start
    groups, _ = load_cases(args.cases)
    all_cases = {(sid, case_key(c, n)) for sid, cs in groups.items() for n, c in enumerate(cs, start=1)}
    with open(out / "findings.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["story_id", "case_id", "check", "level", "message"])
        w.writerows([[x.story_id, x.case_id, x.check, x.level, x.message] for x in findings])
    (out / "replies.json").write_text(json.dumps(recs, indent=1, ensure_ascii=False), encoding="utf-8")
    rows, human = [], None
    if args.compare:
        with open(args.compare / "findings.csv", encoding="utf-8-sig") as f:
            harness = [Finding(r["story_id"], r["case_id"], r["check"], r["level"], r["message"]) for r in csv.DictReader(f)]
        rows = agreement(flagged(findings), flagged(harness), all_cases)
        if args.labels:
            labels = load_labels(args.labels)
            human = {"harness": score_against_labels(labels, flagged(harness)),
                     "skill": score_against_labels(labels, flagged(findings))}
    text = agreement_report(f"{args.cases.name} against {args.stories.name}", rows, len(all_cases), cost, seconds, human)
    (out / "agreement.md").write_text(text, encoding="utf-8")
    print(text)
    print(f"saved {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
