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


def _database_gia_popolato(connection) -> bool:
    """True se qui dentro c'è già qualcosa di nostro."""
    from sqlalchemy import inspect

    tabelle = set(inspect(connection).get_table_names())
    return bool(tabelle & set(Base.metadata.tables)) or "alembic_version" in tabelle


def _applica_migrazioni(connection) -> None:
    """Porta un database già esistente all'ultima migrazione.

    Senza, aggiungere una colonna significava doversi ricordare di lanciare a
    mano `alembic upgrade head` su Render prima che il deploy andasse in
    porto. Dimenticarlo non rompe la funzione appena aggiunta: rompe tutto,
    perché SQLAlchemy chiede tutte le colonne del modello e quella nuova non
    c'è ancora. Meglio che se ne occupi l'avvio.
    """
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    configurazione = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    configurazione.attributes["connection"] = connection
    command.upgrade(configurazione, "head")


async def create_tables():
    """Prepara il database: lo crea se è nuovo, lo aggiorna se esiste già."""
    # create_all conosce solo i modelli già importati. Finora funzionava per
    # combinazione, perché main.py carica i router e uno di quelli importa
    # models.orm: bastava spostare un import perché il database nascesse vuoto.
    # L'import sta qui dentro e non in cima al modulo perché orm.py importa Base
    # da qui, e in testa sarebbe una dipendenza circolare.
    from models import orm  # noqa: F401

    logger = logging.getLogger(__name__)

    async with engine.begin() as conn:
        popolato = await conn.run_sync(_database_gia_popolato)

        if not popolato:
            # Database nuovo: le tabelle nascono dai modelli, già complete.
            await conn.run_sync(Base.metadata.create_all)

        try:
            # Un database mai annotato viene segnato come allineato: le sue
            # tabelle vengono dai modelli, quindi rieseguire 0001 fallirebbe.
            await conn.run_sync(_annota_versione_migrazioni)
        except Exception:  # noqa: BLE001 - non deve impedire l'avvio del bot
            logger.warning(
                "Non è stato possibile annotare la versione delle migrazioni: "
                "prima della prossima migrazione servirà `alembic stamp head`.",
                exc_info=True,
            )
            return

        if popolato:
            try:
                await conn.run_sync(_applica_migrazioni)
            except Exception:  # noqa: BLE001
                logger.error(
                    "Migrazioni non applicate: se una di esse aggiunge colonne, "
                    "le letture di quelle tabelle falliranno. Serve "
                    "`alembic upgrade head` a mano.",
                    exc_info=True,
                )


async def get_db():
    """Dependency FastAPI per ottenere una sessione DB."""
    async with async_session() as session:
        yield session
