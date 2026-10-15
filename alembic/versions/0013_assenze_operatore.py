"""Ferie e assenze di piu' giorni, operatore per operatore

Revision ID: 0013
Revises: 0012

Prima l'assenza non si salvava da nessuna parte: si annullava la giornata e
la richiesta finiva li'. Con un giorno solo si notava — c'e' chi guarda
l'agenda — ma una settimana di ferie senza nessuna traccia vuol dire che il
bot ricomincia a dare appuntamenti il pomeriggio stesso, e il rientro e' una
giornata piena di clienti che l'operatore non sa di avere.
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assenze_operatore",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "parrucchiere_id",
            sa.Integer(),
            sa.ForeignKey("parrucchieri.id"),
            nullable=False,
            index=True,
        ),
        # Estremi compresi: "dal 20 al 24" sono cinque giorni, come li
        # direbbe chiunque in salone.
        sa.Column("dal", sa.Date(), nullable=False, index=True),
        sa.Column("al", sa.Date(), nullable=False, index=True),
        sa.Column("motivo", sa.String(length=120), nullable=True),
        sa.Column("creato_il", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("assenze_operatore")
