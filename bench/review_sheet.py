"""review_sheet.py: build the error-analysis review sheet for a generation run. Free.

One HTML page per run: each story's generated cases on the left, its acceptance
criteria and the expected ideas on the right, coloured by technique label. It is
the material for error analysis (reading real outputs before deciding what to
measure) and the reference for filling in the calibration recall sheet.

It shows no judge verdicts, so it is safe to use while labelling blind.

Usage (from the repo root):
    python -m bench.review_sheet results/testgen/gen_v1_..._r1_....json
    -> results/testgen/review_<run>.html

Change history:
  2026-10-28  v1  first version (Day 4); the 2026-10-23 sheet was made with the same layout.
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

from bench.golden import ROOT, load_golden

RESULTS_DIR = ROOT / "results" / "testgen"

CSS = """
:root{--bg:#fff;--fg:#2C2C2A;--mut:#5F5E5A;--line:#D3D1C7;--card:#F1EFE8;--pos:#E1F5EE;--neg:#FAECE7;--bnd:#EEEDFE}
@media (prefers-color-scheme:dark){:root{--bg:#1f1f1d;--fg:#eceae2;--mut:#b4b2a9;--line:#444441;--card:#2C2C2A;--pos:#085041;--neg:#712B13;--bnd:#3C3489}}
body{background:var(--bg);color:var(--fg);font:14px/1.5 'Segoe UI',Helvetica,Arial,sans-serif;margin:0;padding:16px;max-width:1200px}
h1{font-size:20px;margin:0 0 4px} h2{font-size:17px;margin:28px 0 6px;border-top:1px solid var(--line);padding-top:16px}
.meta,.mut{color:var(--mut);font-size:12.5px} .grid{display:grid;grid-template-columns:3fr 2fr;gap:16px}
@media(max-width:800px){.grid{grid-template-columns:1fr}}
table{border-collapse:collapse;width:100%;font-size:13px} th,td{border:1px solid var(--line);padding:5px 7px;vertical-align:top;text-align:left} th{background:var(--card)}
.positive{background:var(--pos)} .negative{background:var(--neg)} .boundary{background:var(--bnd)} .tag{font-size:11.5px;border-radius:4px;padding:1px 5px;white-space:nowrap}
ul{margin:4px 0;padding-left:20px} code{font-family:Consolas,Menlo,monospace;font-size:12px}
"""


def build(gen_path: Path) -> Path:
    run = json.loads(gen_path.read_text(encoding="utf-8"))
    stories = {s["story_id"]: s for s in load_golden()["stories"]}
    m, e = run["meta"], html.escape
    out = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
           f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
           f"<title>Review sheet: {e(m['prompt_version'])} run {e(m['run_label'])}</title><style>{CSS}</style></head><body>"
           f"<h1>Review sheet: prompt {e(m['prompt_version'])}, run {e(m['run_label'])}</h1>"
           f"<p class='meta'>Model <code>{e(m['model'])}</code> · prompt <code>{e(m['prompt_fingerprint'])}</code> · "
           f"golden v{e(m['golden_version'])} <code>{e(m['golden_fingerprint'])}</code> · {e(m['started_utc'])} · "
           f"{m['totals']['cases']} cases · tokens {m['totals']['input_tokens']} in / {m['totals']['output_tokens']} out</p>"
           f"<p class='mut'>Left: the generated cases (technique and covers are the generator's own labels). "
           f"Right: the story's ACs and the expected ideas, which the generator never saw. No judge verdicts are shown.</p>"]
    for rec in run["records"]:
        s = stories[rec["story_id"]]
        cases = (rec.get("parsed") or {}).get("test_cases") or []
        rows = "".join(
            f"<tr><td><code>{e(c.get('case_id', ''))}</code></td>"
            f"<td><span class='tag {e(c.get('technique', ''))}'>{e(c.get('technique', ''))}</span><br>"
            f"<span class='mut'>{', '.join(map(e, c.get('covers', [])))}</span></td>"
            f"<td><b>{e(c.get('title', ''))}</b><br><span class='mut'>Pre:</span> {e(' | '.join(c.get('preconditions', [])))}"
            f"<br><span class='mut'>Steps:</span> {e(' | '.join(c.get('steps', [])))}</td>"
            f"<td>{e(c.get('expected_result', ''))}</td></tr>" for c in cases)
        if not cases:
            rows = f"<tr><td colspan='4'>No usable cases: {e('; '.join(rec.get('schema_issues', [])))}</td></tr>"
        acs = "".join(f"<li><b>{e(a['ac_id'])}</b> {e(a['text'])}</li>" for a in s["acceptance_criteria"])
        ideas = "".join(f"<li><span class='tag {e(i['technique'])}'>{e(i['technique'])}</span> "
                        f"<code>{e(i['idea_id'])}</code> <span class='mut'>{', '.join(i['ac_ids'])}</span> {e(i['idea'])}</li>"
                        for i in s["expected_ideas"])
        out.append(f"<h2>{e(s['story_id'])} {e(s['title'])}: {len(cases)} cases, {len(s['expected_ideas'])} expected ideas</h2>"
                   f"<div class='grid'><table><tr><th>Case</th><th>Technique / covers</th><th>Case</th>"
                   f"<th>Expected result</th></tr>{rows}</table>"
                   f"<div><b>Acceptance criteria</b><ul>{acs}</ul><b>Expected ideas</b><ul>{ideas}</ul></div></div>")
    out.append("</body></html>")
    stem = gen_path.stem.removeprefix("gen_").rsplit("_", 1)[0]
    path = RESULTS_DIR / f"review_{stem}.html"
    path.write_text("".join(out), encoding="utf-8")
    print(f"saved {path.relative_to(ROOT)}")
    return path


def main() -> None:
    p = argparse.ArgumentParser(description="Build the error-analysis review sheet for a run")
    p.add_argument("gen_file")
    build(Path(p.parse_args().gen_file))


if __name__ == "__main__":
    main()
