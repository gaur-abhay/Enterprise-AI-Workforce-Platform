"""Embedding client shared by the ingestion pipeline and the retrieval tools."""

from __future__ import annotations

import math
from functools import lru_cache

from langchain_ollama import OllamaEmbeddings

from ai_employee.config import get_settings

# nomic-embed-text is trained with task prefixes; retrieval quality drops noticeably
# without them, and the two sides must not be swapped.
DOCUMENT_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "


@lru_cache
def _client() -> OllamaEmbeddings:
    settings = get_settings()
    return OllamaEmbeddings(
        model=settings.embedding_model,
        base_url=settings.ollama_base_url,
    )


def _normalise(vector: list[float]) -> list[float]:
    """L2-normalise so cosine distance in PGVector reduces to a dot product."""
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return vector
    return [value / norm for value in vector]


def embed_documents(texts: list[str]) -> list[list[float]]:
    vectors = _client().embed_documents([DOCUMENT_PREFIX + text for text in texts])
    return [_normalise(vector) for vector in vectors]


def embed_query(text: str) -> list[float]:
    return _normalise(_client().embed_query(QUERY_PREFIX + text))