"""Knowledge plane: documents and their embedded chunks."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Computed,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from ai_employee.config import get_settings
from ai_employee.db.models.base import Base, CreatedAt, TenantScoped, UUIDPrimaryKey

# Baked into the column type; changing it needs a migration and a re-index.
EMBEDDING_DIM = get_settings().embedding_dim

_EMPTY_ARRAY = text("'{}'::text[]")
_EMPTY_JSON = text("'{}'::jsonb")


class Document(UUIDPrimaryKey, TenantScoped, CreatedAt, Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source_connection_id", "source_path"),
        UniqueConstraint("tenant_id", "id"),
        # Composite key: a document cannot point at another tenant's source.
        ForeignKeyConstraint(
            ["tenant_id", "source_connection_id"],
            ["source_connections.tenant_id", "source_connections.id"],
            ondelete="CASCADE",
        ),
        Index("ix_documents_acl_principals", "acl_principals", postgresql_using="gin"),
    )

    source_connection_id: Mapped[uuid.UUID] = mapped_column()
    source_path: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(String(100))
    # SHA-256 of the raw bytes; the authority on whether a document changed.
    content_hash: Mapped[str] = mapped_column(String(64))
    # Source change token (ETag, mtime:size); lets an unchanged item skip the read.
    source_version: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column(Integer)
    # Entra principals allowed to read. Empty means unrestricted.
    acl_principals: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=_EMPTY_ARRAY, default=list
    )
    meta: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, server_default=_EMPTY_JSON, default=dict
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Chunk(UUIDPrimaryKey, TenantScoped, CreatedAt, Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index"),
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            ondelete="CASCADE",
        ),
        Index("ix_chunks_content_tsv", "content_tsv", postgresql_using="gin"),
        Index("ix_chunks_acl_principals", "acl_principals", postgresql_using="gin"),
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    document_id: Mapped[uuid.UUID] = mapped_column()
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    char_count: Mapped[int] = mapped_column(Integer)
    page_number: Mapped[int | None] = mapped_column(Integer)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
    # Vectors from different models are not comparable; retrieval filters on this.
    embedding_model: Mapped[str] = mapped_column(String(200))
    content_tsv: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', content)", persisted=True)
    )
    # Copied from the document so retrieval pre-filters without a join.
    acl_principals: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=_EMPTY_ARRAY, default=list
    )
    meta: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, server_default=_EMPTY_JSON, default=dict
    )
