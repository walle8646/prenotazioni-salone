"""I telefoni che ricevono le notifiche del salone.

Senza notifica, il passaggio a una persona funziona solo per chi si ricorda di
aprire il pannello: il cliente aspetta e nessuno lo sa. L'email c'era già, ma
una notifica sul telefono arriva anche a chi la posta la guarda la sera.

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "iscrizioni_push",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("p256dh", sa.String(length=255), nullable=False),
        sa.Column("auth", sa.String(length=255), nullable=False),
        sa.Column(
            "creato_il", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
        # Unico: reinstallando l'applicazione lo stesso telefono si ripresenta
        # con lo stesso endpoint, e senza vincolo riceverebbe ogni notifica due
        # volte.
        sa.UniqueConstraint("endpoint"),
    )


def downgrade() -> None:
    op.drop_table("iscrizioni_push")
