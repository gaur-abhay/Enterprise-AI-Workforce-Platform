"""Vector retrieval over the chunk store.

Kept separate from the tool wrapper in ai_employee.tools so retrieval quality can be
measured without going through an LLM.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from pgvector import Vector

from ai_employee.db import connect
from ai_employee.embeddings import embed_query

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 5
MAX_TOP_K = 20

# ORDER BY the raw <=> distance so the HNSW index is used; the SELECT converts it to a
# similarity because a score that rises with relevance is easier to reason about.
_SEARCH = """
SELECT
    c.id::text        AS chunk_id,
    c.content         AS content,
    c.page_number     AS page_number,
    d.source_path     AS source_path,
    1 - (c.embedding <=> %(query)s) AS score
FROM chunks AS c
JOIN documents AS d ON d.id = c.document_id
ORDER BY c.embedding <=> %(query)s
LIMIT %(top_k)s
"""


@dataclass(frozen=True)
class SearchHit:
    chunk_id: str
    content: str
    source: str
    page: int | None
    score: float

    def as_dict(self) -> dict:
        return asdict(self)


def search(query: str, top_k: int = DEFAULT_TOP_K) -> list[SearchHit]:
    """Embed the query and return the closest chunks, most relevant first."""
    top_k = max(1, min(top_k, MAX_TOP_K))
    embedding = Vector(embed_query(query))

    with connect() as conn:
        rows = conn.execute(_SEARCH, {"query": embedding, "top_k": top_k}).fetchall()

    logger.debug("search(%r, top_k=%d) -> %d hits", query, top_k, len(rows))
    return [
        SearchHit(
            chunk_id=chunk_id,
            content=content,
            source=Path(source_path).name,
            page=page_number,
            score=round(float(score), 4),
        )
        for chunk_id, content, page_number, source_path, score in rows
    ]