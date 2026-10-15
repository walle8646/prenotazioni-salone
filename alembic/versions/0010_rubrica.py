"""La rubrica del telefono del salone

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rubrica",
        sa.Column("telefono", sa.String(length=20), primary_key=True),
        sa.Column("nome", sa.String(length=100), nullable=True),
        sa.Column("nome_completo", sa.String(length=200), nullable=True),
        sa.Column("aggiornato_il", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("rubrica")
