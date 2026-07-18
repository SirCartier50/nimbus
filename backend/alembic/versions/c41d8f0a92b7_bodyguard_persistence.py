"""bodyguard persistence — alerts/logs/patrol state move from process RAM to Postgres

Revision ID: c41d8f0a92b7
Revises: 5567ba294299
Create Date: 2026-07-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c41d8f0a92b7"
down_revision: Union[str, Sequence[str], None] = "5567ba294299"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bodyguard_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), server_default="warning", nullable=False),
        sa.Column("read", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_bodyguard_alerts_user_id"), "bodyguard_alerts", ["user_id"])
    op.create_index(op.f("ix_bodyguard_alerts_created_at"), "bodyguard_alerts", ["created_at"])

    op.create_table(
        "bodyguard_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("level", sa.String(), server_default="info", nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_bodyguard_logs_user_id"), "bodyguard_logs", ["user_id"])
    op.create_index(op.f("ix_bodyguard_logs_created_at"), "bodyguard_logs", ["created_at"])

    op.create_table(
        "bodyguard_status",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("last_check", sa.DateTime(timezone=True), nullable=True),
        sa.Column("instances_stopped", sa.Integer(), server_default="0", nullable=False),
        sa.Column("sub_resources", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("bodyguard_status")
    op.drop_index(op.f("ix_bodyguard_logs_created_at"), table_name="bodyguard_logs")
    op.drop_index(op.f("ix_bodyguard_logs_user_id"), table_name="bodyguard_logs")
    op.drop_table("bodyguard_logs")
    op.drop_index(op.f("ix_bodyguard_alerts_created_at"), table_name="bodyguard_alerts")
    op.drop_index(op.f("ix_bodyguard_alerts_user_id"), table_name="bodyguard_alerts")
    op.drop_table("bodyguard_alerts")
