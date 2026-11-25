"""report.py: one self-contained HTML page per harness run (M7 step 6).

What the page shows, in reading order (overview first, then the detail; v3 order):
  1. Headline figures: cases, cases with a fail or a warning, ACs with no verified test,
     checklist suggestions and questions for the product owner, judge cost and time.
  2. Stories at a glance: one row per story, linked to its sections below.
  3. Flagged cases first: every case with a fail or a warning, worst first, each with its
     messages and (click to open) the case itself. Clean cases are listed after, folded.
  4. Coverage map per AC: for each acceptance criterion, the cases that claim it, the ones the
     judge verified (judged correct AND really testing it), the technique mix (positive /
     negative / boundary) and any flags (no test, not verified, boundary hint).
  5. Checklist: the settings used (every excluded item named), a matrix of every idea against
     every story (covered / not covered / AC gap / not raised / excluded), questions for the
     product owner and suggestions for the test cases, repeats grouped.
  6. Findings by check: which kinds of problem dominate (a bar chart).
  7. Duplicate groups (judge).
  8. Steps per case: how many steps the cases have (a chart and a table).
  9. Glossary (harness/glossary.toml): every check name, status and column heading on the page
     links to its entry (report.html#g-<key>), and shows the definition on hover.

The page loads nothing from the internet: it opens from disk in any browser, can be attached
to an email, and follows the reader's light or dark setting. A few lines of script filter the
flagged cases by story, check or text; without script the page still shows everything.

Written automatically by python -m harness.check (report.html in the run folder). To build it
for an earlier run without calling the model again (free):
    python -m harness.report --run results/harness/<run folder> --stories <stories file> --cases <cases file>

Change history:
  2026-11-24  v1  first version (M7 step 6). Kept as results/harness/20261124T171442Z/report_v1.html.
  2026-11-24  v2  Roger's review: glossary with linkable terms, checklist matrix, findings-by-check
                  chart, severity bar per story, filter for the flagged cases, sticky navigation.
  2026-11-25  v3  Roger's review: total ACs in the headline; all charts together near the top
                  (Overview), the findings bars coloured by level and clickable (they filter the
                  flagged cases); coverage map says which claiming cases are not verified and why;
                  checklist ideas in the glossary; over-claim findings carry the judge's reason.
  2026-11-25  v4  checklist ideas shown by their title and description (checklist.toml v4);
                  rebuilt reports of earlier runs take them from the current checklist.
"""

from __future__ import annotations

import argparse
import csv
import json
import tomllib
from collections import Counter
from html import escape
from pathlib import Path

from harness.checklist import load_checklist
from harness.contract import Finding, actions, case_key, load_cases, load_stories
from harness.judge import duplicate_groups

SEVERITY = {"fail": 0, "warn": 1}
STEP_BUCKETS = ["1", "2", "3", "4", "5+"]
GLOSSARY_PATH = Path(__file__).resolve().parent / "glossary.toml"
# check name (or status) on the page -> glossary key
TERM_OF = {"verdict": "verdict", "atomic": "atomic", "concrete": "concrete", "duplicate": "duplicate",
           "over_claim": "over_claim", "title_clear": "title_clear", "ac_unverified": "ac_unverified",
           "ac_no_tests": "ac_no_tests", "no_ac_linked": "ac_no_tests", "boundary_hint": "boundary_hint",
           "schema": "schema", "unknown_ac": "unknown_ac", "vague_steps": "vague", "vague_expected": "vague",
           "repeated_expected": "vague", "generic_title": "generic_title", "placeholders": "generic_title",
           "fail": "fail", "warn": "warn", "suggestion": "suggestion", "question": "question", "info": "info",
           "covered": "covered", "not_covered": "covered", "ac_gap": "ac_gap", "not_raised": "not_raised",
           "excluded": "excluded", "every_story": "check_setting", "when_raised": "check_setting", "off": "excluded"}
# checklist matrix: status -> (letter in the cell, css class, words for the legend and tooltip)
MATRIX = {"covered": ("C", "ok", "covered"), "not_covered": ("N", "warn", "not covered (suggestion)"),
          "ac_gap": ("Q", "question", "AC gap (question for the PO)"), "missing": ("?", "warn", "not answered"),
          "defined": ("D", "info", "defined by an AC (no cases yet)"), "every_story": ("E", "info", "to check in every story"),
          "not_raised": ("·", "none", "not raised by the story"), "excluded": ("X", "off", "excluded (check = off)")}


def load_glossary(path: Path = GLOSSARY_PATH) -> dict[str, dict]:
    """The glossary entries by key, in file order: {key: {term, group, definition}}."""
    with open(path, "rb") as f:
        return {t["key"]: t for t in tomllib.load(f).get("term", [])}


GLOSSARY = load_glossary()


# --- small helpers ----------------------------------------------------------------
def _e(text) -> str:
    """Text made safe to put inside HTML."""
    return escape(str(text if text is not None else ""))


def _term(label: str, name: str) -> str:
    """The label linked to its glossary entry, with the definition as a hover tooltip (plain text if unknown)."""
    g = GLOSSARY.get(TERM_OF.get(name, name))
    if not g:
        return _e(label)
    return f'<a class="term" href="#g-{_e(g["key"])}" title="{_e(g["definition"])}">{_e(label)}</a>'


def _chip(label: str, level: str, name: str | None = None) -> str:
    """A small labelled badge; the level (fail, warn, ok, info) sets its colour, the label says it in words.
    With a name (check or status), the badge links to its glossary entry and shows the definition on hover."""
    g = GLOSSARY.get(TERM_OF.get(name or label, name or label))
    if g:
        return (f'<a class="chip {level}" href="#g-{_e(g["key"])}" title="{_e(g["definition"])}">{_e(label)}</a>')
    return f'<span class="chip {level}">{_e(label)}</span>'


def _marks(records: dict, sid: str) -> dict[str, dict]:
    """The case judge's marks for one story, by case ID ({} when the judge did not run)."""
    call = (records.get(sid) or {}).get("cases_call") or {}
    return {m.get("case_id"): m for m in (call.get("parsed") or {}).get("cases", [])}


# --- the numbers behind the page --------------------------------------------------
def coverage_rows(story: dict, cases: list[dict], findings: list[Finding], records: dict) -> list[dict]:
    """One row per AC: {ac_id, text, claimed, verified, techniques, flags}.
    claimed   cases whose covers list names the AC
    verified  of those, cases the judge marked correct with a supported claim on the AC
    techniques the judge's technique label (or the case's own) for the claiming cases"""
    sid, marks = story["story_id"], _marks(records, story["story_id"])
    keyed = [(case_key(c, n), c) for n, c in enumerate(cases, start=1) if isinstance(c, dict)]
    story_flags = [f for f in findings if f.story_id == sid and not f.case_id]
    rows = []
    for ac in story["acceptance_criteria"]:
        aid = ac["ac_id"]
        claimed = [cid for cid, c in keyed if aid in (c.get("covers") or [])]
        verified = [cid for cid in claimed if marks.get(cid, {}).get("verdict") == "correct"
                    and any(cl.get("ac_id") == aid and cl.get("supported") for cl in marks[cid].get("claims", []))]
        tech = Counter((marks.get(cid, {}).get("technique") or dict(keyed)[cid].get("technique") or "unlabelled")
                       for cid in claimed)
        flags = [f for f in story_flags if f.check in ("ac_no_tests", "ac_unverified", "boundary_hint")
                 and (f.message.startswith(aid + " ") or f.message.startswith(aid + ":"))]
        why_not = {}
        for cid in claimed:
            if cid in verified or not marks.get(cid):
                continue
            m = marks[cid]
            failed = m.get("verdict") in ("incorrect", "not_in_basis")
            over = any(cl.get("ac_id") == aid and not cl.get("supported") for cl in m.get("claims", []))
            why_not[cid] = " and ".join([w for w, on in (("fail", failed), ("over-claim", over)) if on]) or "not verified"
        rows.append({"ac_id": aid, "text": ac["text"], "claimed": claimed, "verified": verified,
                     "not_verified": why_not, "techniques": tech, "flags": flags})
    return rows


def step_counts(groups: dict) -> Counter:
    """How many cases have 1, 2, 3, 4 or 5+ steps (all stories together)."""
    out = Counter()
    for cases in groups.values():
        for c in cases:
            if isinstance(c, dict):
                n = len(actions(c))
                out["5+" if n >= 5 else str(max(n, 1))] += 1
    return out


# --- the chart --------------------------------------------------------------------
def steps_chart(counts: Counter) -> str:
    """A small bar chart of cases by number of steps (inline SVG, one series, one colour).
    Each bar has a hover tooltip and the value above it; the same numbers are in the table below."""
    total = sum(counts.values()) or 1
    top = max([counts[b] for b in STEP_BUCKETS] + [1])
    w, h, left, bottom, bar = 420, 210, 36, 40, 44
    gap = (w - left - bar * len(STEP_BUCKETS)) / len(STEP_BUCKETS)
    parts = [f'<svg class="chart" viewBox="0 0 {w} {h}" role="img" aria-labelledby="steps-title">',
             '<title id="steps-title">Test cases by number of steps</title>']
    for t in range(0, 5):                                           # recessive grid
        y = h - bottom - (h - bottom - 16) * t / 4
        parts.append(f'<line class="grid" x1="{left}" x2="{w}" y1="{y:.1f}" y2="{y:.1f}"/>'
                     f'<text class="axis" x="{left - 6}" y="{y + 4:.1f}" text-anchor="end">{round(top * t / 4)}</text>')
    for i, b in enumerate(STEP_BUCKETS):
        n = counts[b]
        bh = (h - bottom - 16) * n / top
        x, y = left + gap / 2 + i * (bar + gap), h - bottom - bh
        r = min(4, bh / 2)
        path = (f"M{x:.1f},{h - bottom} V{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} "
                f"H{x + bar - r:.1f} Q{x + bar:.1f},{y:.1f} {x + bar:.1f},{y + r:.1f} V{h - bottom} Z") if n else ""
        parts.append(f'<g class="bar"><title>{b} step{"s" if b != "1" else ""}: {n} cases ({100 * n / total:.0f}%)</title>'
                     + (f'<path d="{path}"/>' if n else "")
                     + f'<rect class="hit" x="{x - gap / 2:.1f}" y="16" width="{bar + gap:.1f}" height="{h - bottom - 16}"/>'
                     + f'<text class="value" x="{x + bar / 2:.1f}" y="{y - 5:.1f}" text-anchor="middle">{n}</text>'
                     + f'<text class="axis" x="{x + bar / 2:.1f}" y="{h - bottom + 16}" text-anchor="middle">{b}</text></g>')
    parts.append(f'<line class="base" x1="{left}" x2="{w}" y1="{h - bottom}" y2="{h - bottom}"/>'
                 f'<text class="axis" x="{(left + w) / 2:.0f}" y="{h - 2}" text-anchor="middle">number of steps</text></svg>')
    return "".join(parts)


def findings_chart(findings: list[Finding]) -> str:
    """Horizontal bars: how many fails and warnings each check raised, largest first (inline SVG).
    Each bar is its own row, coloured by its level (fail or warning; status colours) with the level
    also written next to the check name, so colour never carries it alone. Clicking a bar filters
    the flagged cases to that check (story-level checks jump to the coverage map)."""
    counts = Counter((f.check, f.level) for f in findings if f.level in SEVERITY)
    if not counts:
        return '<p class="muted">No fails or warnings.</p>'
    items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    top = max(n for _, n in items)
    w, row, left, right = 640, 26, 190, 40
    h = row * len(items) + 8
    parts = [f'<svg class="chart wide" viewBox="0 0 {w} {h}" role="img" aria-labelledby="fbc-title">',
             '<title id="fbc-title">Fails and warnings by check</title>']
    for i, ((check, level), n) in enumerate(items):
        y = 4 + i * row
        bw = max(2.0, (w - left - right) * n / top)
        r = min(4, bw / 2)
        x0 = left
        path = (f"M{x0},{y + 4} H{x0 + bw - r:.1f} Q{x0 + bw:.1f},{y + 4} {x0 + bw:.1f},{y + 4 + r} "
                f"V{y + row - 8 - r} Q{x0 + bw:.1f},{y + row - 8} {x0 + bw - r:.1f},{y + row - 8} H{x0} Z")
        word = "fail" if level == "fail" else "warning"
        parts.append(f'<g class="bar {level}" data-check="{_e(check)}" data-level="{level}" tabindex="0" role="link">'
                     f'<title>{_e(check)} ({word}): {n}. Click to see these cases.</title>'
                     f'<rect class="hit" x="0" y="{y}" width="{w}" height="{row}"/>'
                     f'<text class="axis label" x="{left - 8}" y="{y + row / 2 + 2}" text-anchor="end">{_e(check)} · {word}</text>'
                     f'<path d="{path}"/><text class="value" x="{x0 + bw + 6:.1f}" y="{y + row / 2 + 2}">{n}</text></g>')
    parts.append(f'<line class="base" x1="{left}" x2="{left}" y1="0" y2="{h}"/></svg>')
    return "".join(parts)


def severity_bar(fail: int, warn: int, clean: int) -> str:
    """A thin bar for one story split into cases with a fail, with warnings only, and clean
    (status colours, 2px gaps, a tooltip with the numbers; the numbers are also in the table)."""
    total = fail + warn + clean
    if not total:
        return ""
    w, h, x, parts = 140, 10, 0.0, []
    for n, cls, word in ((fail, "sfail", "with a fail"), (warn, "swarn", "warnings only"), (clean, "sclean", "clean")):
        if n:
            bw = w * n / total
            parts.append(f'<rect class="{cls}" x="{x:.1f}" y="0" width="{max(bw - 2, 1):.1f}" height="{h}" rx="2">'
                         f'<title>{n} {word}</title></rect>')
            x += bw
    return f'<svg class="sev" viewBox="0 0 {w} {h}" role="img" aria-label="{fail} with a fail, {warn} warnings only, {clean} clean">{"".join(parts)}</svg>'


# --- the page ---------------------------------------------------------------------
CSS = """
:root{color-scheme:light;--bg:#fcfcfb;--card:#ffffff;--ink:#1f1f1d;--ink2:#5c5b55;--line:#e4e2dc;
--series:#2a78d6;--fail-bg:#fbe9e7;--fail:#a1260d;--warn-bg:#fdf3dc;--warn:#7a4f00;--ok-bg:#e6f4ea;--ok:#1d6b34;
--info-bg:#e8f0fb;--info:#1c4f8f;--fail-bar:#d0453a;--warn-bar:#e0a020;--ok-bar:#4f9d69}
@media (prefers-color-scheme:dark){:root{color-scheme:dark;--bg:#1a1a19;--card:#232321;--ink:#f0efec;--ink2:#c3c2b7;
--line:#3a3a37;--series:#3987e5;--fail-bg:#4a1f18;--fail:#ffb4a3;--warn-bg:#47360f;--warn:#ffd98a;--ok-bg:#163a22;
--ok:#9be0ae;--info-bg:#1b3150;--info:#a9cbf5;--fail-bar:#e0645a;--warn-bar:#d9a43a;--ok-bar:#5fae7a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1100px;margin:0 auto;padding:28px 20px 60px}h1{font-size:22px;font-weight:600;margin:0 0 4px}
h2{font-size:18px;font-weight:600;margin:36px 0 10px;padding-top:8px;border-top:1px solid var(--line)}h3{font-size:15px;margin:18px 0 6px}
p.sub,.muted{color:var(--ink2)}a{color:var(--series)}nav a{margin-right:14px;font-size:14px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:18px 0}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.tile .n{font-size:26px;font-weight:600;line-height:1.2}.tile .l{font-size:13px;color:var(--ink2)}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden;font-size:14px}
th,td{text-align:left;vertical-align:top;padding:7px 10px;border-bottom:1px solid var(--line)}th{font-weight:600;color:var(--ink2);font-size:13px}
tr:last-child td{border-bottom:none}td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.chip{display:inline-block;border-radius:6px;padding:0 7px;margin:1px 3px 1px 0;font-size:12px;font-weight:500;white-space:nowrap}
.chip.fail{background:var(--fail-bg);color:var(--fail)}.chip.warn{background:var(--warn-bg);color:var(--warn)}
.chip.ok{background:var(--ok-bg);color:var(--ok)}.chip.info,.chip.question,.chip.suggestion{background:var(--info-bg);color:var(--info)}
details{margin:4px 0}summary{cursor:pointer;color:var(--series)}ul.msgs{margin:4px 0 0;padding-left:18px}ul.msgs li{margin:2px 0}
pre.case{white-space:pre-wrap;background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:8px 10px;margin:6px 0;font:13px/1.5 ui-monospace,Consolas,monospace}
.chart{width:100%;max-width:460px;height:auto}.chart .grid{stroke:var(--line);stroke-width:1}.chart .base{stroke:var(--ink2);stroke-width:1}
.chart .axis{fill:var(--ink2);font-size:11px}.chart .value{fill:var(--ink);font-size:11px}.chart path{fill:var(--series)}
.chart .hit{fill:transparent}.chart .bar:hover path{opacity:.8}
h2,h3,dt{scroll-margin-top:56px}nav{position:sticky;top:0;z-index:5;background:var(--bg);padding:8px 0;border-bottom:1px solid var(--line)}
a.term{color:inherit;text-decoration:underline dotted;text-underline-offset:3px}a.chip{text-decoration:none}
.chart.wide{max-width:680px}.chart .bar.fail path{fill:var(--fail-bar)}.chart .bar.warn path{fill:var(--warn-bar)}
.chart .bar[data-check]{cursor:pointer}.chart .bar[data-check]:hover .label{text-decoration:underline}.chart .label{fill:var(--ink)}
.sev{width:140px;height:10px;display:block;margin-top:4px}.sev .sfail{fill:var(--fail-bar)}.sev .swarn{fill:var(--warn-bar)}.sev .sclean{fill:var(--ok-bar)}
.legend{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:13px;color:var(--ink2);margin:6px 0 10px}
table.matrix{width:auto;font-size:13px}table.matrix th,table.matrix td{padding:3px 6px;text-align:center}
table.matrix td.idea,table.matrix th.idea{text-align:left;white-space:nowrap}
.cell{display:inline-block;min-width:22px;border-radius:5px;font-weight:600;font-size:12px;line-height:20px}
.cell.ok{background:var(--ok-bg);color:var(--ok)}.cell.warn{background:var(--warn-bg);color:var(--warn)}
.cell.question,.cell.info{background:var(--info-bg);color:var(--info)}.cell.none{color:var(--ink2)}
.cell.off{background:var(--line);color:var(--ink2)}
.filters{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:0 0 10px;font-size:14px}
.filters select,.filters input{font:inherit;padding:4px 8px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--ink)}
dl.gloss dt{font-weight:600;margin-top:10px}dl.gloss dd{margin:2px 0 0 0;color:var(--ink2)}dl.gloss dt:target,dl.gloss dt:target+dd{background:var(--info-bg)}
.two{display:grid;grid-template-columns:minmax(0,460px) minmax(0,1fr);gap:24px;align-items:start}@media(max-width:760px){.two{grid-template-columns:1fr}}
"""


def _headline(result: dict) -> str:
    """The figures at the top of the page."""
    f, j = result["findings"], result.get("judge") or {}
    n_cases = sum(len(c) for c in result["groups"].values())
    failed = {(x.story_id, x.case_id) for x in f if x.case_id and x.level == "fail"}
    warned = {(x.story_id, x.case_id) for x in f if x.case_id and x.level == "warn"} - failed
    n_acs = sum(len(s["acceptance_criteria"]) for s in result["stories"].values())
    tiles = [(n_cases, "test cases"), (len(result["stories"]), "stories"), (n_acs, "acceptance criteria"),
             (len(failed), "cases with a fail"), (len(warned), "cases with warnings only"),
             (sum(x.check == "ac_unverified" for x in f) if j else "–", "ACs with no verified test"),
             (sum(x.level == "suggestion" for x in f) if j else "–", "checklist suggestions"),
             (sum(x.level == "question" for x in f) if j else "–", "questions for the PO")]
    cost = (f"Judge {j.get('model')}: ${j.get('cost_usd', 0):.2f}, {j.get('seconds', '?')} s" if j.get("mode") == "live"
            else "Judge marks reused from a Day 4 score file" if j else "No judge (free checks only)")
    return ('<div class="tiles">' + "".join(f'<div class="tile"><div class="n">{_e(n)}</div><div class="l">{_e(l)}</div></div>'
                                            for n, l in tiles) + f'</div><p class="muted">{_e(cost)}. '
            'fail = the case breaks the input contract or the judge found it wrong; warning = worth a human look; '
            'suggestion and question = ideas from the checklist (never a fail).</p>')


def _stories_table(result: dict) -> str:
    """One row per story with its counts, linked to its coverage section."""
    f = result["findings"]
    rows = []
    for sid, story in result["stories"].items():
        fs = [x for x in f if x.story_id == sid]
        cases = result["groups"].get(sid, [])
        fail = len({x.case_id for x in fs if x.case_id and x.level == "fail"})
        warn = len({x.case_id for x in fs if x.case_id and x.level == "warn"})
        warn_only = len({x.case_id for x in fs if x.case_id and x.level == "warn"}
                        - {x.case_id for x in fs if x.case_id and x.level == "fail"})
        bar = severity_bar(fail, warn_only, max(len(cases) - fail - warn_only, 0))
        rows.append(f'<tr><td><a href="#cov-{_e(sid)}">{_e(sid)}</a></td><td>{_e(story["title"])}{bar}</td>'
                    f'<td class="num">{len(cases)}</td><td class="num">{fail}</td><td class="num">{warn}</td>'
                    f'<td class="num">{sum(x.check == "ac_unverified" for x in fs)}</td>'
                    f'<td class="num">{sum(x.level == "suggestion" for x in fs)}</td>'
                    f'<td class="num">{sum(x.level == "question" for x in fs)}</td></tr>')
    legend = ('<div class="legend">Bar under each title: '
              '<span><svg width="10" height="10"><rect class="sfail" width="10" height="10" rx="2" style="fill:var(--fail-bar)"/></svg> cases with a fail</span>'
              '<span><svg width="10" height="10"><rect width="10" height="10" rx="2" style="fill:var(--warn-bar)"/></svg> warnings only</span>'
              '<span><svg width="10" height="10"><rect width="10" height="10" rx="2" style="fill:var(--ok-bar)"/></svg> clean</span></div>')
    return (legend + f'<table><tr><th>Story</th><th>Title</th><th class="num">Cases</th><th class="num">With a {_term("fail", "fail")}</th>'
            f'<th class="num">With a {_term("warning", "warn")}</th><th class="num">{_term("ACs not verified", "ac_unverified")}</th>'
            f'<th class="num">{_term("Suggestions", "suggestion")}</th><th class="num">{_term("PO questions", "question")}</th></tr>'
            + "".join(rows) + "</table>")


def _case_text(c: dict) -> str:
    """The case as a reviewer reads it: title, ACs claimed, preconditions, steps, expected result."""
    steps = []
    for n, s in enumerate(c.get("steps") or [], start=1):
        if isinstance(s, dict):
            steps.append(f"{n}. {s.get('action', '')}" + (f"  -> {s['expected']}" if s.get("expected") else ""))
        else:
            steps.append(f"{n}. {s}")
    return (f"Covers: {', '.join(c.get('covers') or []) or '(none)'}\n"
            f"Preconditions: {' / '.join(c.get('preconditions') or []) or '(none)'}\n"
            f"Steps:\n" + "\n".join(steps) + f"\nExpected: {c.get('expected_result', '')}")


def _with_reason(x: Finding, records: dict) -> Finding:
    """An over-claim finding from a run made before 25 Nov has no reason: add the judge's reason for
    that case from the saved marks, so the reviewer sees why the claim was not supported."""
    if x.check != "over_claim" or ": " in x.message:
        return x
    why = _marks(records, x.story_id).get(x.case_id, {}).get("reason")
    return Finding(x.story_id, x.case_id, x.check, x.level, f"{x.message}: {why}") if why else x


def _flagged(result: dict) -> str:
    """Every case with a fail or a warning, worst first; clean cases folded underneath."""
    records = (result.get("judge") or {}).get("records") or {}
    by_case: dict[tuple, list[Finding]] = {}
    for x in (_with_reason(f, records) for f in result["findings"]):
        if x.case_id and x.level in SEVERITY:
            by_case.setdefault((x.story_id, x.case_id), []).append(x)
    lookup = {(sid, case_key(c, n)): c for sid, cs in result["groups"].items()
              for n, c in enumerate(cs, start=1) if isinstance(c, dict)}
    order = sorted(by_case, key=lambda k: (-sum(x.level == "fail" for x in by_case[k]), -len(by_case[k]), k))
    rows = []
    for k in order:
        fs, c = by_case[k], lookup.get(k, {})
        chips = "".join(_chip(chk, lvl, chk) for chk, lvl in sorted({(x.check, x.level) for x in fs}, key=lambda t: (SEVERITY[t[1]], t[0])))
        msgs = "".join(f"<li><b>{_e(x.check)}</b>: {_e(x.message)}</li>" for x in sorted(fs, key=lambda x: SEVERITY[x.level]))
        level = "fail" if any(x.level == "fail" for x in fs) else "warn"
        rows.append(f'<tr data-story="{_e(k[0])}" data-level="{level}" data-checks=" {_e(" ".join(sorted({x.check for x in fs})))} ">'
                    f'<td>{_e(k[0])}</td><td>{_e(k[1])}</td><td>{_e(c.get("title", ""))}'
                    f'<details><summary>show case</summary><pre class="case">{_e(_case_text(c))}</pre></details></td>'
                    f'<td>{chips}<ul class="msgs">{msgs}</ul></td></tr>')
    clean = [k for k in lookup if k not in by_case]
    clean_list = ", ".join(f"{s} {c}" for s, c in clean) or "none"
    stories = sorted({k[0] for k in order})
    checks = sorted({x.check for fs in by_case.values() for x in fs})
    filters = ('<div class="filters" id="flt">Show: <select id="f-story"><option value="">all stories</option>'
               + "".join(f'<option>{_e(x)}</option>' for x in stories)
               + '</select><select id="f-level"><option value="">fails and warnings</option><option value="fail">cases with a fail</option>'
               '<option value="warn">warnings only</option></select><select id="f-check"><option value="">any check</option>'
               + "".join(f'<option>{_e(x)}</option>' for x in checks)
               + '</select><input id="f-text" type="search" placeholder="search titles and messages"><span id="f-count" class="muted"></span></div>')
    return ((filters + f'<table id="flagged-table"><tr><th>Story</th><th>Case</th><th>Title</th><th>Findings</th></tr>{"".join(rows)}</table>'
             if rows else "<p>No case has a fail or a warning.</p>")
            + f'<details><summary>{len(clean)} cases with no fail or warning</summary><p class="muted">{_e(clean_list)}</p></details>')


def _coverage(result: dict) -> str:
    """The coverage map: one table per story, one row per AC."""
    out, records = [], (result.get("judge") or {}).get("records") or {}
    judged = bool(result.get("judge"))
    for sid, story in result["stories"].items():
        rows = []
        for r in coverage_rows(story, result["groups"].get(sid, []), result["findings"], records):
            tech = " ".join(f"{k} {v}" for k, v in sorted(r["techniques"].items())) or "–"
            if judged:
                ver = _chip(f"{len(r['verified'])} of {len(r['claimed'])} verified", "ok" if r["verified"] else "warn", "verified")
                if r["not_verified"]:
                    ver += ('<br><span class="muted">not verified: '
                            + _e(", ".join(f"{c} ({w})" for c, w in r["not_verified"].items())) + "</span>")
            else:
                ver = "–"
            flags = "".join(_chip(f.check, f.level, f.check) + f'<span class="muted">{_e(f.message.split(" ", 1)[1] if " " in f.message else "")}</span><br>'
                            for f in r["flags"]) or "–"
            rows.append(f'<tr><td><b>{_e(r["ac_id"])}</b></td><td>{_e(r["text"])}</td>'
                        f'<td>{_e(", ".join(r["claimed"]) or "none")}</td><td>{ver}</td>'
                        f'<td>{_e(tech)}</td><td>{flags}</td></tr>')
        out.append(f'<h3 id="cov-{_e(sid)}">{_e(sid)} {_e(story["title"])}</h3><table><tr><th>AC</th><th>Criterion</th>'
                   f'<th>Cases claiming it</th><th>{_term("Verified by the judge", "verified")}</th>'
                   f'<th>{_term("Techniques", "technique")}</th><th>Flags</th></tr>'
                   + "".join(rows) + "</table>")
    return "".join(out)


def _checklist(result: dict) -> str:
    """Checklist settings (excluded items named), questions and suggestions, repeats grouped."""
    j = result.get("judge") or {}
    rows = j.get("checklist_rows") or []
    if not rows:
        return '<p class="muted">The checklist did not run.</p>'
    names = {r["item_id"]: r.get("title") or r["name"] for r in rows}      # older runs have no title
    checks = {r["item_id"]: r.get("check", "when_raised") for r in rows}
    off = [f"{i} {names[i]}" for i in names if checks[i] == "off"]
    every = [f"{i} {names[i]}" for i in names if checks[i] == "every_story"]
    fp = (j.get("checklist") or {}).get("fingerprint")
    parts = ["<ul>",
             f'<li>{_chip("excluded", "off", "excluded")} Not checked in any story ({_term("check = off", "check_setting")}): <b>{_e(", ".join(off) or "none")}</b></li>',
             f'<li>Checked in every story\'s test cases (check = every_story): {_e(", ".join(every) or "none")}</li>',
             "<li>All other items: checked when the story raises them.</li>",
             (f"<li class='muted'>Checklist file fingerprint {_e(fp)}</li>" if fp else ""), "</ul>"]
    parts.append('<p class="muted">The matrix of every idea against every story is in the <a href="#overview">Overview</a>.</p>')
    for level, title in (("question", "Questions for the product owner (AC gaps)"),
                         ("suggestion", "Suggestions for the test cases (not covered)")):
        grouped: dict[str, list[Finding]] = {}
        for x in result["findings"]:
            if x.check == "checklist" and x.level == level:
                grouped.setdefault(x.message.split(" ", 1)[0], []).append(x)
        parts.append(f"<h3>{title}</h3>")
        if not grouped:
            parts.append("<p class='muted'>None.</p>")
            continue
        items = []
        for iid, fs in sorted(grouped.items()):
            prefix = f"{iid} {names.get(iid, '')}"
            notes = "".join(f"<li><b>{_e(x.story_id)}</b>: {_e(x.message[len(prefix):].lstrip(' :') if x.message.startswith(prefix) else x.message)}</li>"
                            for x in fs)
            items.append(f'<tr><td><b><a class="term" href="#g-{_e(iid)}">{_e(prefix)}</a></b><br><span class="muted">{len(fs)} stor{"ies" if len(fs) > 1 else "y"}: '
                         f'{_e(", ".join(x.story_id for x in fs))}</span></td><td><ul class="msgs">{notes}</ul></td></tr>')
        parts.append("<table><tr><th>Idea</th><th>Per story</th></tr>" + "".join(items) + "</table>")
    return "".join(parts)


def checklist_matrix(rows: list[dict]) -> str:
    """A grid: one row per checklist idea, one column per story, a letter and colour per status
    (the letter carries the meaning, so the grid works without colour), with totals per idea."""
    stories = list(dict.fromkeys(r["story_id"] for r in rows))
    ideas = list(dict.fromkeys(r["item_id"] for r in rows))
    by = {(r["item_id"], r["story_id"]): r for r in rows}
    head = "".join(f'<th><a href="#cov-{_e(s)}">{_e(s)}</a></th>' for s in stories)
    body = []
    for iid in ideas:
        first = by[(iid, stories[0])]
        cells, tally = [], Counter()
        for sid in stories:
            r = by.get((iid, sid), {})
            st = r.get("status", "not_raised")
            letter, cls, word = MATRIX.get(st, ("?", "warn", st))
            tally[st] += 1
            tip = f"{sid} {iid}: {word}" + (f" - {r.get('note')}" if r.get("note") else "")
            cells.append(f'<td><span class="cell {cls}" title="{_e(tip)}">{letter}</span></td>')
        mark = {"every_story": " (every story)", "off": " (off)"}.get(first.get("check", ""), "")
        label = first.get("title") or first["name"]
        body.append(f'<tr><td class="idea"><a class="term" href="#g-{_e(iid)}" title="{_e(first.get("description") or first.get("question", ""))}">'
                    f'{_e(iid)}</a> {_e(label if len(label) <= 44 else label[:42].rsplit(" ", 1)[0] + "…")}{_e(mark)}</td>{"".join(cells)}'
                    f'<td class="num">{tally["covered"]}</td><td class="num">{tally["not_covered"]}</td><td class="num">{tally["ac_gap"]}</td></tr>')
    legend = '<div class="legend">' + "".join(
        f'<span><span class="cell {cls}">{letter}</span> {_term(word, st)}</span>'
        for st, (letter, cls, word) in MATRIX.items() if st not in ("missing", "defined", "every_story")) + "</div>"
    return (legend + '<div style="overflow-x:auto"><table class="matrix"><tr><th class="idea">Test idea</th>' + head
            + '<th>Covered</th><th>Not covered</th><th>AC gap</th></tr>' + "".join(body) + "</table></div>")


def _findings_by_check(result: dict) -> str:
    """The findings-by-check chart, with a legend and a note on how to read it."""
    legend = ('<div class="legend"><span><svg width="10" height="10"><rect width="10" height="10" rx="2" style="fill:var(--fail-bar)"/></svg> '
              + _term("fail", "fail") + '</span><span><svg width="10" height="10"><rect width="10" height="10" rx="2" style="fill:var(--warn-bar)"/></svg> '
              + _term("warning", "warn") + "</span></div>")
    return ('<p class="muted">Each bar counts the fails or warnings one check raised across all cases. '
            'A long bar is the first thing to raise with the test writer or to fix in the prompt. '
            'Click a bar to see those cases.</p>' + legend + findings_chart(result["findings"]))


def _overview(result: dict) -> str:
    """All the pictures together: findings by check, steps per case, and the checklist matrix."""
    rows = (result.get("judge") or {}).get("checklist_rows") or []
    matrix = ("<h3>Checklist: every test idea against every story</h3>" + checklist_matrix(rows)
              + '<p class="muted">Questions, suggestions and the settings used are in the '
                '<a href="#checklist">Checklist</a> section.</p>') if rows else ""
    return (f"<h3>Findings by check</h3>{_findings_by_check(result)}"
            f"<h3>Steps per case</h3>{_steps(result)}{matrix}")


def _glossary(rows: list[dict] | None = None) -> str:
    """Every glossary term, grouped, each with an anchor other pages and messages can link to, then
    the checklist's test ideas (from the checklist the run used, so the wording always matches)."""
    groups: dict[str, list[dict]] = {}
    for g in GLOSSARY.values():
        groups.setdefault(g["group"], []).append(g)
    ideas = list({r["item_id"]: r for r in (rows or [])}.values())
    if ideas:
        groups["Checklist test ideas"] = [
            {"key": r["item_id"], "term": f'{r["item_id"]} {r.get("title") or r["name"]}',
             "definition": (r.get("description") or r.get("question") or "") + {"every_story": " Checked in every story.",
                                                        "off": " Switched off in this run (excluded)."}.get(r.get("check", ""), "")}
            for r in ideas]
    return ('<p class="muted">Link to a term with report.html#g-&lt;key&gt;, for example #g-atomic. '
            'The wording lives in harness/glossary.toml.</p>'
            + "".join(f"<h3>{_e(grp)}</h3><dl class='gloss'>"
                      + "".join(f'<dt id="g-{_e(t["key"])}">{_e(t["term"])}</dt><dd>{_e(t["definition"])}</dd>' for t in ts)
                      + "</dl>" for grp, ts in groups.items()))


FILTER_JS = """<script>
(function(){var t=document.getElementById('flagged-table');if(!t)return;
var rows=[].slice.call(t.querySelectorAll('tr[data-story]'));
var s=document.getElementById('f-story'),l=document.getElementById('f-level'),c=document.getElementById('f-check'),
x=document.getElementById('f-text'),n=document.getElementById('f-count');
function run(){var q=x.value.toLowerCase(),shown=0;rows.forEach(function(r){
var ok=(!s.value||r.dataset.story===s.value)&&(!l.value||r.dataset.level===l.value)&&
(!c.value||r.dataset.checks.indexOf(' '+c.value+' ')>=0)&&(!q||r.textContent.toLowerCase().indexOf(q)>=0);
r.style.display=ok?'':'none';if(ok)shown++;});n.textContent=shown+' of '+rows.length+' cases';}
[s,l,c].forEach(function(e){e.addEventListener('change',run)});x.addEventListener('input',run);run();
[].slice.call(document.querySelectorAll('.chart .bar[data-check]')).forEach(function(b){
function go(){var k=b.dataset.check,has=[].slice.call(c.options).some(function(o){return o.value===k});
if(has){s.value='';x.value='';c.value=k;l.value=b.dataset.level;run();document.getElementById('flagged').scrollIntoView();}
else{document.getElementById('coverage').scrollIntoView();}}
b.addEventListener('click',go);b.addEventListener('keydown',function(e){if(e.key==='Enter')go();});});})();
</script>"""


def _duplicates(result: dict) -> str:
    """The judge's duplicate groups, per story."""
    groups = duplicate_groups(result["findings"]) if result.get("judge") else {}
    if not groups:
        return '<p class="muted">None found.</p>'
    return "<ul>" + "".join(f"<li><b>{_e(sid)}</b>: " + "; ".join(" = ".join(g) for g in gs) + "</li>"
                            for sid, gs in groups.items()) + "</ul>"


def _steps(result: dict) -> str:
    """The steps-per-case chart with the same numbers as a table beside it."""
    counts = step_counts(result["groups"])
    total = sum(counts.values()) or 1
    table = ("<table><tr><th>Steps</th><th class='num'>Cases</th><th class='num'>Share</th></tr>"
             + "".join(f"<tr><td>{b}</td><td class='num'>{counts[b]}</td><td class='num'>{100 * counts[b] / total:.0f}%</td></tr>"
                       for b in STEP_BUCKETS) + "</table>")
    return f'<div class="two"><div>{steps_chart(counts)}</div><div>{table}</div></div>'


def build_html(result: dict, header: str) -> str:
    """The whole page for one run, as a string."""
    # (anchor, short name for the navigation bar, section heading, content)
    rows = (result.get("judge") or {}).get("checklist_rows") or []
    sections = [("overview", "Overview", "Overview: the pictures", _overview(result)),
                ("flagged", "Flagged cases", "Flagged cases first", _flagged(result)),
                ("coverage", "Coverage", "Coverage map per acceptance criterion", _coverage(result)),
                ("checklist", "Checklist", "Checklist of test ideas", _checklist(result)),
                ("duplicates", "Duplicates", "Duplicate groups (judge)", _duplicates(result)),
                ("glossary", "Glossary", "Glossary", _glossary(rows))]
    nav = '<a href="#stories">Stories</a>' + "".join(f'<a href="#{sid}">{_e(short)}</a>' for sid, short, _, _ in sections)
    body = "".join(f'<h2 id="{sid}">{_e(t)}</h2>{html}' for sid, _, t, html in sections)
    return (f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>Harness check: {_e(header)}</title><style>{CSS}</style></head><body><main>'
            f'<h1>Harness check</h1><p class="sub">{_e(header)}</p><nav>{nav}</nav>{_headline(result)}'
            f'<h2 id="stories">Stories at a glance</h2>{_stories_table(result)}{body}</main>{FILTER_JS}</body></html>')


# --- rebuilding a report for an earlier run (free) --------------------------------
def result_from_folder(run: Path, stories_path: Path, cases_path: Path) -> dict:
    """Rebuild the result of an earlier run from its saved files (findings.csv, checklist.csv,
    judge.json) and the original stories and cases files. No model is called."""
    stories = load_stories(stories_path)
    groups, _ = load_cases(cases_path)
    with open(run / "findings.csv", encoding="utf-8-sig") as f:
        findings = [Finding(r["story_id"], r["case_id"], r["check"], r["level"], r["message"]) for r in csv.DictReader(f)]
    judge = None
    if (run / "judge.json").exists():
        data = json.loads((run / "judge.json").read_text(encoding="utf-8"))
        judge = dict(data["meta"], records=data["stories"], checklist_rows=[])
        if (run / "checklist.csv").exists():
            with open(run / "checklist.csv", encoding="utf-8-sig") as f:
                judge["checklist_rows"] = [dict(r, ac_ids=[x for x in r["ac_ids"].split(", ") if x],
                                                case_ids=[x for x in r["case_ids"].split(", ") if x])
                                           for r in csv.DictReader(f)]
            # runs before 25 Nov saved no title or description: take them from the current checklist
            wording = {i["id"]: i for i in load_checklist()}
            for r in judge["checklist_rows"]:
                if not r.get("title") and r["item_id"] in wording:
                    r["title"], r["description"] = wording[r["item_id"]]["title"], wording[r["item_id"]]["description"]
    return {"stories": stories, "groups": groups, "findings": findings, "rules": {}, "judge": judge}


def main(argv: list[str] | None = None) -> int:
    """Build report.html for an earlier run folder."""
    p = argparse.ArgumentParser(description="Build the HTML report for an earlier harness run (free).")
    p.add_argument("--run", required=True, type=Path, help="the run folder, e.g. results/harness/20261124T171442Z")
    p.add_argument("--stories", required=True, type=Path, help="the stories file the run used")
    p.add_argument("--cases", required=True, type=Path, help="the cases file the run used")
    args = p.parse_args(argv)
    result = result_from_folder(args.run, args.stories, args.cases)
    out = args.run / "report.html"
    out.write_text(build_html(result, f"{args.cases.name} against {args.stories.name}"), encoding="utf-8")
    print(f"saved {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
