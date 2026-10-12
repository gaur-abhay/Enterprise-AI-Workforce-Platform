"""Embedding providers, shared by the ingestion pipeline and the retrieval tools.

Indexing and querying must go through the same provider: vectors from different models are
not comparable, and each model has its own way of distinguishing a passage from a query.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from functools import lru_cache
from typing import Protocol

from ai_employee.config import Settings, get_settings

logger = logging.getLogger(__name__)


class EmbeddingConfigError(RuntimeError):
    """Raised when the selected embedding provider is missing settings or returns the
    wrong number of dimensions."""


def _normalise(vector: list[float]) -> list[float]:
    """L2-normalise so cosine distance in PGVector reduces to a dot product."""
    norm = math.sqrt(sum(value * value for value in vector))
    return vector if norm == 0.0 else [value / norm for value in vector]


class EmbeddingProvider(Protocol):
    """A provider embeds passages and queries differently, and names the model it used."""

    @property
    def model_id(self) -> str: ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class OllamaEmbeddingProvider:
    # nomic-embed-text is trained with task prefixes; retrieval quality drops noticeably
    # without them, and the two must not be swapped. Ollama does not add them for you.
    DOCUMENT_PREFIX = "search_document: "
    QUERY_PREFIX = "search_query: "

    def __init__(self, settings: Settings) -> None:
        from langchain_ollama import OllamaEmbeddings

        self._model = settings.embedding_model
        self._client = OllamaEmbeddings(
            model=settings.embedding_model,
            base_url=settings.ollama_base_url,
        )

    @property
    def model_id(self) -> str:
        return f"ollama:{self._model}"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._client.embed_documents([self.DOCUMENT_PREFIX + text for text in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._client.embed_query(self.QUERY_PREFIX + text)


class GeminiEmbeddingProvider:
    # Gemini takes the passage/query distinction as a task_type argument rather than a text
    # prefix. Adding the nomic prefixes here would corrupt the input.
    DOCUMENT_TASK = "RETRIEVAL_DOCUMENT"
    QUERY_TASK = "RETRIEVAL_QUERY"

    def __init__(self, settings: Settings) -> None:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        if not settings.google_api_key:
            raise EmbeddingConfigError("embedding_provider=gemini requires: GOOGLE_API_KEY")

        self._model = settings.gemini_embedding_model
        self._output_dim = settings.gemini_embedding_output_dim
        self._client = GoogleGenerativeAIEmbeddings(
            model=settings.gemini_embedding_model,
            # Accepted by alias at runtime; the generated __init__ only names the field.
            google_api_key=settings.google_api_key,  # type: ignore[call-arg]
        )

    @property
    def model_id(self) -> str:
        return f"gemini:{self._model}"

    def _extra(self) -> dict:
        return {"output_dimensionality": self._output_dim} if self._output_dim else {}

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._client.embed_documents(texts, task_type=self.DOCUMENT_TASK, **self._extra())

    def embed_query(self, text: str) -> list[float]:
        return self._client.embed_query(text, task_type=self.QUERY_TASK, **self._extra())


_PROVIDERS: dict[str, Callable[[Settings], EmbeddingProvider]] = {
    "ollama": OllamaEmbeddingProvider,
    "gemini": GeminiEmbeddingProvider,
}


@lru_cache
def get_provider() -> EmbeddingProvider:
    settings = get_settings()
    logger.info("embedding provider: %s", settings.embedding_provider)
    return _PROVIDERS[settings.embedding_provider](settings)


def model_id() -> str:
    """Identifier stored alongside every chunk, so vectors from different models never mix."""
    return get_provider().model_id


def _check_dim(vector: list[float]) -> list[float]:
    expected = get_settings().embedding_dim
    if len(vector) != expected:
        raise EmbeddingConfigError(
            f"{model_id()} returned {len(vector)} dimensions, but EMBEDDING_DIM is {expected}; "
            "the chunks table cannot store this vector"
        )
    return vector


def embed_documents(texts: list[str]) -> list[list[float]]:
    vectors = get_provider().embed_documents(texts)
    return [_normalise(_check_dim(vector)) for vector in vectors]


def embed_query(text: str) -> list[float]:
    return _normalise(_check_dim(get_provider().embed_query(text)))
