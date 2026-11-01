"""Add per-account email suppression entries.

Revision ID: 002_add_suppressed
Revises: 001_initial_schema
"""
import sqlalchemy as sa
from alembic import op

revision = "002_add_suppressed"
down_revision = "001_initial_schema"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "suppressed",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("suppressed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "email", name="uq_suppressed_user_email"),
    )
    op.create_index("ix_suppressed_user_id", "suppressed", ["user_id"])


def downgrade():
    op.drop_index("ix_suppressed_user_id", table_name="suppressed")
    op.drop_table("suppressed")
