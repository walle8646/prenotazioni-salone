"""Verifica che un database nuovo risulti già allineato alle migrazioni.

Le tabelle nascono dai modelli al primo avvio, non da Alembic. Senza
l'annotazione, la prima migrazione futura ripartirebbe da 0001 e fallirebbe
creando tabelle già esistenti. Qui si usa SQLite in memoria: non serve nessun
database vero.
"""

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from models.database import _annota_versione_migrazioni


def _ultima_revisione() -> str:
    return ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()


def test_un_database_nuovo_viene_segnato_come_gia_migrato():
    engine = create_engine("sqlite://")

    with engine.begin() as conn:
        _annota_versione_migrazioni(conn)
        versione = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()

    assert versione == _ultima_revisione()


def test_create_all_conosce_tutte_le_tabelle_del_progetto():
    """Bastava un import spostato perché il database nascesse vuoto.

    create_all crea solo i modelli già importati, e models/database.py non
    importava models/orm.py: funzionava perché main.py carica i router e uno di
    quelli lo importa di rimbalzo.
    """
    import importlib
    import sys

    # Si simula un processo che non ha ancora visto i modelli
    for modulo in ("models.orm", "models.database"):
        sys.modules.pop(modulo, None)

    database = importlib.import_module("models.database")
    assert database.Base.metadata.tables == {}, "premessa del test"

    importlib.import_module("models.orm")
    attese = {"clienti", "parrucchieri", "appuntamenti", "servizi"}
    assert attese <= set(database.Base.metadata.tables)


def test_un_database_gia_annotato_non_viene_toccato():
    """Chi ha già una storia di migrazioni non va riscritto."""
    engine = create_engine("sqlite://")

    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
        conn.execute(text("INSERT INTO alembic_version VALUES ('0001')"))

    with engine.begin() as conn:
        _annota_versione_migrazioni(conn)
        righe = conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all()

    assert righe == ["0001"], "una revisione precedente non va sovrascritta"
