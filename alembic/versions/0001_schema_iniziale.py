"""Schema iniziale: clienti, parrucchieri, appuntamenti.

Corrisponde alle tabelle create finora da Base.metadata.create_all().
Se il database esiste già con queste tabelle, non rieseguire questa migrazione:
allineala con `alembic stamp 0001` e poi lancia `alembic upgrade head`.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "parrucchieri",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("nome", sa.String(length=100), nullable=False),
        sa.Column("gcal_calendar_id", sa.String(length=255), nullable=False),
        sa.Column("attivo", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "clienti",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("nome", sa.String(length=100), nullable=True),
        sa.Column("cognome", sa.String(length=100), nullable=True),
        sa.Column("telefono_wa", sa.String(length=20), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("canale_origine", sa.String(length=20), nullable=True),
        sa.Column("note_private", sa.Text(), nullable=True),
        sa.Column("parrucchiere_pref_id", sa.Integer(), nullable=True),
        sa.Column("prima_visita", sa.Date(), nullable=True),
        sa.Column("ultima_visita", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(["parrucchiere_pref_id"], ["parrucchieri.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telefono_wa"),
    )
    op.create_index("ix_clienti_telefono_wa", "clienti", ["telefono_wa"])

    op.create_table(
        "appuntamenti",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("cliente_id", sa.Integer(), nullable=False),
        sa.Column("parrucchiere_id", sa.Integer(), nullable=True),
        sa.Column("data_ora", sa.DateTime(), nullable=False),
        sa.Column("durata_min", sa.Integer(), nullable=True),
        sa.Column("servizi", sa.JSON(), nullable=True),
        sa.Column("stato", sa.String(length=20), nullable=True),
        sa.Column("richieste_spec", sa.Text(), nullable=True),
        sa.Column("foto_riferimento", sa.Text(), nullable=True),
        sa.Column("gcal_event_id", sa.String(length=255), nullable=True),
        sa.Column("note_post_app", sa.Text(), nullable=True),
        sa.Column("reminder_inviato", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["cliente_id"], ["clienti.id"]),
        sa.ForeignKeyConstraint(["parrucchiere_id"], ["parrucchieri.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_appuntamenti_data_ora", "appuntamenti", ["data_ora"])


def downgrade() -> None:
    op.drop_index("ix_appuntamenti_data_ora", table_name="appuntamenti")
    op.drop_table("appuntamenti")
    op.drop_index("ix_clienti_telefono_wa", table_name="clienti")
    op.drop_table("clienti")
    op.drop_table("parrucchieri")
