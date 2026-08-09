"""Presenze settimanali degli operatori.

Fino a qui tutti erano disponibili in tutti gli orari del salone, e chi non
c'era si scopriva solo aprendo il calendario. Ora ogni operatore può avere le
sue fasce, e il bot propone solo chi è davvero in salone a quell'ora.

`orari_propri` distingue "non ho ancora configurato niente" da "non lavora
mai": senza quella colonna i due casi sarebbero la stessa tabella vuota, e
attivare la funzione avrebbe fatto sparire tutti gli operatori insieme.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "parrucchieri",
        sa.Column(
            "orari_propri",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_table(
        "presenze",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("parrucchiere_id", sa.Integer(), nullable=False),
        sa.Column("giorno", sa.Integer(), nullable=False),
        sa.Column("ora_inizio", sa.String(length=5), nullable=False),
        sa.Column("ora_fine", sa.String(length=5), nullable=False),
        sa.ForeignKeyConstraint(["parrucchiere_id"], ["parrucchieri.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_presenze_parrucchiere_id", "presenze", ["parrucchiere_id"])


def downgrade() -> None:
    op.drop_index("ix_presenze_parrucchiere_id", table_name="presenze")
    op.drop_table("presenze")
    op.drop_column("parrucchieri", "orari_propri")
