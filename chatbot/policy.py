"""
chatbot/policy.py: the retriever behind search_policy (M5). The only RAG part of the bot.

What it does
------------
Builds the Day 3 TF-IDF retriever (from rag_pipeline.py, top 3 chunks), over
the M5 set of documents and with one change to how they are cut into chunks.

The documents
  documents 01 to 10   from datasets/policy_docs/   (Day 3, unchanged on disk)
  replaced for M5      any file of the same name in datasets/chatbot_docs/:
                         10_contact_and_privacy.md  the assistant can now look up
                                                    your own claims (spec section 7)
                         04_waiting_periods.md      adds how the days are counted
                                                    (day 0 rule, with an example)

The chunks (changed for M5 on 6 November 2026)
  Day 3 cuts each document at blank lines (paragraph chunks). M5 keeps that,
  with two exceptions:
    - every table is split into one chunk per row. Each row chunk repeats the
      column headings, so it makes sense on its own:
        "Cover and annual limits. Treatment: Physiotherapy; Most we pay per visit
         or item: 50 per session; Visits or items per policy year: 10 sessions; ..."
    - the bullet list in the exclusions document (03_exclusions) is split into
      one chunk per item.
  Why: a whole table or list stored as one long chunk covers many treatments,
  so TF-IDF ranks it below short general paragraphs. In the first two full runs
  the limits table and the exclusions list were missed on 5 turns (C02, C03,
  C11, C19). Other lists (numbered lists in documents 04, 06 and 08) are left as
  paragraphs, because no failure has been traced to them.

Day 3 files are only read, never changed, so the Day 3 bot and its tests are
unaffected. The retriever class, scoring and k are Day 3's, unchanged.

Change history:
  2026-11-05  v1  first version (M5).
  2026-11-05  v1.1  comments expanded; no code change.
  2026-11-06  v2  tables split into one chunk per row, and the exclusions list into
                  one chunk per item; M5 version of document 04 added.
"""
from __future__ import annotations

import re
from pathlib import Path

# All Day 3 building blocks, imported unchanged. _clean is the Day 3 helper that
# removes the "fictional data" banner and bold markers before indexing; using it
# here means the M5 documents are cleaned exactly like the Day 3 documents.
from rag_pipeline import DEFAULT_K, DOCS_DIR, Chunk, TfidfRetriever, _clean, load_docs

M5_DOCS_DIR = Path(__file__).resolve().parent.parent / "datasets" / "chatbot_docs"

# Documents whose bullet lists are split into one chunk per item. Only the
# exclusions list for now (decision of 6 November 2026); add a document here to
# extend the change, and record why.
SPLIT_LIST_DOCS = {"03_exclusions"}


def load_m5_docs() -> dict[str, str]:
    """The M5 corpus: {document ID: cleaned text} for all ten documents.

    Starts from the Day 3 documents, then replaces any document that has a file
    of the same name in datasets/chatbot_docs/ (documents 04 and 10). A file
    there that matches no Day 3 document is an error, so a typo in a file name
    can't quietly add an extra document.
    """
    docs = load_docs(DOCS_DIR)
    for p in sorted(M5_DOCS_DIR.glob("*.md")):
        if p.stem not in docs:
            raise ValueError(f"{p.name} does not replace a Day 3 document")
        docs[p.stem] = _clean(p.read_text(encoding="utf-8"))
    return docs


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def _flat(text: str) -> str:
    """Collapse all whitespace to single spaces, as Day 3's chunker does."""
    return " ".join(text.split())


def _is_table(para: str) -> bool:
    """A Markdown table: every line starts with '|' and the second line is the
    '| --- |' separator."""
    lines = [ln.strip() for ln in para.strip().splitlines() if ln.strip()]
    return len(lines) >= 3 and all(ln.startswith("|") for ln in lines) and set(lines[1]) <= set("|- :")


def _cells(line: str) -> list[str]:
    """The cells of one table line: '| a | b |' -> ['a', 'b']."""
    return [c.strip() for c in line.strip().strip("|").split("|")]


def split_table(title: str, para: str) -> list[str]:
    """One chunk text per table row, each with the column headings repeated:
    'Title. Heading 1: value; Heading 2: value; ...'."""
    lines = [ln for ln in para.strip().splitlines() if ln.strip()]
    headings = _cells(lines[0])
    return [f"{title}. " + "; ".join(f"{h}: {v}" for h, v in zip(headings, _cells(row)))
            for row in lines[2:]]                                   # lines[1] is the separator


def split_bullets(title: str, para: str) -> list[str] | None:
    """One chunk text per bullet item ('- ...', with any indented continuation
    lines joined on), each prefixed with the document title. None if the
    paragraph is not a bullet list."""
    items, current = [], None
    for ln in para.strip().splitlines():
        if ln.lstrip().startswith("- "):
            current = [ln.lstrip()[2:]]
            items.append(current)
        elif current is not None and ln.strip():
            current.append(ln.strip())                              # continuation of the item
        elif ln.strip():
            return None                                             # text that is not part of a list
    return [f"{title}. {_flat(' '.join(i))}" for i in items] or None


def chunk_m5(docs: dict[str, str]) -> list[Chunk]:
    """Cut the M5 documents into chunks.

    Paragraphs are found exactly as Day 3 does (split at blank lines, title
    taken from the '# ' heading and put in front of every chunk), so chunk IDs
    for ordinary paragraphs are the same as Day 3's (for example
    '04_waiting_periods#1'). A table paragraph becomes rows '#N.1', '#N.2', ...
    and a split list becomes items '#N.1', '#N.2', ...
    """
    chunks: list[Chunk] = []
    for doc_id, text in docs.items():
        title_match = re.search(r"^#\s+(.+)$", text, flags=re.MULTILINE)
        title = title_match.group(1).strip() if title_match else doc_id
        body = re.sub(r"^#\s+.+$", "", text, count=1, flags=re.MULTILINE)
        paras = [p for p in re.split(r"\n\s*\n", body) if _flat(p)]   # the same paragraphs as Day 3
        for n, para in enumerate(paras, start=1):
            parts = None
            if _is_table(para):
                parts = split_table(title, para)
            elif doc_id in SPLIT_LIST_DOCS:
                parts = split_bullets(title, para)
            if parts:
                chunks += [Chunk(f"{doc_id}#{n}.{j}", doc_id, t) for j, t in enumerate(parts, start=1)]
            else:
                chunks.append(Chunk(f"{doc_id}#{n}", doc_id, f"{title}. {_flat(para)}"))
    return chunks


def build_m5_retriever() -> TfidfRetriever:
    """The Day 3 TF-IDF retriever, indexed over the M5 corpus with M5 chunking."""
    return TfidfRetriever(chunk_m5(load_m5_docs()))


__all__ = ["DEFAULT_K", "M5_DOCS_DIR", "SPLIT_LIST_DOCS", "build_m5_retriever", "chunk_m5", "load_m5_docs"]
