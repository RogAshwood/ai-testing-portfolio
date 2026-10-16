"""
validate_golden.py: checks the Day 3 RAG golden set against the policy documents.

The policy documents in datasets/policy_docs/ are the test basis for Day 3.
The golden set (datasets/rag_golden.csv) is the oracle. This script checks the
oracle is consistent with the test basis before any model is run, the same role
validate_dataset.py played on Day 2.

Checks:
  1. Required columns present, question_id unique, question_type allowed.
  2. Every expected source names a document that exists.
  3. Answerable questions (standard, adversarial, refusal) have at least one
     expected source and every key fact appears in at least one of them
     (case-insensitive substring).
  4. Unanswerable questions have no expected source and no key facts, and none
     of their absent_terms appears in ANY document, so they really are
     unanswerable from the corpus.

Key facts and absent terms are matched as case-insensitive substrings after
whitespace is normalised, so "gym membership" also matches "Gym Membership".
List each word form you want to rule out (for example "pregnancy" and
"pregnant") rather than relying on a partial stem.

Usage:  python datasets/validate_golden.py
Exit code 0 when all checks pass, 1 otherwise.

Change history:
  2026-10-16  v1  first version (Day 3).
  2026-10-16  v1.1  normalise whitespace and Markdown bold before matching;
                    v1 false-failed 3 facts wrapped across lines.
  2026-10-16  v1.2  docstring: document substring matching; golden set Q10
                    absent terms use full words (pregnancy, pregnant).
  2026-10-16  golden set: key facts added to Q03 ("referral from a GP or
                    consultant") and Q15 ("referral from your GP") so the
                    derived correct context covers every detail in their
                    expected answers. Total key facts 25 -> 27.
"""

import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DOCS_DIR = HERE / "policy_docs"
GOLDEN = HERE / "rag_golden.csv"

REQUIRED_COLUMNS = [
    "question_id", "question_type", "test_focus", "question",
    "expected_answer", "expected_sources", "key_facts", "absent_terms",
]
ALLOWED_TYPES = {"standard", "unanswerable", "adversarial", "refusal"}


def split_list(value: str) -> list[str]:
    """Split a semicolon-separated cell into a list, ignoring blanks."""
    return [part.strip() for part in value.split(";") if part.strip()]


def normalise(text: str) -> str:
    """Lower-case, drop Markdown bold markers and collapse whitespace, so a
    phrase wrapped across lines in the source file still matches."""
    return " ".join(text.replace("**", "").lower().split())


def main() -> int:
    # Load the corpus: document id (file stem) -> normalised text
    docs = {p.stem: normalise(p.read_text(encoding="utf-8"))
            for p in sorted(DOCS_DIR.glob("*.md"))}
    print(f"Loaded {len(docs)} policy documents from {DOCS_DIR.name}/")

    with GOLDEN.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        missing_cols = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        rows = list(reader)

    errors: list[str] = []
    if missing_cols:
        errors.append(f"Missing columns: {missing_cols}")

    # Check 1: unique IDs and allowed types
    ids = [r["question_id"] for r in rows]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        errors.append(f"Duplicate question_id: {sorted(dupes)}")

    for r in rows:
        qid, qtype = r["question_id"], r["question_type"]
        sources = split_list(r["expected_sources"])
        facts = split_list(r["key_facts"])
        absent = split_list(r["absent_terms"])

        if qtype not in ALLOWED_TYPES:
            errors.append(f"{qid}: question_type '{qtype}' not allowed")
            continue

        # Check 2: sources exist
        for s in sources:
            if s not in docs:
                errors.append(f"{qid}: expected source '{s}' not found")

        if qtype == "unanswerable":
            # Check 4: no sources or facts, and absent terms really absent
            if sources or facts:
                errors.append(f"{qid}: unanswerable question has sources or key facts")
            if not absent:
                errors.append(f"{qid}: unanswerable question has no absent_terms")
            for term in absent:
                hits = [d for d, text in docs.items() if normalise(term) in text]
                if hits:
                    errors.append(f"{qid}: absent term '{term}' found in {hits}")
        else:
            # Check 3: answerable questions are supported by their sources
            if not sources:
                errors.append(f"{qid}: answerable question has no expected source")
            if not facts:
                errors.append(f"{qid}: answerable question has no key facts")
            source_text = " ".join(docs.get(s, "") for s in sources)
            for fact in facts:
                if normalise(fact) not in source_text:
                    errors.append(f"{qid}: key fact '{fact}' not in {sources}")

    # Summary table by question type
    print(f"Loaded {len(rows)} golden questions")
    for t in sorted(ALLOWED_TYPES):
        print(f"  {t:<13} {sum(r['question_type'] == t for r in rows)}")
    cited = {s for r in rows for s in split_list(r["expected_sources"])}
    print(f"Documents cited as a source: {len(cited)}/{len(docs)}; "
          f"never cited: {sorted(set(docs) - cited)}")

    if errors:
        print(f"\nFAIL: {len(errors)} problem(s)")
        for e in errors:
            print("  -", e)
        return 1
    print(f"\nPASS: {len(rows)}/{len(rows)} questions consistent with the policy documents")
    return 0


if __name__ == "__main__":
    sys.exit(main())
