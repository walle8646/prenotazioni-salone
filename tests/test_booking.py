import pytest
from services.session_manager import new_session, _key


def test_new_session_structure():
    """Verifica la struttura di una nuova sessione."""
    session = new_session()
    assert session["stato_flusso"] == "saluto"
    assert session["history"] == []
    assert session["dati_temp"]["servizio"] is None
    assert session["dati_temp"]["parrucchiere"] is None
    assert session["dati_temp"]["slot"] is None
    assert session["dati_temp"]["nome"] is None
    assert session["dati_temp"]["cognome"] is None
    assert session["dati_temp"]["email"] is None
    assert "last_activity" in session


def test_session_key():
    """Verifica formato chiave Redis."""
    key = _key("393331234567")
    assert key == "session:393331234567"


@pytest.mark.asyncio
async def test_session_save_and_load(mock_redis):
    """Salvataggio e caricamento sessione da Redis mock."""
    from services.session_manager import save_session, get_session

    session = new_session()
    session["dati_temp"]["nome"] = "Mario"
    session["stato_flusso"] = "scelta_servizio"

    await save_session(mock_redis, "393331234567", session)
    loaded = await get_session(mock_redis, "393331234567")

    assert loaded["dati_temp"]["nome"] == "Mario"
    assert loaded["stato_flusso"] == "scelta_servizio"
