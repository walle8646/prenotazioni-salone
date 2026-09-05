"""Test sul pannello di gestione: listino, operatori e primo popolamento.

Qui non si tocca il database: si verificano le decisioni, che sono la parte
in cui si sbaglia. Il giro completo sulle schermate si prova a mano.
"""

import pytest

from routers.admin import _alias_da_testo, _codice_da_nome, _decimale
from services.db_service import sovrascrive_il_calendario
from services.operatori import PREFISSO_NON_CONFIGURATO


# ------------------------------------------------------------------- prezzi


@pytest.mark.parametrize(
    "scritto,atteso",
    [
        ("13,50", 13.50),  # come lo scrive chiunque in Italia
        ("13.50", 13.50),
        (" 20 ", 20.0),
        ("8,00 €", 8.0),
        ("0", 0.0),
    ],
)
def test_prezzi_scritti_come_capita(scritto, atteso):
    assert _decimale(scritto) == atteso


@pytest.mark.parametrize("scritto", ["", "gratis", "13,5,0", None])
def test_un_prezzo_illeggibile_si_fa_riconoscere(scritto):
    """Meglio un errore in faccia che un servizio a zero euro."""
    with pytest.raises(ValueError):
        _decimale(scritto)


# ------------------------------------------------------------------- codici


def test_il_codice_nasce_dal_nome():
    assert _codice_da_nome("Taglio + Barba", set()) == "taglio_barba"


def test_due_servizi_con_lo_stesso_nome_non_si_sovrappongono():
    """`codice` è unico in tabella: senza distinguerli, il secondo non entra."""
    presi = {"taglio", "taglio_2"}

    assert _codice_da_nome("Taglio", presi) == "taglio_3"


def test_un_nome_di_soli_simboli_ha_comunque_un_codice():
    assert _codice_da_nome("+++", set()) == "servizio"


# -------------------------------------------------------------------- alias


def test_gli_alias_si_scrivono_come_viene():
    assert _alias_da_testo("taglio e barba, taglio+barba") == [
        "taglio e barba",
        "taglio+barba",
    ]
    assert _alias_da_testo("uno\ndue , tre") == ["uno", "due", "tre"]
    assert _alias_da_testo("") == []
    assert _alias_da_testo(None) == []


# --------------------------------------------- primo popolamento degli operatori
#
# `seed_parrucchieri` gira a ogni avvio. Prima riattivava chi era nell'elenco
# del codice e disattivava chi non c'era: col pannello vorrebbe dire vedersi
# sparire al deploy l'operatore appena assunto.


def test_un_calendario_vero_non_viene_sovrascritto_dalla_configurazione():
    """È il pannello a cambiarlo: un riavvio non deve disfare quel lavoro."""
    assert (
        sovrascrive_il_calendario(
            "scelto-dal-pannello@group.calendar.google.com",
            "vecchio@group.calendar.google.com",
        )
        is False
    )


def test_un_segnaposto_viene_configurato_dalla_variabile_d_ambiente():
    """Il caso utile: operatore creato senza calendario, poi configurato."""
    assert (
        sovrascrive_il_calendario(
            f"{PREFISSO_NON_CONFIGURATO}andrea",
            "vero@group.calendar.google.com",
        )
        is True
    )


def test_un_segnaposto_non_si_sostituisce_con_un_altro_segnaposto():
    assert (
        sovrascrive_il_calendario(
            f"{PREFISSO_NON_CONFIGURATO}andrea",
            f"{PREFISSO_NON_CONFIGURATO}andrea",
        )
        is False
    )


# ------------------------------------------------- assenza di un operatore
#
# Regola del modulo: ogni appuntamento va per conto suo. Un'email che non
# parte non deve impedire l'annullamento degli altri, e chi resta senza
# avviso deve finire nell'elenco di chi va chiamato.


def _appuntamento(app_id: int, **campi) -> dict:
    base = {
        "app_id": app_id,
        "gcal_event_id": f"evt_{app_id}",
        "cal_id": "cal_francesco",
        "data_ora": "2026-08-20T09:00",
        "servizi": ["Taglio"],
        "cliente_nome": f"Cliente {app_id}",
        "cliente_email": f"cliente{app_id}@example.it",
        "cliente_telefono": "393331234567",
        "parrucchiere": "Francesco",
    }
    base.update(campi)
    return base


@pytest.mark.asyncio
async def test_la_giornata_viene_annullata_e_i_clienti_avvisati(backends):
    from services.assenze import annulla_giornata

    backends.eventi = {"evt_1": {}, "evt_2": {}}

    resoconto = await annulla_giornata(
        [_appuntamento(1), _appuntamento(2)], backends
    )

    assert resoconto["annullati"] == 2
    assert resoconto["avvisati"] == ["Cliente 1", "Cliente 2"]
    assert resoconto["da_chiamare"] == []
    assert [e["to"] for e in backends.email_assenze] == [
        "cliente1@example.it",
        "cliente2@example.it",
    ]


@pytest.mark.asyncio
async def test_chi_non_ha_email_finisce_fra_quelli_da_chiamare(backends):
    """Da WhatsApp l'email spesso non c'è: quel cliente non va perso."""
    from services.assenze import annulla_giornata

    resoconto = await annulla_giornata(
        [_appuntamento(1, cliente_email=None, cliente_telefono="393339999999")],
        backends,
    )

    assert resoconto["annullati"] == 1
    assert resoconto["da_chiamare"] == [
        {"nome": "Cliente 1", "telefono": "393339999999"}
    ]
    assert backends.email_assenze == []


@pytest.mark.asyncio
async def test_un_email_che_non_parte_non_ferma_gli_altri(backends, monkeypatch):
    from services.assenze import annulla_giornata

    async def rifiuta_il_primo(to, **_):
        if to == "cliente1@example.it":
            raise OSError("server di posta irraggiungibile")

    monkeypatch.setattr(backends, "send_absence_email", rifiuta_il_primo)

    resoconto = await annulla_giornata(
        [_appuntamento(1), _appuntamento(2)], backends
    )

    assert resoconto["annullati"] == 2, "gli appuntamenti si annullano comunque"
    assert resoconto["avvisati"] == ["Cliente 2"]
    assert resoconto["da_chiamare"][0]["nome"] == "Cliente 1"


@pytest.mark.asyncio
async def test_un_evento_che_google_non_trova_non_ferma_l_annullamento(
    backends, monkeypatch
):
    """Lasciare l'appuntamento buono sarebbe peggio di un evento orfano."""
    from services.assenze import annulla_giornata

    async def esplode(event_id, calendar_id):
        raise RuntimeError("Google non risponde")

    monkeypatch.setattr(backends, "delete_event", esplode)

    resoconto = await annulla_giornata([_appuntamento(1)], backends)

    assert resoconto["annullati"] == 1
    assert resoconto["avvisati"] == ["Cliente 1"]
    assert "calendario di Google" in resoconto["problemi"][0]


@pytest.mark.asyncio
async def test_se_l_annullamento_fallisce_il_cliente_non_viene_avvisato(
    backends, monkeypatch
):
    """Avvisare di un annullamento che non c'è stato è il danno peggiore."""
    from services.assenze import annulla_giornata

    async def esplode(app_id, status):
        raise RuntimeError("database irraggiungibile")

    monkeypatch.setattr(backends, "update_appointment_status", esplode)

    resoconto = await annulla_giornata([_appuntamento(1)], backends)

    assert resoconto["annullati"] == 0
    assert backends.email_assenze == []
    assert "NON annullato" in resoconto["problemi"][0]


# ------------------------------------------- aggiornamento della conversazione


@pytest.fixture
def pannello_aperto(monkeypatch):
    """Il pannello con la sessione già valida e il database sostituito."""
    from datetime import datetime, timedelta

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers import admin
    import services.db_service as db

    adesso = datetime.now()
    conversazione = {
        "id": 1,
        "nome": "Mario Rossi",
        "telefono": "393331234567",
        "cliente_id": None,
        "canale": "whatsapp",
        "stato": "attesa",
        "motivo": "vuole parlare con qualcuno",
        "aperta_il": adesso - timedelta(minutes=30),
        "ultimo_messaggio_cliente": adesso - timedelta(minutes=2),
        "presa_il": None,
        "chiusa_il": None,
        "messaggi": [
            {"id": 1, "autore": "cliente", "testo": "ciao", "creato_il": adesso},
            {"id": 2, "autore": "bot", "testo": "Dimmi pure", "creato_il": adesso},
            {"id": 3, "autore": "cliente", "testo": "è urgente", "creato_il": adesso},
        ],
    }

    async def finta_lettura(conversazione_id):
        return conversazione if conversazione_id == 1 else None

    monkeypatch.setattr(db, "conversazione_con_messaggi", finta_lettura)

    app = FastAPI()
    app.include_router(admin.router)
    app.dependency_overrides[admin.utente_del_pannello] = lambda: "nadia"
    client = TestClient(app)
    client.conversazione = conversazione
    return client


def test_si_chiedono_solo_i_messaggi_nuovi(pannello_aperto):
    """La pagina resta aperta anche un'ora: riscaricare tutto a ogni controllo
    sarebbe uno spreco che cresce da solo."""
    dati = pannello_aperto.get("/admin/conversazioni/1/messaggi?dopo=2").json()

    assert [m["id"] for m in dati["messaggi"]] == [3]
    assert dati["messaggi"][0]["testo"] == "è urgente"


def test_senza_novita_non_torna_niente(pannello_aperto):
    dati = pannello_aperto.get("/admin/conversazioni/1/messaggi?dopo=3").json()

    assert dati["messaggi"] == []


def test_dall_inizio_tornano_tutti(pannello_aperto):
    dati = pannello_aperto.get("/admin/conversazioni/1/messaggi?dopo=0").json()

    assert [m["id"] for m in dati["messaggi"]] == [1, 2, 3]


def test_l_aggiornamento_dice_anche_se_la_finestra_e_ancora_aperta(pannello_aperto):
    """Se scade mentre la receptionist ha la pagina davanti, deve accorgersene
    prima di scrivere una risposta che verrebbe rifiutata."""
    from datetime import datetime, timedelta

    dati = pannello_aperto.get("/admin/conversazioni/1/messaggi").json()
    assert dati["finestra_aperta"] is True

    pannello_aperto.conversazione["ultimo_messaggio_cliente"] = (
        datetime.now() - timedelta(hours=25)
    )
    dati = pannello_aperto.get("/admin/conversazioni/1/messaggi").json()
    assert dati["finestra_aperta"] is False


def test_una_conversazione_inesistente_non_esplode(pannello_aperto):
    assert pannello_aperto.get("/admin/conversazioni/99/messaggi").status_code == 404
