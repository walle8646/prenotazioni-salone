"""Foto degli operatori, salvate nel database.

Nel database e non su disco perché su Render il disco è effimero: una foto
caricata dal pannello sparirebbe al primo deploy, che è peggio di non averla.
Sono sei immagini piccole, il costo è trascurabile.

Finché la colonna è vuota, l'avatar viene disegnato dal codice con le
iniziali (`services/avatar.py`): niente file da preparare per partire.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("parrucchieri", sa.Column("foto", sa.LargeBinary(), nullable=True))
    op.add_column(
        "parrucchieri", sa.Column("foto_mime", sa.String(length=50), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("parrucchieri", "foto_mime")
    op.drop_column("parrucchieri", "foto")
