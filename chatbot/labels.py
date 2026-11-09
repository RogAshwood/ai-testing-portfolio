"""
chatbot/labels.py: blind human labels for the M5 judge, and the agreement report.

Why this exists
---------------
The seeded replies show the judge gets clear-cut cases right. Real replies are
messier, so the judge is also measured against a person: Roger labels a sample
of real turn-checks pass or fail without seeing the judge's verdict, and this
module compares the two. Same method as Day 4 (results/judge_labels*.csv).

Two halves
----------
Every label is put in one of two halves, the same way each time:
  tune       disagreements here may be used to improve the rubric wording
  held_out   never used for tuning; the agreement figure we report comes from here
Day 4 showed why: agreement tuned to 20/20 fell to 10/20 on labels held back.

How the sample is chosen (build)
--------------------------------
From one judged run (judge.json):
  - turns used as examples in the rubric are left out (the judge was shown them)
  - every turn-specific check is included (they are few: no_leak, no_promise, ...)
  - plain_language: every turn the judge failed, plus 5 it passed
  - no_invented_fact: every turn the judge failed, plus 10 it passed, picked at
    random from turns where a tool was called
  - BORDERLINE: turn-checks whose verdict changed between two judgings of the same
    run with no change to their rubric wording (always included if present)
The sample is weighted towards failures so both outcomes get labelled; the
agreement figure is for this sample, not for the whole run.

Files written to results/chatbot_labels/
  <run>_labels.csv       what Roger fills in (human_label, human_notes). No verdicts.
  <run>_label_pack.md    the full context for each turn, as the judge saw it
  <run>_labels_key.csv   the judge's verdicts and the half for each label. Not to be
                         opened before labelling is finished.
An existing labels file is never overwritten, so labels can't be lost.

Usage (from the repo root)
--------------------------
  python -m chatbot.labels build results/chatbot/<run_id>
  python -m chatbot.labels agree results/chatbot/<run_id>
  python -m chatbot.labels rekey results/chatbot/<run_id>     after the run is judged again
  python -m chatbot.labels agree results/chatbot/<run_id> --show-held-out   (only for the final report)

After a rubric change, the run is judged again and `rekey` refreshes the judge's
verdicts in the key file. The labels, the label IDs and the halves stay exactly as
they were; the old key is kept with its rubric fingerprint in the file name.

No API calls.

Change history:
  2026-11-09  v1  first version (M5 step 4d).
  2026-11-09  v1.1  rekey (refresh verdicts after a rubric change); agree prints the
                    rubric version and refuses a key that doesn't match the judged run.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

from chatbot.judge import (GOLDEN_PATH, RUBRIC_PATH, build_packet, evidence, load_rubric, render_packet,
                           spec_rules)

ROOT = Path(__file__).resolve().parents[1]
LABELS_DIR = ROOT / "results" / "chatbot_labels"
EVERY_TURN = ("plain_language", "no_invented_fact")
PL_PASSES, NIF_PASSES, SEED = 5, 10, 20261109     # sample sizes and the random seed (fixed, so reproducible)
TARGET_OVERALL, TARGET_PER_CHECK, MIN_HELD_OUT = 0.85, 0.80, 5      # decision D6
# Verdicts that flipped between the two judgings of run 20261106T144933Z on 9 Nov
# (rubric v1.0 then v1.1; neither change touched these checks' wording).
BORDERLINE = {("L02", 4, "no_invented_fact"), ("C05", 2, "no_invented_fact")}


# ---------------------------------------------------------------------------
# Choosing the sample
# ---------------------------------------------------------------------------

def rubric_example_turns(run_dir: Path, rubric_path: Path = RUBRIC_PATH) -> set[tuple[str, int]]:
    """Turns in this run whose reply is quoted as an example in the rubric.

    An example line looks like: - "reply text, with … for cut parts" → verdict.
    A turn matches if every quoted part (longer than 8 characters) is in its reply."""
    def norm(s):
        return re.sub(r"[’']", "'", s)
    lines = [l for l in rubric_path.read_text(encoding="utf-8").splitlines() if l.startswith('- "') and '" →' in l]
    replies = {(r["conv_id"], i): norm(t["reply"]) for r in load_records(run_dir)
               for i, t in enumerate(r["turns"], start=1)}
    found = set()
    for line in lines:
        parts = [p.strip() for p in norm(line[3:line.index('" →')]).split("…") if len(p.strip()) > 8]
        found |= {k for k, reply in replies.items() if parts and all(p in reply for p in parts)}
    return found


def load_records(run_dir: Path) -> list[dict]:
    """The conversation records in a run folder (skips checks.json, judge.json)."""
    out = []
    for p in sorted(run_dir.glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(d, dict) and "conv_id" in d and "turns" in d:
            out.append(d)
    return out


def half_for(position: int) -> str:
    """tune or held_out. Within each check, labels are put in a fixed shuffled order
    (label_order_key) and alternate between the halves, so each check is split evenly
    and the split never depends on the labels or the verdicts."""
    return "tune" if position % 2 == 0 else "held_out"


def label_order_key(conv_id: str, turn: int, check: str) -> str:
    """A stable, shuffled-looking order for labels within a check."""
    return hashlib.sha256(f"{conv_id}|{turn}|{check}".encode()).hexdigest()


def choose_sample(judge: dict, excluded: set[tuple[str, int]], tool_turns: set[tuple[str, int]]) -> list[dict]:
    """The turn-checks to label, each with the judge's verdict and its half.
    (C05 t2 is in BORDERLINE but is a rubric example turn, so it stays out.)"""
    rng = random.Random(SEED)
    pool = defaultdict(list)                                   # check -> [(conv, turn, verdict, reason)]
    for t in judge["turns"]:
        if (t["conv_id"], t["turn"]) in excluded:
            continue
        for c, v in t["verdicts"].items():
            pool[c].append((t["conv_id"], t["turn"], v["verdict"], v["reason"]))
    chosen = []
    for c, items in pool.items():
        if c == "plain_language":
            fails = [x for x in items if x[2] != "pass"]
            passes = [x for x in items if x[2] == "pass"]
            chosen += [(c, x) for x in fails + rng.sample(passes, min(PL_PASSES, len(passes)))]
        elif c == "no_invented_fact":
            fails = [x for x in items if x[2] != "pass"]
            passes = [x for x in items if x[2] == "pass" and (x[0], x[1]) in tool_turns]
            chosen += [(c, x) for x in fails + rng.sample(passes, min(NIF_PASSES, len(passes)))]
        else:
            chosen += [(c, x) for x in items]
    have = {(x[0], x[1], c) for c, x in chosen}
    chosen += [(c, x) for c, items in pool.items() for x in items
               if (x[0], x[1], c) in BORDERLINE and (x[0], x[1], c) not in have]
    by_check = defaultdict(list)
    for c, x in chosen:
        by_check[c].append(x)
    rows = []
    for c, items in by_check.items():
        items.sort(key=lambda x: label_order_key(x[0], x[1], c))
        for pos, (conv, turn, verdict, reason) in enumerate(items):
            rows.append({"conv_id": conv, "turn": turn, "check": c, "judge_verdict": verdict,
                         "judge_reason": reason, "half": half_for(pos)})
    rows.sort(key=lambda r: (r["conv_id"], r["turn"], r["check"]))     # grouped by turn for reading
    for i, r in enumerate(rows, start=1):
        r["label_id"] = f"H{i:02d}"
    return rows


# ---------------------------------------------------------------------------
# Writing the files
# ---------------------------------------------------------------------------

def check_parts(section: str) -> dict[str, str]:
    """The Question / Pass if / Fail if text of a rubric check section."""
    out = {}
    for key in ("Question", "Pass if", "Fail if"):
        m = re.search(rf"^{key}:(.*?)(?=^(?:Question|Pass if|Fail if|Examples):|\Z)", section, flags=re.MULTILINE | re.DOTALL)
        out[key] = " ".join(m.group(1).split()) if m else ""
    return out


def build(run_dir: Path, out_dir: Path = LABELS_DIR) -> dict:
    """Write the blind label sheet, the context pack and the key for one judged run."""
    judge = json.loads((run_dir / "judge.json").read_text(encoding="utf-8"))
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    convs = {c["conv_id"]: c for c in golden["conversations"]}
    records = {r["conv_id"]: r for r in load_records(run_dir)}
    _, rubric_checks, rubric_fp = load_rubric()
    if judge["meta"]["rubric_fp"] != rubric_fp:
        raise SystemExit(f"judge.json was made with rubric {judge['meta']['rubric_fp']}, the rubric is now "
                         f"{rubric_fp}: judge the run again first")
    rules = spec_rules()
    tool_turns = {(cid, i) for cid, r in records.items() for i, t in enumerate(r["turns"], start=1) if t["tool_calls"]}
    excluded = rubric_example_turns(run_dir)
    rows = choose_sample(judge, excluded, tool_turns)

    out_dir.mkdir(parents=True, exist_ok=True)
    run = run_dir.name
    labels_path, key_path, pack_path = (out_dir / f"{run}_labels.csv", out_dir / f"{run}_labels_key.csv",
                                        out_dir / f"{run}_label_pack.md")
    if labels_path.exists():
        raise SystemExit(f"{labels_path} already exists; not overwriting labels. Move it first to rebuild.")

    with labels_path.open("w", newline="", encoding="utf-8-sig") as f:          # utf-8-sig: Excel shows € correctly
        w = csv.writer(f)
        w.writerow(["label_id", "conv_id", "turn", "check", "question", "pass_if", "fail_if", "reply",
                     "human_label", "human_notes"])
        for r in rows:
            p = check_parts(rubric_checks[r["check"]])
            reply = records[r["conv_id"]]["turns"][r["turn"] - 1]["reply"]
            w.writerow([r["label_id"], r["conv_id"], r["turn"], r["check"], p["Question"], p["Pass if"],
                        p["Fail if"], reply, "", ""])
    with key_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["label_id", "conv_id", "turn", "check", "half", "judge_verdict", "judge_reason", "rubric_fp"])
        for r in rows:
            w.writerow([r["label_id"], r["conv_id"], r["turn"], r["check"], r["half"], r["judge_verdict"],
                        r["judge_reason"], rubric_fp])

    # The context pack: for each turn, exactly what the judge was shown, then the label IDs to fill in.
    by_turn = defaultdict(list)
    for r in rows:
        by_turn[(r["conv_id"], r["turn"])].append(r)
    md = [f"# Label pack: run {run}", "",
          "For each turn below: read the packet (what the judge saw), then for each label ID",
          "write pass or fail in the human_label column of the labels CSV, judging against the",
          "check's question and its pass/fail rules (in the CSV and at the end of this file).",
          "Judge only the reply on that turn. The judge's verdicts are not shown anywhere here.", ""]
    for (conv, turn), rs in sorted(by_turn.items()):
        rec = records[conv]
        gt = convs[conv]["turns"][turn - 1]
        history = [{"member": t["user"], "assistant": t["reply"]} for t in rec["turns"][:turn - 1]]
        checks = sorted({r["check"] for r in rs})
        packet = render_packet(build_packet(gt, history, rec["turns"][turn - 1]["reply"],
                                            evidence(rec["turns"], turn), checks, rubric_checks, rules,
                                            member_id=convs[conv]["member_id"]))
        packet = packet.split("\nCHECKS TO ANSWER")[0]
        md += [f"## {conv} turn {turn}", "", "Labels: " + ", ".join(f"{r['label_id']} `{r['check']}`" for r in rs),
               "", "```text", packet, "```", ""]
    md += ["# The checks", ""]
    for c in sorted({r["check"] for r in rows}):
        md += [rubric_checks[c], ""]
    pack_path.write_text("\n".join(md), encoding="utf-8")
    return {"rows": rows, "excluded": sorted(excluded), "files": [labels_path, pack_path, key_path]}


def rekey(key: list[dict], judge: dict) -> list[dict]:
    """The key with every judge verdict and reason taken from a newer judge.json.

    Label IDs, turns, checks and halves are unchanged. Stops if a labelled
    turn-check is missing from the new judging (for example a --limit run)."""
    verdicts = {(t["conv_id"], t["turn"], c): v for t in judge["turns"] for c, v in t["verdicts"].items()}
    fp = judge["meta"]["rubric_fp"]
    out = []
    for k in key:
        v = verdicts.get((k["conv_id"], int(k["turn"]), k["check"]))
        if v is None:
            raise SystemExit(f"{k['label_id']} ({k['conv_id']} t{k['turn']} {k['check']}) is not in judge.json: "
                             "judge the whole run first")
        out.append({**k, "judge_verdict": v["verdict"], "judge_reason": v["reason"], "rubric_fp": fp})
    return out


KEY_FIELDS = ["label_id", "conv_id", "turn", "check", "half", "judge_verdict", "judge_reason", "rubric_fp"]


# ---------------------------------------------------------------------------
# Agreement
# ---------------------------------------------------------------------------

def read_labels(path: Path) -> dict[str, dict]:
    """The filled-in labels, by label ID. Accepts a file re-saved by Excel."""
    for enc in ("utf-8-sig", "cp1252"):
        try:
            with path.open(encoding=enc, newline="") as f:
                return {r["label_id"]: r for r in csv.DictReader(f)}
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"cannot read {path}")


def agreement(labels: dict[str, dict], key: list[dict]) -> dict:
    """Compare human labels with the judge: overall, per half and per check.

    A label must be pass or fail; anything else (blank, typo) stops the report, so
    a missing label is never counted as agreement."""
    bad = [k["label_id"] for k in key
           if labels.get(k["label_id"], {}).get("human_label", "").strip().lower() not in ("pass", "fail")]
    if bad:
        raise SystemExit(f"labels missing or not pass/fail: {', '.join(bad)}")
    rows = []
    for k in key:
        human = labels[k["label_id"]]["human_label"].strip().lower()
        rows.append({**k, "human": human, "notes": labels[k["label_id"]].get("human_notes", ""),
                     "agree": human == k["judge_verdict"]})

    def score(rs):
        n = len(rs)
        return {"n": n, "agree": sum(r["agree"] for r in rs), "rate": round(sum(r["agree"] for r in rs) / n, 3) if n else None,
                "judge_fail_human_pass": sum(r["judge_verdict"] == "fail" and r["human"] == "pass" for r in rs),
                "judge_pass_human_fail": sum(r["judge_verdict"] == "pass" and r["human"] == "fail" for r in rs)}

    out = {"overall": score(rows), "tune": score([r for r in rows if r["half"] == "tune"]),
           "held_out": score([r for r in rows if r["half"] == "held_out"]), "per_check": {}, "rows": rows}
    for c in sorted({r["check"] for r in rows}):
        held = [r for r in rows if r["check"] == c and r["half"] == "held_out"]
        s = score(held)
        s["status"] = ("indicative only (fewer than 5 held-out labels)" if s["n"] < MIN_HELD_OUT else
                       "meets target" if s["rate"] >= TARGET_PER_CHECK else "below target")
        s["all_labels"] = score([r for r in rows if r["check"] == c])
        out["per_check"][c] = s
    out["held_out"]["meets_overall_target"] = (out["held_out"]["rate"] or 0) >= TARGET_OVERALL
    return out


def print_agreement(res: dict, show_held_out: bool) -> None:
    def line(name, s):
        return f"  {name:36} {s['agree']:>3}/{s['n']:<3} {s['rate']!s:>6}   judge stricter {s['judge_fail_human_pass']}, " \
               f"judge looser {s['judge_pass_human_fail']}"
    print("Agreement between the judge and the human labels")
    print(line("tune half (may be used for tuning)", res["tune"]))
    print(line("HELD-OUT half (the reported figure)", res["held_out"]) +
          f"   target {TARGET_OVERALL:.0%}: {'met' if res['held_out']['meets_overall_target'] else 'not met'}")
    print(line("all labels", res["overall"]))
    print("\n  per check, held-out half:")
    for c, s in res["per_check"].items():
        print(f"    {c:36} {s['agree']}/{s['n']}  {s['status']}")
    print("\n  Disagreements in the tune half (use these to improve the rubric):")
    for r in res["rows"]:
        if not r["agree"] and (r["half"] == "tune" or show_held_out):
            print(f"    {r['label_id']} [{r['half']}] {r['conv_id']} t{r['turn']} {r['check']}: judge {r['judge_verdict']}, "
                  f"you {r['human']}.  Judge: {r['judge_reason']}  You: {r['notes']}")
    if not show_held_out:
        n = res["held_out"]["n"] - res["held_out"]["agree"]
        print(f"\n  ({n} held-out disagreement(s) not shown, so the rubric is not tuned to them.)")


def main(argv=None) -> int:
    """Entry point for `python -m chatbot.labels`."""
    ap = argparse.ArgumentParser(description="Blind human labels for the M5 judge.")
    ap.add_argument("action", choices=["build", "agree", "rekey"])
    ap.add_argument("run_dir", help="results/chatbot/<run_id> (must have judge.json)")
    ap.add_argument("--show-held-out", action="store_true", help="also list held-out disagreements")
    a = ap.parse_args(argv)
    run_dir = Path(a.run_dir)
    if a.action == "build":
        res = build(run_dir)
        rows = res["rows"]
        n = defaultdict(int)
        for r in rows:
            n[r["check"]] += 1
        print(f"{len(rows)} labels over {len({(r['conv_id'], r['turn']) for r in rows})} turns "
              f"({sum(r['half'] == 'held_out' for r in rows)} held out); rubric example turns left out: "
              f"{', '.join(f'{c} t{t}' for c, t in res['excluded'])}")
        for c in sorted(n):
            print(f"  {c:36} {n[c]}")
        for f in res["files"]:
            print(f"Wrote {f}")
        return 0
    run = run_dir.name
    key_path = LABELS_DIR / f"{run}_labels_key.csv"
    with key_path.open(encoding="utf-8", newline="") as f:
        key = list(csv.DictReader(f))
    judge_fp = json.loads((run_dir / "judge.json").read_text(encoding="utf-8"))["meta"]["rubric_fp"]
    if a.action == "rekey":
        judge = json.loads((run_dir / "judge.json").read_text(encoding="utf-8"))
        old_fp = key[0]["rubric_fp"]
        if old_fp == judge_fp:
            print(f"Key already matches rubric {judge_fp}; nothing to do.")
            return 0
        new = rekey(key, judge)
        key_path.rename(LABELS_DIR / f"{run}_labels_key_{old_fp}.csv")         # keep the old key
        with key_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=KEY_FIELDS)
            w.writeheader()
            w.writerows(new)
        changed = sum(o["judge_verdict"] != n["judge_verdict"] for o, n in zip(key, new))
        print(f"Key refreshed from rubric {old_fp} to {judge_fp}: {changed} judge verdict(s) changed "
              f"(not shown, as some may be held out). Old key kept as {run}_labels_key_{old_fp}.csv")
        return 0
    if key[0]["rubric_fp"] != judge_fp:
        raise SystemExit(f"the key is for rubric {key[0]['rubric_fp']} but judge.json is rubric {judge_fp}: "
                         "run `python -m chatbot.labels rekey` first")
    print(f"Rubric {judge_fp}")
    res = agreement(read_labels(LABELS_DIR / f"{run}_labels.csv"), key)
    (LABELS_DIR / f"{run}_agreement.json").write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    print_agreement(res, a.show_held_out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
