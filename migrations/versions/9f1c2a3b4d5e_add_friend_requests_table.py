"""add friend requests table

Revision ID: 9f1c2a3b4d5e
Revises: 6b11089fb8d5
Create Date: 2026-05-15 11:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "9f1c2a3b4d5e"
down_revision = "6b11089fb8d5"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "friend_request",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_low_id", sa.Integer(), nullable=False),
        sa.Column("user_high_id", sa.Integer(), nullable=False),
        sa.Column("requested_by_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["requested_by_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["user_high_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["user_low_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_low_id", "user_high_id", name="uq_friend_pair"),
    )


def downgrade():
    op.drop_table("friend_request")
