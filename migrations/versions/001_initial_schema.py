"""Create the initial MailFlow Studio schema.

Revision ID: 001_initial_schema
Revises:
"""
from alembic import op

from models import db
from template_models import EmailTemplate  # noqa: F401 - registers its table

revision = "001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # The model metadata is the canonical initial schema. Subsequent schema
    # changes must be represented by normal Alembic operations in new files.
    db.metadata.create_all(bind=op.get_bind())


def downgrade():
    db.metadata.drop_all(bind=op.get_bind())
