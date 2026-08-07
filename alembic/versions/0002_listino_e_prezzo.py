"""Listino a database e prezzo salvato sull'appuntamento.

Due cose:
1. la tabella `servizi`, così prezzi e durate si possono modificare dal
   pannello di gestione senza toccare il codice;
2. la colonna `prezzo` sull'appuntamento, che conserva la cifra pattuita al
   momento della prenotazione anche se il listino cambierà in futuro.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "servizi",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("codice", sa.String(length=50), nullable=False),
        sa.Column("nome", sa.String(length=200), nullable=False),
        sa.Column("prezzo", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("durata_min", sa.Integer(), nullable=False),
        sa.Column("alias", sa.JSON(), nullable=True),
        sa.Column("ordine", sa.Integer(), nullable=True),
        sa.Column("attivo", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("codice"),
    )
    op.create_index("ix_servizi_codice", "servizi", ["codice"])

    op.add_column(
        "appuntamenti",
        sa.Column("prezzo", sa.Numeric(precision=6, scale=2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("appuntamenti", "prezzo")
    op.drop_index("ix_servizi_codice", table_name="servizi")
    op.drop_table("servizi")
