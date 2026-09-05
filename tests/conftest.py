from datetime import date, timedelta

import pytest

from prompts.system_prompt import PARRUCCHIERI_MAP, set_parrucchieri_cache
from services.channels import CollectorChannel
from services.fakes import FakeBackends, FakeRedis
from services.operatori import OPERATORI
from services.slots import is_open

OPERATORE_TEST = OPERATORI[2]  # Francesco


def prossimo_giorno_aperto(minimo_giorni_avanti: int = 7) -> str:
    """Una data futura in cui il salone è aperto.

    I test non devono invecchiare. Una data fissa col passare dei mesi finisce
    nel passato, e la disponibilità — che ora scarta gli slot già trascorsi —
    smette di proporne, facendo fallire test che non c'entrano niente.
    """
    giorno = date.today() + timedelta(days=minimo_giorni_avanti)
    for _ in range(14):
        if is_open(giorno.isoformat()):
            return giorno.isoformat()
        giorno += timedelta(days=1)
    raise RuntimeError("nessun giorno di apertura nelle prossime due settimane")


@pytest.fixture(autouse=True)
def parrucchieri_noti():
    """Popola la cache dei parrucchieri come farebbe l'avvio dell'app."""
    set_parrucchieri_cache(PARRUCCHIERI_MAP)
    yield
    set_parrucchieri_cache({})


@pytest.fixture
def mock_redis():
    """Redis in memoria con la stessa interfaccia usata dal codice."""
    return FakeRedis()


@pytest.fixture
def backends():
    """Calendario, database ed email finti."""
    return FakeBackends()


@pytest.fixture
def canale():
    """Canale che raccoglie quello che il bot direbbe, invece di inviarlo."""
    return CollectorChannel()


@pytest.fixture
def cal_id_operatore():
    """Calendar ID del primo operatore, usato negli scenari di prenotazione."""
    return PARRUCCHIERI_MAP[OPERATORE_TEST]


@pytest.fixture
def sample_session():
    """Sessione di esempio."""
    return {
        "stato_flusso": "saluto",
        "history": [],
        "dati_temp": {
            "servizio": None,
            "parrucchiere": None,
            "slot": None,
            "nome": None,
            "cognome": None,
            "email": None,
            "richieste_spec": None,
        },
        "last_activity": "2026-05-16T10:00:00",
    }


@pytest.fixture
def orari_del_salone():
    """Cambia gli orari in vigore per la durata del test, e poi li rimette.

    Senza il ripristino un test che chiude il martedì farebbe fallire tutti
    quelli che vengono dopo, e la causa sarebbe altrove: la cache degli orari
    vive nel modulo, non nel test.
    """
    from services.slots import set_orari_salone

    def cambia(orari: dict[int, list[tuple[str, str]]]):
        set_orari_salone(orari)

    yield cambia
    set_orari_salone(None)


@pytest.fixture
def chiusure_del_salone():
    """Come sopra, per le chiusure straordinarie."""
    from services.slots import set_chiusure

    def cambia(date):
        set_chiusure(date)

    yield cambia
    set_chiusure(set())
