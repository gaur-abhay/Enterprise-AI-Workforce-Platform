"""Approvals and outbox with tenant RLS; awaiting_approval task status.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-19 17:41:28.318166
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from ai_employee.config import get_settings

STATUSES = ("queued", "running", "awaiting_approval", "succeeded", "failed")


def _status_check(values: tuple[str, ...]) -> None:
    op.drop_constraint(op.f("ck_turn_tasks_task_status"), "turn_tasks", type_="check")
    allowed = ", ".join(f"'{v}'" for v in values)
    op.create_check_constraint(
        op.f("ck_turn_tasks_task_status"), "turn_tasks", f"status IN ({allowed})"
    )


def _tenant_rls(table: str, grants: str) -> None:
    role = get_settings().db_app_role
    op.execute(
        f"""
        ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = app_current_tenant())
            WITH CHECK (tenant_id = app_current_tenant());
        GRANT {grants} ON {table} TO "{role}";
        """
    )


revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "outbox_messages",
        sa.Column("recipient", sa.String(length=320), nullable=False),
        sa.Column("subject", sa.String(length=300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("sent_by", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
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
            name=op.f("fk_outbox_messages_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbox_messages")),
    )
    op.create_index(
        op.f("ix_outbox_messages_tenant_id"), "outbox_messages", ["tenant_id"], unique=False
    )
    op.create_table(
        "approvals",
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("tool_call_id", sa.String(length=100), nullable=False),
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
            nullable=False,
        ),
        sa.Column("arguments", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("approver", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "approved",
                "rejected",
                name="approval_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["turn_tasks.id"],
            name=op.f("fk_approvals_task_id_turn_tasks"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_approvals_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approvals")),
        sa.UniqueConstraint(
            "task_id", "tool_call_id", name=op.f("uq_approvals_task_id_tool_call_id")
        ),
    )
    op.create_index(op.f("ix_approvals_status"), "approvals", ["status"], unique=False)
    op.create_index(op.f("ix_approvals_tenant_id"), "approvals", ["tenant_id"], unique=False)

    _tenant_rls("approvals", "SELECT, INSERT, UPDATE")
    # Sent mail is a record, like the audit log: never rewritten.
    _tenant_rls("outbox_messages", "SELECT, INSERT")
    # A checked string column, so a new value means replacing its CHECK constraint.
    _status_check(STATUSES)


def downgrade() -> None:
    _status_check(tuple(v for v in STATUSES if v != "awaiting_approval"))
    op.drop_index(op.f("ix_approvals_tenant_id"), table_name="approvals")
    op.drop_index(op.f("ix_approvals_status"), table_name="approvals")
    op.drop_table("approvals")
    op.drop_index(op.f("ix_outbox_messages_tenant_id"), table_name="outbox_messages")
    op.drop_table("outbox_messages")
