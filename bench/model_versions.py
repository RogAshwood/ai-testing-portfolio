"""model_versions.py: record which model version the provider actually served (M1).

A model name such as `gpt-6-luna` is an alias: the provider can change the model behind it
without notice. Each CI run starts with one minimal call per model and records the version the
API reports it served (`response.model`). If that differs from the last recorded version for
the same name, a WARN gate says so; it never fails the run.

    one tiny call per model --> served version --> results/model_versions.csv (one row per model per run)
                                               --> WARN gate "version changed since the last run"

Why a separate probe: Promptfoo and DeepEval make their own API calls and do not keep the served
version in their results, so the probe covers them. The benchmark's own calls (bench/generate.py,
bench/judge.py) also save the served version with every record and history row.

Decision (M1, 2026-11-03): keep the aliases and record the served version, so the history shows
when the model changes. Production would usually pin a dated version for the release model.

Limitation: if the API reports the alias itself rather than a dated version, a silent update
behind the alias cannot be seen. The run summary says so when that happens.

Cost: one call per model, a handful of tokens each (well under $0.001 a run).

Usage (from the repo root, in the ai-testing env):
    python -m bench.model_versions --workflow evals        # models from bench/ci_thresholds.py
    python -m bench.model_versions --workflow benchmark
    python -m bench.model_versions --history               # print the recorded versions; free

Change history:
  2026-11-03  v1  first version (M1).
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from bench import ci_thresholds as T
from bench.ci_report import Gate, report
from bench.golden import ROOT

VERSIONS = ROOT / "results" / "model_versions.csv"
COLUMNS = ["checked_utc", "run_label", "workflow", "model", "served", "error"]
PROBE_INPUT = "Reply with the single word OK."


def probe(model: str, client) -> tuple[str | None, str]:
    """One minimal call. Returns (served version or None, error text or '')."""
    try:
        resp = client.responses.create(model=model, input=PROBE_INPUT, max_output_tokens=16)
        return getattr(resp, "model", None), ""
    except Exception as e:                       # reported as a warning, never fails the run
        return None, f"{type(e).__name__}: {e}"[:200]


def read_versions(path: Path = VERSIONS) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def last_served(rows: list[dict], model: str) -> str | None:
    """The most recent successfully recorded version for this model name, from any workflow."""
    for r in reversed(rows):
        if r["model"] == model and r["served"]:
            return r["served"]
    return None


def append_versions(new_rows: list[dict], path: Path = VERSIONS) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        if new_file:
            w.writeheader()
        w.writerows(new_rows)


def build_gates(results: dict[str, tuple[str | None, str]], history: list[dict]) -> tuple[list[Gate], list[str]]:
    """One WARN gate per model, comparing the served version with the last recorded one."""
    gates, notes = [], []
    for model, (served, error) in results.items():
        before = last_served(history, model)
        if served is None:
            gates.append(Gate(f"{model}: served version recorded", "WARN", False,
                              f"probe failed ({error})", "a version"))
            continue
        if before is None:
            gates.append(Gate(f"{model}: version unchanged since the last run", "WARN", True,
                              served, "(first record)"))
        else:
            gates.append(Gate(f"{model}: version unchanged since the last run", "WARN", served == before,
                              served, before))
        if served == model:
            notes.append(f"{model}: the API reported the alias itself, not a dated version, so a silent "
                         "update behind this name cannot be detected from the response.")
    return gates, notes


def main() -> None:
    p = argparse.ArgumentParser(description="Record the model versions the provider served")
    p.add_argument("--workflow", choices=sorted(T.MODEL_PROBES), help="which CI workflow's models to probe")
    p.add_argument("--history", action="store_true", help="print the recorded versions and stop; no API call")
    a = p.parse_args()

    history = read_versions()
    if a.history or not a.workflow:
        for r in history:
            print(f"{r['checked_utc']}  {r['run_label']:<12} {r['model']:<12} {r['served'] or '-'}  {r['error']}")
        if not history:
            print(f"No versions recorded yet ({VERSIONS.relative_to(ROOT)}).")
        return

    from bench.generate import make_client
    client = make_client()
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    label = os.environ.get("CI_RUN_LABEL", "local")
    results = {m: probe(m, client) for m in T.MODEL_PROBES[a.workflow]}
    gates, notes = build_gates(results, history)
    append_versions([{"checked_utc": stamp, "run_label": label, "workflow": a.workflow, "model": m,
                      "served": served or "", "error": error} for m, (served, error) in results.items()])
    notes.append(f"Recorded in {VERSIONS.relative_to(ROOT)}. Aliases are kept on purpose (M1 decision); "
                 "a changed version is reported, not failed.")
    sys.exit(report(f"Model versions: {a.workflow}", gates, notes))


if __name__ == "__main__":
    main()
