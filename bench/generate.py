"""generate.py: run the test-case generator (system under test, Day 4) and save every output.

One generator call per story:

    story card (golden.story_card) --> prompt vN --> LLM --> JSON test cases --> results file

Design notes
- The prompt file is the `instructions`; the story card is the `input`. The two
  prompt versions share the output contract and differ only in the test-design
  guidance, so any score difference comes from that guidance.
- Every run is saved in full (raw reply, parse result, schema issues, tokens,
  latency) with the model, prompt fingerprint and golden-set fingerprint, plus
  per-story card and ideas fingerprints (see golden.py). Files are named by
  configuration and timestamp and never overwritten, so scoring can be re-run
  later without paying for generation again.
- A JSON parse failure is a measured result, not something to retry. Only an
  API error is retried, once.
- Nothing calls an API at import time, and `--dry-run` prints the exact prompt
  and input for one story without calling anything.

Usage (from the repo root, in the ai-testing env):
    python -m bench.generate --prompt v1 --dry-run              # free: show the S01 prompt
    python -m bench.generate --prompt v1 --run 1                # all 10 stories
    python -m bench.generate --prompt v1 --run 1 --stories S01,S05

Change history:
  2026-10-23  v1  first version (Day 4).
  2026-10-23  v2  per-story fingerprints saved in each record.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from bench.golden import ROOT, load_golden, load_prompt, story_card, story_fingerprints
from bench.testcase_schema import check_cases, parse_reply

GENERATOR_MODEL = "gpt-6-luna"   # cheap model, system under test (as Days 2 and 3)
RESULTS_DIR = ROOT / "results" / "testgen"


def make_client():
    from dotenv import load_dotenv
    from openai import OpenAI
    load_dotenv()
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"])


def call_generator(card: str, prompt_text: str, client, model: str) -> tuple[str, dict]:
    """One LLM call for one story. Returns (reply text, usage). Retries an API error once."""
    for attempt in (1, 2):
        try:
            start = time.perf_counter()
            response = client.responses.create(model=model, instructions=prompt_text, input=card)
            latency = time.perf_counter() - start
            usage = getattr(response, "usage", None)
            return response.output_text.strip(), {
                "latency_s": round(latency, 2),
                "input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
                "attempts": attempt,
            }
        except Exception:
            if attempt == 2:
                raise
            time.sleep(5)


def generate_story(story: dict, prompt_text: str, client, model: str) -> dict:
    """Generate, parse and schema-check one story. Returns the record that is saved."""
    reply, usage = call_generator(story_card(story), prompt_text, client, model)
    parsed, info = parse_reply(reply)
    issues = check_cases(parsed, story) if parsed is not None else [info["error"]]
    cases = parsed.get("test_cases") if parsed else None
    return {
        "story_id": story["story_id"],
        "story_fingerprints": story_fingerprints(story),
        "raw_reply": reply,
        "parsed": parsed,
        "parse_info": info,
        "schema_issues": issues,
        "schema_valid": parsed is not None and not issues,
        "n_cases": len(cases) if isinstance(cases, list) else 0,
        "usage": usage,
    }


def run(prompt_version: str, run_label: str, model: str = GENERATOR_MODEL,
        story_ids: list[str] | None = None, client=None) -> Path:
    """Generate test cases for the chosen stories and save one results file."""
    golden = load_golden()
    prompt_text, prompt_fp = load_prompt(prompt_version)
    stories = [s for s in golden["stories"] if not story_ids or s["story_id"] in story_ids]
    if story_ids and len(stories) != len(story_ids):
        raise SystemExit(f"Unknown story IDs in {story_ids}")
    client = client or make_client()

    started = datetime.now(timezone.utc)
    records = []
    for story in stories:
        rec = generate_story(story, prompt_text, client, model)
        records.append(rec)
        u = rec["usage"]
        print(f"{rec['story_id']}  cases {rec['n_cases']:>3}  "
              f"schema {'ok ' if rec['schema_valid'] else 'BAD'}  "
              f"strict JSON {'yes' if rec['parse_info']['strict_json'] else 'no '}  "
              f"tokens {u['input_tokens']}/{u['output_tokens']}  {u['latency_s']} s")

    meta = {
        "started_utc": started.isoformat(timespec="seconds"),
        "model": model,
        "prompt_version": prompt_version,
        "prompt_fingerprint": prompt_fp,
        "golden_version": golden["version"],
        "golden_fingerprint": golden["_fingerprint"],
        "run_label": run_label,
        "stories": [r["story_id"] for r in records],
        "totals": {
            "cases": sum(r["n_cases"] for r in records),
            "schema_valid": sum(r["schema_valid"] for r in records),
            "input_tokens": sum(r["usage"]["input_tokens"] or 0 for r in records),
            "output_tokens": sum(r["usage"]["output_tokens"] or 0 for r in records),
            "latency_s": round(sum(r["usage"]["latency_s"] for r in records), 1),
        },
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    subset = "" if not story_ids else "_" + "-".join(story_ids)
    out = RESULTS_DIR / (f"gen_{prompt_version}_{model}_g{golden['version']}"
                         f"_r{run_label}{subset}_{stamp}.json")
    if out.exists():
        raise SystemExit(f"{out.name} already exists; not overwriting")
    out.write_text(json.dumps({"meta": meta, "records": records}, indent=2, ensure_ascii=False),
                   encoding="utf-8")

    t = meta["totals"]
    print(f"\n{len(records)} stories, {t['cases']} cases, schema valid {t['schema_valid']}/{len(records)}, "
          f"tokens {t['input_tokens']}/{t['output_tokens']}, {t['latency_s']} s")
    print(f"saved {out.relative_to(ROOT)}")
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="Day 4 test-case generator")
    p.add_argument("--prompt", required=True, choices=["v1", "v2"])
    p.add_argument("--run", default="1", help="run label, e.g. 1, 2, 3")
    p.add_argument("--model", default=GENERATOR_MODEL)
    p.add_argument("--stories", help="comma-separated story IDs, e.g. S01,S05 (default: all)")
    p.add_argument("--dry-run", action="store_true", help="print the prompt and one story card; no API call")
    a = p.parse_args()
    story_ids = a.stories.split(",") if a.stories else None

    if a.dry_run:
        golden = load_golden()
        text, fp = load_prompt(a.prompt)
        story = next(s for s in golden["stories"] if s["story_id"] == (story_ids or ["S01"])[0])
        print(f"=== instructions (prompt {a.prompt}, fingerprint {fp})\n{text}\n")
        print(f"=== input (golden v{golden['version']}, fingerprint {golden['_fingerprint']})\n{story_card(story)}")
        return
    run(a.prompt, a.run, a.model, story_ids)


if __name__ == "__main__":
    main()
