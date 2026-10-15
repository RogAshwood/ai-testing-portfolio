"""
Build the test cases for judge validation (promptfoo/judge_validation.yaml).

Usage (from the repo root, with the ai-testing environment active):
    python build_judge_cases.py

Why this exists
---------------
To measure a judge fairly, every version of the rubric must judge exactly the same summaries,
and those summaries must have a human label. A normal eval run would ask the triage models for
new answers, so the summaries would change. Instead, this script collects outputs that already
exist, and the judge-validation config replays them through Promptfoo's echo provider.

Inputs
    results/judge_labels.csv          the 24 sampled summaries with your labels (section 9a/9b)
    results/promptfoo_v3.json         the run they were sampled from, to recover the exact output
    datasets/judge_seeded_summaries.csv   deliberately flawed summaries (expected label: fail)
    datasets/claim_triage.csv         the full claim records the judge needs to see

Output
    results/judge_validation_cases.csv    one row per case, read by promptfoo/judge_validation.yaml
"""
import csv
import json
import sys
from pathlib import Path

LABELS = Path("results/judge_labels.csv")
RESULTS = Path("results/promptfoo_v3.json")
SEEDED = Path("datasets/judge_seeded_summaries.csv")
CLAIMS = Path("datasets/claim_triage.csv")
OUT = Path("results/judge_validation_cases.csv")

# Claim record fields shown to the judge (same list as the rubric)
RECORD_FIELDS = ["claim_id", "policy_start_date", "treatment_date", "submission_date",
                 "treatment_description", "amount_claimed", "receipt_attached", "referral_attached",
                 "preauth_number", "used_this_year", "claimant_note"]


def read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:   # utf-8-sig copes with a BOM added by Excel
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# Step 1: Load the claim records, keyed by claim_id
# ---------------------------------------------------------------------------
claims = {c["claim_id"]: c for c in read_csv(CLAIMS)}

# ---------------------------------------------------------------------------
# Step 2: Index the original model outputs by claim, prompt and model
# The sampled summaries came from this run. Re-using the exact output string means the judge
# sees exactly what it saw the first time, including the category field.
# ---------------------------------------------------------------------------
original = {}
raw = json.loads(RESULTS.read_text(encoding="utf-8"))
for r in raw["results"]["results"]:
    key = (r["vars"]["claim_id"],
           r["prompt"]["label"].split(":")[0],
           r["provider"].get("label") or r["provider"]["id"])
    original[key] = (r.get("response") or {}).get("output")

cases = []

# ---------------------------------------------------------------------------
# Step 3: Sampled summaries (human-labelled in section 9b)
# ---------------------------------------------------------------------------
for s in read_csv(LABELS):
    label = s["human_label"].strip().lower()
    if label not in ("pass", "fail"):
        sys.exit(f"{s['sample_id']} has no pass/fail label. Finish labelling in {LABELS} first.")

    output = original.get((s["claim_id"], s["prompt"], s["model"]))
    if isinstance(output, dict):
        output = json.dumps(output)
    # Safety check: the recovered output must contain the summary that was labelled
    if not output or json.loads(output).get("summary") != s["summary"]:
        sys.exit(f"{s['sample_id']}: could not find the labelled output in {RESULTS}. "
                 "Was the file replaced after section 9a ran?")

    cases.append({
        "case_id": s["sample_id"],
        "case_type": "sampled",
        "source": f"{s['prompt']} / {s['model']}",
        "human_label": label,
        "human_notes": s.get("human_notes", ""),
        "model_output": output,
        **{k: claims[s["claim_id"]][k] for k in RECORD_FIELDS},
    })

# ---------------------------------------------------------------------------
# Step 4: Seeded summaries (written to break one rubric criterion each; expected label: fail)
# The routing and reason code are the correct ones from the dataset, so the summary is the
# only thing wrong.
# ---------------------------------------------------------------------------
for s in read_csv(SEEDED):
    claim = claims[s["claim_id"]]
    output = json.dumps({
        "claim_id": s["claim_id"],
        "category": claim["expected_category"],
        "routing": s["routing"],
        "reason_code": s["reason_code"],
        "summary": s["summary"],
    })
    cases.append({
        "case_id": s["case_id"],
        "case_type": "seeded",
        "source": "seeded defect",
        "human_label": "fail",
        "human_notes": f"Criterion {s['criterion_broken']}: {s['seeded_defect']}",
        "model_output": output,
        **{k: claim[k] for k in RECORD_FIELDS},
    })

# ---------------------------------------------------------------------------
# Step 5: Write the cases file for Promptfoo
# __description is a Promptfoo column: it names each test in the results viewer.
# ---------------------------------------------------------------------------
for c in cases:
    c["__description"] = f"{c['case_id']} {c['claim_id']} ({c['source']})"

with open(OUT, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=list(cases[0].keys()))
    writer.writeheader()
    writer.writerows(cases)

n_sampled = sum(c["case_type"] == "sampled" for c in cases)
print(f"Wrote {len(cases)} cases to {OUT}: {n_sampled} sampled, {len(cases) - n_sampled} seeded.")
