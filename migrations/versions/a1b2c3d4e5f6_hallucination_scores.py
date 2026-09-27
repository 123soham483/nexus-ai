"""hallucination score history

Revision ID: a1b2c3d4e5f6
Revises: 54bd7b89394e
Create Date: 2026-09-24
"""
from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "54bd7b89394e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hallucination_scores",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("agent_type", sa.String(length=64), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("verdict", sa.String(length=32), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_hallucination_scores_task_id", "hallucination_scores", ["task_id"])
    op.create_index("ix_hallucination_scores_tenant_id", "hallucination_scores", ["tenant_id"])
    op.create_index("ix_hallucination_scores_agent_type", "hallucination_scores", ["agent_type"])
    op.create_index("ix_hallucination_scores_recorded_at", "hallucination_scores", ["recorded_at"])


def downgrade() -> None:
    op.drop_table("hallucination_scores")
