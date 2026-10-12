"""Wire models for turns. Never the ORM classes."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TurnRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class Source(BaseModel):
    chunk_id: str
    document_id: str
    source: str
    title: str
    uri: str
    page: int | None
    chunk_index: int
    indexed_at: str
    score: float
    content: str


class TurnResponse(BaseModel):
    answer: str
    # Correlation id for this turn's logs and audit rows.
    request_id: str
    # Passages retrieved during the turn, not necessarily the ones cited.
    sources: list[Source]
    tool_calls: list[dict[str, Any]]
