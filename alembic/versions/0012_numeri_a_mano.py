"""I numeri a cui risponde solo una persona

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "numeri_a_mano",
        sa.Column("telefono", sa.String(length=20), primary_key=True),
        sa.Column("nota", sa.String(length=200), nullable=True),
        sa.Column("creato_il", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("numeri_a_mano")
