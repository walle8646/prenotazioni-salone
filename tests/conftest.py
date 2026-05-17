import pytest
from unittest.mock import AsyncMock


@pytest.fixture
def mock_redis():
    """Redis mock che simula get/set/delete."""
    redis = AsyncMock()
    store = {}

    async def mock_get(key):
        return store.get(key)

    async def mock_set(key, value, ex=None):
        store[key] = value

    async def mock_delete(key):
        store.pop(key, None)

    redis.get = mock_get
    redis.set = mock_set
    redis.delete = mock_delete
    return redis


@pytest.fixture
def sample_session():
    """Sessione di esempio per testing."""
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
def mock_claude_response():
    """Mock per la risposta Claude."""
    async def _mock(system_prompt, history):
        return "Ciao! Benvenuto al Salone Nadia. Come posso aiutarti?"
    return _mock
