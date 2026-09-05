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


def _database_migrato():
    """Un SQLite in memoria con tutte le migrazioni applicate in ordine.

    Le migrazioni si eseguono a mano invece che con `alembic upgrade`, e non è
    pigrizia: `alembic/env.py` sovrascrive l'URL con `DATABASE_URL`, quindi un
    upgrade lanciato da qui andrebbe a toccare il database di produzione.
    """
    import importlib.util
    import pathlib

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine

    engine = create_engine("sqlite://")
    conn = engine.connect()
    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        for percorso in sorted(pathlib.Path("alembic/versions").glob("0*.py")):
            spec = importlib.util.spec_from_file_location(percorso.stem, percorso)
            migrazione = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migrazione)
            migrazione.upgrade()
    return conn


def test_le_migrazioni_creano_le_stesse_colonne_dei_modelli():
    """Il difetto che questo test previene non rompe una funzione: rompe tutto.

    SQLAlchemy chiede al database tutte le colonne del modello. Se una c'è nel
    modello e non nella migrazione, in produzione ogni singola query su quella
    tabella fallisce — anche quelle che con la novità non c'entrano niente — e
    la suite resta verde, perché i test girano sui finti.
    """
    from sqlalchemy import inspect

    from models.database import Base
    import models.orm  # noqa: F401 - serve a popolare i metadata

    conn = _database_migrato()
    ispettore = inspect(conn)
    presenti = set(ispettore.get_table_names())

    mancanti = {}
    for nome, tabella in Base.metadata.tables.items():
        if nome not in presenti:
            mancanti[nome] = ["tabella intera"]
            continue
        nel_database = {c["name"] for c in ispettore.get_columns(nome)}
        assenti = {c.name for c in tabella.columns} - nel_database
        if assenti:
            mancanti[nome] = sorted(assenti)

    conn.close()
    assert mancanti == {}, f"le migrazioni non creano: {mancanti}"


def test_applicare_le_migrazioni_non_zittisce_i_log_dell_applicazione():
    """Il difetto che ha reso cieco il debug di un'intera serata.

    `alembic/env.py` chiama `fileConfig(alembic.ini)`, e quella funzione non
    aggiunge una configurazione: la sostituisce, disattivando tutti i logger
    già esistenti e riportando la radice a WARN. Lanciando alembic da riga di
    comando è innocuo. Ma le migrazioni le applica anche l'applicazione a ogni
    avvio, e lì i logger già esistenti sono quelli di tutto il progetto: da
    quel momento in produzione non usciva più una riga, nemmeno gli errori.
    """
    import logging

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine

    logging.basicConfig(level=logging.INFO)
    logging.getLogger().setLevel(logging.INFO)
    log_applicazione = logging.getLogger("services.conversation")
    log_applicazione.disabled = False

    engine = create_engine("sqlite://")
    with engine.connect() as connessione:
        configurazione = Config("alembic.ini")
        configurazione.attributes["connection"] = connessione
        command.upgrade(configurazione, "head")

    assert not log_applicazione.disabled, (
        "le migrazioni hanno disattivato i logger dell'applicazione: "
        "in produzione il bot diventa muto nei log"
    )
    assert logging.getLogger().level <= logging.INFO, (
        "le migrazioni hanno alzato il livello della radice: gli INFO spariscono"
    )
