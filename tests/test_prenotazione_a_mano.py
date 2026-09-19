"""Test sulla prenotazione presa dal pannello, al telefono o di persona.

Passa dalle stesse funzioni del bot apposta: due strade diverse per creare la
stessa cosa divergono al primo cambiamento, e una delle due smette di mandare
le email senza che nessuno se ne accorga. Questi test guardano che la strada
sia davvero quella, e che i due rifiuti che contano restino in piedi.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import admin

GIORNO = "2026-10-06"
SLOT = f"{GIORNO}T10:00"


@pytest.fixture
def pannello(monkeypatch):
    """Il pannello con la sessione valida e i servizi esterni sostituiti."""
    fatto = {"eventi": [], "appuntamenti": [], "clienti": [], "email": [], "libero": True}

    async def finto_slot_libero(slot, cal_id, durata, backends):
        return fatto["libero"]

    async def finto_cliente(phone=None, nome=None, cognome=None, email=None, canale="whatsapp"):
        fatto["clienti"].append(
            {"telefono": phone, "nome": nome, "cognome": cognome, "email": email, "canale": canale}
        )
        return {"id": 1, "nome": nome, "cognome": cognome}

    async def finto_appuntamento(**argomenti):
        fatto["appuntamenti"].append(argomenti)
        return {"id": 99}

    async def finto_evento(self, slot, parrucchiere_cal_id, servizi, durata, cliente_nome, descrizione=""):
        fatto["eventi"].append(
            {"slot": slot, "cal_id": parrucchiere_cal_id, "servizi": servizi,
             "durata": durata, "cliente": cliente_nome, "descrizione": descrizione}
        )
        return "evento_finto"

    async def finta_email(self, to, nome, data_ora, parrucchiere, servizi):
        fatto["email"].append({"to": to, "nome": nome})

    from services.backends import RealBackends

    monkeypatch.setattr("services.conversation._slot_ancora_libero", finto_slot_libero)
    monkeypatch.setattr("services.db_service.find_or_create_client", finto_cliente)
    monkeypatch.setattr("services.db_service.create_appointment", finto_appuntamento)
    monkeypatch.setattr(RealBackends, "create_event", finto_evento)
    monkeypatch.setattr(RealBackends, "send_confirmation_email", finta_email)

    app = FastAPI()
    app.include_router(admin.router)
    app.dependency_overrides[admin.utente_del_pannello] = lambda: "nadia"
    client = TestClient(app, follow_redirects=False)
    client.fatto = fatto
    return client


def _prenota(pannello, **cambiamenti):
    modulo = {
        "slot": SLOT,
        "operatore": "Francesco",
        "servizio": "Taglio",
        "nome": "Mario",
        "cognome": "Rossi",
        "telefono": "+39 349 102 1925",
        "email": "",
        "note": "",
    }
    modulo.update(cambiamenti)
    return pannello.post("/admin/appuntamenti", data=modulo)


def test_una_prenotazione_finisce_su_google_e_in_agenda(pannello):
    risposta = _prenota(pannello)

    assert risposta.status_code == 303
    assert "creato=1" in risposta.headers["location"]
    assert len(pannello.fatto["eventi"]) == 1, "deve nascere l'evento sul calendario"
    assert len(pannello.fatto["appuntamenti"]) == 1, "e la riga in agenda"
    assert pannello.fatto["appuntamenti"][0]["gcal_event_id"] == "evento_finto"


def test_la_durata_la_decide_il_listino_non_chi_scrive(pannello):
    """Un colore da due ore prenotato come mezz'ora finisce sopra
    l'appuntamento successivo: la durata non si chiede nel modulo."""
    _prenota(pannello, servizio="Colore + Taglio + Trattamento capello")

    assert pannello.fatto["eventi"][0]["durata"] == 120
    assert pannello.fatto["appuntamenti"][0]["durata_min"] == 120


def test_il_telefono_arriva_in_sole_cifre(pannello):
    """Scritto con spazi e prefisso non combacia con quello che manda WhatsApp,
    e lo stesso cliente finirebbe in due schede."""
    _prenota(pannello)
    assert pannello.fatto["clienti"][0]["telefono"] == "393491021925"


def test_su_un_orario_occupato_non_si_scrive_niente(pannello):
    """Fra quando la schermata disegna il verde e quando si conferma passano
    minuti, e in quei minuti può prenotare il bot."""
    pannello.fatto["libero"] = False

    risposta = _prenota(pannello)

    assert "errore=" in risposta.headers["location"]
    assert pannello.fatto["eventi"] == []
    assert pannello.fatto["appuntamenti"] == []


def test_senza_i_dati_minimi_non_si_prenota(pannello):
    risposta = _prenota(pannello, nome="")

    assert "errore=" in risposta.headers["location"]
    assert pannello.fatto["eventi"] == []


def test_l_email_di_conferma_parte_solo_se_c_e_un_indirizzo(pannello):
    _prenota(pannello)
    assert pannello.fatto["email"] == []

    _prenota(pannello, email="mario@example.invalid")
    assert pannello.fatto["email"][0]["to"] == "mario@example.invalid"


def test_senza_telefono_si_prenota_lo_stesso(pannello):
    """Chi passa dal salone e non lascia il numero deve poter prenotare:
    l'anagrafica lo distingue da sola, senza inventargli un numero vero."""
    risposta = _prenota(pannello, telefono="")

    assert "creato=1" in risposta.headers["location"]
    assert len(pannello.fatto["appuntamenti"]) == 1


def test_il_pannello_puo_dare_un_secondo_appuntamento_allo_stesso_cliente(pannello):
    """Il bot lo rifiuta perché sbagliava da solo. Chi prenota a mano ha la
    persona al telefono e sa quello che sta facendo."""
    _prenota(pannello)
    risposta = _prenota(pannello, slot=f"{GIORNO}T15:00")

    assert "creato=1" in risposta.headers["location"]
    assert len(pannello.fatto["appuntamenti"]) == 2
