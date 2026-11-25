"""generate.py: generate test cases for ANY stories file, with the Day 4 v1/v2 prompts or the bare prompt.

Why: the Day 4 generator (bench/generate.py) and harness/generate_bare.py both read the insurance
golden set (datasets/testgen_golden.json) only. Step 5 needs the same generators run on a second
domain (datasets/aml_kyc_stories.json). bench/ is left unchanged (it is the Day 4 benchmark and
starts the CI workflow); this module reuses its generator call so the only differences between
runs are the prompt and the stories.

  --prompt v1 / v2   bench/prompts/testgen_v1.txt / testgen_v2.txt, checked against the strict Day 4
                     contract (bench/testcase_schema.check_cases: technique labels, AC IDs)
  --prompt bare      harness/prompts/testgen_bare.txt ("write test cases" + the JSON format), checked
                     against the harness input contract only

Same model (gpt-6-luna), one call per story, the same story card. Stories run in parallel
(--workers, default 4); the results keep story order.

Usage (repo root, ai-testing env; one line each; paid, about $0.01-0.02 per prompt for 12 stories):
    python -m harness.generate --prompt v2 --stories-file datasets/aml_kyc_stories.json
    python -m harness.generate --prompt bare --stories-file datasets/aml_kyc_stories.json
    python -m harness.generate --prompt v2 --stories-file datasets/aml_kyc_stories.json --only K11,K12
Writes results/m7/gen_<prompt>_<model>_<stories file name>_<UTC time>.json in the Day 4
generation-file shape, so it can be checked directly:
    python -m harness.check --stories datasets/aml_kyc_stories.json --cases results/m7/gen_v2_<...>.json

Change history:
  2026-11-24  v1  first version (M7 step 5).
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from bench import generate as day4
from bench.golden import ROOT, fingerprint, load_prompt
from bench.pricing import cost_usd
from harness import generate_bare

OUT_DIR = ROOT / "results" / "m7"
PROMPTS = ("v1", "v2", "bare")


def load_stories_file(path: Path) -> dict:
    """The stories file (same shape as testgen_golden.json), with its fingerprint added."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    data["_fingerprint"] = fingerprint(Path(path))
    return data


def prompt_for(name: str) -> tuple[str, str, object]:
    """Prompt text, fingerprint and the function that generates one story with it:
    the Day 4 one (strict contract) for v1/v2, the harness one for bare."""
    if name == "bare":
        text, fp = generate_bare.load_bare_prompt()
        return text, fp, generate_bare.generate_story
    text, fp = load_prompt(name)
    return text, fp, day4.generate_story


def run(prompt: str, stories_file: Path, only: list[str] | None = None, client=None,
        model: str = day4.GENERATOR_MODEL, workers: int = 4) -> Path:
    """Generate for the chosen stories and save one results file. Returns its path."""
    data = load_stories_file(stories_file)
    stories = [s for s in data["stories"] if not only or s["story_id"] in only]
    if only and len(stories) != len(only):
        raise SystemExit(f"unknown story IDs in {only}")
    if client is None:
        client = day4.make_client()                       # reads OPENAI_API_KEY from .env
    text, fp, generate_one = prompt_for(prompt)
    started = datetime.now(timezone.utc)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        records = list(pool.map(lambda s: generate_one(s, text, client, model), stories))   # story order kept
    tokens_in = sum(r["usage"]["input_tokens"] or 0 for r in records)
    tokens_out = sum(r["usage"]["output_tokens"] or 0 for r in records)
    meta = {"started_utc": started.isoformat(timespec="seconds"), "model": model, "prompt_version": prompt,
            "prompt_fingerprint": fp, "stories_file": Path(stories_file).name,
            "golden_version": data.get("version"), "golden_fingerprint": data["_fingerprint"],
            "stories": [s["story_id"] for s in stories],
            "totals": {"cases": sum(r["n_cases"] for r in records),
                       "schema_valid": sum(r["schema_valid"] for r in records),
                       "input_tokens": tokens_in, "output_tokens": tokens_out,
                       "cost_usd": cost_usd(model, tokens_in, tokens_out),
                       "latency_s": round(sum(r["usage"]["latency_s"] or 0 for r in records), 1)}}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"gen_{prompt}_{model}_{Path(stories_file).stem}_{started.strftime('%Y%m%dT%H%M%SZ')}.json"
    out.write_text(json.dumps({"meta": meta, "records": records}, indent=1, ensure_ascii=False), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    """Parse the command line, generate, and print one line per story and a total."""
    p = argparse.ArgumentParser(description="Generate test cases for a stories file.")
    p.add_argument("--prompt", required=True, choices=PROMPTS, help="v1, v2 (Day 4 prompts) or bare")
    p.add_argument("--stories-file", required=True, type=Path, help="stories JSON file, e.g. datasets/aml_kyc_stories.json")
    p.add_argument("--only", help="comma-separated story IDs (default: all)")
    p.add_argument("--workers", type=int, default=4, help="stories generated at the same time (default 4)")
    args = p.parse_args(argv)
    out = run(args.prompt, args.stories_file, [s.strip() for s in args.only.split(",")] if args.only else None,
              workers=args.workers)
    data = json.loads(out.read_text(encoding="utf-8"))
    for r in data["records"]:
        status = "valid" if r["schema_valid"] else "issues: " + "; ".join(r["schema_issues"][:2])
        print(f"{r['story_id']}  cases {r['n_cases']:>3}  {r['usage']['latency_s']:>5} s  {status}")
    t = data["meta"]["totals"]
    print(f"{t['cases']} cases, {t['schema_valid']}/{len(data['records'])} stories valid, "
          f"${t['cost_usd']}, {t['latency_s']} s of model time")
    print(f"saved {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
