"""Quali condizioni ha accettato il cliente, e quando

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # In batch perche' SQLite non sa alterare le tabelle, e i test fanno
    # girare le migrazioni proprio su SQLite.
    with op.batch_alter_table("clienti") as batch:
        batch.add_column(sa.Column("condizioni_accettate", sa.String(length=50), nullable=True))
        batch.add_column(sa.Column("condizioni_accettate_il", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("clienti") as batch:
        batch.drop_column("condizioni_accettate_il")
        batch.drop_column("condizioni_accettate")
