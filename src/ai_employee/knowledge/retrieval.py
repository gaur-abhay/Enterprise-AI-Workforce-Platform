"""Vector retrieval over the tenant's chunk store, returning citation-ready hits.

Kept independent of the agent and tools so retrieval quality can be scored on its own.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import select, text

from ai_employee.context import TurnContext
from ai_employee.db import tenant_session
from ai_employee.db.models import Chunk, Document
from ai_employee.knowledge.embeddings import embed_query, model_id

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 5
MAX_TOP_K = 20


@dataclass(frozen=True)
class SearchHit:
    """One retrieved passage with everything a citation needs to be followed back."""

    chunk_id: str
    document_id: str
    content: str
    # File name the model cites; `uri` and `document_id` identify it unambiguously.
    source: str
    title: str
    uri: str
    page: int | None
    chunk_index: int
    indexed_at: str
    score: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def search(ctx: TurnContext, query: str, top_k: int = DEFAULT_TOP_K) -> list[SearchHit]:
    """Embed the query and return the tenant's closest chunks, most relevant first."""
    top_k = max(1, min(top_k, MAX_TOP_K))
    vector = embed_query(query)
    embedding_model = model_id()
    distance = Chunk.embedding.cosine_distance(vector)

    # Tenant is filtered explicitly as well as by RLS, so the planner sees the predicate.
    # Vectors from another model are not comparable and are excluded, not mis-scored.
    query_stmt = (
        select(Chunk, Document, (1 - distance).label("score"))
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.tenant_id == ctx.tenant_id, Chunk.embedding_model == embedding_model)
        .order_by(distance)
        .limit(top_k)
    )

    with tenant_session(ctx.tenant_id) as session:
        # Filtered HNSW scans otherwise stop at ef_search candidates and return too few rows.
        session.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))
        rows = session.execute(query_stmt).all()

    hits = [
        SearchHit(
            chunk_id=str(chunk.id),
            document_id=str(document.id),
            content=chunk.content,
            source=document.source_path.rsplit("/", 1)[-1],
            title=document.title,
            uri=document.source_path,
            page=chunk.page_number,
            chunk_index=chunk.chunk_index,
            indexed_at=document.updated_at.isoformat(),
            score=round(float(score), 4),
        )
        for chunk, document, score in rows
    ]

    logger.info(
        "search %r top_k=%d -> %d hits, best %.3f [%s]",
        query,
        top_k,
        len(hits),
        hits[0].score if hits else 0.0,
        embedding_model,
    )
    return hits
