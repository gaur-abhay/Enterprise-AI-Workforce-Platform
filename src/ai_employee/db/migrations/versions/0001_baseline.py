"""Baseline: control and knowledge tables, application role, tenant RLS.

Revision ID: 0001
Revises:
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import SchemaItem

from ai_employee.config import get_settings

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = ("employees", "users", "source_connections", "documents", "chunks")


def _uuid_pk() -> list[SchemaItem]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def _tenant_fk(table: str) -> list[SchemaItem]:
    return [
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{table}_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
    ]


def _str_enum(name: str, *values: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True, length=32)


def upgrade() -> None:
    role = get_settings().db_app_role
    dim = get_settings().embedding_dim

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Roles are cluster-wide, so another database on the server may already have created it.
    op.execute(
        f"""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN
                CREATE ROLE "{role}" NOLOGIN;
            END IF;
        END $$;
        GRANT "{role}" TO CURRENT_USER;
        GRANT USAGE ON SCHEMA public TO "{role}";
        """
    )

    # NULL when unset, so a session that never bound a tenant matches no rows.
    op.execute(
        """
        CREATE FUNCTION app_current_tenant() RETURNS uuid
        LANGUAGE sql STABLE
        AS $$ SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid $$
        """
    )

    op.create_table(
        "tenants",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("entra_tenant_id", sa.String(length=64), nullable=True),
        sa.Column(
            "status",
            _str_enum("tenant_status", "discovered", "claimed", "configured", "active"),
            nullable=False,
        ),
        *_uuid_pk(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenants")),
        sa.UniqueConstraint("entra_tenant_id", name=op.f("uq_tenants_entra_tenant_id")),
    )

    op.create_table(
        "employees",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        *_uuid_pk(),
        *_tenant_fk("employees"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_employees")),
        sa.UniqueConstraint("tenant_id", name=op.f("uq_employees_tenant_id")),
    )
    op.create_index(op.f("ix_employees_tenant_id"), "employees", ["tenant_id"])

    op.create_table(
        "users",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("entra_object_id", sa.String(length=64), nullable=True),
        sa.Column("role", _str_enum("user_role", "admin", "member"), nullable=False),
        *_uuid_pk(),
        *_tenant_fk("users"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("tenant_id", "email", name=op.f("uq_users_tenant_id_email")),
        sa.UniqueConstraint(
            "tenant_id", "entra_object_id", name=op.f("uq_users_tenant_id_entra_object_id")
        ),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_users_tenant_id_id")),
    )
    op.create_index(op.f("ix_users_tenant_id"), "users", ["tenant_id"])

    op.create_table(
        "source_connections",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("kind", _str_enum("source_kind", "directory", "azure_blob"), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("credential_ref", sa.String(length=200), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        *_uuid_pk(),
        *_tenant_fk("source_connections"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_source_connections_tenant_id_created_by_users"),
            ondelete="SET NULL (created_by)",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_connections")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_source_connections_tenant_id_id")),
        sa.UniqueConstraint("tenant_id", "name", name=op.f("uq_source_connections_tenant_id_name")),
    )
    op.create_index(op.f("ix_source_connections_tenant_id"), "source_connections", ["tenant_id"])

    op.create_table(
        "documents",
        sa.Column("source_connection_id", sa.Uuid(), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("source_version", sa.Text(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column(
            "acl_principals",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        *_uuid_pk(),
        *_tenant_fk("documents"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "source_connection_id"],
            ["source_connections.tenant_id", "source_connections.id"],
            name=op.f("fk_documents_tenant_id_source_connection_id_source_connections"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_documents_tenant_id_id")),
        sa.UniqueConstraint(
            "tenant_id",
            "source_connection_id",
            "source_path",
            name=op.f("uq_documents_tenant_id_source_connection_id_source_path"),
        ),
    )
    op.create_index(
        "ix_documents_acl_principals", "documents", ["acl_principals"], postgresql_using="gin"
    )
    op.create_index(op.f("ix_documents_tenant_id"), "documents", ["tenant_id"])

    op.create_table(
        "chunks",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("embedding", Vector(dim), nullable=False),
        sa.Column("embedding_model", sa.String(length=200), nullable=False),
        sa.Column(
            "content_tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('english', content)", persisted=True),
            nullable=False,
        ),
        sa.Column(
            "acl_principals",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        *_uuid_pk(),
        *_tenant_fk("chunks"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            name=op.f("fk_chunks_tenant_id_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chunks")),
        sa.UniqueConstraint(
            "document_id", "chunk_index", name=op.f("uq_chunks_document_id_chunk_index")
        ),
    )
    op.create_index(
        "ix_chunks_acl_principals", "chunks", ["acl_principals"], postgresql_using="gin"
    )
    op.create_index("ix_chunks_content_tsv", "chunks", ["content_tsv"], postgresql_using="gin")
    op.create_index(
        "ix_chunks_embedding_hnsw",
        "chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(op.f("ix_chunks_tenant_id"), "chunks", ["tenant_id"])

    # FORCE so the policy also binds a table owner that is not a superuser.
    _enable_rls("tenants", "id", role)
    for table in TENANT_TABLES:
        _enable_rls(table, "tenant_id", role)


def _enable_rls(table: str, column: str, role: str) -> None:
    op.execute(
        f"""
        ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON {table}
            USING ({column} = app_current_tenant())
            WITH CHECK ({column} = app_current_tenant());
        GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO "{role}";
        """
    )


def downgrade() -> None:
    for table in ("chunks", "documents", "source_connections", "users", "employees", "tenants"):
        op.drop_table(table)
    op.execute("DROP FUNCTION app_current_tenant()")
    # The role and the vector extension are left in place: other databases may use them.
