"""judge.py: the harness's AI checks. Turns LLM-judge marks into harness findings.

Two judge calls per story
-------------------------
  Case judge   the frozen Day 4 judge prompt bench/prompts/judge_cases_v2.txt (fingerprint
               ff34c1fc3ab1), called through bench/judge.py unchanged. It sees only the story
               and the cases, never an answer key, so it is oracle-free. Per case it returns:
               verdict, technique, concrete, atomic, AC claims supported, duplicate_of, reason.
  Title judge  a new short prompt, harness/prompts/judge_title_v1.txt: does the title alone tell
               a reader exactly what the test checks? (Roger's definition, 12 Nov.) Per case:
               title_clear, reason. Not yet calibrated against human labels, so warnings only.

How marks become findings (levels agreed 12 Nov)
------------------------------------------------
  verdict        fail   incorrect, or not_in_basis (asserts something the story does not define)
  atomic         warn   tests more than one condition; how a team asserts outcomes varies, so a person decides
  duplicate      warn   repeats an earlier case; the message names both cases, and the summary groups them.
                        When the two cases differ by a calendar edge (year end, month end, 28/29 February,
                        end of day) and the story's rules use dates, the warning adds a caution: the
                        "duplicate" may be a real edge test (Roger, 12 Nov, after the S05 live run).
  over_claim     warn   B2: covers lists an AC that the judge says the case does not really test
  ac_unverified  warn   A2 (story-level): no case judged correct really tests this AC
  concrete       warn   inputs are classes ("an amount over 1,000"), not values; indicative only (13/20 at Day 4)
  title_clear    warn   the title does not say what the test checks
  judge_missing  warn   the judge returned no mark for a case (re-run; never silently scored)
The judge's own technique label (positive / negative / boundary) is kept as information
for the report; it is not a finding.

Reuse mode: marks can be read from a Day 4 score file instead of calling the model. That
makes the regression check free and exact (same marks in, same findings out).

Change history:
  2026-11-12  v1  first version (M7 step 3).
  2026-11-12  v2  calendar-edge caution on duplicate warnings (M7 step 4).
  2026-11-25  v3  over-claim warnings carry the judge's reason (Roger's report review).
"""

from __future__ import annotations

import calendar
import json
import re
import time
from datetime import date
from pathlib import Path

from bench.golden import fingerprint_text, story_card
from bench.judge import CASES_PROMPT, CASES_SCHEMA, JUDGE_MODEL, call_judge, cases_input, check_judgement
from bench.pricing import cost_usd
from bench.testcase_schema import parse_reply
from harness.contract import Finding, case_key, flat_case, input_text

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
TITLE_PROMPT = "judge_title_v1"
TITLE_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["titles"],
    "properties": {"titles": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["case_id", "title_clear", "reason"],
        "properties": {"case_id": {"type": "string"}, "title_clear": {"type": "boolean"},
                       "reason": {"type": "string"}}}}}}


# --- calling the judge -------------------------------------------------------------
def load_title_prompt() -> tuple[str, str]:
    """The title-judge instructions and their fingerprint (line endings normalised, as bench/golden.py)."""
    text = (PROMPTS_DIR / f"{TITLE_PROMPT}.txt").read_text(encoding="utf-8").replace("\r\n", "\n").strip()
    return text, fingerprint_text(text)


def title_input(story: dict, cases: list[dict]) -> str:
    """What the title judge sees: the story card, then each case's ID, title, steps and expected result."""
    view = [{k: c.get(k) for k in ("case_id", "title", "steps", "expected_result")} for c in cases]
    return f"User story:\n{story_card(story)}\n\nTest cases:\n" + json.dumps(view, indent=1, ensure_ascii=False)


def call_title_judge(story: dict, cases: list[dict], client, model: str = JUDGE_MODEL) -> dict:
    """One title-judge call for one story. Same record shape as bench.judge.call_judge, so cost
    and time are reported the same way. Retries an API error once."""
    instructions, fp = load_title_prompt()
    fmt = {"format": {"type": "json_schema", "name": TITLE_PROMPT, "schema": TITLE_SCHEMA, "strict": True}}
    start = time.perf_counter()
    for attempt in (1, 2):
        try:
            resp = client.responses.create(model=model, instructions=instructions,
                                           input=title_input(story, cases), text=fmt)
            break
        except Exception:
            if attempt == 2:
                raise
            time.sleep(5)
    raw = resp.output_text.strip()
    parsed, info = parse_reply(raw)
    usage = getattr(resp, "usage", None)
    return {"prompt": TITLE_PROMPT, "prompt_fingerprint": fp, "parsed": parsed,
            "raw": raw if parsed is None else None, "parse_error": info["error"],
            "usage": {"input_tokens": getattr(usage, "input_tokens", None),
                      "output_tokens": getattr(usage, "output_tokens", None),
                      "latency_s": round(time.perf_counter() - start, 2),
                      "model_served": getattr(resp, "model", None)}}


def judge_story(story: dict, cases: list[dict], client, model: str = JUDGE_MODEL, titles: bool = True) -> dict:
    """Both judge calls for one story: {'cases_call': ..., 'title_call': ... or None}.
    Cases are flattened first, so step objects and per-step expected results reach the
    frozen judge in the Day 4 shape it was calibrated on."""
    flat = [flat_case(c) for c in cases if isinstance(c, dict)]
    a = call_judge(CASES_PROMPT, cases_input(story, flat), CASES_SCHEMA, client, model)
    a["issues"] = check_judgement(a["parsed"], "cases", "case_id", [c["case_id"] for c in flat])
    t = call_title_judge(story, flat, client, model) if titles else None
    if t is not None:
        t["issues"] = check_judgement(t["parsed"], "titles", "case_id", [c["case_id"] for c in flat])
    return {"cases_call": a, "title_call": t}


def marks_from_score_file(path: Path) -> dict[str, dict]:
    """Reuse mode: {story_id: {'cases_call': ..., 'title_call': None}} from a Day 4 score file
    (results/testgen/score_*.json), so no model is called."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out = {}
    for st in data["stories"]:
        call = (st.get("judgement") or {}).get("cases_call")
        if call:
            out[st["metrics"]["story_id"]] = {"cases_call": call, "title_call": None}
    return out


def call_cost(call: dict | None, model: str = JUDGE_MODEL) -> float:
    """Cost in USD of one judge call from its recorded tokens (0 if unknown, e.g. in reuse mode)."""
    if not call:
        return 0.0
    u = call.get("usage") or {}
    return cost_usd(model, u.get("input_tokens"), u.get("output_tokens")) or 0.0


# --- calendar edges (caution on duplicates) ---------------------------------------
_MONTH_NAMES = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_LONG = re.compile(r"\b(\d{1,2}) (" + "|".join(_MONTH_NAMES) + r") (\d{4})\b", re.I)
_SLASH = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_DAY_EDGE_TIME = re.compile(r"\b(23:59(?::59)?|00:00(?::00)?|midnight)\b", re.I)
# Words that show a story's rules depend on dates or time, not just mention a date field.
# "day case" (a hospital procedure type) is not about time, so it is excluded.
_DATED_RULE = re.compile(r"\b(day(?!\s+case)|days|week|weeks|month|months|year|years|annual|anniversary|deadline|"
                         r"calendar|leap|midnight)\b", re.I)


def dates_in(text: str) -> list[date]:
    """Every date written in the text as 2027-03-10, 10 March 2027 or 10/03/2027 (day first)."""
    found = []
    for y, m, d in _ISO.findall(text):
        found.append((int(y), int(m), int(d)))
    for d, mon, y in _LONG.findall(text):
        found.append((int(y), _MONTH_NAMES[mon.lower()], int(d)))
    for d, m, y in _SLASH.findall(text):
        found.append((int(y), int(m), int(d)))
    out = []
    for y, m, d in found:
        try:
            out.append(date(y, m, d))
        except ValueError:          # an impossible date such as 30 February: not a calendar edge we can name
            pass
    return out


def calendar_edges(text: str) -> set[str]:
    """The calendar edges a case's inputs touch: year end, month end, 28/29 February, end of day."""
    edges = set()
    for d in dates_in(text):
        last_day = calendar.monthrange(d.year, d.month)[1]
        if d.month == 2 and d.day >= 28:
            edges.add("28/29 February (leap year)")
        elif (d.month, d.day) in ((12, 31), (1, 1)):
            edges.add("year end")
        elif d.day == last_day:
            edges.add("month end")
    if _DAY_EDGE_TIME.search(text):
        edges.add("end of day")
    return edges


def story_rules_use_dates(story: dict) -> bool:
    """True if the story's acceptance criteria work with days, months, years or deadlines,
    so a calendar edge could change the outcome (a date that is only recorded does not count)."""
    return any(_DATED_RULE.search(ac["text"]) for ac in story["acceptance_criteria"])


def calendar_caution(story: dict, case_a: dict, case_b: dict) -> str:
    """A caution to add to a duplicate warning, or "" if none applies: the two cases differ by a
    calendar edge AND the story's rules use dates, so the 'duplicate' may be a real edge test."""
    if not story_rules_use_dates(story):
        return ""
    a, b = calendar_edges(input_text(case_a)), calendar_edges(input_text(case_b))
    differ = sorted(a ^ b)
    if not differ:
        return ""
    return (f" Caution: the two cases differ by a calendar edge ({', '.join(differ)}) and this story's rules "
            "use dates; check whether the edge matters before removing either case.")


# --- turning marks into findings ---------------------------------------------------
def judge_findings(story: dict, cases: list[dict], judged: dict) -> tuple[list[Finding], dict]:
    """Findings for one story from its judge marks, plus {case_id: technique} for the report.
    A duplicate counts only when it names an EARLIER case, as in bench/score.py."""
    sid = story["story_id"]
    ids = [case_key(c, n) for n, c in enumerate(cases, start=1)]
    marks = {m.get("case_id"): m for m in ((judged.get("cases_call") or {}).get("parsed") or {}).get("cases", [])}
    out: list[Finding] = []
    techniques: dict[str, str] = {}

    def add(cid: str, check: str, level: str, message: str) -> None:
        """Record one finding for this story."""
        out.append(Finding(sid, cid, check, level, message))

    for pos, cid in enumerate(ids):
        m = marks.get(cid)
        if m is None:
            add(cid, "judge_missing", "warn", "the judge returned no mark for this case; re-run the check")
            continue
        techniques[cid] = m.get("technique", "")
        why = f": {m['reason']}" if m.get("reason") else ""
        if m.get("verdict") == "incorrect":
            add(cid, "verdict", "fail", f"the expected result contradicts the acceptance criteria{why}")
        elif m.get("verdict") == "not_in_basis":
            add(cid, "verdict", "fail", f"the case asserts something the story does not define (not in basis){why}")
        if m.get("atomic") is False:
            add(cid, "atomic", "warn", f"the case tests more than one condition{why}")
        dup = m.get("duplicate_of") or ""
        if dup and dup in ids[:pos]:
            message = f"repeats {dup} (same condition, same expected outcome){why}".rstrip(".") + "."
            add(cid, "duplicate", "warn", message + calendar_caution(story, cases[ids.index(dup)], cases[pos]))
        unsupported = [cl["ac_id"] for cl in m.get("claims", []) if not cl.get("supported")]
        if unsupported:
            add(cid, "over_claim", "warn",
                f"covers lists {', '.join(unsupported)} but the case does not really test "
                f"{'it' if len(unsupported) == 1 else 'them'}{why}")
        if m.get("concrete") is False:
            add(cid, "concrete", "warn", f"inputs are described as classes rather than exact values{why}")

    # A2: an AC is verified when a case judged correct has a supported claim on it.
    correct = {cid for cid in ids if marks.get(cid, {}).get("verdict") == "correct"}
    verified = {cl["ac_id"] for cid in correct for cl in marks[cid].get("claims", []) if cl.get("supported")}
    for ac in story["acceptance_criteria"]:
        if ac["ac_id"] not in verified:
            add("", "ac_unverified", "warn", f"{ac['ac_id']}: no case judged correct really tests this criterion")

    titles = {m.get("case_id"): m for m in ((judged.get("title_call") or {}).get("parsed") or {}).get("titles", [])}
    for cid in ids:
        t = titles.get(cid)
        if t is not None and t.get("title_clear") is False:
            add(cid, "title_clear", "warn",
                f"the title does not say what the test checks{': ' + t['reason'] if t.get('reason') else ''}")
    return out, techniques


def duplicate_groups(findings: list[Finding]) -> dict[str, list[list[str]]]:
    """{story_id: [[TC01, TC09, TC10], ...]}: cases joined by the judge's duplicate marks,
    so a reviewer sees each set of repeats together, earliest case first."""
    parent: dict[tuple[str, str], tuple[str, str]] = {}

    def root(x):
        """Follow the links to the first case of x's group."""
        while parent.get(x, x) != x:
            x = parent[x]
        return x

    for f in findings:
        if f.check == "duplicate":
            earlier = f.message.split(" ", 2)[1]                      # "repeats TC01 (...)"
            a, b = root((f.story_id, earlier)), root((f.story_id, f.case_id))
            parent.setdefault(a, a)
            parent[b] = a
    groups: dict[tuple[str, str], set[str]] = {}
    for node in list(parent):
        groups.setdefault(root(node), set()).add(node[1])
    out: dict[str, list[list[str]]] = {}
    for (sid, _), members in groups.items():
        out.setdefault(sid, []).append(sorted(members))
    return {sid: sorted(g) for sid, g in sorted(out.items())}
