"""Ingestion: list -> load -> chunk -> embed -> store, for one tenant's source connection.

Reads and writes run in short tenant sessions; loading and embedding happen between them,
so no transaction is held open across network calls.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from typing import Literal

from sqlalchemy import ColumnElement, and_, delete, exists, select, update
from sqlalchemy.orm import Session

from ai_employee.db import tenant_session
from ai_employee.db.models import Chunk, Document, SourceConnection, Tenant, TenantStatus
from ai_employee.knowledge import loaders
from ai_employee.knowledge.chunking import Passage, chunk
from ai_employee.knowledge.embeddings import embed_documents, model_id
from ai_employee.knowledge.sources import Source, SourceItem, source_for

logger = logging.getLogger(__name__)

EMBED_BATCH_SIZE = 64

Status = Literal["indexed", "skipped", "empty", "unsupported", "pruned"]


@dataclass(frozen=True)
class IngestResult:
    uri: str
    status: Status
    chunk_count: int = 0
    detail: str = ""


@dataclass(frozen=True)
class _IndexState:
    """What the store already holds for one document."""

    content_hash: str
    source_version: str | None
    # After a provider switch the bytes are identical but the vectors are in the old model's
    # space, which retrieval filters out. Both skip paths require this, or the document
    # becomes permanently unsearchable with no error.
    embedded_by_current_model: bool

    def matches_version(self, version: str | None) -> bool:
        """The source's token proves the indexed copy is current, without reading it."""
        return bool(version) and self.source_version == version and self.embedded_by_current_model

    def matches_content(self, content_hash: str) -> bool:
        return self.content_hash == content_hash and self.embedded_by_current_model


@dataclass(frozen=True)
class _Target:
    tenant_id: uuid.UUID
    source_connection_id: uuid.UUID


def _document_filter(target: _Target, uri: str) -> ColumnElement[bool]:
    return and_(
        Document.source_connection_id == target.source_connection_id,
        Document.source_path == uri,
    )


def _index_state(session: Session, target: _Target, uri: str) -> _IndexState | None:
    embedded = exists().where(Chunk.document_id == Document.id, Chunk.embedding_model == model_id())
    row = session.execute(
        select(Document.content_hash, Document.source_version, embedded).where(
            _document_filter(target, uri)
        )
    ).one_or_none()
    return _IndexState(*row) if row else None


def _embed_in_batches(passages: list[Passage]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for start in range(0, len(passages), EMBED_BATCH_SIZE):
        batch = passages[start : start + EMBED_BATCH_SIZE]
        vectors.extend(embed_documents([p.content for p in batch]))
    return vectors


def _store(
    session: Session,
    target: _Target,
    document: loaders.LoadedDocument,
    passages: list[Passage],
    vectors: list[list[float]],
    source_version: str | None,
) -> None:
    row = session.scalar(select(Document).where(_document_filter(target, document.uri)))
    if row is None:
        row = Document(
            tenant_id=target.tenant_id,
            source_connection_id=target.source_connection_id,
            source_path=document.uri,
        )
        session.add(row)
    row.title = document.title
    row.mime_type = document.mime_type
    row.content_hash = document.content_hash
    row.source_version = source_version
    row.page_count = document.page_count
    session.flush()

    # Chunk boundaries shift when a document changes, so the set is replaced outright.
    session.execute(delete(Chunk).where(Chunk.document_id == row.id))
    embedding_model = model_id()
    session.add_all(
        Chunk(
            tenant_id=target.tenant_id,
            document_id=row.id,
            chunk_index=p.index,
            content=p.content,
            char_count=p.char_count,
            page_number=p.page_number,
            embedding=vector,
            embedding_model=embedding_model,
            acl_principals=row.acl_principals,
        )
        for p, vector in zip(passages, vectors, strict=True)
    )


def ingest_item(
    target: _Target, source: Source, item: SourceItem, *, force: bool = False
) -> IngestResult:
    """Index one item. Unchanged documents are skipped unless force is set."""
    result = partial(IngestResult, uri=item.uri)

    with tenant_session(target.tenant_id) as session:
        state = None if force else _index_state(session, target, item.uri)

    # Cheap path: the source's token says nothing changed, so the item is never fetched.
    if state and state.matches_version(item.version):
        return result(status="skipped", detail="unchanged at source")

    try:
        with source.open(item) as local:
            document = loaders.load(local.path, uri=item.uri, name=item.name)
    except loaders.UnsupportedFileTypeError as exc:
        return result(status="unsupported", detail=str(exc))

    if not document.pages:
        return result(status="empty", detail="no extractable text")

    # Token moved but bytes did not: record the new token so the next run takes the cheap path.
    if state and state.matches_content(document.content_hash):
        with tenant_session(target.tenant_id) as session:
            session.execute(
                update(Document)
                .where(_document_filter(target, item.uri))
                .values(source_version=local.version)
            )
        return result(status="skipped", detail="content unchanged")

    passages = chunk(document)
    if not passages:
        return result(status="empty", detail="no chunks produced")

    vectors = _embed_in_batches(passages)
    with tenant_session(target.tenant_id) as session:
        _store(session, target, document, passages, vectors, local.version)
    return result(status="indexed", chunk_count=len(passages))


def _prune(target: _Target, items: list[SourceItem]) -> list[IngestResult]:
    """Drop documents indexed from this connection that no longer exist at the source."""
    # An empty listing must never reach the DELETE: it would clear the whole connection on
    # the strength of a bad path or a permissions failure.
    if not items:
        return []
    with tenant_session(target.tenant_id) as session:
        removed = session.scalars(
            delete(Document)
            .where(
                Document.source_connection_id == target.source_connection_id,
                Document.source_path.not_in([item.uri for item in items]),
            )
            .returning(Document.source_path)
        ).all()
    return [IngestResult(uri=uri, status="pruned", detail="removed at source") for uri in removed]


def ingest(
    tenant_id: uuid.UUID, source_connection_id: uuid.UUID, *, force: bool = False
) -> list[IngestResult]:
    """Sync one source connection into the tenant's index."""
    target = _Target(tenant_id, source_connection_id)
    with tenant_session(tenant_id) as session:
        connection = session.get_one(SourceConnection, source_connection_id)
        source = source_for(connection)

    items = source.list_items()
    if not items:
        logger.warning("no supported documents found in %s", source.label)
        return []

    results = [ingest_item(target, source, item, force=force) for item in items]
    results.extend(_prune(target, items))
    for r in results:
        logger.info("%s: %s (%d chunks) %s", r.uri, r.status, r.chunk_count, r.detail)

    with tenant_session(tenant_id) as session:
        session.execute(
            update(SourceConnection)
            .where(SourceConnection.id == source_connection_id)
            .values(last_synced_at=datetime.now(UTC))
        )
        session.execute(
            update(Tenant)
            .where(Tenant.id == tenant_id, Tenant.status == TenantStatus.CONFIGURED)
            .values(status=TenantStatus.ACTIVE)
        )
    return results
