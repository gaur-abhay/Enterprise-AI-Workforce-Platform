"""Ingestion pipeline: load -> chunk -> embed -> store in PGVector."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Literal

from pgvector import Vector
from psycopg import Connection

from ai_employee.db import connect
from ai_employee.embeddings import embed_documents, model_id
from ai_employee.ingestion import loaders
from ai_employee.ingestion.chunker import Chunk, chunk
from ai_employee.ingestion.sources import LocalSource, Source, SourceItem

logger = logging.getLogger(__name__)

EMBED_BATCH_SIZE = 64

Status = Literal["indexed", "skipped", "empty", "unsupported", "pruned"]

_UPSERT_DOCUMENT = """
INSERT INTO documents
    (source_path, title, mime_type, content_hash, source_version, page_count, acl_principals)
VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (source_path) DO UPDATE SET
    title = EXCLUDED.title,
    mime_type = EXCLUDED.mime_type,
    content_hash = EXCLUDED.content_hash,
    source_version = EXCLUDED.source_version,
    page_count = EXCLUDED.page_count,
    acl_principals = EXCLUDED.acl_principals,
    updated_at = now()
RETURNING id
"""

_UPDATE_VERSION = """
UPDATE documents SET source_version = %s, updated_at = now() WHERE source_path = %s
"""

# Bounded by the source's own listing scope, so a run over one prefix can never delete
# documents belonging to another.
_PRUNE = """
DELETE FROM documents
WHERE starts_with(source_path, %(prefix)s)
  AND source_path <> ALL(%(present)s)
RETURNING source_path
"""

_INSERT_CHUNK = """
INSERT INTO chunks
    (document_id, chunk_index, content, char_count, page_number, embedding, embedding_model)
VALUES (%s, %s, %s, %s, %s, %s, %s)
"""


@dataclass(frozen=True)
class IngestResult:
    uri: str
    name: str
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


_INDEX_STATE = """
SELECT
    d.content_hash,
    d.source_version,
    EXISTS (
        SELECT 1 FROM chunks AS c
        WHERE c.document_id = d.id AND c.embedding_model = %(embedding_model)s
    ) AS embedded_by_current_model
FROM documents AS d
WHERE d.source_path = %(source_path)s
"""


@dataclass(frozen=True)
class _IndexState:
    """What the store already holds for one document."""

    content_hash: str
    source_version: str | None
    # The content hash alone is never enough: after an embedding-provider switch the bytes
    # are identical but the stored vectors are in the previous model's space, which retrieval
    # filters out. Skipping on content alone would leave the document permanently
    # unsearchable with no error anywhere, so both skip paths require this.
    embedded_by_current_model: bool

    def matches_version(self, version: str | None) -> bool:
        """True when the source's token proves the indexed copy is current, unread."""
        return bool(version) and self.source_version == version and self.embedded_by_current_model

    def matches_content(self, content_hash: str) -> bool:
        return self.content_hash == content_hash and self.embedded_by_current_model


def _index_state(conn: Connection, source_path: str) -> _IndexState | None:
    row = conn.execute(
        _INDEX_STATE, {"source_path": source_path, "embedding_model": model_id()}
    ).fetchone()
    return _IndexState(*row) if row else None


def _store(
    conn: Connection,
    document: loaders.LoadedDocument,
    chunks: list[Chunk],
    vectors: list[list[float]],
    acl_principals: list[str],
    source_version: str | None,
) -> None:
    row = conn.execute(
        _UPSERT_DOCUMENT,
        (
            document.uri,
            document.title,
            document.mime_type,
            document.content_hash,
            source_version,
            document.page_count,
            acl_principals,
        ),
    ).fetchone()
    if row is None:
        # RETURNING on an upsert always yields a row; a None here means the statement
        # changed shape, and silently indexing it would fail far from the cause.
        raise RuntimeError(f"upsert returned no document id for {document.uri}")
    document_id = row[0]

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


def ingest_item(
    source: Source,
    item: SourceItem,
    *,
    force: bool = False,
    acl_principals: list[str] | None = None,
) -> IngestResult:
    """Index one item from a source. Unchanged documents are skipped unless force is set."""
    result = partial(IngestResult, uri=item.uri, name=item.name)

    with connect() as conn:
        state = None if force else _index_state(conn, item.uri)

        # Cheap path: the source's own token says nothing has changed, so the document is
        # never fetched at all. This is what keeps a re-run over a large container free.
        if state and state.matches_version(item.version):
            return result(status="skipped", detail="unchanged at source")

        try:
            # The context holds a temporary download for remote sources; loading reads every
            # page into memory, so nothing below needs the file to still exist.
            with source.open(item) as local:
                document = loaders.load(local.path, uri=item.uri, name=item.name)
        except loaders.UnsupportedFileTypeError as exc:
            return result(status="unsupported", detail=str(exc))

        if not document.pages:
            return result(status="empty", detail="no extractable text")

        # Correct path: the token moved but the bytes did not - a touch, a copy, a re-upload
        # of the same file. Record the new token so the next run takes the cheap path.
        if state and state.matches_content(document.content_hash):
            conn.execute(_UPDATE_VERSION, (local.version, item.uri))
            conn.commit()
            return result(status="skipped", detail="content unchanged")

        chunks = chunk(document)
        if not chunks:
            return result(status="empty", detail="no chunks produced")

        vectors = _embed_in_batches(chunks)
        _store(conn, document, chunks, vectors, acl_principals or [], local.version)
        conn.commit()

    return result(status="indexed", chunk_count=len(chunks))


def ingest_file(
    path: Path, *, force: bool = False, acl_principals: list[str] | None = None
) -> IngestResult:
    """Index a single local file."""
    resolved = path.expanduser().resolve()
    source = LocalSource(resolved.parent)
    item = SourceItem(uri=str(resolved), key=str(resolved), name=resolved.name)
    return ingest_item(source, item, force=force, acl_principals=acl_principals)


def _prune(source: Source, items: list[SourceItem]) -> list[IngestResult]:
    """Drop documents that are indexed under this source but no longer exist in it.

    Without this, a deleted file keeps answering queries: retrieval has no idea the source
    is gone, so the agent cites it with full confidence. Renames look the same, since a new
    URI means a new row and the old one is simply left behind.
    """
    # An empty listing must never reach the DELETE - it would clear the whole prefix on the
    # strength of a bad prefix or a permissions failure. ingest() returns before this, and
    # this is the second lock on that door.
    if not items:
        return []

    with connect() as conn:
        rows = conn.execute(
            _PRUNE, {"prefix": source.uri_prefix, "present": [item.uri for item in items]}
        ).fetchall()
        conn.commit()

    # Chunks go with them via ON DELETE CASCADE.
    return [
        IngestResult(
            uri=uri, name=uri.rsplit("/", 1)[-1], status="pruned", detail="removed at source"
        )
        for (uri,) in rows
    ]


def ingest(
    source: Source,
    *,
    force: bool = False,
    acl_principals: list[str] | None = None,
    prune: bool = False,
) -> list[IngestResult]:
    """Index every supported document the source lists."""
    items = source.list_items()
    if not items:
        logger.warning("no supported documents found in %s", source.label)
        return []

    results = []
    for item in items:
        result = ingest_item(source, item, force=force, acl_principals=acl_principals)
        logger.info(
            "%s: %s (%d chunks) %s", result.name, result.status, result.chunk_count, result.detail
        )
        results.append(result)

    if prune:
        for result in _prune(source, items):
            logger.info("%s: pruned", result.name)
            results.append(result)
    return results
