"""Vector retrieval over the chunk store.

Kept separate from the tool wrapper in ai_employee.tools so retrieval quality can be
measured without going through an LLM.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass

from pgvector import Vector

from ai_employee.db import connect
from ai_employee.embeddings import embed_query, model_id

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 5
MAX_TOP_K = 20

# ORDER BY the raw <=> distance so the HNSW index is used; the SELECT converts it to a
# similarity because a score that rises with relevance is easier to reason about.
_SEARCH = """
SELECT
    c.id::text        AS chunk_id,
    c.content         AS content,
    c.chunk_index     AS chunk_index,
    c.page_number     AS page_number,
    d.id::text        AS document_id,
    d.title           AS title,
    d.source_path     AS source_path,
    d.updated_at      AS updated_at,
    1 - (c.embedding <=> %(query)s) AS score
FROM chunks AS c
JOIN documents AS d ON d.id = c.document_id
WHERE c.embedding_model = %(embedding_model)s
ORDER BY c.embedding <=> %(query)s
LIMIT %(top_k)s
"""


def _display_name(source_path: str) -> str:
    """The file name a citation names. Works for both a local path and an azure:// URI,
    neither of which Path handles correctly in every case."""
    return source_path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1] or source_path


@dataclass(frozen=True)
class SearchHit:
    """One retrieved passage, carrying everything a citation needs to be checked.

    `source` is what the model cites; `uri` and `document_id` are what let a reader follow
    that citation back to the exact file or blob it came from. Two documents can share a
    file name, so the name alone identifies nothing.
    """

    chunk_id: str
    document_id: str
    content: str
    source: str
    title: str
    uri: str
    page: int | None
    chunk_index: int
    # When the document was last indexed, so "as of when?" has an answer.
    indexed_at: str | None
    score: float

    def as_dict(self) -> dict:
        return asdict(self)


def search(query: str, top_k: int = DEFAULT_TOP_K) -> list[SearchHit]:
    """Embed the query and return the closest chunks, most relevant first."""
    top_k = max(1, min(top_k, MAX_TOP_K))
    embedding = Vector(embed_query(query))
    # Only chunks embedded by the active model are comparable to this query vector. Chunks
    # left behind by a previous provider are ignored rather than silently scored as garbage.
    embedding_model = model_id()

    with connect() as conn:
        rows = conn.execute(
            _SEARCH,
            {"query": embedding, "top_k": top_k, "embedding_model": embedding_model},
        ).fetchall()

    hits = [
        SearchHit(
            chunk_id=chunk_id,
            document_id=document_id,
            content=content,
            source=_display_name(source_path),
            title=title,
            uri=source_path,
            page=page_number,
            chunk_index=chunk_index,
            indexed_at=updated_at.isoformat() if updated_at else None,
            score=round(float(score), 4),
        )
        for (
            chunk_id,
            content,
            chunk_index,
            page_number,
            document_id,
            title,
            source_path,
            updated_at,
            score,
        ) in rows
    ]

    # At INFO because this is the audit trail: without the query and what came back for it,
    # an answer cannot be explained after the fact.
    logger.info(
        "search %r top_k=%d -> %d hits, best %.3f [%s]",
        query,
        top_k,
        len(hits),
        hits[0].score if hits else 0.0,
        embedding_model,
    )
    for hit in hits:
        logger.debug("  %.3f %s p%s #%d", hit.score, hit.source, hit.page, hit.chunk_index)
    return hits