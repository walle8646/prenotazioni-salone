"""Orari del salone e chiusure straordinarie, modificabili dal pannello.

Fin qui gli orari erano una costante nel codice, e cambiarli voleva dire un
deploy. Erano anche sbagliati: il salone fa orario continuato, non spezzato.

Un giorno di chiusura settimanale è una riga con gli orari a NULL e non
l'assenza di righe, per distinguere "chiuso il lunedì" da "nessuno ha ancora
configurato niente": senza, svuotare la tabella per chiudere tutta la settimana
la farebbe riempire di nuovo al riavvio con gli orari iniziali del codice.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "orari_salone",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("giorno", sa.Integer(), nullable=False),
        sa.Column("ora_inizio", sa.String(length=5), nullable=True),
        sa.Column("ora_fine", sa.String(length=5), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_orari_salone_giorno", "orari_salone", ["giorno"])

    op.create_table(
        "chiusure_salone",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("data", sa.Date(), nullable=False),
        sa.Column("motivo", sa.String(length=120), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("data"),
    )
    op.create_index("ix_chiusure_salone_data", "chiusure_salone", ["data"])


def downgrade() -> None:
    op.drop_table("chiusure_salone")
    op.drop_table("orari_salone")
