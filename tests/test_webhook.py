"""Test sul webhook di Meta: risposta immediata e nessun doppione.

Meta aspetta pochi secondi prima di considerare un messaggio non consegnato e
rimandarlo. Interrogare Claude e Google prima di rispondere significava
farselo rimandare, e far arrivare al cliente due volte la stessa risposta.
"""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import webhook
from services.fakes import FakeRedis


def _payload(message_id: str = "wamid.1", testo: str = "vorrei un taglio") -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [{"profile": {"name": "Mario"}}],
                            "messages": [
                                {
                                    "id": message_id,
                                    "from": "393331234567",
                                    "type": "text",
                                    "text": {"body": testo},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }


@pytest.fixture
def client(monkeypatch):
    """App minima col solo webhook, e la conversazione sostituita da una spia."""
    elaborati = []
    segnalati = []
    solo_lette = []
    stato = {"risponde_una_persona": False}

    async def finto_handle(redis, **argomenti):
        # Simula il tempo vero di un giro con Claude e Google
        await asyncio.sleep(0.05)
        elaborati.append(argomenti)

    async def finto_segnale(message_id):
        segnalati.append(message_id)
        return True

    async def finta_lettura(message_id):
        solo_lette.append(message_id)
        return True

    async def finto_chi_risponde(phone, backends=None):
        return stato["risponde_una_persona"]

    monkeypatch.setattr(webhook, "handle_incoming_message", finto_handle)
    # Senza questi i test chiamerebbero davvero Meta e il database: qui non si
    # tocca né la rete né Postgres.
    monkeypatch.setattr(webhook, "segna_letto_e_sta_scrivendo", finto_segnale)
    monkeypatch.setattr(webhook, "segna_letto", finta_lettura)
    monkeypatch.setattr(webhook, "risponde_una_persona", finto_chi_risponde)

    app = FastAPI()
    app.include_router(webhook.router)
    app.state.redis = FakeRedis()

    with TestClient(app) as c:
        c.elaborati = elaborati
        c.segnalati = segnalati
        c.solo_lette = solo_lette
        c.stato = stato
        yield c


# ------------------------------------------------- verifica dell'iscrizione


def test_la_verifica_restituisce_il_challenge_cosi_come_arriva(client, monkeypatch):
    """Meta confronta la risposta con quello che ha mandato, carattere per carattere."""
    from config import settings

    monkeypatch.setattr(settings, "meta_verify_token", "parola-concordata")

    risposta = client.get(
        "/webhook/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "parola-concordata",
            "hub.challenge": "1234567890",
        },
    )

    assert risposta.status_code == 200
    assert risposta.text == "1234567890"


def test_un_challenge_non_numerico_non_fa_fallire_la_verifica(client, monkeypatch):
    """Convertirlo a intero funzionava solo finché Meta ne mandava di numerici."""
    from config import settings

    monkeypatch.setattr(settings, "meta_verify_token", "parola-concordata")

    risposta = client.get(
        "/webhook/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "parola-concordata",
            "hub.challenge": "abc123",
        },
    )

    assert risposta.status_code == 200
    assert risposta.text == "abc123"


def test_un_token_sbagliato_viene_rifiutato(client, monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "meta_verify_token", "parola-concordata")

    risposta = client.get(
        "/webhook/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "tentativo",
            "hub.challenge": "1234567890",
        },
    )

    assert risposta.status_code == 403


def test_senza_token_configurato_non_si_verifica_nulla(client, monkeypatch):
    """Altrimenti chiunque potrebbe iscrivere il proprio webhook al nostro server."""
    from config import settings

    monkeypatch.setattr(settings, "meta_verify_token", "")

    risposta = client.get(
        "/webhook/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "",
            "hub.challenge": "1234567890",
        },
    )

    assert risposta.status_code == 403


# ------------------------------------------------------- messaggi in entrata


def test_meta_riceve_conferma_e_il_lavoro_viene_dopo(client):
    risposta = client.post("/webhook/whatsapp", json=_payload())

    assert risposta.status_code == 200
    assert risposta.json() == {"status": "ok"}
    # TestClient attende anche i task in background: se sono stati eseguiti,
    # significa che erano registrati come tali e non dentro la richiesta.
    assert len(client.elaborati) == 1
    assert client.elaborati[0]["text"] == "vorrei un taglio"
    assert client.elaborati[0]["phone"] == "393331234567"


def test_il_cliente_vede_subito_che_il_messaggio_e_arrivato(client):
    """Fra Claude e i calendari passano dei secondi, e su Render appena
    risvegliato una trentina: senza segnale il cliente riscrive o se ne va."""
    client.post("/webhook/whatsapp", json=_payload(message_id="wamid.7"))

    assert client.segnalati == ["wamid.7"]


def test_un_segnale_non_partito_non_impedisce_la_risposta(client, monkeypatch):
    """È solo un'indicazione di cortesia: se fallisce, si prenota lo stesso."""

    async def esplode(message_id):
        raise RuntimeError("Meta non risponde")

    monkeypatch.setattr(webhook, "segna_letto_e_sta_scrivendo", esplode)

    client.post("/webhook/whatsapp", json=_payload(message_id="wamid.8"))

    assert len(client.elaborati) == 1


def test_lo_stesso_messaggio_non_viene_elaborato_due_volte(client):
    """Meta rimanda quello che considera non consegnato."""
    primo = client.post("/webhook/whatsapp", json=_payload(message_id="wamid.42"))
    secondo = client.post("/webhook/whatsapp", json=_payload(message_id="wamid.42"))

    assert primo.json() == {"status": "ok"}
    assert secondo.json() == {"status": "duplicato"}
    assert len(client.elaborati) == 1, "il cliente riceverebbe due risposte uguali"


def test_messaggi_diversi_vengono_elaborati_entrambi(client):
    client.post("/webhook/whatsapp", json=_payload(message_id="wamid.1", testo="ciao"))
    client.post("/webhook/whatsapp", json=_payload(message_id="wamid.2", testo="taglio"))

    assert [e["text"] for e in client.elaborati] == ["ciao", "taglio"]


def _scelta_da_lista(list_reply: dict) -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": "wamid.scelta",
                                    "from": "393331234567",
                                    "type": "interactive",
                                    "interactive": {
                                        "type": "list_reply",
                                        "list_reply": list_reply,
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }


def test_di_una_riga_accorciata_si_legge_la_descrizione(client):
    """Il titolo si ferma a 24 caratteri: il listino non riconoscerebbe il troncone."""
    intero = "Taglio + Shampoo + Trattamento barba con oli e panno bagnato — 45,00 €"

    client.post(
        "/webhook/whatsapp",
        json=_scelta_da_lista(
            {
                "id": "opt_3",
                "title": "Taglio + Shampoo + Tra…",
                "description": intero,
            }
        ),
    )

    assert client.elaborati[0]["text"] == intero


def test_senza_descrizione_si_legge_il_titolo(client):
    """Le voci corte non ne hanno una, e vanno bene così."""
    client.post(
        "/webhook/whatsapp",
        json=_scelta_da_lista({"id": "opt_0", "title": "Indifferente"}),
    )

    assert client.elaborati[0]["text"] == "Indifferente"


def test_le_notifiche_di_stato_vengono_ignorate(client):
    """Consegnato, letto e simili non sono messaggi del cliente."""
    risposta = client.post(
        "/webhook/whatsapp",
        json={"entry": [{"changes": [{"value": {"statuses": [{"status": "read"}]}}]}]},
    )

    assert risposta.json() == {"status": "ignored"}
    assert client.elaborati == []


def test_un_errore_nella_conversazione_non_arriva_a_meta(client, monkeypatch):
    """La risposta è già partita: un guasto interno non deve diventare un rinvio."""

    async def esplode(redis, **argomenti):
        raise RuntimeError("Claude non risponde")

    monkeypatch.setattr(webhook, "handle_incoming_message", esplode)

    risposta = client.post("/webhook/whatsapp", json=_payload(message_id="wamid.99"))

    assert risposta.status_code == 200


def test_se_risponde_una_persona_niente_puntini(client):
    """I puntini promettono una risposta fra pochi secondi.

    Con la conversazione in mano al salone quella promessa non la manteniamo:
    l'indicatore resterebbe lì mentre non scrive nessuno, e il cliente aspetta
    guardando lo schermo. Peggio di nessun segnale.
    """
    client.stato["risponde_una_persona"] = True

    client.post("/webhook/whatsapp", json=_payload(message_id="wamid.99"))

    assert client.solo_lette == ["wamid.99"], "le spunte blu devono partire lo stesso"
    assert client.segnalati == [], "non doveva comparire 'sta scrivendo'"


def test_se_risponde_il_bot_i_puntini_ci_sono(client):
    """Quando la risposta arriva davvero fra pochi secondi, l'indicatore serve."""
    client.stato["risponde_una_persona"] = False

    client.post("/webhook/whatsapp", json=_payload(message_id="wamid.100"))

    assert client.segnalati == ["wamid.100"]
    assert client.solo_lette == []
