"""
images/make_m5_oracle_timeline.py: draws images/m5_oracle_timeline.svg, the history of the M5 oracle.

What it shows
-------------
Every version of datasets/conversations_golden.json (the oracle for the M5 chatbot),
from v1.0 to the latest, with what changed, what exposed the need for the change,
and what kind of change it was:

  fixed the oracle   the bot's reply was right; the oracle was too literal or too narrow
  added coverage     new conversations or turns
  rules and checks   a rule or judge check added or changed, following the spec or rubric

Where the facts come from
-------------------------
The version numbers and dates are read from the "changes" list inside the golden
file, so the picture can't fall behind the real file: if a version is added to the
file without a line below, the script stops and says which one. The short labels,
kinds and triggers are written here (the file's own wording is longer).

  python images/make_m5_oracle_timeline.py

No API calls.

Change history:
  2026-11-10  v1  first version (M5 write-up, task T4).
"""
from __future__ import annotations

import json
import re
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "datasets" / "conversations_golden.json"
OUT = ROOT / "images" / "m5_oracle_timeline.svg"

# version: (kinds, scored conversations, what changed in plain words, an example, what exposed it)
VERSIONS = {
    "1.0": ([], 20, "First version, written from the spec before the bot was built",
            "20 conversations: claim questions, policy questions, mistyped IDs, privacy, a system outage",
            "Written first, as the test basis"),
    "1.1": (["fix", "coverage", "check"], 23, "Expected answers were too literal; three long conversations added",
            "A correct reply failed for mentioning the member's 'sister': the rule bans repeating medical details, not family",
            "First full run: 13 of 20 passed, mostly because of the oracle"),
    "1.2": (["fix", "check"], 23, "More correct wordings accepted; new check that members aren't shown internal codes",
            "The bot told a member: 'The decision code is **WAITING_PERIOD**'",
            "Error analysis of the second run"),
    "1.3": (["coverage", "check"], 26, "New conversations for small talk and for dates the member gives",
            ("Member: 'My cover started on 20 May, so I'll be out of the waiting period by 17 November, won't I?'",
             "Correct answer: no. 17 November is day 181, still inside the 182-day waiting period; cover starts the next day"),
            "Review: also test off-topic remarks and members' own dates"),
    "1.4": (["fix", "check"], 26, "Wordings accepted; a rule clarified",
            "Expected 'not covered'; the bot said 'the plan does not cover acupuncture'",
            "Two more runs"),
    "1.5": (["check"], 26, "New judge check: is something only the member said treated as fact?",
            "'17 November is day 181 of your waiting period', when only the member gave the start date",
            "Writing the judge's rubric"),
    "1.6": (["fix", "coverage"], 28, "A correct refusal no longer has to name the assessor; tests for IDs that can't be corrected",
            "'No decision has been made yet, so I can't say' is right; 'HLH-01A' must not be guessed as HLH-012",
            "Baseline runs; review question about IDs like HLH-01A"),
    "1.7": (["fix"], 28, "Two valid ways to answer allowed",
            ("The member gave an invalid ID, then said 'Sorry, the consultant one'. The test expected the bot to look up her",
             "consultant claim straight away; the bot listed her three claims and asked which one. Both are reasonable, so both now pass"),
            "First run of the new ID test"),
    "1.8": (["fix"], 28, "Plainer wording accepted after the plain-language prompt change",
            ("Told to write in plain words, the bot phrased correct answers differently from the expected words:",
             "'acupuncture is excluded' (expected 'not covered'), 'up to EUR 50 a session' (expected 'limit'), 'no decision yet' (expected 'assessor')"),
            "Prompt experiment 1"),
    "1.9": (["fix"], 28, "Another correct wording accepted",
            "'The claim decision is still pending' is a correct refusal to predict the outcome",
            "Prompt experiment 3"),
    "1.10": (["fix"], 28, "Exact wording no longer required where the tool call proves the behaviour",
             "'Your consultant review claim is under review', after looking up the right claim",
             "Repeat runs of the ID tests"),
}

KINDS = {   # label, fill, stroke, text: the colour ramps used in the other project diagrams
    "fix": ("fixed the oracle", "#FAECE7", "#993C1D", "#712B13"),
    "coverage": ("added coverage", "#E1F5EE", "#0F6E56", "#085041"),
    "check": ("rules and checks", "#EEEDFE", "#534AB7", "#3C3489"),
}
FONT = "Segoe UI, Helvetica, Arial, sans-serif"
INK, MUTED, LINE = "#2C2C2A", "#5F5E5A", "#B4B2A9"


def versions_in_file() -> list[tuple[str, str]]:
    """(version, date) for every entry in the golden file's change history, oldest first."""
    changes = json.loads(GOLDEN.read_text(encoding="utf-8"))["changes"]
    out = []
    for c in changes:
        m = re.match(r"(\d+\.\d+) \((\d{4}-\d{2}-\d{2})\)", c)
        if not m:
            raise SystemExit(f"change entry not in the form '1.2 (2026-11-06): ...': {c[:60]!r}")
        out.append((m.group(1), m.group(2)))
    return sorted(out, key=lambda v: tuple(int(x) for x in v[0].split(".")))


def text(x, y, s, size=12, weight=400, fill=INK, anchor="start"):
    return (f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
            f'text-anchor="{anchor}" dominant-baseline="central">{escape(s)}</text>')


def draw(rows: list[tuple[str, str]]) -> str:
    """The SVG for the given (version, date) rows."""
    W, top, row_h = 1000, 118, 70
    ex_lines = [1 if isinstance(VERSIONS[v][3], str) else len(VERSIONS[v][3]) for v, _ in rows]
    heights = [row_h + 18 * (n - 1) for n in ex_lines]
    H = top + sum(heights) + 92
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img">',
           "<title>How the M5 oracle changed, v1.0 to v" + rows[-1][0] + "</title>",
           f'<rect width="{W}" height="{H}" rx="12" fill="#FCFCFB"/>',
           text(24, 28, "How the test oracle for an AI chatbot changed: every version, with an example", 15, 600),
           text(24, 50, "The oracle is the set of expected results for 28 scripted conversations with the bot.", 12, 400, MUTED),
           text(24, 68, "Most changes fixed the oracle, not the bot: the bot's reply was right and the test was too literal "
                        "or too narrow.", 12, 400, MUTED)]
    # legend
    lx = 24
    for k, (label, fill, stroke, ink) in KINDS.items():
        out.append(f'<rect x="{lx}" y="84" width="12" height="12" rx="3" fill="{fill}" stroke="{stroke}" stroke-width="0.8"/>')
        out.append(text(lx + 18, 90, label, 12, 400, MUTED))
        lx += 150
    # timeline spine
    x_spine = 150
    out.append(f'<path d="M{x_spine} {top + 8}V{top + sum(heights) - 20}" stroke="{LINE}" stroke-width="1.2"/>')
    counts = {k: 0 for k in KINDS}
    for i, (ver, date) in enumerate(rows):
        kinds, convs, what, example, why = VERSIONS[ver]
        y = top + sum(heights[:i]) + 14
        for k in kinds:
            counts[k] += 1
        out.append(text(24, y, f"v{ver}", 13, 600))
        out.append(text(24, y + 18, date, 11, 400, MUTED))
        dot = KINDS[kinds[0]][2] if kinds else MUTED
        out.append(f'<circle cx="{x_spine}" cy="{y}" r="5" fill="#FFFFFF" stroke="{dot}" stroke-width="1.6"/>')
        cx = 166                                                 # one small chip per kind
        for k in kinds:
            label, fill, stroke, ink = KINDS[k]
            out.append(f'<rect x="{cx}" y="{y - 7}" width="14" height="14" rx="3" fill="{fill}" stroke="{stroke}" '
                       f'stroke-width="0.8"/>')
            cx += 18
        out.append(text(226, y, what, 12, 600))
        ex = [example] if isinstance(example, str) else list(example)
        for k, line in enumerate(ex):
            out.append(text(226, y + 18 + 18 * k, ("e.g. " if k == 0 else "      ") + line, 11.5, 400, INK))
        out.append(text(226, y + 18 + 18 * len(ex), f"Exposed by: {why}   |   {convs} scored conversations", 11, 400, MUTED))
    fixes = counts["fix"]
    later = len(rows) - 1
    y = top + sum(heights) + 22
    out.append(f'<rect x="24" y="{y - 14}" width="{W - 48}" height="60" rx="8" fill="#FFFFFF" stroke="{LINE}" stroke-width="0.8"/>')
    out.append(text(40, y + 4, f"{fixes} of {later} changes fixed the oracle, {counts['coverage']} added coverage, "
                               f"{counts['check']} changed rules or checks (a change can be more than one kind).", 12, 600))
    out.append(text(40, y + 26, "Every fix only widened what is accepted, and saved runs were re-scored with the new "
                                "version before being compared, so comparisons stayed fair.", 12, 400, MUTED))
    out.append("</svg>")
    return "".join(out)


def main() -> int:
    rows = versions_in_file()
    missing = [v for v, _ in rows if v not in VERSIONS]
    if missing:
        raise SystemExit(f"versions in the golden file with no label here: {missing}; add them to VERSIONS")
    OUT.write_text(draw(rows), encoding="utf-8")
    print(f"Wrote {OUT} ({len(rows)} versions, v{rows[0][0]} to v{rows[-1][0]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
