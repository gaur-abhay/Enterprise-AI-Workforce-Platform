"""Turn queue with tenant RLS, and a schema for the LangGraph checkpointer.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-19 17:02:48.140950
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from ai_employee.config import get_settings

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "turn_tasks",
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("actor", sa.String(length=64), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("actor_principals", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("conversation_ref", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "succeeded",
                "failed",
                name="task_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("claimed_by", sa.String(length=100), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
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
            name=op.f("fk_turn_tasks_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_turn_tasks")),
    )
    op.create_index("ix_turn_tasks_claimable", "turn_tasks", ["status", "created_at"], unique=False)
    op.create_index(op.f("ix_turn_tasks_tenant_id"), "turn_tasks", ["tenant_id"], unique=False)

    # Claiming spans tenants and runs as the connecting role; tenant sessions enqueue and read.
    role = get_settings().db_app_role
    op.execute(
        f"""
        ALTER TABLE turn_tasks ENABLE ROW LEVEL SECURITY;
        ALTER TABLE turn_tasks FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON turn_tasks
            USING (tenant_id = app_current_tenant())
            WITH CHECK (tenant_id = app_current_tenant());
        GRANT SELECT, INSERT, UPDATE ON turn_tasks TO "{role}";
        """
    )

    # Checkpointer tables are created by PostgresSaver.setup() inside this schema, kept out of
    # public so they never appear in model/migration comparisons. The application role has
    # no access: only the worker reads checkpoints, keyed by task id.
    op.execute("CREATE SCHEMA IF NOT EXISTS langgraph")


def downgrade() -> None:
    op.drop_index(op.f("ix_turn_tasks_tenant_id"), table_name="turn_tasks")
    op.drop_index("ix_turn_tasks_claimable", table_name="turn_tasks")
    op.drop_table("turn_tasks")
    op.execute("DROP SCHEMA IF EXISTS langgraph CASCADE")
