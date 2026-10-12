"""Control plane: tenants, users, the employee, and tenant-level knowledge sources."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ai_employee.db.models.base import Base, CreatedAt, TenantScoped, UUIDPrimaryKey, str_enum


class TenantStatus(enum.StrEnum):
    DISCOVERED = "discovered"
    CLAIMED = "claimed"
    CONFIGURED = "configured"
    ACTIVE = "active"


class UserRole(enum.StrEnum):
    ADMIN = "admin"
    MEMBER = "member"


class SourceKind(enum.StrEnum):
    DIRECTORY = "directory"
    AZURE_BLOB = "azure_blob"


class Tenant(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(200))
    # Entra `tid`; null until the tenant is reached through real sign-in.
    entra_tenant_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    status: Mapped[TenantStatus] = mapped_column(
        str_enum(TenantStatus, "tenant_status"), default=TenantStatus.DISCOVERED
    )


class User(UUIDPrimaryKey, TenantScoped, CreatedAt, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email"),
        UniqueConstraint("tenant_id", "entra_object_id"),
        UniqueConstraint("tenant_id", "id"),
    )

    email: Mapped[str] = mapped_column(String(320))
    display_name: Mapped[str] = mapped_column(String(200))
    # Entra `oid`; null for seeded users.
    entra_object_id: Mapped[str | None] = mapped_column(String(64))
    role: Mapped[UserRole] = mapped_column(str_enum(UserRole, "user_role"))


class Employee(UUIDPrimaryKey, TenantScoped, CreatedAt, Base):
    """The tenant's AI coworker. One per tenant, stored as configuration."""

    __tablename__ = "employees"
    __table_args__ = (UniqueConstraint("tenant_id"),)

    name: Mapped[str] = mapped_column(String(200))
    instructions: Mapped[str] = mapped_column(Text, default="")


class SourceConnection(UUIDPrimaryKey, TenantScoped, CreatedAt, Base):
    """A tenant-level knowledge source, configured by an admin."""

    __tablename__ = "source_connections"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name"),
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "created_by"],
            ["users.tenant_id", "users.id"],
            ondelete="SET NULL (created_by)",
        ),
    )

    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[SourceKind] = mapped_column(str_enum(SourceKind, "source_kind"))
    # Non-secret settings: path, container, prefix.
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Vault reference for the source credential. Never the secret itself.
    credential_ref: Mapped[str | None] = mapped_column(String(200))
    created_by: Mapped[uuid.UUID | None] = mapped_column()
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
