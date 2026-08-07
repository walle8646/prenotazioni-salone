import pytest

from prompts.system_prompt import PARRUCCHIERI_MAP, set_parrucchieri_cache
from services.channels import CollectorChannel
from services.fakes import FakeBackends, FakeRedis
from services.operatori import OPERATORI

OPERATORE_TEST = OPERATORI[2]  # Francesco


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
