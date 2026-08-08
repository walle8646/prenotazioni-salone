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

    async def finto_handle(redis, **argomenti):
        # Simula il tempo vero di un giro con Claude e Google
        await asyncio.sleep(0.05)
        elaborati.append(argomenti)

    monkeypatch.setattr(webhook, "handle_incoming_message", finto_handle)

    app = FastAPI()
    app.include_router(webhook.router)
    app.state.redis = FakeRedis()

    with TestClient(app) as c:
        c.elaborati = elaborati
        yield c


def test_meta_riceve_conferma_e_il_lavoro_viene_dopo(client):
    risposta = client.post("/webhook/whatsapp", json=_payload())

    assert risposta.status_code == 200
    assert risposta.json() == {"status": "ok"}
    # TestClient attende anche i task in background: se sono stati eseguiti,
    # significa che erano registrati come tali e non dentro la richiesta.
    assert len(client.elaborati) == 1
    assert client.elaborati[0]["text"] == "vorrei un taglio"
    assert client.elaborati[0]["phone"] == "393331234567"


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
