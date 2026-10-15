"""L'interruttore che zittisce il bot.

Esiste perche' il numero e' quello vero del salone: senza, l'unico modo di
fermare il bot sarebbe cambiare le variabili d'ambiente su Render e aspettare
il riavvio, e un interruttore d'emergenza che richiede un deploy non e' un
interruttore d'emergenza.

Due cose vanno provate piu' delle altre: che spento voglia dire **davvero
zitto** — nessuna risposta automatica, nemmeno un rifiuto — e che quello che
arriva mentre e' spento **non si perda**, o spegnerlo diventerebbe un modo di
perdere clienti in silenzio.
"""

import pytest

from services import interruttore
from services.conversation import (
    handle_incoming_message,
    handle_incoming_message_web,
    risponde_una_persona,
)
from services.channels import CollectorChannel
from services.fakes import FakeBackends, FakeRedis, ScriptedClaude

CLIENTE = "393331234567"


@pytest.fixture(autouse=True)
def bot_acceso():
    """Ogni test parte col bot acceso e lo rimette com'era.

    La copia sta in una variabile di modulo: un test che la lascia spenta
    farebbe fallire tutti quelli dopo, e il motivo non si leggerebbe da
    nessuna parte.
    """
    prima = interruttore.bot_attivo()
    interruttore.set_bot_attivo_cache(True)
    yield
    interruttore.set_bot_attivo_cache(prima)


# ------------------------------------------------------- lettura del valore


def test_quello_che_non_si_capisce_lascia_il_bot_acceso():
    """Un salone che tace perche' una riga non si legge e' peggio di una
    risposta sbagliata: nessuno se ne accorge finche' non manca un cliente."""
    assert interruttore.da_testo(None) is True
    assert interruttore.da_testo("") is True
    assert interruttore.da_testo("boh") is True


def test_spento_si_riconosce_in_tutti_i_modi_in_cui_puo_essere_scritto():
    for valore in ("0", "false", "no", "spento", " SPENTO "):
        assert interruttore.da_testo(valore) is False, valore


def test_il_valore_fa_andata_e_ritorno():
    for valore in (True, False):
        assert interruttore.da_testo(interruttore.a_testo(valore)) is valore


# --------------------------------------------------------------- WhatsApp


@pytest.mark.asyncio
async def test_col_bot_spento_al_cliente_non_si_manda_niente():
    backends = FakeBackends()
    channel = CollectorChannel()
    interruttore.set_bot_attivo_cache(False)

    await handle_incoming_message(
        redis=FakeRedis(),
        phone=CLIENTE,
        text="vorrei un taglio",
        msg_type="text",
        channel=channel,
        backends=backends,
        claude=ScriptedClaude([]),
    )

    assert channel.messages == []


@pytest.mark.asyncio
async def test_col_bot_spento_nemmeno_i_rifiuti_partono():
    """Il controllo sta prima di tutto, anche prima di dire che un tipo di
    messaggio non si gestisce: quello sarebbe comunque una risposta del bot."""
    backends = FakeBackends()
    channel = CollectorChannel()
    interruttore.set_bot_attivo_cache(False)

    await handle_incoming_message(
        redis=FakeRedis(),
        phone=CLIENTE,
        text=None,
        msg_type="audio",
        channel=channel,
        backends=backends,
        claude=ScriptedClaude([]),
    )

    assert channel.messages == []


@pytest.mark.asyncio
async def test_col_bot_spento_il_messaggio_finisce_comunque_nel_pannello():
    """Altrimenti spegnere il bot sarebbe un modo di perdere clienti senza
    accorgersene: il messaggio resterebbe solo sul telefono del salone."""
    backends = FakeBackends()
    interruttore.set_bot_attivo_cache(False)

    await handle_incoming_message(
        redis=FakeRedis(),
        phone=CLIENTE,
        text="siete aperti domani?",
        msg_type="text",
        channel=CollectorChannel(),
        backends=backends,
        claude=ScriptedClaude([]),
    )

    assert len(backends.conversazioni_operatore) == 1
    conversazione = backends.conversazioni_operatore[0]
    assert conversazione["motivo"] == "Bot disattivato dal pannello."
    assert [(m["autore"], m["testo"]) for m in conversazione["messaggi"]] == [
        ("cliente", "siete aperti domani?")
    ]


@pytest.mark.asyncio
async def test_due_messaggi_col_bot_spento_restano_una_conversazione_sola():
    backends = FakeBackends()
    interruttore.set_bot_attivo_cache(False)

    for testo in ("ci siete?", "pronto?"):
        await handle_incoming_message(
            redis=FakeRedis(),
            phone=CLIENTE,
            text=testo,
            msg_type="text",
            channel=CollectorChannel(),
            backends=backends,
            claude=ScriptedClaude([]),
        )

    assert len(backends.conversazioni_operatore) == 1
    assert len(backends.conversazioni_operatore[0]["messaggi"]) == 2


@pytest.mark.asyncio
async def test_col_bot_spento_claude_non_viene_mai_chiamato():
    """Il controllo sta prima di spendere un solo token."""
    backends = FakeBackends()
    claude = ScriptedClaude(["non dovrei essere chiamato"])
    interruttore.set_bot_attivo_cache(False)

    await handle_incoming_message(
        redis=FakeRedis(),
        phone=CLIENTE,
        text="vorrei un taglio",
        msg_type="text",
        channel=CollectorChannel(),
        backends=backends,
        claude=claude,
    )

    assert claude.chiamate == []


@pytest.mark.asyncio
async def test_col_bot_acceso_non_cambia_niente():
    backends = FakeBackends()
    channel = CollectorChannel()

    await handle_incoming_message(
        redis=FakeRedis(),
        phone=CLIENTE,
        text="buongiorno",
        msg_type="text",
        channel=channel,
        backends=backends,
        claude=ScriptedClaude(["Buongiorno! Come posso aiutarti?"]),
    )

    assert channel.messages
    assert backends.conversazioni_operatore == []


# ------------------------------------------------------------------- sito


@pytest.mark.asyncio
async def test_dal_sito_il_silenzio_non_va_bene(monkeypatch):
    """Qui non c'e' nessuno che legge il messaggio su un telefono, e una
    pagina che non risponde sembra rotta."""
    from config import settings

    monkeypatch.setattr(settings, "salone_telefono", "0362 123456")
    interruttore.set_bot_attivo_cache(False)

    risposta = await handle_incoming_message_web(
        redis=FakeRedis(),
        session_id="web:abc",
        text="vorrei un taglio",
        backends=FakeBackends(),
        claude=ScriptedClaude([]),
    )

    assert "0362 123456" in risposta["text"]


# ------------------------------------------- i puntini e "sta scrivendo"


@pytest.mark.asyncio
async def test_col_bot_spento_non_si_promettono_risposte_in_arrivo():
    """I puntini dicono "fra pochi secondi": col bot spento quella promessa
    non la mantiene nessuno, e il cliente aspetta guardando lo schermo."""
    backends = FakeBackends()
    interruttore.set_bot_attivo_cache(False)

    assert await risponde_una_persona(CLIENTE, backends=backends) is True


@pytest.mark.asyncio
async def test_col_bot_acceso_e_senza_passaggi_i_puntini_tornano_veri():
    backends = FakeBackends()

    assert await risponde_una_persona(CLIENTE, backends=backends) is False
