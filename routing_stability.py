"""
Find claims whose routing changes across repeated runs.

Usage (from the repo root, with the ai-testing environment active):
    python routing_stability.py results/promptfoo_repeat3.json

For each claim, prompt and model it lists the routings seen across the repeats,
and flags any combination where the routing was not the same every time.

Outputs:
    - printed list of unstable claim/prompt/model combinations
    - printed stability rate per prompt and model
    - results/routing_stability.csv with the full table (for Notebook 01)
"""
import json
import sys
from collections import Counter

import pandas as pd

# ---------------------------------------------------------------------------
# Step 1: Load the Promptfoo results file
# The file path comes from the command line; it defaults to the repeat-3 run.
# ---------------------------------------------------------------------------
path = sys.argv[1] if len(sys.argv) > 1 else "results/promptfoo_repeat3.json"
with open(path, encoding="utf-8") as f:
    data = json.load(f)

# ---------------------------------------------------------------------------
# Step 2: Extract one row per model response
# Each Promptfoo result is one claim x one prompt x one model x one repeat.
# We keep only what is needed: which claim, which prompt and model, what the
# expected routing was, and what routing the model actually returned.
# ---------------------------------------------------------------------------
rows = []
for r in data["results"]["results"]:
    # Prompt label is stored as "v2-rules: <file>: <prompt text>", so keep the part before the first colon
    prompt = r["prompt"]["label"].split(":")[0]
    # Use the model's label (e.g. "luna-cheap") if set, otherwise its id
    provider = r["provider"].get("label") or r["provider"]["id"]

    # The model's answer is a JSON string. Pull out the routing field.
    # If the answer is not valid JSON, record that instead of crashing,
    # so broken outputs still show up in the stability results.
    output = (r.get("response") or {}).get("output")
    try:
        parsed = json.loads(output) if isinstance(output, str) else output
        routing = parsed.get("routing", "MISSING")
    except Exception:
        routing = "INVALID_JSON"

    rows.append({
        "claim_id": r["vars"]["claim_id"],
        "test_focus": r["vars"].get("test_focus", ""),
        "expected": r["vars"]["expected_routing"],
        "prompt": prompt,
        "model": provider,
        "routing": routing,
    })

df = pd.DataFrame(rows)

# Mark each individual response as correct or not against the oracle
df["correct"] = df["routing"] == df["expected"]

# ---------------------------------------------------------------------------
# Step 3: Group the repeats together and measure stability
# For each claim + prompt + model we calculate:
#   runs      how many responses there were (3 for --repeat 3)
#   distinct  how many different routings appeared (1 = stable)
#   routings  the routings seen and how often, e.g. "auto_approve x2, decline_recommended x1"
#   correct   how many of the runs matched the expected routing
# ---------------------------------------------------------------------------
summary = (
    df.groupby(["claim_id", "test_focus", "expected", "prompt", "model"])
    .agg(runs=("routing", "count"),
         distinct=("routing", "nunique"),
         routings=("routing", lambda s: ", ".join(f"{k} x{v}" for k, v in Counter(s).items())),
         correct=("correct", "sum"))
    .reset_index()
)
# Stable = the model gave the same routing on every run (right or wrong)
summary["stable"] = summary["distinct"] == 1

# ---------------------------------------------------------------------------
# Step 4: Report the unstable combinations
# These are the claims where the same prompt and model gave different routings
# on different runs: the non-determinism findings.
# ---------------------------------------------------------------------------
unstable = summary[~summary["stable"]].sort_values(["prompt", "model", "claim_id"])

pd.set_option("display.width", 200)
pd.set_option("display.max_colwidth", 60)
print(f"\n{len(summary)} claim/prompt/model combinations, {len(unstable)} with routing changes across repeats\n")
if len(unstable):
    print(unstable[["claim_id", "prompt", "model", "expected", "routings", "correct", "runs", "test_focus"]].to_string(index=False))

# ---------------------------------------------------------------------------
# Step 5: Report the overall stability rate per prompt and model
# e.g. "v3-rules-dates  sol-strong  97%" = 97% of claims got the same routing every run
# ---------------------------------------------------------------------------
print("\nStability by prompt and model (share of claims with the same routing every run):")
print(summary.groupby(["prompt", "model"])["stable"].mean().map("{:.0%}".format).to_string())

# ---------------------------------------------------------------------------
# Step 6: Save the full table for Notebook 01
# ---------------------------------------------------------------------------
summary.to_csv("results/routing_stability.csv", index=False)
print("\nFull table saved to results/routing_stability.csv")
