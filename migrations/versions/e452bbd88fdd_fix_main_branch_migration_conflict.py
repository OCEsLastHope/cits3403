"""fix main branch migration conflict

Revision ID: e452bbd88fdd
Revises: ab12cd34ef56, d9f36befe962
Create Date: 2026-05-09 21:45:07.359290

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e452bbd88fdd'
down_revision = ('ab12cd34ef56', 'd9f36befe962')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
