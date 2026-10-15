"""Interruttori del sistema

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "impostazioni",
        sa.Column("chiave", sa.String(length=50), primary_key=True),
        sa.Column("valore", sa.String(length=255), nullable=False),
        sa.Column("aggiornato_il", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("impostazioni")
