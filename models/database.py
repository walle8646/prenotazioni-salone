import logging

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from config import settings

engine = create_async_engine(settings.async_database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def _annota_versione_migrazioni(connection) -> None:
    """Segna un database appena creato come già allineato alle migrazioni.

    Le tabelle qui sopra nascono dai modelli, non da Alembic, che quindi
    considererebbe questo database mai migrato. Alla prima migrazione futura
    ripartirebbe da 0001 e si fermerebbe creando tabelle già esistenti — nel
    mezzo di un deploy, cioè nel momento peggiore.

    Annotare qui la revisione corrente evita che qualcuno debba ricordarsi di
    lanciare `alembic stamp head` a mano su ogni database nuovo.
    """
    from pathlib import Path

    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.script import ScriptDirectory

    contesto = MigrationContext.configure(connection)
    if contesto.get_current_revision() is not None:
        return  # già annotato, o database gestito davvero da Alembic

    configurazione = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    contesto.stamp(ScriptDirectory.from_config(configurazione), "head")


async def create_tables():
    """Crea le tabelle se non esistono (solo per dev/primo avvio)."""
    # create_all conosce solo i modelli già importati. Finora funzionava per
    # combinazione, perché main.py carica i router e uno di quelli importa
    # models.orm: bastava spostare un import perché il database nascesse vuoto.
    # L'import sta qui dentro e non in cima al modulo perché orm.py importa Base
    # da qui, e in testa sarebbe una dipendenza circolare.
    from models import orm  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        try:
            await conn.run_sync(_annota_versione_migrazioni)
        except Exception:  # noqa: BLE001 - non deve impedire l'avvio del bot
            logging.getLogger(__name__).warning(
                "Non è stato possibile annotare la versione delle migrazioni: "
                "prima della prossima migrazione servirà `alembic stamp head`.",
                exc_info=True,
            )


async def get_db():
    """Dependency FastAPI per ottenere una sessione DB."""
    async with async_session() as session:
        yield session
