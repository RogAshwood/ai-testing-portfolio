"""
rag_metrics.py: deterministic helpers for evaluating the Day 3 RAG pipeline.

No LLM calls here. Shared by the notebook 02_deepeval_rag_component_vs_e2e.ipynb
and tests/test_rag.py so both measure the same way.

- load_golden()         the golden set (oracle) as a list of dicts
- golden_context()      the "correct chunks" for a question, derived mechanically
- key_fact_recall()     share of a question's key facts present in some text
- retriever_report()    deterministic retriever metrics for one configuration

Change history:
  2026-10-16  v1  first version (Day 3).
"""

from __future__ import annotations

import csv
from pathlib import Path

from rag_pipeline import Chunk, TfidfRetriever

GOLDEN_PATH = Path(__file__).resolve().parent / "datasets" / "rag_golden.csv"


def split_list(value: str) -> list[str]:
    """Split a semicolon-separated golden-set cell into a list."""
    return [p.strip() for p in value.split(";") if p.strip()]


def normalise(text: str) -> str:
    """Lower-case, drop Markdown bold and collapse whitespace (same rule as
    datasets/validate_golden.py, so facts are matched consistently)."""
    return " ".join(text.replace("**", "").lower().split())


def load_golden(path: Path = GOLDEN_PATH) -> list[dict]:
    """Golden questions with list fields already split."""
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for col in ("expected_sources", "key_facts", "absent_terms"):
            r[col] = split_list(r[col])
    return rows


def is_answerable(row: dict) -> bool:
    return row["question_type"] != "unanswerable"


def key_fact_recall(facts: list[str], texts: list[str]) -> float:
    """Share of key facts that appear (normalised substring) in the joined texts."""
    if not facts:
        return float("nan")
    joined = normalise(" ".join(texts))
    return sum(normalise(f) in joined for f in facts) / len(facts)


def golden_context(row: dict, chunks: list[Chunk]) -> list[Chunk]:
    """The correct chunks for a question: chunks from its expected source
    documents that contain at least one of its key facts. Derived, not
    hand-picked, so the generator-only test cannot be tuned by hand.
    Returns [] for unanswerable questions."""
    sources, facts = row["expected_sources"], row["key_facts"]
    return [c for c in chunks
            if c.doc_id in sources
            and any(normalise(f) in normalise(c.text) for f in facts)]


def retriever_report(retriever: TfidfRetriever, golden: list[dict],
                     k: int) -> list[dict]:
    """One row per answerable question: rank of the first correct-document
    chunk, doc hit@k, key-fact recall in the top k, and the retrieved ids."""
    rows = []
    for g in filter(is_answerable, golden):
        chunks, scores = retriever.retrieve(g["question"], k)
        rank = retriever.doc_rank(g["question"], g["expected_sources"])
        recall = key_fact_recall(g["key_facts"], [c.text for c in chunks])
        rows.append({
            "question_id": g["question_id"],
            "question_type": g["question_type"],
            "k": k,
            "doc_rank": rank,
            "doc_hit": rank is not None and rank <= k,
            "key_fact_recall": recall,
            "all_facts_present": recall == 1.0,
            "retrieved": [c.chunk_id for c in chunks],
        })
    return rows
