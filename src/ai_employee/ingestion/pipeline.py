"""Ingestion pipeline: load -> chunk -> embed -> store in PGVector."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pgvector import Vector
from psycopg import Connection

from ai_employee.db import connect
from ai_employee.embeddings import embed_documents, model_id
from ai_employee.ingestion import loaders
from ai_employee.ingestion.chunker import Chunk, chunk

logger = logging.getLogger(__name__)

EMBED_BATCH_SIZE = 64

Status = Literal["indexed", "skipped", "empty", "unsupported"]

_UPSERT_DOCUMENT = """
INSERT INTO documents (source_path, title, mime_type, content_hash, page_count, acl_principals)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (source_path) DO UPDATE SET
    title = EXCLUDED.title,
    mime_type = EXCLUDED.mime_type,
    content_hash = EXCLUDED.content_hash,
    page_count = EXCLUDED.page_count,
    acl_principals = EXCLUDED.acl_principals,
    updated_at = now()
RETURNING id
"""

_INSERT_CHUNK = """
INSERT INTO chunks
    (document_id, chunk_index, content, char_count, page_number, embedding, embedding_model)
VALUES (%s, %s, %s, %s, %s, %s, %s)
"""


@dataclass(frozen=True)
class IngestResult:
    path: Path
    status: Status
    chunk_count: int = 0
    detail: str = ""


def _embed_in_batches(chunks: list[Chunk]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for start in range(0, len(chunks), EMBED_BATCH_SIZE):
        batch = chunks[start : start + EMBED_BATCH_SIZE]
        logger.debug("embedding chunks %d-%d", start, start + len(batch) - 1)
        vectors.extend(embed_documents([c.content for c in batch]))
    return vectors


_IS_INDEXED = """
SELECT
    d.content_hash,
    EXISTS (
        SELECT 1 FROM chunks AS c
        WHERE c.document_id = d.id AND c.embedding_model = %(embedding_model)s
    ) AS embedded_by_current_model
FROM documents AS d
WHERE d.source_path = %(source_path)s
"""


def _is_unchanged(conn: Connection, source_path: str, content_hash: str) -> bool:
    """True when this file is already indexed with the active embedding model.

    The content hash alone is not enough: after switching embedding provider the file is
    byte-identical but its stored vectors are in the previous model's space, which retrieval
    filters out. Skipping on the hash alone would leave the document permanently unsearchable
    with no error anywhere.
    """
    row = conn.execute(
        _IS_INDEXED, {"source_path": source_path, "embedding_model": model_id()}
    ).fetchone()
    if row is None:
        return False

    stored_hash, embedded_by_current_model = row
    return stored_hash == content_hash and embedded_by_current_model


def _store(
    conn: Connection,
    document: loaders.LoadedDocument,
    chunks: list[Chunk],
    vectors: list[list[float]],
    acl_principals: list[str],
) -> None:
    document_id = conn.execute(
        _UPSERT_DOCUMENT,
        (
            str(document.path),
            document.title,
            document.mime_type,
            document.content_hash,
            document.page_count,
            acl_principals,
        ),
    ).fetchone()[0]

    # Re-ingestion replaces the previous chunk set outright; chunk boundaries shift
    # when a document changes, so incremental updates would leave orphans.
    conn.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))
    embedding_model = model_id()
    with conn.cursor() as cur:
        cur.executemany(
            _INSERT_CHUNK,
            [
                (
                    document_id,
                    c.index,
                    c.content,
                    c.char_count,
                    c.page_number,
                    Vector(vector),
                    embedding_model,
                )
                for c, vector in zip(chunks, vectors, strict=True)
            ],
        )


def ingest_file(
    path: Path, *, force: bool = False, acl_principals: list[str] | None = None
) -> IngestResult:
    """Index a single file. Unchanged files are skipped unless force is set."""
    path = path.resolve()
    try:
        document = loaders.load(path)
    except loaders.UnsupportedFileTypeError as exc:
        return IngestResult(path=path, status="unsupported", detail=str(exc))

    if not document.pages:
        return IngestResult(path=path, status="empty", detail="no extractable text")

    with connect() as conn:
        if not force and _is_unchanged(conn, str(document.path), document.content_hash):
            return IngestResult(path=path, status="skipped", detail="content hash unchanged")

        chunks = chunk(document)
        if not chunks:
            return IngestResult(path=path, status="empty", detail="no chunks produced")

        vectors = _embed_in_batches(chunks)
        _store(conn, document, chunks, vectors, acl_principals or [])
        conn.commit()

    return IngestResult(path=path, status="indexed", chunk_count=len(chunks))


def ingest(
    root: Path, *, force: bool = False, acl_principals: list[str] | None = None
) -> list[IngestResult]:
    """Index every supported file under root (or root itself, if it is a file)."""
    paths = loaders.discover(root)
    if not paths:
        logger.warning("no supported files found under %s", root)
        return []

    results = []
    for path in paths:
        result = ingest_file(path, force=force, acl_principals=acl_principals)
        logger.info("%s: %s (%d chunks) %s", result.path.name, result.status, result.chunk_count, result.detail)
        results.append(result)
    return results