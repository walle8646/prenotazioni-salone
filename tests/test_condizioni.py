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


def test_si_avvisa_quando_ha_detto_cosa_e_quando():
    """Da li' in poi sta prenotando: il riepilogo arriva uno o due messaggi
    dopo."""
    sessione = {"dati_temp": {"servizio": "Taglio", "giorno": "2026-10-20"}}

    assert condizioni.serve_avviso(sessione) is True


@pytest.mark.parametrize("manca", ["servizio", "giorno"])
def test_non_si_avvisa_finche_manca_qualcosa(manca):
    """Prima non sta ancora prenotando, e un avviso a meta' conversazione e'
    solo rumore."""
    dati = {"servizio": "Taglio", "giorno": "2026-10-20"}
    del dati[manca]

    assert condizioni.serve_avviso({"dati_temp": dati}) is False


def test_l_operatore_non_conta():
    """Chi risponde "Indifferente" non sceglie nessun operatore, e quella voce
    il bot la offre apposta: legarci l'avviso lo spegnerebbe per tutti loro."""
    sessione = {"dati_temp": {"servizio": "Taglio", "giorno": "2026-10-20"}}

    assert "parrucchiere" not in condizioni._DATI_COMPLETI
    assert condizioni.serve_avviso(sessione) is True


def test_lo_slot_non_conta():
    """`slot` lo scrive CREA_APPUNTAMENTO, cioe' quando l'appuntamento esiste
    gia': una condizione che lo guardasse non scatterebbe mai."""
    assert "slot" not in condizioni._DATI_COMPLETI


def test_non_si_ripete():
    """Ripeterlo a ogni messaggio e' rumore, e il rumore si smette di leggerlo."""
    sessione = {
        "dati_temp": {"servizio": "Taglio", "giorno": "2026-10-20"},
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
    sessione["dati_temp"].update({"servizio": "Taglio", "giorno": "2026-10-20"})
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
    sessione["dati_temp"].update({"servizio": "Taglio", "giorno": "2026-10-20"})
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
    sessione["dati_temp"].update({"servizio": "Taglio", "giorno": "2026-10-20"})
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


# ---------------------------------------- accettata una volta, non si ripete


def test_chi_ha_accettato_questa_versione_non_la_rivede():
    """Un avviso che compare sempre non lo legge piu' nessuno, e a quel punto
    non protegge nessuno."""
    sessione = {
        "dati_temp": {"servizio": "Taglio", "giorno": "2026-10-20"},
        "condizioni_accettate": condizioni.VERSIONE,
    }

    assert condizioni.serve_avviso(sessione) is False


def test_chi_ha_accettato_una_versione_vecchia_la_rivede():
    """Senza versione, "accettato una volta" vorrebbe dire accettato per
    sempre un testo che nel frattempo dice altro."""
    sessione = {
        "dati_temp": {"servizio": "Taglio", "giorno": "2026-10-20"},
        "condizioni_accettate": "1 gennaio 2020",
    }

    assert condizioni.serve_avviso(sessione) is True


def test_la_versione_e_la_data_che_legge_il_cliente():
    """Scritte in due posti, una delle due resterebbe indietro: il testo
    cambierebbe senza che l'avviso ricompaia."""
    from routers import website

    assert website.CONDIZIONI_AGGIORNATE == condizioni.VERSIONE


@pytest.mark.asyncio
async def test_prenotando_si_registra_l_accettazione():
    from services.conversation import execute_action

    backends = FakeBackends()
    cliente = await backends.find_or_create_client(
        phone=CLIENTE, nome="Mario", cognome="Rossi"
    )
    session = {
        "dati_temp": {"nome": "Mario", "cognome": "Rossi"},
        "history": [],
        "condizioni_avvisate": True,
    }

    risultato = await execute_action(
        {
            "action": "CREA_APPUNTAMENTO",
            "slot": "2026-10-20T10:00",
            "servizi": ["Taglio"],
            "parrucchiere": "Andrea",
            "nome": "Mario",
            "cognome": "Rossi",
        },
        CLIENTE,
        session,
        backends,
    )

    assert "errore" not in risultato, risultato
    assert backends.condizioni_accettate[cliente["id"]] == condizioni.VERSIONE
    # E vale subito, senza aspettare la conversazione dopo.
    assert session["condizioni_accettate"] == condizioni.VERSIONE


@pytest.mark.asyncio
async def test_se_l_accettazione_non_si_registra_la_prenotazione_resta_buona():
    """Dire fallito quello che e' riuscito e' il modo peggiore di sbagliare:
    il cliente riprova."""
    from services.conversation import execute_action

    class BackendsRotti(FakeBackends):
        async def registra_accettazione_condizioni(self, cliente_id, versione):
            raise RuntimeError("database non raggiungibile")

    backends = BackendsRotti()
    await backends.find_or_create_client(phone=CLIENTE, nome="Mario", cognome="Rossi")

    risultato = await execute_action(
        {
            "action": "CREA_APPUNTAMENTO",
            "slot": "2026-10-20T10:00",
            "servizi": ["Taglio"],
            "parrucchiere": "Andrea",
            "nome": "Mario",
            "cognome": "Rossi",
        },
        CLIENTE,
        {"dati_temp": {"nome": "Mario", "cognome": "Rossi"}, "history": []},
        backends,
    )

    assert "errore" not in risultato, risultato


def test_l_email_di_conferma_porta_il_link(indirizzo):
    """Da quando l'avviso in chat non si ripete, questa e' la via che resta
    sempre aperta."""
    from services.email_service import _riga_condizioni

    assert indirizzo in _riga_condizioni()


def test_senza_indirizzo_pubblico_l_email_non_porta_un_link_rotto(monkeypatch):
    from config import settings
    from services.email_service import _riga_condizioni

    monkeypatch.setattr(settings, "public_base_url", "")

    assert _riga_condizioni() == ""


# ------------------------------- l'innesco provato su una conversazione vera


@pytest.mark.asyncio
async def test_l_avviso_esce_in_una_prenotazione_normale(indirizzo):
    """La prova che mancava, ed e' il motivo per cui il difetto e' arrivato in
    produzione: gli altri test costruivano `dati_temp` a mano, quindi
    provavano il meccanismo e non l'innesco. Qui la sessione la riempie il
    motore, come in una conversazione vera.
    """
    from .conftest import prossimo_giorno_aperto

    giorno = prossimo_giorno_aperto()
    backends = FakeBackends()
    channel = CollectorChannel()

    claude = ScriptedClaude(
        [
            ScriptedClaude.azione(
                action="CHECK_DISPONIBILITA",
                data=giorno,
                servizi=["Taglio"],
                durata_min=30,
            ),
            "Ci sono questi orari. Quale preferisci?",
        ]
    )

    await handle_incoming_message(
        redis=FakeRedis(),
        phone=CLIENTE,
        text=f"vorrei un taglio il {giorno}",
        msg_type="text",
        channel=channel,
        backends=backends,
        claude=claude,
    )

    assert any(indirizzo in t for t in channel.testi), channel.testi


@pytest.mark.asyncio
async def test_l_avviso_esce_anche_a_chi_dice_indifferente(indirizzo):
    """Chi non sceglie l'operatore e' il caso piu' frequente, non un caso
    limite: senza operatore in sessione l'avviso non usciva per nessuno di
    loro."""
    from .conftest import prossimo_giorno_aperto

    giorno = prossimo_giorno_aperto()
    backends = FakeBackends()
    channel = CollectorChannel()

    claude = ScriptedClaude(
        [
            # Senza `parrucchiere`: e' come cerca il bot quando il cliente
            # risponde "Indifferente".
            ScriptedClaude.azione(
                action="CHECK_DISPONIBILITA",
                data=giorno,
                servizi=["Taglio"],
                durata_min=30,
            ),
            "Perfetto, scelgo Francesco. Confermi?",
        ]
    )

    await handle_incoming_message(
        redis=FakeRedis(),
        phone=CLIENTE,
        text="indifferente",
        msg_type="text",
        channel=channel,
        backends=backends,
        claude=claude,
    )

    assert any(indirizzo in t for t in channel.testi), channel.testi


@pytest.mark.asyncio
async def test_senza_avviso_non_si_registra_nessuna_accettazione():
    """Registrare un'accettazione per qualcosa che non e' stato mostrato non e'
    solo falso: zittisce l'avviso per sempre su quel cliente, e il difetto si
    nasconde da se'."""
    from services.conversation import execute_action

    backends = FakeBackends()
    await backends.find_or_create_client(phone=CLIENTE, nome="Mario", cognome="Rossi")

    risultato = await execute_action(
        {
            "action": "CREA_APPUNTAMENTO",
            "slot": "2026-10-20T10:00",
            "servizi": ["Taglio"],
            "parrucchiere": "Andrea",
            "nome": "Mario",
            "cognome": "Rossi",
        },
        CLIENTE,
        {"dati_temp": {"nome": "Mario", "cognome": "Rossi"}, "history": []},
        backends,
    )

    assert "errore" not in risultato, risultato
    assert backends.condizioni_accettate == {}
