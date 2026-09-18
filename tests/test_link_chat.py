"""Test sul link che porta da WhatsApp alla chat del sito.

Quel link è una prova d'identità: chi lo apre entra come titolare di un
numero, e vede e disdice i suoi appuntamenti. Le tre garanzie che lo rendono
accettabile — nel link non c'è il numero, vale una volta sola, scade — non
sono dettagli di stile: sono il motivo per cui la funzione può esistere.
"""

import pytest

from services.conversation import handle_incoming_message
from services.fakes import ScriptedClaude
from services.link_chat import consuma_gettone, crea_gettone, indirizzo

NUMERO = "393491021925"


@pytest.mark.asyncio
async def test_il_numero_non_compare_nel_gettone(mock_redis):
    """Col numero nell'indirizzo, chiunque abbia il link sarebbe quel cliente."""
    gettone = await crea_gettone(mock_redis, NUMERO)

    assert NUMERO not in gettone
    assert "3491021925" not in gettone
    assert len(gettone) >= 24, "corto è indovinabile"


@pytest.mark.asyncio
async def test_il_gettone_riporta_al_numero(mock_redis):
    gettone = await crea_gettone(mock_redis, NUMERO)
    assert await consuma_gettone(mock_redis, gettone) == NUMERO


@pytest.mark.asyncio
async def test_vale_una_volta_sola(mock_redis):
    """Un link inoltrato al marito non apre gli appuntamenti della moglie."""
    gettone = await crea_gettone(mock_redis, NUMERO)

    assert await consuma_gettone(mock_redis, gettone) == NUMERO
    assert await consuma_gettone(mock_redis, gettone) is None


@pytest.mark.asyncio
async def test_due_gettoni_non_si_somigliano(mock_redis):
    primo = await crea_gettone(mock_redis, NUMERO)
    secondo = await crea_gettone(mock_redis, NUMERO)
    assert primo != secondo


@pytest.mark.asyncio
async def test_un_gettone_inventato_non_apre_niente(mock_redis):
    assert await consuma_gettone(mock_redis, "provaAdIndovinare") is None


@pytest.mark.asyncio
async def test_senza_redis_non_si_finge_un_gettone(mock_redis):
    """Meglio continuare su WhatsApp che mandare un link che non funziona."""
    assert await crea_gettone(None, NUMERO) is None
    assert await consuma_gettone(None, "qualsiasi") is None


def test_l_indirizzo_si_compone_sulla_radice_pubblica():
    assert indirizzo("abc123", base="https://salone.example") == (
        "https://salone.example/chat/abc123"
    )
    # Anche con la barra finale, che è come la si incolla di solito
    assert indirizzo("abc123", base="https://salone.example/") == (
        "https://salone.example/chat/abc123"
    )


def test_senza_indirizzo_pubblico_non_c_e_link():
    """Un link relativo dentro un messaggio WhatsApp non porta da nessuna parte."""
    assert indirizzo("abc123", base="") is None


# ------------------------------------------------------ il bot che lo manda


@pytest.mark.asyncio
async def test_il_bot_manda_il_link_al_numero_da_cui_scrive(
    mock_redis, backends, canale, monkeypatch
):
    """Il gettone non arriva mai da un parametro del modello.

    Così la richiesta di un link per il numero di un altro non è nemmeno
    esprimibile: vale sempre e solo il mittente della conversazione.
    """
    from config import settings

    monkeypatch.setattr(settings, "public_base_url", "https://salone.example")

    await handle_incoming_message(
        redis=mock_redis,
        phone=NUMERO,
        text="mi fai vedere tutti gli orari di questa settimana?",
        msg_type="text",
        channel=canale,
        backends=backends,
        claude=ScriptedClaude([ScriptedClaude.azione(action="CONTINUA_SUL_SITO")]),
    )

    inviato = "\n".join(canale.testi)
    assert "https://salone.example/chat/" in inviato

    gettone = inviato.split("/chat/")[1].strip()
    assert await consuma_gettone(mock_redis, gettone) == NUMERO


@pytest.mark.asyncio
async def test_dal_sito_il_link_non_ha_senso(mock_redis, backends, monkeypatch):
    """Ci si è già: mandarcelo sarebbe dire "vai dove sei"."""
    from config import settings

    from services.conversation import handle_incoming_message_web

    monkeypatch.setattr(settings, "public_base_url", "https://salone.example")

    risposta = await handle_incoming_message_web(
        redis=mock_redis,
        session_id="web_abc123456789",
        text="mi fai vedere gli orari?",
        backends=backends,
        claude=ScriptedClaude([ScriptedClaude.azione(action="CONTINUA_SUL_SITO")]),
    )

    assert "/chat/" not in (risposta.get("text") or "")


# --------------------------------------------- l'identità che il link prova


@pytest.mark.asyncio
async def test_chi_entra_col_link_e_riconosciuto(mock_redis, backends):
    """Dopo il link la sessione del sito sa chi scrive, come dopo il codice email."""
    from services.conversation import _appuntamenti_del_richiedente, _identita_provata

    backends.clienti.append(
        {"id": 1, "nome": "Valerio", "cognome": "Di Dio", "telefono": NUMERO, "email": None}
    )

    sessione = {"telefono_verificato": NUMERO, "dati_temp": {}}
    assert _identita_provata("web_abc123456789", sessione) is True

    trovato = await _appuntamenti_del_richiedente("web_abc123456789", sessione, backends)
    assert trovato["cliente"]["nome"] == "Valerio"


def test_senza_prove_dal_sito_non_si_e_nessuno():
    from services.conversation import _identita_provata

    assert _identita_provata("web_abc123456789", {"dati_temp": {}}) is False
    # Da WhatsApp il numero del mittente basta e avanza
    assert _identita_provata(NUMERO, {"dati_temp": {}}) is True


# ------------------------------------------------------------- la rotta web


@pytest.fixture
def sito(mock_redis):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers import website

    app = FastAPI()
    app.include_router(website.router)
    app.state.redis = mock_redis
    client = TestClient(app, follow_redirects=False)
    client.redis = mock_redis
    return client


@pytest.mark.asyncio
async def test_il_link_apre_una_sessione_gia_riconosciuta(sito, mock_redis):
    import json
    import re

    gettone = await crea_gettone(mock_redis, NUMERO)
    risposta = sito.get(f"/chat/{gettone}")

    assert risposta.status_code == 303
    sessione = re.search(r"sessione=(web_[0-9a-f]{12})", risposta.headers["location"])
    assert sessione, risposta.headers["location"]

    # Il formato deve essere quello che il WebSocket accetta, altrimenti la
    # sessione appena creata verrebbe scartata e il cliente ripartirebbe da zero.
    salvata = json.loads(await mock_redis.get(f"session:{sessione.group(1)}"))
    assert salvata["telefono_verificato"] == NUMERO
    assert salvata["dati_temp"]["telefono"] == NUMERO


@pytest.mark.asyncio
async def test_un_link_gia_usato_apre_la_chat_normale(sito, mock_redis):
    """Non una pagina di errore: l'unica colpa del cliente è aver aspettato."""
    gettone = await crea_gettone(mock_redis, NUMERO)
    sito.get(f"/chat/{gettone}")

    risposta = sito.get(f"/chat/{gettone}")

    assert risposta.status_code == 303
    assert risposta.headers["location"] == "/?chat=1"
    assert "sessione=" not in risposta.headers["location"]
