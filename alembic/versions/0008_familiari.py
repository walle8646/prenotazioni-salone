"""Le persone per cui un cliente prenota senza che abbiano un telefono loro.

Un figlio, un genitore: prima finivano tutti sulla stessa scheda, e la regola
"un appuntamento per volta" rendeva impossibile prenotare per due persone
dello stesso contatto.

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # In batch perche' SQLite non sa alterare i vincoli, e i test fanno girare
    # le migrazioni proprio su SQLite: su Postgres batch emette gli stessi
    # ALTER di sempre, quindi non costa niente.
    with op.batch_alter_table("clienti") as batch:
        batch.add_column(sa.Column("titolare_id", sa.Integer(), nullable=True))
        batch.create_index("ix_clienti_titolare_id", ["titolare_id"])
        batch.create_foreign_key(
            "fk_clienti_titolare", "clienti", ["titolare_id"], ["id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("clienti") as batch:
        batch.drop_constraint("fk_clienti_titolare", type_="foreignkey")
        batch.drop_index("ix_clienti_titolare_id")
        batch.drop_column("titolare_id")
