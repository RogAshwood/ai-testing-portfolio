"""checklist.py: checklist-based testing in two passes. Generic test ideas, story first, then tests.

The checklist (harness/checklist.toml, team-editable) holds generic test ideas such as
authorisation, create/read/update/delete read back, rule interactions, limits in words and
period-end processing. Each item has a "check" setting that says WHEN it is checked:

  when_raised  (default) checked only when the story's words call for it (pass A decides)
  every_story  the story is not consulted; every story's test cases are checked for it
  off          never checked; listed in the report as excluded

Two judge calls per story (design agreed with Roger, 13 Nov):

  Pass A  story review   prompts/judge_story_review_v3.txt. Story and ACs only, NO test cases,
                         and only the when_raised items. For each idea the story raises: is it
                         defined by an AC (which), or implied but not defined (an AC gap ->
                         a question for the product owner)? Ideas left out are "not raised by
                         the story": the tool makes no claim about them. Saved and reused: re-run
                         only when the story card, the checked items, the prompt or the model changes.
  Pass B  test coverage  prompts/judge_test_coverage_v3.txt. The ideas pass A found defined, plus
                         every every_story item, with the test cases: covered (which cases) or not.

Each item ends with one status per story:
  excluded     check = off                                  -> listed once in the report
  not_raised   when_raised, and the story does not call for it -> no finding
  ac_gap       the story implies it, no AC defines it        -> level "question" (product owner)
  covered      raised and defined (or every_story), and a case tests it -> no finding
  not_covered  ... and no case tests it                       -> level "suggestion" (test cases)
  defined / every_story   stories-only mode (no test cases yet): what pass B would check
Questions and suggestions never fail a case or count as warnings.

Pass A alone (python -m harness.check --stories <file> --stories-only) reviews stories before
any test cases exist.

Trigger words in the checklist are a cross-check only: the report marks when_raised ideas where
the code (trigger words) and pass A disagree on whether the story raises it, as a tuning aid.

Change history:
  2026-11-13  v1  first version (M7 step 4b): one call per story, all 18 answers returned.
  2026-11-13  v2  two passes (story review, then test coverage); pass A returns only ideas that
                  apply and is cached; agreed with Roger after the first run ($0.51, checklist $0.22).
  2026-11-13  v3  report rows spell out the idea's question, the AC texts and the case titles.
  2026-11-13  v4  (tried and dropped the same day) project rules file and a "not stated" status: the
                  rules overrode the stories' own ACs and repeated one question in up to 10 stories
                  (50 questions); "not stated" fired 0 times in 190 answers.
  2026-11-13  v5  design review with Roger: one "check" setting per item (when_raised, every_story,
                  off); "not applicable" renamed "not raised by the story" (the tool claims only what
                  the story's words raise); excluded items reported; quotes kept short; prompts v3.
"""

from __future__ import annotations

import json
import re
import time
import tomllib
from pathlib import Path

from bench.golden import ROOT, fingerprint_text, story_card
from bench.judge import JUDGE_MODEL, check_judgement
from bench.testcase_schema import parse_reply
from harness.contract import Finding, flat_case

HERE = Path(__file__).resolve().parent
CHECKLIST_PATH = HERE / "checklist.toml"
REVIEW_PROMPT, COVERAGE_PROMPT = "judge_story_review_v3", "judge_test_coverage_v3"
CACHE_DIR = ROOT / "results" / "harness" / "story_reviews"
CHECK_VALUES = ("when_raised", "every_story", "off")
_str, _list = {"type": "string"}, {"type": "array", "items": {"type": "string"}}
REVIEW_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["items"],
    "properties": {"items": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["item_id", "status", "quote", "ac_ids", "note"],
        "properties": {"item_id": _str, "status": {"type": "string", "enum": ["defined", "ac_gap"]},
                       "quote": _str, "ac_ids": _list, "note": _str}}}}}
COVERAGE_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["items"],
    "properties": {"items": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["item_id", "covered", "case_ids", "note"],
        "properties": {"item_id": _str, "covered": {"type": "boolean"}, "case_ids": _list, "note": _str}}}}}


# --- loading ----------------------------------------------------------------------
def load_checklist(path: Path = CHECKLIST_PATH) -> list[dict]:
    """The checklist items (id, name, check, triggers, question), in file order. 'check' defaults
    to when_raised; a repeated ID or an unknown check value stops the run with a plain message."""
    with open(path, "rb") as f:
        items = tomllib.load(f).get("item", [])
    ids = [i["id"] for i in items]
    if len(set(ids)) != len(ids):
        raise ValueError(f"{path}: repeated checklist IDs {ids}")
    for i in items:
        i.setdefault("check", "when_raised")
        if i["check"] not in CHECK_VALUES:
            raise ValueError(f"{path}: {i['id']} check must be one of {', '.join(CHECK_VALUES)}, not {i['check']!r}")
    return items


def checklist_fingerprint(path: Path = CHECKLIST_PATH) -> str:
    """Fingerprint of the checklist file (line endings normalised), shown in the report so a reader
    knows exactly which items and settings a run used."""
    return fingerprint_text(Path(path).read_text(encoding="utf-8").replace("\r\n", "\n"))


def by_check(items: list[dict], value: str) -> list[dict]:
    """The items whose check setting is `value` (when_raised, every_story or off)."""
    return [i for i in items if i["check"] == value]


def load_prompt(name: str) -> tuple[str, str]:
    """A checklist prompt's text and fingerprint (line endings normalised, as bench/golden.py)."""
    text = (HERE / "prompts" / f"{name}.txt").read_text(encoding="utf-8").replace("\r\n", "\n").strip()
    return text, fingerprint_text(text)


def triggered(story: dict, item: dict) -> bool:
    """Code cross-check: does any trigger word appear (as whole words) in the story or its ACs?"""
    text = " ".join([story["title"], story["as_a"], story["i_want"], story["so_that"]]
                    + [a["text"] for a in story["acceptance_criteria"]])
    return any(re.search(rf"(?<![A-Za-z]){re.escape(t)}(?![A-Za-z])", text, re.I) for t in item.get("triggers", []))


# --- calling the judge ------------------------------------------------------------
def _call(client, model: str, prompt: str, schema: dict, input_text: str) -> dict:
    """One structured judge call with one retry on an API error; the same record shape as the
    other judge calls ({'prompt', 'prompt_fingerprint', 'parsed', 'raw', 'parse_error', 'usage'})."""
    instructions, fp = load_prompt(prompt)
    fmt = {"format": {"type": "json_schema", "name": prompt, "schema": schema, "strict": True}}
    start = time.perf_counter()
    for attempt in (1, 2):
        try:
            resp = client.responses.create(model=model, instructions=instructions, input=input_text, text=fmt)
            break
        except Exception:
            if attempt == 2:
                raise
            time.sleep(5)
    raw = resp.output_text.strip()
    parsed, info = parse_reply(raw)
    usage = getattr(resp, "usage", None)
    return {"prompt": prompt, "prompt_fingerprint": fp, "parsed": parsed,
            "raw": raw if parsed is None else None, "parse_error": info["error"],
            "usage": {"input_tokens": getattr(usage, "input_tokens", None),
                      "output_tokens": getattr(usage, "output_tokens", None),
                      "latency_s": round(time.perf_counter() - start, 2),
                      "model_served": getattr(resp, "model", None)}}


def _items_view(items: list[dict]) -> list[dict]:
    """The checklist as the story review sees it: ID, idea and question of the when_raised items only."""
    return [{"item_id": i["id"], "idea": i["name"], "question": " ".join(i["question"].split())}
            for i in by_check(items, "when_raised")]


def review_key(story: dict, items: list[dict], model: str) -> str:
    """Cache key for pass A: changes when the story card, the when_raised items, the prompt or the model changes."""
    return fingerprint_text(json.dumps([story_card(story), _items_view(items), load_prompt(REVIEW_PROMPT)[1], model]))


def review_story(story: dict, client, items: list[dict], model: str = JUDGE_MODEL,
                 cache_dir: Path | None = CACHE_DIR) -> dict:
    """Pass A for one story: story and ACs only, when_raised items only. Reuses a saved review when
    nothing has changed (record['cached'] is True, and its cost is not counted again). Unknown,
    repeated or not-sent IDs are listed in record['issues']; items left out are not raised."""
    if not _items_view(items):                             # nothing to review: no call
        return {"parsed": {"items": []}, "issues": [], "cached": True, "usage": {}}
    key = review_key(story, items, model)
    path = cache_dir / f"{story['story_id']}_{key}.json" if cache_dir else None
    if path and path.exists():
        rec = json.loads(path.read_text(encoding="utf-8"))
        rec["cached"] = True
        return rec
    rec = _call(client, model, REVIEW_PROMPT, REVIEW_SCHEMA,
                f"User story:\n{story_card(story)}\n\nChecklist:\n"
                + json.dumps(_items_view(items), indent=1, ensure_ascii=False))
    returned = [a.get("item_id") for a in (rec["parsed"] or {}).get("items", [])]
    sent = {i["item_id"] for i in _items_view(items)}
    rec["issues"] = ([] if rec["parsed"] else ["no reply"]) + \
        [f"{i} is not a checklist ID it was asked about" for i in returned if i not in sent] + \
        [f"{i} returned twice" for i in sorted({i for i in returned if returned.count(i) > 1})]
    rec["cached"] = False
    if path and rec["parsed"] is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({k: v for k, v in rec.items() if k != "cached"}, indent=1, ensure_ascii=False),
                        encoding="utf-8")
    return rec


def check_coverage(story: dict, cases: list[dict], review: dict, client, items: list[dict],
                   model: str = JUDGE_MODEL) -> dict | None:
    """Pass B for one story: the when_raised ideas pass A found 'defined', plus every every_story
    item, with the test cases. Returns None (no call) when there is nothing to check."""
    by_id = {i["id"]: i for i in by_check(items, "when_raised")}
    defined = [a for a in (review.get("parsed") or {}).get("items", [])
               if a.get("status") == "defined" and a.get("item_id") in by_id]
    ideas = [{"item_id": a["item_id"], "idea": by_id[a["item_id"]]["name"],
              "question": " ".join(by_id[a["item_id"]]["question"].split()),
              "checked_because": "the story raises it", "defined_by": a.get("ac_ids", []),
              "story_words": a.get("quote", "")} for a in defined]
    ideas += [{"item_id": i["id"], "idea": i["name"], "question": " ".join(i["question"].split()),
               "checked_because": "the project checks it in every story", "defined_by": [], "story_words": ""}
              for i in by_check(items, "every_story")]
    if not ideas:
        return None
    view = [{k: c.get(k) for k in ("case_id", "title", "preconditions", "steps", "expected_result")}
            for c in (flat_case(x) for x in cases if isinstance(x, dict))]
    rec = _call(client, model, COVERAGE_PROMPT, COVERAGE_SCHEMA,
                f"User story:\n{story_card(story)}\n\nTest ideas to check:\n"
                + json.dumps(ideas, indent=1, ensure_ascii=False)
                + "\n\nTest cases:\n" + json.dumps(view, indent=1, ensure_ascii=False))
    rec["issues"] = check_judgement(rec["parsed"], "items", "item_id", [a["item_id"] for a in ideas])
    return rec


# --- turning answers into findings and report rows --------------------------------
def _status(item: dict, answer: dict | None, cov: dict | None, coverage: dict | None) -> str:
    """One item's status for one story, from its check setting and the two passes' answers."""
    if item["check"] == "off":
        return "excluded"
    if item["check"] == "when_raised":
        if answer is None:
            return "not_raised"
        if answer.get("status") == "ac_gap":
            return "ac_gap"
    if coverage is None:                                    # stories-only mode: what pass B would check
        return "defined" if item["check"] == "when_raised" else "every_story"
    if cov is None:
        return "missing"
    return "covered" if cov.get("covered") else "not_covered"


def checklist_results(story: dict, review: dict | None, coverage: dict | None,
                      items: list[dict], cases: list[dict] | None = None) -> tuple[list[Finding], list[dict]]:
    """Findings (questions and suggestions) for one story, and one report row per checklist item:
    {story_id, item_id, name, check, question, status, quote, ac_ids, ac_text, case_ids, case_titles,
    note, triggered, disagree, review_cached}. ac_text and case_titles spell out the ACs and cases
    named, so a reviewer can judge each row without looking them up (Roger, 13 Nov). 'disagree' is
    only set for when_raised items (the other two settings do not ask the story)."""
    sid = story["story_id"]
    ac_text = {a["ac_id"]: a["text"] for a in story["acceptance_criteria"]}
    titles = {c.get("case_id"): c.get("title", "") for c in (cases or []) if isinstance(c, dict)}
    found = {a.get("item_id"): a for a in ((review or {}).get("parsed") or {}).get("items", [])}
    cov = {a.get("item_id"): a for a in ((coverage or {}).get("parsed") or {}).get("items", [])}
    findings, rows = [], []
    for item in items:
        a = found.get(item["id"]) if item["check"] == "when_raised" else None
        c = cov.get(item["id"])
        status = _status(item, a, c, coverage)
        fired = triggered(story, item)
        note = (c or {}).get("note", "") if status in ("covered", "not_covered") else (a or {}).get("note", "")
        ac_ids, case_ids = (a or {}).get("ac_ids", []), (c or {}).get("case_ids", [])
        rows.append({"story_id": sid, "item_id": item["id"], "name": item["name"], "check": item["check"],
                     "question": " ".join(item["question"].split()), "status": status,
                     "quote": (a or {}).get("quote", ""), "ac_ids": ac_ids,
                     "ac_text": " | ".join(f"{x}: {ac_text.get(x, '?')}" for x in ac_ids),
                     "case_ids": case_ids, "case_titles": " | ".join(f"{x}: {titles.get(x, '?')}" for x in case_ids),
                     "note": note, "triggered": fired,
                     "disagree": item["check"] == "when_raised" and fired != (a is not None),
                     "review_cached": bool((review or {}).get("cached"))})
        if status == "ac_gap":
            findings.append(Finding(sid, "", "checklist", "question",
                                    f"{item['id']} {item['name']}: {note} [the story says: \"{a.get('quote', '')}\"]"))
        elif status == "not_covered":
            why = (f"({', '.join(ac_ids)}): {note} [raised by: \"{a.get('quote', '')}\"]" if a
                   else f"(checked in every story): {note}")
            findings.append(Finding(sid, "", "checklist", "suggestion", f"{item['id']} {item['name']} {why}"))
    issues = ((review or {}).get("issues") or []) + ((coverage or {}).get("issues") or [])
    if issues:
        findings.append(Finding(sid, "", "checklist", "warn",
                                "a checklist judge reply was incomplete: " + "; ".join(issues[:3])))
    return findings, rows
