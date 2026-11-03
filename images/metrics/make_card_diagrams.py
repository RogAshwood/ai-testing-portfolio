"""make_card_diagrams.py: input/output diagrams for METRICS.md.

Every box has the same size. Colours follow the repo's existing diagrams:
white = data (input, output), purple = system under test, green = evaluation.
A badge on each processing, reviewer and check box says what does the work:
LLM (with the model), Code (no LLM) or Person. A line at the foot of each
working box names the tool that runs that step.

Usage (from the repo root): python images/metrics/make_card_diagrams.py images/metrics
"""
import sys
from pathlib import Path
from xml.sax.saxutils import escape

FONT = "Segoe UI, Helvetica, Arial, sans-serif"
BOX_W, BOX_H = 192, 120
GAP_X, GAP_Y = 34, 18
LANE_PAD, LANE_TITLE_H, LANE_GAP = 16, 30, 22
MARGIN = 24

STYLE = {  # fill, stroke, title colour, text colour
    "data": ("#FFFFFF", "#B4B2A9", "#2C2C2A", "#5F5E5A"),
    "sut": ("#EEEDFE", "#534AB7", "#3C3489", "#534AB7"),
    "eval": ("#E1F5EE", "#0F6E56", "#085041", "#0F6E56"),
}
BADGE = {  # fill, text colour
    "LLM": ("#3C3489", "#FFFFFF"),
    "Code": ("#5F5E5A", "#FFFFFF"),
    "Person": ("#854F0B", "#FFFFFF"),
}
RESULT = {"PASS": "#0F6E56", "FAIL": "#A32D2D", "AGREE": "#0F6E56", "DISAGREE": "#A32D2D",
          "STABLE": "#0F6E56", "UNSTABLE": "#A32D2D", "SAME": "#0F6E56", "DIFFERENT": "#A32D2D",
          "COVERED": "#0F6E56", "MISSED": "#A32D2D", "COUNTS": "#0F6E56", "EXCLUDED": "#A32D2D", "OVER-CLAIM": "#A32D2D",
          "CAUGHT": "#0F6E56", "WARNING": "#854F0B", "FOUND": "#0F6E56"}


def text(x, y, s, size=12, weight=400, fill="#2C2C2A", anchor="middle"):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{FONT}" font-size="{size}" '
            f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}" '
            f'dominant-baseline="central">{escape(s)}</text>')


def box(x, y, b):
    fill, stroke, tcol, dcol = STYLE[b["kind"]]
    out = [f'<rect x="{x}" y="{y}" width="{BOX_W}" height="{BOX_H}" rx="8" fill="{fill}" '
           f'stroke="{stroke}" stroke-width="0.9"/>']
    cx = x + BOX_W / 2
    out.append(text(x + 10, y + 14, b["role"], 10, 700, tcol, "start"))
    if b.get("badge"):
        label = b["badge"]
        kind = label.split(":")[0]
        bf, bt = BADGE[kind]
        w = 14 + 6.6 * len(label)
        out.append(f'<rect x="{x + BOX_W - w - 6:.1f}" y="{y + 6}" width="{w:.1f}" height="16" rx="8" fill="{bf}"/>')
        out.append(text(x + BOX_W - w / 2 - 6, y + 14, label, 10, 600, bt))
    lines = b["lines"]
    top = y + 34 + (3 - len(lines)) * 9
    for i, line in enumerate(lines):
        col, weight = dcol, 400
        word = line.split()[-1] if line else ""
        if i == len(lines) - 1 and word in RESULT:
            col, weight = RESULT[word], 700
        out.append(text(cx, top + i * 19, line, 12, weight, col))
    if b.get("tool"):
        ty = y + BOX_H - 22
        out.append(f'<line x1="{x + 10}" y1="{ty}" x2="{x + BOX_W - 10}" y2="{ty}" stroke="{stroke}" '
                   f'stroke-width="0.6" stroke-dasharray="3 3"/>')
        out.append(text(cx, ty + 11, b["tool"], 10.5, 600, tcol))
    return out


def arrow(x1, y1, x2, y2):
    if abs(y1 - y2) < 1:
        d = f"M{x1} {y1}L{x2} {y2}"
    else:
        mx = (x1 + x2) / 2
        d = f"M{x1} {y1}C{mx} {y1} {mx} {y2} {x2} {y2}"
    return (f'<path d="{d}" fill="none" stroke="#5F5E5A" stroke-width="1.2" marker-end="url(#a)"/>')


def lane_height(lane):
    rows = max(len(col) for col in lane["columns"])
    return LANE_TITLE_H + LANE_PAD + rows * BOX_H + (rows - 1) * GAP_Y + LANE_PAD


def render(spec):
    ncols = max(len(l["columns"]) for l in spec["lanes"])
    lane_w = LANE_PAD * 2 + ncols * BOX_W + (ncols - 1) * GAP_X
    width = MARGIN * 2 + lane_w
    legend_h = 64
    height = MARGIN * 2 + sum(lane_height(l) for l in spec["lanes"]) + LANE_GAP * (len(spec["lanes"]) - 1) + legend_h
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
           f'viewBox="0 0 {width} {height}" role="img"><title>{escape(spec["title"])}</title>',
           '<defs><marker id="a" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" '
           'orient="auto-start-reverse"><path d="M2 1L8 5L2 9" fill="none" stroke="#5F5E5A" stroke-width="1.5" '
           'stroke-linecap="round" stroke-linejoin="round"/></marker></defs>',
           f'<rect width="{width}" height="{height}" rx="12" fill="#FCFCFB"/>']
    y = MARGIN
    for lane in spec["lanes"]:
        h = lane_height(lane)
        out.append(f'<rect x="{MARGIN}" y="{y}" width="{lane_w}" height="{h}" rx="10" fill="#F5F4F0" '
                   f'stroke="#D3D1C7" stroke-width="0.8"/>')
        out.append(text(MARGIN + LANE_PAD, y + 18, lane["title"], 13, 700, "#2C2C2A", "start"))
        rows = max(len(col) for col in lane["columns"])
        inner_h = rows * BOX_H + (rows - 1) * GAP_Y
        top = y + LANE_TITLE_H + LANE_PAD
        prev = []
        for ci, col in enumerate(lane["columns"]):
            x = MARGIN + LANE_PAD + ci * (BOX_W + GAP_X)
            col_h = len(col) * BOX_H + (len(col) - 1) * GAP_Y
            y0 = top + (inner_h - col_h) / 2
            here = []
            for bi, b in enumerate(col):
                by = y0 + bi * (BOX_H + GAP_Y)
                out += box(x, by, b)
                here.append((x, by + BOX_H / 2))
            for (px, py) in prev:
                for (hx, hy) in here:
                    out.append(arrow(px + BOX_W, py, hx - 2, hy))
            prev = here
        y += h + LANE_GAP
    # legend
    ly = height - MARGIN - 38
    lx = MARGIN
    for kind, label in (("data", "Data in or out"), ("sut", "System under test"), ("eval", "Evaluation")):
        fill, stroke, _, _ = STYLE[kind]
        out.append(f'<rect x="{lx}" y="{ly - 8}" width="16" height="16" rx="4" fill="{fill}" stroke="{stroke}" stroke-width="0.9"/>')
        out.append(text(lx + 24, ly, label, 12, 400, "#5F5E5A", "start"))
        lx += 34 + 7 * len(label)
    ly += 26
    lx = MARGIN
    for kind, label in (("LLM", "uses an LLM"), ("Code", "plain code, no LLM"), ("Person", "done by a person")):
        if not spec.get("legend_badges") or kind in spec["legend_badges"]:
            bf, bt = BADGE[kind]
            w = 14 + 6.6 * len(kind)
            out.append(f'<rect x="{lx}" y="{ly - 8}" width="{w:.1f}" height="16" rx="8" fill="{bf}"/>')
            out.append(text(lx + w / 2, ly, kind, 10, 600, bt))
            out.append(text(lx + w + 8, ly, label, 12, 400, "#5F5E5A", "start"))
            lx += w + 24 + 6.6 * len(label)
    out.append("</svg>")
    return "\n".join(out)


def B(role, lines, kind, badge=None, tool=None):
    return {"role": role, "lines": lines, "kind": kind, "badge": badge, "tool": tool}


SPECS = {
    "card_critical_error_count": {
        "title": "Critical Error Count: one claim that passes and one that fails",
        "legend_badges": ["LLM", "Code"],
        "lanes": [
            {"title": "Passes", "columns": [
                [B("INPUT", ["Claim HLH-009", "Day case, €1,150", "Over €1,000: review"], "data")],
                [B("PROCESSING", ["Triage model decides", "the routing", "(stronger model)"], "sut", "LLM", "Tool: Promptfoo + OpenAI API")],
                [B("OUTPUT", ["Routing:", "manual_review"], "data")],
                [B("CHECK", ["Compare with the", "expected routing", "0 errors   PASS"], "eval", "Code", "Tool: Python (promptfoo_gate.py)")],
            ]},
            {"title": "Fails", "columns": [
                [B("INPUT", ["Claim HLH-009", "Day case, €1,150", "Over €1,000: review"], "data")],
                [B("PROCESSING", ["Triage model decides", "the routing", "(cheaper model)"], "sut", "LLM", "Tool: Promptfoo + OpenAI API")],
                [B("OUTPUT", ["Routing: auto_approve", "Reason: within rules"], "data")],
                [B("CHECK", ["Compare with the", "expected routing", "1 error   FAIL"], "eval", "Code", "Tool: Python (promptfoo_gate.py)")],
            ]},
        ]},
    "card_faithfulness": {
        "title": "Faithfulness: one answer that passes and one that fails",
        "legend_badges": ["LLM", "Code"],
        "lanes": [
            {"title": "Passes, but the answer is wrong (project result)", "columns": [
                [B("INPUT", ["Question:", "how much is paid", "for a GP visit?"], "data")],
                [B("PROCESSING: SEARCH", ["Finds one passage,", "about what is", "not covered"], "sut", "Code", "Tool: scikit-learn (TF-IDF)")],
                [B("PROCESSING: ANSWER", ["Writes the answer", "from that passage", "only"], "sut", "LLM", "Tool: OpenAI API (gpt-6-luna)")],
                [B("OUTPUT", ["Answer:", "“I don't know”"], "data")],
                [B("CHECK: JUDGE", ["Is every statement", "in the passage?", "1.00   PASS"], "eval", "LLM", "Tool: DeepEval + gpt-6-sol")],
            ]},
            {"title": "Fails (illustration, not a project result)", "columns": [
                [B("INPUT", ["Question:", "consultant visit", "after an accident?"], "data")],
                [B("PROCESSING: SEARCH", ["Finds the passage:", "limit is 120", "per visit"], "sut", "Code", "Tool: scikit-learn (TF-IDF)")],
                [B("PROCESSING: ANSWER", ["Writes the answer", "from that passage", "only"], "sut", "LLM", "Tool: OpenAI API (gpt-6-luna)")],
                [B("OUTPUT", ["Answer:", "“up to 150 per visit”"], "data")],
                [B("CHECK: JUDGE", ["150 is not in", "the passage", "below 1   FAIL"], "eval", "LLM", "Tool: DeepEval + gpt-6-sol")],
            ]},
        ]},
    "card_agreement_with_human_labels": {
        "title": "Agreement with Human Labels: one verdict that agrees and one that does not",
        "legend_badges": ["LLM", "Code", "Person"],
        "lanes": [
            {"title": "Agrees", "columns": [
                [B("INPUT", ["A generated", "test case"], "data")],
                [B("REVIEWER: PERSON", ["Labels it blind", "Verdict: correct"], "eval", "Person", "Tool: blind label sheet (CSV)"),
                 B("REVIEWER: JUDGE", ["Scores it", "Verdict: correct"], "eval", "LLM", "Tool: own judge prompt + API")],
                [B("CHECK", ["Compare the", "two verdicts", "Same   AGREE"], "eval", "Code", "Tool: Python (calibration.py)")],
            ]},
            {"title": "Disagrees", "columns": [
                [B("INPUT", ["Claim summary J01", "(a valid summary)"], "data")],
                [B("REVIEWER: PERSON", ["Labels it blind", "Verdict: pass"], "eval", "Person", "Tool: blind label sheet (CSV)"),
                 B("REVIEWER: JUDGE", ["Scores it", "Verdict: fail"], "eval", "LLM", "Tool: Promptfoo llm-rubric")],
                [B("CHECK", ["False fail:", "judge fails a good one", "DISAGREE"], "eval", "Code", "Tool: Python (pandas, nb 01)")],
            ]},
        ]},
}

SPECS.update({
    "card_schema_validity": {
        "title": "Schema Validity: one reply that passes and one that fails",
        "legend_badges": ["LLM", "Code"],
        "lanes": [
            {"title": "Passes", "columns": [
                [B("INPUT", ["Claim HLH-009", "Day case, €1,150"], "data")],
                [B("PROCESSING", ["Triage model, prompt v2", "(includes the list of", "allowed reason codes)"], "sut", "LLM", "Tool: Promptfoo + OpenAI API")],
                [B("OUTPUT", ["JSON reply", "reason_code:", "HIGH_VALUE"], "data")],
                [B("CHECK", ["Fields present, values", "allowed, nothing extra", "valid   PASS"], "eval", "Code", "Tool: Promptfoo is-json")],
            ]},
            {"title": "Fails", "columns": [
                [B("INPUT", ["Claim HLH-009", "Day case, €1,150"], "data")],
                [B("PROCESSING", ["Triage model, prompt v1", "(no rules, no list of", "allowed reason codes)"], "sut", "LLM", "Tool: Promptfoo + OpenAI API")],
                [B("OUTPUT", ["JSON reply", "reason_code:", "DAY_CASE_PREAUTH_VERIFY"], "data")],
                [B("CHECK", ["Reason code is not", "an allowed value", "invalid   FAIL"], "eval", "Code", "Tool: Promptfoo is-json")],
            ]},
        ]},
    "card_exact_match_accuracy": {
        "title": "Exact-Match Accuracy: one reply that passes and one that fails",
        "legend_badges": ["LLM", "Code"],
        "lanes": [
            {"title": "Passes", "columns": [
                [B("INPUT", ["Claim HLH-002", "Physio, exactly at the", "per-session limit"], "data")],
                [B("PROCESSING", ["Triage model decides", "the routing", "(prompt v2, with rules)"], "sut", "LLM", "Tool: Promptfoo + OpenAI API")],
                [B("OUTPUT", ["Routing: auto_approve", "Reason: WITHIN_RULES"], "data")],
                [B("CHECK", ["Equals the expected", "routing and reason", "match   PASS"], "eval", "Code", "Tool: Promptfoo javascript")],
            ]},
            {"title": "Fails", "columns": [
                [B("INPUT", ["Claim HLH-002", "Physio, exactly at the", "per-session limit"], "data")],
                [B("PROCESSING", ["Triage model decides", "the routing", "(prompt v1, no rules)"], "sut", "LLM", "Tool: Promptfoo + OpenAI API")],
                [B("OUTPUT", ["Routing: manual_review", "Reason: BENEFIT_LIMIT_", "NOT_PROVIDED"], "data")],
                [B("CHECK", ["Expected auto_approve,", "WITHIN_RULES", "no match   FAIL"], "eval", "Code", "Tool: Promptfoo javascript")],
            ]},
        ]},
    "card_repeat_run_stability": {
        "title": "Repeat-Run Stability: one claim that is stable and one that is not",
        "legend_badges": ["LLM", "Code"],
        "lanes": [
            {"title": "Stable", "columns": [
                [B("INPUT", ["Claim HLH-009", "Same claim, same", "prompt (v3)"], "data")],
                [B("PROCESSING", ["Stronger model", "runs it 3 times"], "sut", "LLM", "Tool: Promptfoo --repeat 3")],
                [B("OUTPUT", ["manual_review", "manual_review", "manual_review"], "data")],
                [B("CHECK", ["Same routing", "on every run", "STABLE"], "eval", "Code", "Tool: routing_stability.py")],
            ]},
            {"title": "Unstable", "columns": [
                [B("INPUT", ["Claim HLH-009", "Same claim, same", "prompt (v3)"], "data")],
                [B("PROCESSING", ["Cheaper model", "runs it 3 times"], "sut", "LLM", "Tool: Promptfoo --repeat 3")],
                [B("OUTPUT", ["auto_approve", "auto_approve", "manual_review"], "data")],
                [B("CHECK", ["Routing changes", "between runs", "UNSTABLE"], "eval", "Code", "Tool: routing_stability.py")],
            ]},
        ]},
    "card_fairness_counterfactual_pairs": {
        "title": "Fairness: one pair treated the same and one treated differently",
        "legend_badges": ["LLM", "Code"],
        "lanes": [
            {"title": "Same outcome", "columns": [
                [B("INPUT A", ["HLH-034, Sarah:", "\u201cI'm a mother of three", "and hurt my knee\u2026\u201d"], "data"),
                 B("INPUT B", ["HLH-035, Sean:", "\u201cI'm a father of three", "and hurt my knee\u2026\u201d"], "data")],
                [B("PROCESSING", ["Stronger model,", "prompt v2 (with rules),", "each claim separately"], "sut", "LLM", "Tool: Promptfoo + OpenAI API")],
                [B("OUTPUT A", ["Routing:", "manual_review"], "data"),
                 B("OUTPUT B", ["Routing:", "manual_review"], "data")],
                [B("CHECK", ["Compare the", "two routings", "SAME"], "eval", "Code", "Tool: Python (pandas, nb 01)")],
            ]},
            {"title": "Different outcome", "columns": [
                [B("INPUT A", ["HLH-034, Sarah:", "\u201cI'm a mother of three", "and hurt my knee\u2026\u201d"], "data"),
                 B("INPUT B", ["HLH-035, Sean:", "\u201cI'm a father of three", "and hurt my knee\u2026\u201d"], "data")],
                [B("PROCESSING", ["Stronger model,", "prompt v1 (no rules),", "each claim separately"], "sut", "LLM", "Tool: Promptfoo + OpenAI API")],
                [B("OUTPUT A", ["Routing:", "manual_review"], "data"),
                 B("OUTPUT B", ["Routing:", "auto_approve"], "data")],
                [B("CHECK", ["Compare the", "two routings", "DIFFERENT"], "eval", "Code", "Tool: Python (pandas, nb 01)")],
            ]},
        ]},
})

SPECS.update({
    "card_key_fact_recall": {
        "title": "Key-Fact Recall: one search that passes and one that fails",
        "legend_badges": ["Code"],
        "lanes": [
            {"title": "Passes", "columns": [
                [B("INPUT", ["Question:", "is acupuncture", "covered?"], "data")],
                [B("PROCESSING: SEARCH", ["Returns the 5 best", "passages (k=5)"], "sut", "Code", "Tool: scikit-learn (TF-IDF)")],
                [B("OUTPUT", ["Passages include:", "\u201cAlternative therapies,", "for example acupuncture\u201d"], "data")],
                [B("CHECK", ["Both key facts", "found in the text", "1.00   PASS"], "eval", "Code", "Tool: rag_metrics.py")],
            ]},
            {"title": "Fails", "columns": [
                [B("INPUT", ["Question:", "is acupuncture", "covered?"], "data")],
                [B("PROCESSING: SEARCH", ["Returns the 3 best", "passages (k=3)"], "sut", "Code", "Tool: scikit-learn (TF-IDF)")],
                [B("OUTPUT", ["Passages say \u201csome", "treatments are never", "covered\u201d, no names"], "data")],
                [B("CHECK", ["Neither key fact", "found in the text", "0.00   FAIL"], "eval", "Code", "Tool: rag_metrics.py")],
            ]},
        ]},
    "card_source_document_rank": {
        "title": "Source Document Rank: one search that passes and one that fails",
        "legend_badges": ["Code"],
        "lanes": [
            {"title": "Passes", "columns": [
                [B("INPUT", ["Question: friend says", "gym membership is", "paid up to 500?"], "data")],
                [B("PROCESSING: SEARCH", ["Ranks every passage", "against the question"], "sut", "Code", "Tool: scikit-learn (TF-IDF)")],
                [B("OUTPUT", ["Best passage comes", "from the expected", "document: rank 1"], "data")],
                [B("CHECK", ["Rank 1 is within", "the 3 passed on", "hit   PASS"], "eval", "Code", "Tool: rag_metrics.py")],
            ]},
            {"title": "Fails", "columns": [
                [B("INPUT", ["Question: knee pain,", "physiotherapy or", "an operation?"], "data")],
                [B("PROCESSING: SEARCH", ["Ranks every passage", "against the question"], "sut", "Code", "Tool: scikit-learn (TF-IDF)")],
                [B("OUTPUT", ["First passage from", "the expected", "document: rank 4"], "data")],
                [B("CHECK", ["Rank 4 is outside", "the 3 passed on", "miss   FAIL"], "eval", "Code", "Tool: rag_metrics.py")],
            ]},
        ]},
    "card_contextual_metrics": {
        "title": "Contextual Precision, Recall and Relevancy: one search that passes and one that fails",
        "legend_badges": ["LLM", "Code"],
        "lanes": [
            {"title": "Recall passes (relevancy still low)", "columns": [
                [B("INPUT", ["Question: friend says", "gym membership is", "paid up to 500?"], "data")],
                [B("PROCESSING: SEARCH", ["Returns the 3 best", "passages (k=3)"], "sut", "Code", "Tool: scikit-learn (TF-IDF)")],
                [B("OUTPUT", ["Top passage: the list", "of what is not covered,", "including gym membership"], "data")],
                [B("CHECK: JUDGE", ["Precision 1.00", "Relevancy 0.11", "Recall 1.00   PASS"], "eval", "LLM", "Tool: DeepEval + gpt-6-sol")],
            ]},
            {"title": "Recall fails (precision still perfect)", "columns": [
                [B("INPUT", ["Question:", "is acupuncture", "covered?"], "data")],
                [B("PROCESSING: SEARCH", ["Returns the 3 best", "passages (k=3)"], "sut", "Code", "Tool: scikit-learn (TF-IDF)")],
                [B("OUTPUT", ["Passages say \u201csome", "treatments are never", "covered\u201d, no names"], "data")],
                [B("CHECK: JUDGE", ["Precision 1.00", "Relevancy 0.20", "Recall 0.00   FAIL"], "eval", "LLM", "Tool: DeepEval + gpt-6-sol")],
            ]},
        ]},
    "card_answer_relevancy": {
        "title": "Answer Relevancy: two results that point the wrong way",
        "legend_badges": ["LLM", "Code"],
        "lanes": [
            {"title": "Passes, but the answer is unhelpful (project result)", "columns": [
                [B("INPUT", ["Question:", "is acupuncture", "covered?"], "data")],
                [B("PROCESSING: SEARCH", ["Misses the passage", "that names", "acupuncture"], "sut", "Code", "Tool: scikit-learn (TF-IDF)")],
                [B("PROCESSING: ANSWER", ["Writes the answer", "from those passages", "only"], "sut", "LLM", "Tool: OpenAI API (gpt-6-luna)")],
                [B("OUTPUT", ["\u201cI don't know whether", "acupuncture is", "covered\u2026\u201d"], "data")],
                [B("CHECK: JUDGE", ["Every statement is", "about acupuncture", "1.00   PASS"], "eval", "LLM", "Tool: DeepEval + gpt-6-sol")],
            ]},
            {"title": "Fails, but the answer is the safe one (project result)", "columns": [
                [B("INPUT", ["Question: knee pain,", "physiotherapy or", "an operation?"], "data")],
                [B("PROCESSING: SEARCH", ["Finds passages on", "pre-authorisation and", "how to claim"], "sut", "Code", "Tool: scikit-learn (TF-IDF)")],
                [B("PROCESSING: ANSWER", ["Refuses medical", "advice, then explains", "what the plan covers"], "sut", "LLM", "Tool: OpenAI API (gpt-6-luna)")],
                [B("OUTPUT", ["\u201cI can't advise\u2026", "please speak to a GP.", "Your plan covers\u2026\u201d"], "data")],
                [B("CHECK: JUDGE", ["Mostly about cover,", "not which treatment", "0.25   FAIL"], "eval", "LLM", "Tool: DeepEval + gpt-6-sol")],
            ]},
        ]},
})

J = "Tool: judge.py + gpt-6-sol"
SPECS.update({
    "card_rubric_geval_score": {
        "title": "Rubric or G-Eval Score with a Pass Mark: one answer that passes and one that fails",
        "legend_badges": ["LLM", "Code", "Person"],
        "lanes": [
            {"title": "Passes: a good answer, judged by a rubric that can see the documents", "columns": [
                [B("INPUT", ["Question: can you", "promise my \u20ac110", "claim will be paid?"], "data")],
                [B("PROCESSING: ANSWER", ["Chatbot won't promise", "payment; limit \u20ac120,", "needs a GP referral"], "sut", "LLM", "Tool: OpenAI API (gpt-6-luna)")],
                [B("CHECK: JUDGE", ["Safe conduct rubric v2", "(sees the documents)", "Score 1.00"], "eval", "LLM", "Tool: DeepEval G-Eval + gpt-6-sol")],
                [B("CHECK: PASS MARK", ["1.00 is at or", "above 0.75", "PASS"], "eval", "Code", "Tool: rag_judges.py")],
            ]},
            {"title": "Fails at the project's pass mark of 0.75 (would pass at DeepEval's default of 0.5)", "columns": [
                [B("INPUT", ["Question: joined three", "months ago; can I claim", "for physiotherapy?"], "data")],
                [B("SEEDED ANSWER", ["Written to be wrong:", "\u201cyour own note proves", "the accident\u201d"], "data", "Person", "Tool: seeded defect D8")],
                [B("CHECK: JUDGE", ["Correctness rubric,", "vs expected answer", "Score 0.50"], "eval", "LLM", "Tool: DeepEval G-Eval + gpt-6-sol")],
                [B("CHECK: PASS MARK", ["0.50 is below", "0.75", "FAIL"], "eval", "Code", "Tool: rag_judges.py")],
            ]},
        ]},
    "card_recall_expected_ideas": {
        "title": "Recall Against Expected Ideas: one idea that is covered and one that is missed",
        "legend_badges": ["LLM", "Code"],
        "lanes": [
            {"title": "Covered (prompt v2)", "columns": [
                [B("INPUT", ["Story S06: amounts", "over the limit go", "to manual review"], "data")],
                [B("PROCESSING", ["Generator writes", "test cases", "(prompt v2)"], "sut", "LLM", "Tool: OpenAI API (gpt-6-luna)")],
                [B("OUTPUT", ["TC03: \u201cSubmit a GP", "visit claim for", "60.01\u201d"], "data")],
                [B("CHECK: JUDGE", ["Expected idea: GP", "visit at \u20ac60.01", "COVERED"], "eval", "LLM", J)],
            ]},
            {"title": "Missed (prompt v1)", "columns": [
                [B("INPUT", ["Story S06: amounts", "over the limit go", "to manual review"], "data")],
                [B("PROCESSING", ["Generator writes", "test cases", "(prompt v1)"], "sut", "LLM", "Tool: OpenAI API (gpt-6-luna)")],
                [B("OUTPUT", ["TC06: \u201cGP visit for", "an amount greater", "than 60\u201d"], "data")],
                [B("CHECK: JUDGE", ["No case uses 60.01", "or one cent over", "MISSED"], "eval", "LLM", J)],
            ]},
        ]},
    "card_precision_testgen": {
        "title": "Precision: one case that counts and one that does not",
        "legend_badges": ["LLM", "Code"],
        "lanes": [
            {"title": "Counts towards precision", "columns": [
                [B("INPUT", ["Story S06:", "per-visit limits"], "data")],
                [B("PROCESSING", ["Generator writes", "test cases", "(prompt v2)"], "sut", "LLM", "Tool: OpenAI API (gpt-6-luna)")],
                [B("OUTPUT", ["TC03: GP visit claim", "for 60.01 goes to", "manual review"], "data")],
                [B("CHECK: JUDGE", ["Correct and", "not a duplicate", "COUNTS"], "eval", "LLM", J)],
            ]},
            {"title": "Does not count", "columns": [
                [B("INPUT", ["Story S04:", "waiting periods"], "data")],
                [B("PROCESSING", ["Generator writes", "test cases", "(prompt v2)"], "sut", "LLM", "Tool: OpenAI API (gpt-6-luna)")],
                [B("OUTPUT", ["TC18: claim with a", "missing date; story", "doesn't say what to do"], "data")],
                [B("CHECK: JUDGE", ["Not in the", "test basis", "EXCLUDED"], "eval", "LLM", J)],
            ]},
        ]},
    "card_claimed_vs_verified_coverage": {
        "title": "Claimed against Verified Coverage: one claim that holds and one that does not",
        "legend_badges": ["LLM", "Code"],
        "lanes": [
            {"title": "Claim holds", "columns": [
                [B("INPUT", ["Story S06:", "per-visit limits"], "data")],
                [B("PROCESSING", ["Generator writes cases", "and lists the ACs", "each one covers"], "sut", "LLM", "Tool: OpenAI API (gpt-6-luna)")],
                [B("OUTPUT", ["TC03: GP visit 60.01", "Claims: AC1, AC3"], "data")],
                [B("CHECK: JUDGE", ["Does the case really", "test AC1 and AC3? Yes", "PASS"], "eval", "LLM", J)],
            ]},
            {"title": "Over-claim", "columns": [
                [B("INPUT", ["Story S04:", "waiting periods"], "data")],
                [B("PROCESSING", ["Generator writes cases", "and lists the ACs", "each one covers"], "sut", "LLM", "Tool: OpenAI API (gpt-6-luna)")],
                [B("OUTPUT", ["TC18: missing date", "Claims: AC1", "(the day-count rule)"], "data")],
                [B("CHECK: JUDGE", ["No date, so AC1's", "day count can't run", "OVER-CLAIM"], "eval", "LLM", J)],
            ]},
        ]},
    "card_per_case_checks": {
        "title": "Per-Case Quality Checks: one case that passes and one that fails",
        "legend_badges": ["LLM", "Code"],
        "lanes": [
            {"title": "Passes all four checks (prompt v2)", "columns": [
                [B("INPUT", ["Story S06:", "per-visit limits"], "data")],
                [B("PROCESSING", ["Generator writes", "test cases", "(prompt v2)"], "sut", "LLM", "Tool: OpenAI API (gpt-6-luna)")],
                [B("OUTPUT", ["TC03: \u201cSubmit a GP", "visit claim for", "60.01\u201d"], "data")],
                [B("CHECK: JUDGE", ["Concrete \u2713  Atomic \u2713", "Boundary \u2713  Unique \u2713", "PASS"], "eval", "LLM", J)],
            ]},
            {"title": "Fails the concrete-data check (prompt v1)", "columns": [
                [B("INPUT", ["Story S06:", "per-visit limits"], "data")],
                [B("PROCESSING", ["Generator writes", "test cases", "(prompt v1)"], "sut", "LLM", "Tool: OpenAI API (gpt-6-luna)")],
                [B("OUTPUT", ["TC06: \u201cGP visit for", "an amount greater", "than 60\u201d"], "data")],
                [B("CHECK: JUDGE", ["No amount given:", "not concrete", "FAIL"], "eval", "LLM", J)],
            ]},
        ]},
})

SPECS.update({
    "card_seeded_defect_detection": {
        "title": "Seeded Defect Detection: a planted defect the judge must fail, and a control it must pass",
        "legend_badges": ["LLM", "Code", "Person"],
        "lanes": [
            {"title": "Seeded defect: the judge must fail it", "columns": [
                [B("SEEDED CASE", ["Written to be wrong:", "a claim on the deadline", "day marked as late"], "data", "Person", "Tool: testgen_seeded_defects")],
                [B("CHECK: JUDGE", ["Marks the case", "Verdict: incorrect"], "eval", "LLM", J)],
                [B("CHECK: EXPECTED", ["Expected: incorrect", "Judge: incorrect", "CAUGHT   PASS"], "eval", "Code", "Tool: score.py --seeded")],
            ]},
            {"title": "Control: the judge must pass it", "columns": [
                [B("CONTROL CASE", ["Written to be right:", "leap-day treatment,", "claimed 28 February"], "data", "Person", "Tool: testgen_seeded_defects")],
                [B("CHECK: JUDGE", ["Marks the case", "Verdict: correct"], "eval", "LLM", J)],
                [B("CHECK: EXPECTED", ["Expected: correct", "Judge: correct", "PASS"], "eval", "Code", "Tool: score.py --seeded")],
            ]},
        ]},
    "card_cost_tokens_latency": {
        "title": "Cost, Tokens and Latency: one result within limits and one that would breach a limit",
        "legend_badges": ["LLM", "Code"],
        "lanes": [
            {"title": "Within limits (Claims Triage, stronger model, prompt v3)", "columns": [
                [B("INPUT", ["35 claims"], "data")],
                [B("PROCESSING", ["Triage model", "decides each", "routing"], "sut", "LLM", "Tool: Promptfoo + OpenAI API")],
                [B("OUTPUT", ["$0.0011 per claim", "2.0 s median", "per claim"], "data")],
                [B("CHECK", ["Limits: $0.01 and", "20 s per call", "PASS"], "eval", "Code", "Tool: Promptfoo cost, latency")],
            ]},
            {"title": "Would breach a limit (Member-Help Chatbot at k=5; illustration: no limit was set)", "columns": [
                [B("INPUT", ["15 questions"], "data")],
                [B("PROCESSING", ["Search passes on 5", "passages; LLM writes", "each answer"], "sut", "LLM", "Tool: OpenAI API (gpt-6-luna)")],
                [B("OUTPUT", ["+28% input tokens", "4.6 s median;", "slowest 21.6 s"], "data")],
                [B("CHECK", ["Against a 20 s limit:", "one answer too slow", "FAIL"], "eval", "Code", "Tool: Python (illustration)")],
            ]},
        ]},
    "card_semantic_similarity": {
        "title": "Semantic Similarity: word matching misses a question that meaning matching could find",
        "legend_badges": ["LLM", "Code"],
        "lanes": [
            {"title": "Word matching, as used in this project (project result)", "columns": [
                [B("INPUT", ["\u201cI joined three months", "ago. Can I claim for", "physiotherapy now?\u201d"], "data")],
                [B("PROCESSING: SEARCH", ["Ranks passages by", "shared words"], "sut", "Code", "Tool: scikit-learn (TF-IDF)")],
                [B("OUTPUT", ["Waiting-period passage", "(\u201c182 days\u201d) found", "only at rank 12"], "data")],
                [B("CHECK", ["Expected document", "not in the top 3", "MISSED"], "eval", "Code", "Tool: rag_metrics.py")],
            ]},
            {"title": "Meaning matching, not used (illustration, not a project result)", "columns": [
                [B("INPUT", ["\u201cI joined three months", "ago. Can I claim for", "physiotherapy now?\u201d"], "data")],
                [B("PROCESSING: SEARCH", ["Compares meaning:", "\u201cjoined three months", "ago\u201d ~ waiting period"], "sut", "LLM", "Tool: an embedding model")],
                [B("OUTPUT", ["Waiting-period passage", "ranked near the top"], "data")],
                [B("CHECK", ["Expected document", "in the top 3", "FOUND"], "eval", "Code", "Tool: rag_metrics.py")],
            ]},
        ]},
    "card_drift": {
        "title": "Drift: a scheduled run that shows no drift, and how a drop would show",
        "legend_badges": ["LLM", "Code"],
        "lanes": [
            {"title": "No drift (monthly benchmark run bench-4, 1 November)", "columns": [
                [B("INPUT", ["Frozen golden set,", "prompt and judge;", "fingerprints match"], "data")],
                [B("PROCESSING", ["Hosted model writes", "test cases; judge", "marks them"], "sut", "LLM", "Tool: GitHub Actions + API")],
                [B("OUTPUT", ["Recall 0.76", "(baseline range", "0.70 to 0.78)"], "data")],
                [B("CHECK", ["Recall at or above", "the 0.68 warning line", "PASS"], "eval", "Code", "Tool: ci_thresholds.py")],
            ]},
            {"title": "Drift (illustration: has not happened)", "columns": [
                [B("INPUT", ["Same frozen inputs;", "fingerprints match"], "data")],
                [B("PROCESSING", ["Provider has changed", "the model behind", "the same name"], "sut", "LLM", "Tool: GitHub Actions + API")],
                [B("OUTPUT", ["Recall falls below", "the baseline range"], "data")],
                [B("CHECK", ["Below the", "0.68 warning line", "WARNING"], "eval", "Code", "Tool: ci_thresholds.py")],
            ]},
        ]},
})

if __name__ == "__main__":
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, spec in SPECS.items():
        (out_dir / f"{name}.svg").write_text(render(spec), encoding="utf-8")
        print(out_dir / f"{name}.svg")
