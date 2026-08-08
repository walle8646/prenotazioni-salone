import asyncio
from logging.config import fileConfig
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context

import sys
sys.path.insert(0, ".")

from config import settings
from models.database import Base
from models.orm import Cliente, Parrucchiere, Appuntamento  # noqa: F401 - import per metadata

config = context.config

# Override sqlalchemy.url con il valore dall'env. Serve la forma asincrona:
# Render fornisce DATABASE_URL come postgresql://, ma qui sotto l'engine è
# asincrono e con quel prefisso SQLAlchemy cercherebbe psycopg2, che non è
# tra le dipendenze.
config.set_main_option("sqlalchemy.url", settings.async_database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    # Quando è l'applicazione ad applicare le migrazioni all'avvio ci passa la
    # connessione che ha già aperto: aprirne un'altra qui significherebbe
    # attendere un lock tenuto da noi stessi, cioè non partire più.
    connessione = config.attributes.get("connection")
    if connessione is not None:
        do_run_migrations(connessione)
        return
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
