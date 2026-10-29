"""ci_report.py: record gate results and report them, for the CI scripts.

Each CI script builds a list of Gate results, then calls report(). That
- prints a table to the console,
- adds the same table to the GitHub Actions run summary (when $GITHUB_STEP_SUMMARY is set),
- saves the gates as JSON under results/ci_gates/ (committed by CI, so every week's
  pass/fail record stays in the repo),
- returns the exit code: 1 if any HARD gate failed, else 0. WARN gates never fail the run.

Change history:
  2026-10-29  v1  first version (Day 5).
  2026-10-29  v2  gates saved to results/ci_gates/ (committed) instead of results/ci/ (artifact only);
                  file name includes the GitHub run number when there is one.
  2026-10-29  v3  run label taken from $CI_RUN_LABEL (evals-N or bench-N, set by each workflow),
                  because the two workflows number their runs separately.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from bench.golden import ROOT

GATES_DIR = ROOT / "results" / "ci_gates"


@dataclass
class Gate:
    name: str          # what is checked, in plain words
    level: str         # "HARD" or "WARN"
    passed: bool
    actual: str        # what was measured
    expected: str      # the threshold


def _table(gates: list[Gate]) -> str:
    rows = ["| Result | Level | Gate | Measured | Threshold |", "|---|---|---|---|---|"]
    for g in gates:
        mark = "pass" if g.passed else ("**FAIL**" if g.level == "HARD" else "warn")
        rows.append(f"| {mark} | {g.level} | {g.name} | {g.actual} | {g.expected} |")
    return "\n".join(rows)


def report(suite: str, gates: list[Gate], notes: list[str] | None = None, extra: dict | None = None) -> int:
    hard_fail = [g for g in gates if g.level == "HARD" and not g.passed]
    warns = [g for g in gates if g.level == "WARN" and not g.passed]
    verdict = "FAILED" if hard_fail else ("passed with warnings" if warns else "passed")

    text = f"### {suite}: {verdict}\n\n{_table(gates)}\n"
    if notes:
        text += "\n" + "\n".join(f"- {n}" for n in notes) + "\n"
    print(text)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(text + "\n")

    GATES_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = suite.lower().split(":")[0].replace(" ", "_")
    label = os.environ.get("CI_RUN_LABEL")       # e.g. evals-12 or bench-3; unset when run locally
    out = GATES_DIR / f"gates_{slug}_{label + '_' if label else ''}{stamp}.json"
    out.write_text(json.dumps({"suite": suite, "verdict": verdict, "gates": [asdict(g) for g in gates],
                               "notes": notes or [], **(extra or {})}, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    print(f"saved {out.relative_to(ROOT)}")
    return 1 if hard_fail else 0
