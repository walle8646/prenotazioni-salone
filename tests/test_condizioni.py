"""L'avviso sulle condizioni prima che il cliente confermi.

Lo mette il codice e non il modello: il prompt viene rispettato quasi sempre,
e "quasi" non basta per una cosa che deve esserci tutte le volte. Quello che
va provato e' che compaia **prima** del riepilogo, **una volta sola**, e che
non si porti dietro la prenotazione quando qualcosa va storto.
"""

import pytest

from services import condizioni
from services.channels import CollectorChannel
from services.conversation import handle_incoming_message
from services.fakes import FakeBackends, FakeRedis, ScriptedClaude

CLIENTE = "393331234567"


@pytest.fixture
def indirizzo(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "public_base_url", "https://simoneacconciature.it")
    return "https://simoneacconciature.it/condizioni"


# ------------------------------------------------------- quando avvisare


def test_si_avvisa_quando_ha_scelto_tutto():
    """Scelti servizio, orario e operatore, il passo dopo e' confermare."""
    sessione = {
        "dati_temp": {"servizio": "Taglio", "slot": "2026-10-20T10:00", "parrucchiere": "Andrea"}
    }

    assert condizioni.serve_avviso(sessione) is True


@pytest.mark.parametrize("manca", ["servizio", "slot", "parrucchiere"])
def test_non_si_avvisa_finche_manca_qualcosa(manca):
    """Prima della scelta completa non c'e' niente da confermare, e un avviso
    a meta' conversazione e' solo rumore."""
    dati = {"servizio": "Taglio", "slot": "2026-10-20T10:00", "parrucchiere": "Andrea"}
    del dati[manca]

    assert condizioni.serve_avviso({"dati_temp": dati}) is False


def test_non_si_ripete():
    """Ripeterlo a ogni messaggio e' rumore, e il rumore si smette di leggerlo."""
    sessione = {
        "dati_temp": {"servizio": "Taglio", "slot": "x", "parrucchiere": "Andrea"},
        "condizioni_avvisate": True,
    }

    assert condizioni.serve_avviso(sessione) is False


def test_una_sessione_vuota_non_fa_esplodere_niente():
    assert condizioni.serve_avviso({}) is False
    assert condizioni.serve_avviso(None) is False


# ------------------------------------------------------------- il link


def test_il_link_porta_sul_sito_del_salone(indirizzo):
    assert condizioni.indirizzo() == indirizzo
    assert indirizzo in condizioni.frase()


def test_senza_indirizzo_pubblico_non_si_manda_un_avviso_senza_link(monkeypatch):
    """Un avviso senza link non informa nessuno: mandarlo servirebbe solo a
    sembrare in regola."""
    from config import settings

    monkeypatch.setattr(settings, "public_base_url", "")

    assert condizioni.indirizzo() is None
    assert condizioni.frase() is None


def test_la_barra_finale_non_raddoppia(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "public_base_url", "https://simoneacconciature.it/")

    assert condizioni.indirizzo() == "https://simoneacconciature.it/condizioni"


# ------------------------------------------------ dentro la conversazione


@pytest.mark.asyncio
async def test_l_avviso_arriva_prima_del_riepilogo(indirizzo):
    """Sotto ai bottoni si tocca prima di leggerlo: dire dopo quello che
    andava detto prima vale come non averlo detto."""
    backends = FakeBackends()
    channel = CollectorChannel()
    redis = FakeRedis()

    # La sessione e' gia' al punto in cui il cliente ha scelto tutto.
    from services.session_manager import get_session, save_session

    sessione = await get_session(redis, CLIENTE)
    sessione["dati_temp"].update(
        {"servizio": "Taglio", "slot": "2026-10-20T10:00", "parrucchiere": "Andrea"}
    )
    await save_session(redis, CLIENTE, sessione)

    await handle_incoming_message(
        redis=redis,
        phone=CLIENTE,
        text="si",
        msg_type="text",
        channel=channel,
        backends=backends,
        claude=ScriptedClaude(["Taglio giovedi' alle 10 con Andrea. Confermi?"]),
    )

    assert len(channel.testi) == 2
    assert indirizzo in channel.testi[0]
    assert "Confermi?" in channel.testi[1]


@pytest.mark.asyncio
async def test_l_avviso_non_torna_al_messaggio_dopo(indirizzo):
    backends = FakeBackends()
    channel = CollectorChannel()
    redis = FakeRedis()

    from services.session_manager import get_session, save_session

    sessione = await get_session(redis, CLIENTE)
    sessione["dati_temp"].update(
        {"servizio": "Taglio", "slot": "2026-10-20T10:00", "parrucchiere": "Andrea"}
    )
    await save_session(redis, CLIENTE, sessione)

    for risposta in ("Confermi?", "Allora confermi?"):
        await handle_incoming_message(
            redis=redis,
            phone=CLIENTE,
            text="boh",
            msg_type="text",
            channel=channel,
            backends=backends,
            claude=ScriptedClaude([risposta]),
        )

    quanti = [t for t in channel.testi if indirizzo in t]
    assert len(quanti) == 1


@pytest.mark.asyncio
async def test_a_inizio_conversazione_non_si_avvisa(indirizzo):
    backends = FakeBackends()
    channel = CollectorChannel()

    await handle_incoming_message(
        redis=FakeRedis(),
        phone=CLIENTE,
        text="buongiorno",
        msg_type="text",
        channel=channel,
        backends=backends,
        claude=ScriptedClaude(["Buongiorno! Che servizio ti serve?"]),
    )

    assert all(indirizzo not in t for t in channel.testi)


@pytest.mark.asyncio
async def test_un_avviso_non_partito_non_ferma_la_prenotazione(indirizzo):
    """Una prenotazione fallita per un avviso non spedito sarebbe un danno piu'
    grosso di quello che l'avviso previene."""

    class CanaleRotto(CollectorChannel):
        def __init__(self):
            super().__init__()
            self.primo = True

        async def send_text(self, to, text):
            if self.primo:
                self.primo = False
                raise RuntimeError("Meta non risponde")
            await super().send_text(to, text)

    channel = CanaleRotto()
    redis = FakeRedis()

    from services.session_manager import get_session, save_session

    sessione = await get_session(redis, CLIENTE)
    sessione["dati_temp"].update(
        {"servizio": "Taglio", "slot": "2026-10-20T10:00", "parrucchiere": "Andrea"}
    )
    await save_session(redis, CLIENTE, sessione)

    await handle_incoming_message(
        redis=redis,
        phone=CLIENTE,
        text="si",
        msg_type="text",
        channel=channel,
        backends=FakeBackends(),
        claude=ScriptedClaude(["Confermi?"]),
    )

    assert channel.testi == ["Confermi?"]


# ------------------------------------------------------------ la pagina


def test_la_pagina_dichiara_i_numeri_che_il_bot_applica(monkeypatch):
    """Scritti a mano direbbero una cosa mentre il bot ne fa un'altra, ed e' il
    genere di difetto che si scopre da un cliente che protesta citando una
    pagina che gli abbiamo dato noi."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from config import settings
    from routers import website

    monkeypatch.setattr(settings, "cancel_policy_hours", 3)
    monkeypatch.setattr(settings, "min_booking_hours_ahead", 4)
    monkeypatch.setattr(settings, "max_booking_days_ahead", 45)

    app = FastAPI()
    app.include_router(website.router)
    pagina = TestClient(app).get("/condizioni").text

    assert "45 giorni" in pagina
    assert "4 ore" in pagina
    assert "3 ore" in pagina


def test_la_pagina_rimanda_all_informativa():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers import website

    app = FastAPI()
    app.include_router(website.router)
    pagina = TestClient(app).get("/condizioni").text

    assert 'href="/privacy"' in pagina
    assert 'href="/cancellazione-dati"' in pagina
