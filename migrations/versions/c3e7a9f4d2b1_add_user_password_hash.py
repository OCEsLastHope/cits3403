"""add user password hash

Revision ID: c3e7a9f4d2b1
Revises: b1f3c9d2a7e1
Create Date: 2026-05-06 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c3e7a9f4d2b1"
down_revision = "b1f3c9d2a7e1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("user", sa.Column("password_hash", sa.String(length=255), nullable=True))


def downgrade():
    op.drop_column("user", "password_hash")
