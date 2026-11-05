"""
chatbot/policy.py: the retriever behind search_policy (M5). The only RAG part of the bot.

What it does
------------
Builds the same TF-IDF retriever as Day 3 (from rag_pipeline.py: paragraph
chunks, top 3), but over a slightly different set of documents:

  documents 01 to 09   from datasets/policy_docs/   (Day 3, unchanged)
  document 10          from datasets/chatbot_docs/  (M5 version)

The M5 document 10 replaces the Day 3 one because the Day 3 text says the
assistant "cannot see your claims", which is no longer true for the M5 bot
(spec section 7). Day 3 files are only read, never changed, so the Day 3 bot
and its tests are unaffected.

Change history:
  2026-11-05  v1  first version (M5).
  2026-11-05  v1.1  comments expanded; no code change.
"""
from __future__ import annotations

from pathlib import Path

# All Day 3 building blocks, imported unchanged. _clean is the Day 3 helper that
# removes the "fictional data" banner and bold markers before indexing; using it
# here means the M5 document 10 is cleaned exactly like the Day 3 documents.
from rag_pipeline import DEFAULT_K, DOCS_DIR, TfidfRetriever, _clean, chunk_docs, load_docs

M5_DOCS_DIR = Path(__file__).resolve().parent.parent / "datasets" / "chatbot_docs"


def load_m5_docs() -> dict[str, str]:
    """The M5 corpus: {document ID: cleaned text} for all ten documents.

    Starts from the Day 3 documents, then replaces any document that has a file
    of the same name in datasets/chatbot_docs/ (today only document 10). A file
    there that matches no Day 3 document is an error, so a typo in a file name
    can't quietly add an extra document.
    """
    docs = load_docs(DOCS_DIR)
    for p in sorted(M5_DOCS_DIR.glob("*.md")):
        if p.stem not in docs:
            raise ValueError(f"{p.name} does not replace a Day 3 document")
        docs[p.stem] = _clean(p.read_text(encoding="utf-8"))
    return docs


def build_m5_retriever() -> TfidfRetriever:
    """The Day 3 TF-IDF retriever, indexed over the M5 corpus with paragraph chunks."""
    return TfidfRetriever(chunk_docs(load_m5_docs(), mode="paragraph"))


__all__ = ["DEFAULT_K", "M5_DOCS_DIR", "build_m5_retriever", "load_m5_docs"]
