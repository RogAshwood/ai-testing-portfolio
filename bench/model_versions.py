"""model_versions.py: record which model version the provider actually served (M1).

A model name such as `gpt-6-luna` is an alias: the provider can change the model behind it
without notice. Each CI run starts with a few minimal calls per model and records three things:

    served            the model the Responses API says it used (`response.model`)
    chat_served       the same, from the Chat Completions API, which Promptfoo uses
    system_fingerprint  the backend configuration that served the Chat Completions call; the
                      provider documents that it changes when that configuration changes
    dated_available   dated versions of the same name listed by the models endpoint, if any
                      (shows whether pinning a version would be possible)

    calls per model --> results/model_versions.csv (one row per model per run)
                    --> WARN gates: served version / backend fingerprint changed since the last run

A change is reported, never failed. Aliases are kept on purpose (M1 decision, 2026-11-03), so the
history shows when the model changes; production would usually pin a dated version.

Why a separate probe: Promptfoo and DeepEval make their own API calls and do not keep the served
version in their results. The benchmark's own calls (bench/generate.py, bench/judge.py) also save
the served version with every record and history row.

What bench-5 (2026-11-03) showed: the Responses API reports the alias itself, so `served` alone
cannot reveal a silent update. v2 adds the fingerprint and the dated-version list to find out
whether either can.

Cost: two tiny calls per model plus one free models listing (well under $0.001 a run).

Usage (from the repo root, in the ai-testing env):
    python -m bench.model_versions --workflow evals --no-record   # try it: print only, write nothing
    python -m bench.model_versions --workflow evals                # as CI runs it
    python -m bench.model_versions --history                       # print the recorded rows; free

Change history:
  2026-11-03  v1  first version (M1).
  2026-11-03  v2  Chat Completions served model and system_fingerprint, dated versions from the
                  models endpoint, --no-record. Older CSV rows are kept; new columns stay empty.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from bench import ci_thresholds as T
from bench.ci_report import Gate, _table, report
from bench.golden import ROOT

VERSIONS = ROOT / "results" / "model_versions.csv"
COLUMNS = ["checked_utc", "run_label", "workflow", "model", "served", "chat_served",
           "system_fingerprint", "dated_available", "error"]
PROBE_INPUT = "Reply with the single word OK."


def _err(e: Exception) -> str:
    return f"{type(e).__name__}: {e}"[:160]


def probe(model: str, client, listed: list[str] | None) -> dict:
    """Minimal calls for one model. Every field is None or '' if its call fails; nothing raises."""
    out = {"served": None, "chat_served": None, "system_fingerprint": None, "dated_available": None, "error": ""}
    errors = []
    try:
        resp = client.responses.create(model=model, input=PROBE_INPUT, max_output_tokens=16)
        out["served"] = getattr(resp, "model", None)
    except Exception as e:
        errors.append("responses " + _err(e))
    try:
        chat = client.chat.completions.create(model=model, messages=[{"role": "user", "content": PROBE_INPUT}],
                                              max_completion_tokens=16)
        out["chat_served"] = getattr(chat, "model", None)
        out["system_fingerprint"] = getattr(chat, "system_fingerprint", None)
    except Exception as e:
        errors.append("chat " + _err(e))
    if listed is not None:
        dated = sorted(m for m in listed if m.startswith(model + "-"))
        out["dated_available"] = ";".join(dated) if dated else "none"
    out["error"] = " | ".join(errors)
    return out


def list_models(client) -> tuple[list[str] | None, str]:
    """IDs from the models endpoint (free), or (None, error)."""
    try:
        return [m.id for m in client.models.list()], ""
    except Exception as e:
        return None, _err(e)


def read_versions(path: Path = VERSIONS) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def last_value(rows: list[dict], model: str, field: str) -> str | None:
    """The most recent non-empty value of `field` for this model name, from any workflow."""
    for r in reversed(rows):
        if r.get("model") == model and r.get(field):
            return r[field]
    return None


def append_versions(new_rows: list[dict], path: Path = VERSIONS) -> None:
    """Append rows. If the file was written with fewer columns (v1), rewrite it with the
    current columns first, keeping every row; the new columns stay empty for old rows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    old = read_versions(path)
    header = []
    if path.exists():
        with path.open(encoding="utf-8", newline="") as f:
            header = next(csv.reader(f), [])
    mode = "a" if header == COLUMNS else "w"
    with path.open(mode, encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, restval="", extrasaction="ignore")
        if mode == "w":
            w.writeheader()
            w.writerows(old)
        w.writerows(new_rows)


def build_gates(results: dict[str, dict], history: list[dict]) -> tuple[list[Gate], list[str]]:
    """WARN gates per model: served version and backend fingerprint against the last recorded."""
    gates, notes = [], []
    for model, r in results.items():
        if r["error"]:
            notes.append(f"{model}: {r['error']}")
        for field, label in (("served", "served version"), ("system_fingerprint", "backend fingerprint")):
            now, before = r[field], last_value(history, model, field)
            name = f"{model}: {label} unchanged since the last run"
            if not now:
                # Missing after it was seen before: warn. Never returned by this model: report only.
                gates.append(Gate(name, "WARN", before is None, "not returned",
                                  before or "(not available for this model)"))
            else:
                gates.append(Gate(name, "WARN", before is None or now == before, now, before or "(first record)"))
        if r["served"] == model:
            notes.append(f"{model}: the API reports the alias itself as the served model, so a silent update "
                         "cannot be seen from that field" + (" (the backend fingerprint is the check that can)."
                                                             if r["system_fingerprint"] else "."))
        if r["dated_available"] and r["dated_available"] != "none":
            notes.append(f"{model}: dated versions listed: {r['dated_available'].replace(';', ', ')}")
        elif r["dated_available"] == "none":
            notes.append(f"{model}: no dated versions listed, so pinning is not possible for this name.")
    notes.append("The provider changes the backend fingerprint when it changes the serving configuration; it can "
                 "also change for reasons that do not affect behaviour, so a change is a prompt to look at the "
                 "scores, not proof of drift.")
    return gates, notes


def main() -> None:
    p = argparse.ArgumentParser(description="Record the model versions the provider served")
    p.add_argument("--workflow", choices=sorted(T.MODEL_PROBES), help="which CI workflow's models to probe")
    p.add_argument("--no-record", action="store_true", help="print the results only; write no files")
    p.add_argument("--history", action="store_true", help="print the recorded rows and stop; no API call")
    a = p.parse_args()

    history = read_versions()
    if a.history or not a.workflow:
        for r in history:
            print(f"{r['checked_utc']}  {r['run_label']:<10} {r['model']:<11} served {r.get('served') or '-'}  "
                  f"fingerprint {r.get('system_fingerprint') or '-'}  dated {r.get('dated_available') or '-'}")
        if not history:
            print(f"No versions recorded yet ({VERSIONS.relative_to(ROOT)}).")
        return

    from bench.generate import make_client
    client = make_client()
    listed, list_error = list_models(client)
    results = {m: probe(m, client, listed) for m in T.MODEL_PROBES[a.workflow]}
    if list_error:
        for r in results.values():
            r["error"] = " | ".join(x for x in (r["error"], "models " + list_error) if x)
    gates, notes = build_gates(results, history)
    suite = f"Model versions: {a.workflow}"

    if a.no_record:
        print(f"### {suite} (--no-record: nothing written)\n\n{_table(gates)}\n")
        print("\n".join(f"- {n}" for n in notes))
        for m, r in results.items():
            print(f"\n{m}: " + ", ".join(f"{k}={v!r}" for k, v in r.items()))
        return

    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    label = os.environ.get("CI_RUN_LABEL", "local")
    append_versions([{"checked_utc": stamp, "run_label": label, "workflow": a.workflow, "model": m,
                      **{k: (v or "") for k, v in r.items()}} for m, r in results.items()])
    notes.append(f"Recorded in {VERSIONS.relative_to(ROOT)}. Aliases are kept on purpose (M1 decision); "
                 "a change is reported, not failed.")
    sys.exit(report(suite, gates, notes))


if __name__ == "__main__":
    main()
