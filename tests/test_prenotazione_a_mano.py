"""Test sulla prenotazione presa dal pannello, al telefono o di persona.

Passa dalle stesse funzioni del bot apposta: due strade diverse per creare la
stessa cosa divergono al primo cambiamento, e una delle due smette di mandare
le email senza che nessuno se ne accorga. Questi test guardano che la strada
sia davvero quella, e che i due rifiuti che contano restino in piedi.
"""

from datetime import date, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import admin

GIORNO = "2026-10-06"
SLOT = f"{GIORNO}T10:00"


@pytest.fixture
def pannello(monkeypatch):
    """Il pannello con la sessione valida e i servizi esterni sostituiti."""
    fatto = {
        "eventi": [], "appuntamenti": [], "clienti": [], "email": [],
        "libero": True,
        # Chi è già in anagrafica, per id. None = sparito da sotto le mani.
        "anagrafica": {
            7: {
                "id": 7, "nome": "Roberto", "cognome": "Santoro",
                "email": "roberto@example.invalid", "telefono": "393491021925",
            },
            8: {
                "id": 8, "nome": "Chiara", "cognome": "Neri",
                "email": "chiara@example.invalid", "telefono": "web_4f1c9a",
            },
        },
    }

    async def finto_per_id(cliente_id):
        fatto["letti"] = fatto.get("letti", []) + [cliente_id]
        return fatto["anagrafica"].get(cliente_id)

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
    monkeypatch.setattr("services.db_service.cliente_per_id", finto_per_id)
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
        "cliente_id": "",
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


# ------------------------------------------- il cliente scelto dall'elenco
#
# Prenotando al telefono la persona quasi sempre c'è già. Ritrovarla per numero
# la perderebbe proprio nei casi che contano — chi è arrivato dal sito ha per
# telefono un identificativo di sessione, chi non l'ha lasciato non ne ha
# nessuno — e nascerebbe una seconda scheda per la stessa persona: storico
# spezzato, e il bot che non la riconosce più.


def test_chi_si_sceglie_dall_elenco_si_prende_per_id(pannello):
    risposta = _prenota(pannello, cliente_id="7", nome="", cognome="", telefono="")

    assert "creato=1" in risposta.headers["location"]
    assert pannello.fatto["letti"] == [7]
    assert pannello.fatto["clienti"] == [], "non deve nascere nessuna scheda nuova"
    assert pannello.fatto["appuntamenti"][0]["client_id"] == 7


def test_del_cliente_scelto_si_riprendono_i_dati(pannello):
    """Il modulo manda solo l'id: nome ed email per l'evento e per la conferma
    arrivano dall'anagrafica, non da quello che è rimasto scritto nei campi."""
    _prenota(pannello, cliente_id="7", nome="", cognome="", telefono="")

    assert "Roberto Santoro" in pannello.fatto["eventi"][0]["cliente"]
    assert pannello.fatto["email"][0]["to"] == "roberto@example.invalid"


def test_il_numero_di_sessione_del_sito_non_finisce_sull_evento(pannello):
    """`web_4f1c9a` non è un telefono: scritto sull'appuntamento, chi legge
    crede di avere un numero da chiamare."""
    _prenota(pannello, cliente_id="8", nome="", cognome="", telefono="")

    assert "web_" not in pannello.fatto["eventi"][0]["descrizione"]


def test_un_cliente_sparito_non_diventa_un_appuntamento_senza_nome(pannello):
    """Fra quando l'elenco l'ha mostrato e quando si conferma può essere stato
    cancellato: prenotare lo stesso lascerebbe in agenda una riga di nessuno."""
    risposta = _prenota(pannello, cliente_id="999", nome="", cognome="", telefono="")

    assert "errore=" in risposta.headers["location"]
    assert pannello.fatto["appuntamenti"] == []
    assert pannello.fatto["eventi"] == []


def test_senza_ne_id_ne_nome_non_si_prenota(pannello):
    risposta = _prenota(pannello, cliente_id="", nome="")

    assert "errore=" in risposta.headers["location"]
    assert pannello.fatto["eventi"] == []


# ------------------------------------------------- dove c'è posto, e perché no
#
# Il verde è il punto di questa schermata. Quando non c'è, la pagina deve dire
# quale dei tre motivi è: giornata finita, calendari illeggibili, tutto pieno.
# Si somigliano solo a guardarli, e chi guarda conclude sempre "siamo pieni" —
# che nel caso del guasto vuol dire mandare via un cliente che aveva posto.

APERTO = ("09:00", "19:00")


@pytest.fixture
def salone(monkeypatch):
    """Salone aperto tutti i giorni, tutti in servizio, Google che risponde."""
    risposta = {"slot": [], "esplode": False}

    async def finta_disponibilita(self, date_str, cal_id, durata):
        if risposta["esplode"]:
            raise RuntimeError("Google irraggiungibile")
        return risposta["slot"]

    from services.backends import RealBackends

    monkeypatch.setattr("services.slots.orari_salone", lambda: {g: [APERTO] for g in range(7)})
    monkeypatch.setattr("services.presenze.e_in_salone", lambda nome, quando: True)
    monkeypatch.setattr(RealBackends, "check_availability", finta_disponibilita)
    return risposta


def _domani():
    """Mai una data fissa: una del passato non ha più slot liberi."""
    return date.today() + timedelta(days=1)


def _adesso_alle(giorno, ora="10:00"):
    ore, minuti = map(int, ora.split(":"))
    return datetime.combine(giorno, datetime.min.time()).replace(hour=ore, minute=minuti)


@pytest.mark.asyncio
async def test_i_liberi_arrivano_raggruppati_per_operatore(salone):
    giorno = _domani()
    salone["slot"] = [
        {"slot": f"{giorno}T10:00", "parrucchiere": "Andrea"},
        {"slot": f"{giorno}T10:30", "parrucchiere": "Andrea"},
        {"slot": f"{giorno}T10:00", "parrucchiere": "Giava"},
    ]

    liberi, nota = await admin._dove_c_e_posto(giorno, _adesso_alle(_domani() - timedelta(days=1)))

    assert liberi == {
        "Andrea": {f"{giorno}T10:00", f"{giorno}T10:30"},
        "Giava": {f"{giorno}T10:00"},
    }
    assert nota is None, "con del verde da mostrare non serve spiegare niente"


@pytest.mark.asyncio
async def test_chi_oggi_non_lavora_non_ha_posti_liberi(salone, monkeypatch):
    """Google dice se l'operatore è occupato, non se quel giorno è in salone:
    senza questo filtro il verde compare sopra le righe di chi non c'è."""
    giorno = _domani()
    salone["slot"] = [
        {"slot": f"{giorno}T10:00", "parrucchiere": "Andrea"},
        {"slot": f"{giorno}T10:00", "parrucchiere": "Bario"},
    ]
    monkeypatch.setattr(
        "services.presenze.e_in_salone", lambda nome, quando: nome != "Bario"
    )

    liberi, _ = await admin._dove_c_e_posto(giorno, _adesso_alle(_domani() - timedelta(days=1)))

    assert list(liberi) == ["Andrea"]


@pytest.mark.asyncio
async def test_se_google_non_risponde_lo_dice(salone):
    """Il caso grave: caselle non segnate lette come poltrone occupate."""
    salone["esplode"] = True
    giorno = _domani()

    liberi, nota = await admin._dove_c_e_posto(giorno, _adesso_alle(giorno - timedelta(days=1)))

    assert liberi == {}
    assert "Google" in nota


@pytest.mark.asyncio
async def test_una_giornata_finita_non_si_chiede_nemmeno(salone):
    giorno = date.today()
    salone["slot"] = [{"slot": f"{giorno}T10:00", "parrucchiere": "Andrea"}]

    liberi, nota = await admin._dove_c_e_posto(giorno, _adesso_alle(giorno, "19:30"))

    assert liberi == {}
    assert "passata" in nota


@pytest.mark.asyncio
async def test_a_salone_chiuso_non_si_spiega_niente(salone, monkeypatch):
    """Che sia chiuso lo dice già la griglia: ripeterlo è rumore."""
    monkeypatch.setattr("services.slots.orari_salone", lambda: {})

    assert await admin._dove_c_e_posto(_domani(), _adesso_alle(date.today())) == ({}, None)


@pytest.mark.asyncio
async def test_una_giornata_piena_lo_dice_con_parole_sue(salone):
    giorno = _domani()

    liberi, nota = await admin._dove_c_e_posto(giorno, _adesso_alle(giorno - timedelta(days=1)))

    assert liberi == {}
    assert "Nessuna mezz'ora libera" in nota
