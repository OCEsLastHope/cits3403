"""add events tables

Revision ID: ab12cd34ef56
Revises: c3e7a9f4d2b1
Create Date: 2026-05-08 12:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "ab12cd34ef56"
down_revision = "c3e7a9f4d2b1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "event",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("creator_user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("location_or_link", sa.String(length=255), nullable=True),
        sa.Column("visibility_mode", sa.String(length=20), nullable=False),
        sa.Column("max_attendees", sa.Integer(), nullable=True),
        sa.Column("start_at", sa.DateTime(), nullable=False),
        sa.Column("end_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["creator_user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("visibility_mode in ('invite_only', 'open')", name="ck_event_visibility_mode"),
        sa.CheckConstraint("status in ('scheduled', 'cancelled')", name="ck_event_status"),
        sa.CheckConstraint("max_attendees IS NULL OR max_attendees >= 2", name="ck_event_max_attendees"),
        sa.CheckConstraint("end_at > start_at", name="ck_event_time_window"),
    )
    op.create_index("ix_event_creator_user_id", "event", ["creator_user_id"], unique=False)
    op.create_index("ix_event_status_start_at", "event", ["status", "start_at"], unique=False)

    op.create_table(
        "event_attendee",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("invite_status", sa.String(length=20), nullable=False),
        sa.Column("responded_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["event.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "user_id", name="uq_event_attendee"),
        sa.CheckConstraint(
            "invite_status in ('invited', 'accepted', 'declined', 'left')",
            name="ck_event_attendee_status",
        ),
    )
    op.create_index("ix_event_attendee_user_id", "event_attendee", ["user_id"], unique=False)


def downgrade():
    op.drop_index("ix_event_attendee_user_id", table_name="event_attendee")
    op.drop_table("event_attendee")

    op.drop_index("ix_event_status_start_at", table_name="event")
    op.drop_index("ix_event_creator_user_id", table_name="event")
    op.drop_table("event")
