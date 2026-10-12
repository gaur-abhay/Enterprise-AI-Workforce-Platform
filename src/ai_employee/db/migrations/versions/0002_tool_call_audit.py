"""Tool call audit log, append-only for the application role.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-12 18:06:57.623613
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from ai_employee.config import get_settings

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tool_calls",
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("actor", sa.String(length=64), nullable=False),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column(
            "side_effect_class",
            sa.Enum(
                "read",
                "write",
                "irreversible",
                name="side_effect_class",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("arguments", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "outcome",
            sa.Enum(
                "ok",
                "error",
                "pending_approval",
                name="tool_outcome",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_tool_calls_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tool_calls")),
    )
    op.create_index(
        op.f("ix_tool_calls_correlation_id"), "tool_calls", ["correlation_id"], unique=False
    )
    op.create_index(op.f("ix_tool_calls_tenant_id"), "tool_calls", ["tenant_id"], unique=False)

    # No UPDATE or DELETE grant: the application can record history but never rewrite it.
    role = get_settings().db_app_role
    op.execute(
        f"""
        ALTER TABLE tool_calls ENABLE ROW LEVEL SECURITY;
        ALTER TABLE tool_calls FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON tool_calls
            USING (tenant_id = app_current_tenant())
            WITH CHECK (tenant_id = app_current_tenant());
        GRANT SELECT, INSERT ON tool_calls TO "{role}";
        """
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_tool_calls_tenant_id"), table_name="tool_calls")
    op.drop_index(op.f("ix_tool_calls_correlation_id"), table_name="tool_calls")
    op.drop_table("tool_calls")
