"""
images/make_m5_diagrams.py: draws the M5 set-up diagrams in the project's diagram style.

  m5_qa_view.svg      T1: the M5 test set-up in QA terms (basis, oracle, execution,
                      two check layers, verdict), with the tooling for each part
  m5_judge_setup.svg  T3: how the judge's input is built and how the judge was
                      checked before use (seeded replies, blind labels, freeze)

Each diagram is described as boxes and arrows below, so a change is a one-line edit
and both diagrams keep the same look. The oracle timeline (T4) has its own script,
make_m5_oracle_timeline.py, because it is built from the golden file.

  python images/make_m5_diagrams.py

No API calls.

Change history:
  2026-11-10  v1  first version (M5 write-up, tasks T1 and T3).
  2026-11-11  v1.1  QA view: unit test count 113 (diagram and CI gate tests added).
"""
from __future__ import annotations

import sys
from html import escape
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent
FONT = "Segoe UI, Helvetica, Arial, sans-serif"
INK, MUTED, FAINT, LINE, ARROW = "#2C2C2A", "#5F5E5A", "#888780", "#B4B2A9", "#5F5E5A"
RAMPS = {   # fill, stroke, title text: the colour ramps used in the other project diagrams
    "plain": ("#FFFFFF", LINE, INK),
    "teal": ("#E1F5EE", "#0F6E56", "#085041"),
    "purple": ("#EEEDFE", "#534AB7", "#3C3489"),
    "coral": ("#FAECE7", "#993C1D", "#712B13"),
    "grey": ("#F1EFE8", "#888780", "#444441"),
}


class Svg:
    """A small helper that collects SVG elements and writes the file."""

    def __init__(self, w: int, h: int, title: str):
        self.w, self.h, self.parts = w, h, []
        self.parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
                          f'role="img"><title>{escape(title)}</title><defs><marker id="a" viewBox="0 0 10 10" refX="8" '
                          f'refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M2 1L8 5L2 9" '
                          f'fill="none" stroke="{ARROW}" stroke-width="1.5" stroke-linecap="round" '
                          f'stroke-linejoin="round"/></marker></defs><rect width="{w}" height="{h}" rx="12" fill="#FCFCFB"/>')

    def text(self, x, y, s, size=12, weight=400, fill=INK, anchor="start"):
        self.parts.append(f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" font-weight="{weight}" '
                          f'fill="{fill}" text-anchor="{anchor}" dominant-baseline="central">{escape(s)}</text>')

    def box(self, x, y, w, h, title, lines=(), ramp="plain", dashed=False, align="middle"):
        """A rounded box with a bold title and up to a few muted lines, centred or left-aligned."""
        fill, stroke, ink = RAMPS[ramp]
        dash = ' stroke-dasharray="4 3"' if dashed else ""
        self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{fill}" stroke="{stroke}" '
                          f'stroke-width="0.8"{dash}/>')
        n = 1 + len(lines)
        top = y + h / 2 - (n - 1) * 9
        tx = x + w / 2 if align == "middle" else x + 12
        self.text(tx, top, title, 13, 600, ink, align if align == "middle" else "start")
        for i, line in enumerate(lines, start=1):
            self.text(tx, top + i * 18, line, 11.5, 400, MUTED, align if align == "middle" else "start")

    def arrow(self, d, label=None, lx=None, ly=None, dashed=False):
        dash = ' stroke-dasharray="4 3"' if dashed else ""
        self.parts.append(f'<path d="{d}" fill="none" stroke="{ARROW}" stroke-width="1.2"{dash} marker-end="url(#a)"/>')
        if label:
            self.text(lx, ly, label, 11, 400, FAINT, "middle")

    def heading(self, x, y, s):
        self.text(x, y, s.upper(), 11, 700, FAINT, "middle")

    def save(self, name: str) -> Path:
        path = OUT_DIR / name
        path.write_text("".join(self.parts) + "</svg>", encoding="utf-8")
        return path


# ---------------------------------------------------------------------------
# T1: the QA view
# ---------------------------------------------------------------------------

def table(s: Svg, x, y, col_w, rows, header_ramp="purple"):
    """A simple table: first row is the header; first column is the row label."""
    fill, stroke, ink = RAMPS[header_ramp]
    row_h, w = 24, sum(col_w)
    s.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{row_h * len(rows)}" rx="6" fill="#FFFFFF" '
                   f'stroke="{LINE}" stroke-width="0.8"/>')
    s.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{row_h}" rx="6" fill="{fill}"/>')
    for r, row in enumerate(rows):
        cy = y + r * row_h + row_h / 2
        if r:
            s.parts.append(f'<path d="M{x} {y + r * row_h}H{x + w}" stroke="#E5E3DC" stroke-width="0.8"/>')
        cx = x
        for c, cell in enumerate(row):
            weight = 600 if r == 0 or c == 0 else 400
            colour = ink if r == 0 else (INK if c == 0 else MUTED)
            s.text(cx + 10, cy, cell, 11.5, weight, colour)
            cx += col_w[c]


def qa_view() -> Path:
    s = Svg(940, 760, "The M5 chatbot test set-up in QA terms")
    s.text(24, 28, "How the M5 chatbot was tested, in QA terms", 15, 600)
    s.text(24, 50, "Two check layers on every turn; the judge itself was tested before it was trusted.", 12, 400, MUTED)
    cols = [(24, 150), (196, 170), (388, 170), (580, 190), (792, 124)]
    for (x, w), h in zip(cols, ["Test basis", "Oracle", "Execution", "Checks", "Result"]):
        s.heading(x + w / 2, 84, h)
    s.box(24, 110, 150, 120, "Test basis", ["chatbot_spec.md", "rules R1-R25", "claims data", "policy documents"])
    s.box(196, 110, 170, 120, "Oracle (golden set)", ["28 conversations; for each", "turn: tools to call or avoid,",
                                                      "facts the reply must hold,", "which judge checks apply"], "teal")
    s.box(196, 268, 170, 76, "QA of the oracle", ["validate_conversations.py", "traces facts to the basis"], "teal")
    s.arrow("M281 268V234")
    s.arrow("M174 170H192")
    s.box(388, 110, 170, 120, "Test execution", ["chatbot.run", "scripted member turns", "one trace record per", "conversation"])
    s.box(388, 268, 170, 76, "System under test", ["LangGraph bot, gpt-6-luna", "3 read-only tools, memory"], "grey")
    s.arrow("M473 230V264")
    s.arrow("M366 170H384")
    s.box(580, 110, 190, 76, "Layer 1: exact checks", ["chatbot.checks (plain Python)", "tools, arguments, facts"], "purple")
    s.box(580, 200, 190, 76, "Layer 2: LLM judge", ["chatbot.judge, gpt-6-sol", "12 behaviour checks"], "purple")
    s.box(580, 300, 190, 94, "Testing the judge", ["40 seeded replies, all right", "blind labels: held-out", "22 of 23 agree; frozen"],
          "coral")
    s.arrow("M675 296V280")
    s.arrow("M558 160H576")
    s.arrow("M558 200H566V238H576")
    s.box(792, 110, 124, 166, "Verdict", ["a turn passes", "only if both", "layers pass;", "chatbot.compare:", "mean [min-max]",
                                          "over runs"])
    s.arrow("M770 148H788")
    s.arrow("M770 238H788")
    # comparison table: our checks against general DeepEval metrics, same runs and judge model
    s.text(24, 428, "Comparison on the same 28 conversations: our two layers against four general DeepEval metrics "
                    "(same judge model)", 13, 600)
    table(s, 24, 446, [262, 262, 368], [
        ["", "Our checks and judge", "DeepEval general metrics"],
        ["Judged against", "our 12 rules from the spec, turn by turn", "not our rules: helpfulness, completeness, memory"],
        ["14 conversations breaking a spec rule*", "flagged 14 of 14", "flagged 0 of 14 (expected: not told the rules)"],
        ["Correct refusals marked as failures", "none seen", "4 (medical advice, privacy, actions, outage)"],
        ["Checked against human labels", "yes: held-out 22 of 23 agree", "no"],
        ["Cost per run", "about $0.49 (text checks are free)", "$2.21"],
    ])
    s.text(24, 616, "* e.g. internal codes shown to the member, the member's own dates stated as fact, a mistyped ID looked "
                    "up before confirming. The point: general", 11, 400, MUTED)
    s.text(24, 632, "metrics alone would have passed this bot, and the 4 conversations they did fail were the bot doing "
                    "the right thing (required refusals).", 11, 400, MUTED)
    s.box(24, 652, 892, 84, "Unit tests of the code and tooling: pytest, 113 tests, free",
          ["access check, chunking, prompt experiments, checks, judge plumbing, labels, compare, diagrams, CI gate.",
           "They test our code, not the bot's replies; the replies are tested by the two layers above."], "grey")
    return s.save("m5_qa_view.svg")


# ---------------------------------------------------------------------------
# T3: the judge set-up
# ---------------------------------------------------------------------------

def step(s: Svg, x, y, n, label):
    """A numbered step label: a small dark circle with the number, then the label."""
    s.parts.append(f'<circle cx="{x + 9}" cy="{y}" r="9" fill="{INK}"/>')
    s.text(x + 9, y, str(n), 11, 700, "#FFFFFF", "middle")
    s.text(x + 24, y, label, 12.5, 600)


def judge_setup() -> Path:
    s = Svg(1000, 880, "How the M5 judge works and how it was checked before use")
    s.text(24, 28, "The LLM judge: how one turn is judged, and how the judge was checked before use", 15, 600)
    s.text(24, 50, "chatbot/judge.py. The same code judges seeded replies and real runs, so the calibration tests "
                   "exactly the set-up that is used.", 12, 400, MUTED)
    s.heading(500, 82, "A. Judging one turn")
    step(s, 24, 106, 1, "Gather the inputs for the turn")
    w = 232
    xs = [24, 264, 504, 744]
    s.box(xs[0], 122, w, 108, "Saved conversation", ["- the conversation so far", "- every tool result so far",
                                                      "- the bot's reply to judge", "  (or a seeded reply)"], align="left")
    s.box(xs[1], 122, w, 108, "Golden set, for this turn", ["- the member's message", "- which checks apply here",
                                                            "- dates: correct answer from code", "- a note on expected behaviour"],
          "teal", align="left")
    s.box(xs[2], 122, w, 108, "Spec and session", ["- the text of each rule the", "  checks cite (e.g. R12)",
                                                   "- signed-in member and plan", "  (what the portal tells the bot)"],
          align="left")
    s.box(xs[3], 122, w, 108, "Rubric v1.2", ["- instructions: judge only this", "  reply; if unsure, use 'fail if'",
                                              "- per check: question, pass if,", "  fail if, real examples"],
          "purple", align="left")
    step(s, 24, 262, 2, "Build the packet and the instructions")
    s.box(24, 280, 112, 112, "Never sent", ["key facts,", "absent terms:", "the judge", "doesn't see our", "answers"],
          "plain", dashed=True)
    s.box(152, 280, 584, 112, "Packet: the text the judge reads", [
        "CONVERSATION SO FAR, THIS TURN (member's message and the reply),",
        "EVIDENCE (what the tools returned), RULES (the spec text),",
        "CORRECT DATES (from code), NOTE, CHECKS TO ANSWER", "build_packet(), render_packet()"])
    s.box(752, 280, 224, 112, "System prompt", ["instructions + the rubric", "sections for the checks", "asked on this turn",
                                                "system_prompt()"], "purple")
    s.arrow("M140 230V250H300V276")
    s.arrow("M380 230V276")
    s.arrow("M620 230V250H560V276")
    s.arrow("M860 230V276")
    step(s, 24, 424, 3, "Ask the judge and read its answer strictly")
    s.box(152, 442, 584, 92, "gpt-6-sol: one call per turn, all the turn's checks at once", [
        "The answer must be JSON: pass or fail, and a one-sentence reason, for every check asked.",
        "Not JSON, a check missing or a score instead of pass/fail: asked again once;",
        "still wrong: judge_error, which is never counted as a pass.   judge_turn(), parse_verdicts()"], "grey")
    s.arrow("M444 392V438")
    s.arrow("M864 392V488H740")
    step(s, 24, 566, 4, "Use the verdicts")
    s.box(24, 584, 952, 64, "Real runs: verdicts saved in judge.json, beside the text checks in checks.json", [
        "A turn passes only if every text check and every judge check passes; chatbot.compare reports mean [min-max] over runs."])
    s.arrow("M444 534V580")
    s.heading(500, 690, "B. Checking the judge before trusting it (in this order)")
    s.box(24, 712, 300, 140, "1. Seeded replies", [
        "Real conversations with a made-up", "reply whose verdict is known.",
        "2 fail and 1 pass per check: 40.", "The judge must get every one right.", "Result: 40 of 40"], "coral")
    s.box(350, 712, 300, 140, "2. Blind human labels", [
        "51 real turn-checks, verdicts hidden.", "Split before labelling: tune 28",
        "(may improve the rubric), held-out 23", "(scored only, never tuned on).",
        "Result: held-out 22 of 23 agree"], "coral")
    s.box(676, 712, 300, 140, "3. Freeze", [
        "Rubric fingerprint 4aa123f7f26c,", "recorded with every result.", "No changes for the rest of M5,",
        "so any improvement measured", "after this is the bot's"], "coral")
    s.arrow("M324 782H346")
    s.arrow("M650 782H672")
    return s.save("m5_judge_setup.svg")


def main() -> int:
    for path in (qa_view(), judge_setup()):
        print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
