"""Conversazioni passate a una persona.

Quando un cliente chiede di parlare con qualcuno del salone, il bot si ferma e
la conversazione compare nel pannello. Servono due tabelle: una per lo stato
del passaggio, una per lo scambio che la receptionist deve poter leggere.

Lo scambio si salva **solo** per queste conversazioni. Quelle normali col bot
restano nella sessione Redis che scade da sé: registrarle tutte vorrebbe dire
conservare a tempo indeterminato ogni parola di ogni cliente, che non è quello
che l'informativa promette.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversazioni_operatore",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("telefono", sa.String(length=64), nullable=False),
        sa.Column(
            "canale", sa.String(length=20), nullable=False, server_default="whatsapp"
        ),
        sa.Column("cliente_id", sa.Integer(), nullable=True),
        sa.Column("nome_visualizzato", sa.String(length=120), nullable=True),
        sa.Column(
            "stato", sa.String(length=20), nullable=False, server_default="attesa"
        ),
        sa.Column("motivo", sa.Text(), nullable=True),
        sa.Column(
            "aperta_il",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "ultimo_messaggio_cliente",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("presa_il", sa.DateTime(), nullable=True),
        sa.Column("chiusa_il", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["cliente_id"], ["clienti.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_conversazioni_operatore_telefono",
        "conversazioni_operatore",
        ["telefono"],
    )
    # Il pannello chiede sempre "quali sono aperte" e "le più recenti in cima":
    # sono le due colonne su cui si ordina e si filtra a ogni apertura.
    op.create_index(
        "ix_conversazioni_operatore_stato", "conversazioni_operatore", ["stato"]
    )
    op.create_index(
        "ix_conversazioni_operatore_aperta_il",
        "conversazioni_operatore",
        ["aperta_il"],
    )

    op.create_table(
        "messaggi_conversazione",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("conversazione_id", sa.Integer(), nullable=False),
        sa.Column("autore", sa.String(length=20), nullable=False),
        sa.Column("testo", sa.Text(), nullable=False),
        sa.Column(
            "creato_il", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["conversazione_id"], ["conversazioni_operatore.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_messaggi_conversazione_conversazione_id",
        "messaggi_conversazione",
        ["conversazione_id"],
    )
    op.create_index(
        "ix_messaggi_conversazione_creato_il",
        "messaggi_conversazione",
        ["creato_il"],
    )


def downgrade() -> None:
    op.drop_table("messaggi_conversazione")
    op.drop_table("conversazioni_operatore")
