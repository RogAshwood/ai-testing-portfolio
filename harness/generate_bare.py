"""generate_bare.py: generate test cases with a bare prompt, as many people use AI tools in practice.

Why: the Day 4 prompts are disciplined. v1 already says "base every expected result on the
story only; do not invent rules" and defines positive / negative / boundary and `covers`;
v2 adds seven test-design techniques. Their output was too clean to prove several harness
lints. The bare prompt (harness/prompts/testgen_bare.txt) is just "Write test cases for the
user story below" plus the JSON format the harness needs to read the reply: no guardrails,
no techniques, no definitions. It is a third, weaker generator style, closer to everyday use.

It reuses the Day 4 generator call (bench/generate.py: same model gpt-6-luna, one call per
story, the same story card) so the only difference from v1 and v2 is the prompt. The prompt
lives in harness/prompts/, not bench/prompts/, so the benchmark CI workflow is not started.

Usage (repo root; paid, about $0.01 for 10 stories):
    python -m harness.generate_bare
    python -m harness.generate_bare --stories S01,S05
Writes results/m7/gen_bare_gpt-6-luna_<UTC time>.json in the Day 4 generation-file shape, so it
can be checked directly:
    python -m harness.check --stories datasets/testgen_golden.json --cases results/m7/gen_bare_<...>.json

Change history:
  2026-11-12  v1  first version (M7 step 4).
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from bench.generate import GENERATOR_MODEL, call_generator
from bench.golden import ROOT, fingerprint_text, load_golden, story_card
from bench.pricing import cost_usd
from bench.testcase_schema import parse_reply
from harness.contract import check_case_schema

PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "testgen_bare.txt"
OUT_DIR = ROOT / "results" / "m7"


def load_bare_prompt() -> tuple[str, str]:
    """The bare prompt text and its fingerprint (line endings normalised, as bench/golden.py)."""
    text = PROMPT_PATH.read_text(encoding="utf-8").replace("\r\n", "\n").strip()
    return text, fingerprint_text(text)


def generate_story(story: dict, prompt_text: str, client, model: str) -> dict:
    """One generator call for one story; the reply is parsed and checked against the harness input
    contract (not the stricter Day 4 contract, which needs a technique label the bare prompt does not ask for)."""
    reply, usage = call_generator(story_card(story), prompt_text, client, model)
    parsed, info = parse_reply(reply)
    cases = (parsed or {}).get("test_cases")
    cases = cases if isinstance(cases, list) else []
    issues = [f.message for n, c in enumerate(cases, start=1) for f in check_case_schema(story["story_id"], c, n)]
    return {"story_id": story["story_id"], "raw_reply": reply, "parsed": parsed, "parse_info": info,
            "schema_issues": issues if parsed is not None else [info["error"]],
            "schema_valid": parsed is not None and bool(cases) and not issues,
            "n_cases": len(cases), "usage": usage}


def run(story_ids: list[str] | None = None, client=None, model: str = GENERATOR_MODEL) -> Path:
    """Generate for the chosen stories (default all 10) and save one results file. Returns its path."""
    golden = load_golden()
    stories = [s for s in golden["stories"] if not story_ids or s["story_id"] in story_ids]
    if story_ids and len(stories) != len(story_ids):
        raise SystemExit(f"unknown story IDs in {story_ids}")
    if client is None:
        from bench.generate import make_client           # reads OPENAI_API_KEY from .env
        client = make_client()
    prompt_text, prompt_fp = load_bare_prompt()
    started = datetime.now(timezone.utc)
    records = [generate_story(s, prompt_text, client, model) for s in stories]
    tokens_in = sum(r["usage"]["input_tokens"] or 0 for r in records)
    tokens_out = sum(r["usage"]["output_tokens"] or 0 for r in records)
    meta = {"started_utc": started.isoformat(timespec="seconds"), "model": model, "prompt_version": "bare",
            "prompt_fingerprint": prompt_fp, "golden_version": golden["version"],
            "golden_fingerprint": golden["_fingerprint"], "stories": [s["story_id"] for s in stories],
            "totals": {"cases": sum(r["n_cases"] for r in records),
                       "schema_valid": sum(r["schema_valid"] for r in records),
                       "input_tokens": tokens_in, "output_tokens": tokens_out,
                       "cost_usd": cost_usd(model, tokens_in, tokens_out),
                       "latency_s": round(sum(r["usage"]["latency_s"] or 0 for r in records), 1)}}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"gen_bare_{model}_{started.strftime('%Y%m%dT%H%M%SZ')}.json"
    out.write_text(json.dumps({"meta": meta, "records": records}, indent=1, ensure_ascii=False), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    """Parse the command line, generate, and print a one-line summary per story."""
    p = argparse.ArgumentParser(description="Generate test cases with the bare prompt.")
    p.add_argument("--stories", help="comma-separated story IDs (default: all)")
    args = p.parse_args(argv)
    out = run([s.strip() for s in args.stories.split(",")] if args.stories else None)
    data = json.loads(out.read_text(encoding="utf-8"))
    for r in data["records"]:
        print(f"{r['story_id']}  cases {r['n_cases']:>3}  {'valid' if r['schema_valid'] else 'issues: ' + '; '.join(r['schema_issues'][:2])}")
    t = data["meta"]["totals"]
    print(f"{t['cases']} cases, {t['schema_valid']}/{len(data['records'])} stories valid, ${t['cost_usd']}, {t['latency_s']} s")
    print(f"saved {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
