"""Chunking. Splits page text into overlapping passages sized for retrieval."""

from __future__ import annotations

from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter

from ai_employee.knowledge.loaders import LoadedDocument

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150
# Splitting on "\n\n" strands headings as their own passage; anything shorter than
# this is folded into the passage that follows it.
MIN_CHUNK_CHARS = 120


@dataclass(frozen=True)
class Passage:
    index: int
    content: str
    page_number: int | None

    @property
    def char_count(self) -> int:
        return len(self.content)


def _splitter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )


def _merge_undersized(texts: list[str]) -> list[str]:
    """Fold fragments below MIN_CHUNK_CHARS forward, so a heading rides with its section."""
    merged: list[str] = []
    pending = ""
    for text in texts:
        candidate = f"{pending}\n\n{text}" if pending else text
        if len(candidate) < MIN_CHUNK_CHARS:
            pending = candidate
            continue
        merged.append(candidate)
        pending = ""

    if pending:
        if merged:
            merged[-1] = f"{merged[-1]}\n\n{pending}"
        else:
            merged.append(pending)
    return merged


def chunk(document: LoadedDocument) -> list[Passage]:
    """Split page by page so a chunk never straddles a page boundary."""
    splitter = _splitter()
    chunks: list[Passage] = []
    for page in document.pages:
        texts = [text.strip() for text in splitter.split_text(page.text)]
        for text in _merge_undersized([text for text in texts if text]):
            chunks.append(Passage(index=len(chunks), content=text, page_number=page.number))
    return chunks
