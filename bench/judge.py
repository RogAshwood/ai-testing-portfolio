"""judge.py: the LLM judge for the Day 4 benchmark (gpt-6-sol). Two calls per story.

    Call A, cases   story card + generated cases       -> per case: verdict, technique,
                                                          concrete, atomic, AC claims supported,
                                                          duplicate of an earlier case
    Call B, recall  story card + expected ideas + cases -> per idea: covered, by which cases

Design notes
- Call A never sees the expected ideas, so they cannot anchor the correctness
  verdict. Only Call B, which needs them, sees them.
- The judge is blind to the configuration: no prompt version, model name or
  generator technique label is passed. Cases are sent with case_id, covers
  (Call A only), title, preconditions, steps and expected result.
- Binary or categorical verdicts per item, never a single 0-1 score per story,
  so each verdict can be compared with a human label (bench/calibration.py).
- Output uses structured outputs (strict JSON schema) where the API accepts it.
  Unlike the generator, the judge's formatting is not under test. If the API
  rejects the schema parameter, the call is retried once without it and parsed
  leniently; the record says which happened.
- `check_judgement()` lists missing, duplicate or unknown IDs in a reply, so a
  judge that skips a case is caught rather than silently scored.

Change history:
  2026-10-24  v1  first version (Day 4).
  2026-10-28  v2  judge prompts v2 after calibration round 1: atomic check; concrete counts only
                  inputs that matter; technique judges what the case tests; recall accepts
                  implied outcomes, ignores background assumptions, lets ranges cover members.
"""

from __future__ import annotations

import json
import time

from bench.golden import load_named_prompt, story_card
from bench.testcase_schema import parse_reply

JUDGE_MODEL = "gpt-6-sol"           # stronger model, as Days 2 and 3
CASES_PROMPT = "judge_cases_v2"     # v1 kept in bench/prompts/ for the record
RECALL_PROMPT = "judge_recall_v2"
_STRUCTURED_OK = True               # set False after the API first rejects the schema

_str = {"type": "string"}
CASES_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["cases"],
    "properties": {"cases": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["case_id", "verdict", "technique", "concrete", "atomic", "claims", "duplicate_of", "reason"],
        "properties": {
            "case_id": _str,
            "verdict": {"type": "string", "enum": ["correct", "incorrect", "not_in_basis"]},
            "technique": {"type": "string", "enum": ["positive", "negative", "boundary"]},
            "concrete": {"type": "boolean"},
            "atomic": {"type": "boolean"},
            "claims": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["ac_id", "supported"],
                "properties": {"ac_id": _str, "supported": {"type": "boolean"}}}},
            "duplicate_of": _str,
            "reason": _str}}}}}
RECALL_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["ideas"],
    "properties": {"ideas": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["idea_id", "covered", "case_ids", "reason"],
        "properties": {"idea_id": _str, "covered": {"type": "boolean"},
                       "case_ids": {"type": "array", "items": _str}, "reason": _str}}}}}


def _case_view(case: dict, with_covers: bool) -> dict:
    keys = ["case_id"] + (["covers"] if with_covers else []) + \
           ["title", "preconditions", "steps", "expected_result"]
    return {k: case.get(k) for k in keys}


def cases_input(story: dict, cases: list[dict]) -> str:
    return (f"User story:\n{story_card(story)}\n\nTest cases:\n"
            + json.dumps([_case_view(c, True) for c in cases], indent=1, ensure_ascii=False))


def recall_input(story: dict, cases: list[dict]) -> str:
    ideas = [{"idea_id": i["idea_id"], "technique": i["technique"], "idea": i["idea"]}
             for i in story["expected_ideas"]]
    return (f"User story:\n{story_card(story)}\n\nExpected test ideas:\n"
            + json.dumps(ideas, indent=1, ensure_ascii=False)
            + "\n\nTest cases:\n"
            + json.dumps([_case_view(c, False) for c in cases], indent=1, ensure_ascii=False))


def call_judge(prompt_name: str, input_text: str, schema: dict, client,
               model: str = JUDGE_MODEL) -> dict:
    """One judge call. Returns {'parsed', 'raw', 'structured', 'usage'}."""
    instructions, fp = load_named_prompt(prompt_name)
    fmt = {"format": {"type": "json_schema", "name": prompt_name, "schema": schema, "strict": True}}
    global _STRUCTURED_OK
    structured = _STRUCTURED_OK
    start = time.perf_counter()
    for attempt in (1, 2):
        try:
            if structured:
                resp = client.responses.create(model=model, instructions=instructions,
                                               input=input_text, text=fmt)
            else:
                resp = client.responses.create(model=model, instructions=instructions,
                                               input=input_text)
            break
        except Exception as e:
            if type(e).__name__ == "BadRequestError" and structured:
                structured = _STRUCTURED_OK = False   # schema not accepted: retry, and skip it from now on
                continue
            if attempt == 2:
                raise
            time.sleep(5)                    # transient API error: retry once
    latency = time.perf_counter() - start
    raw = resp.output_text.strip()
    parsed, info = parse_reply(raw)
    usage = getattr(resp, "usage", None)
    return {"prompt": prompt_name, "prompt_fingerprint": fp, "structured": structured,
            "raw": raw if parsed is None else None, "parse_error": info["error"],
            "parsed": parsed,
            "usage": {"input_tokens": getattr(usage, "input_tokens", None),
                      "output_tokens": getattr(usage, "output_tokens", None),
                      "latency_s": round(latency, 2)}}


def check_judgement(parsed: dict | None, key: str, id_field: str, expected_ids: list[str]) -> list[str]:
    """List problems: reply missing, IDs judged twice, missing, or unknown."""
    if not parsed or not isinstance(parsed.get(key), list):
        return [f"judge reply has no '{key}' list"]
    got = [item.get(id_field) for item in parsed[key]]
    issues = [f"{i} judged twice" for i in sorted({g for g in got if got.count(g) > 1})]
    issues += [f"{i} not judged" for i in expected_ids if i not in got]
    issues += [f"{i} is not a known ID" for i in got if i not in expected_ids]
    return issues


def judge_story(story: dict, cases: list[dict], client, model: str = JUDGE_MODEL) -> dict:
    """Both judge calls for one story, with their ID checks."""
    a = call_judge(CASES_PROMPT, cases_input(story, cases), CASES_SCHEMA, client, model)
    a["issues"] = check_judgement(a["parsed"], "cases", "case_id", [c["case_id"] for c in cases])
    b = call_judge(RECALL_PROMPT, recall_input(story, cases), RECALL_SCHEMA, client, model)
    b["issues"] = check_judgement(b["parsed"], "ideas", "idea_id",
                                  [i["idea_id"] for i in story["expected_ideas"]])
    return {"cases_call": a, "recall_call": b}
