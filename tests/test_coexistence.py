"""Il numero del salone resta sul telefono, e il bot deve farsi da parte.

In coexistence la stessa conversazione ce l'hanno davanti in due: il bot, che
risponde in tre secondi, e chi e' in salone, che vede arrivare la notifica. Due
risposte diverse alla stessa domanda sono peggio di una risposta lenta, ed e'
l'unica cosa che distingue "online sul numero del salone" da "online e basta".

Meta ci dice che ha risposto una persona con un'eco (`smb_message_echoes`): e'
l'unico modo che abbiamo di saperlo, perche' quello che parte dal telefono non
passa da noi.
"""

import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import webhook
from services import whatsapp_service
from services.conversation import (
    registra_risposta_dal_telefono,
    risponde_una_persona,
)
from services.fakes import FakeBackends, FakeRedis

CLIENTE = "393331234567"
NUMERO_SALONE = "393513456789"


# ------------------------------------------------- il bot si fa da parte


@pytest.mark.asyncio
async def test_una_risposta_dal_telefono_mette_da_parte_il_bot():
    backends = FakeBackends()

    await registra_risposta_dal_telefono(
        CLIENTE, "Buongiorno, le confermo per giovedi'", backends=backends
    )

    assert await risponde_una_persona(CLIENTE, backends=backends) is True


@pytest.mark.asyncio
async def test_quello_che_e_stato_detto_dal_telefono_si_legge_nel_pannello():
    """Senza, la receptionist vede la domanda e nessuna risposta: e risponde
    una seconda volta alla stessa cosa."""
    backends = FakeBackends()

    await registra_risposta_dal_telefono(CLIENTE, "Giovedi' alle 10 va bene", backends=backends)

    conversazione = await backends.conversazione_operatore_aperta(CLIENTE)
    assert [(m["autore"], m["testo"]) for m in conversazione["messaggi"]] == [
        ("operatore", "Giovedi' alle 10 va bene")
    ]
    # Registrata come risposta di una persona, quindi la conversazione risulta
    # presa: e' da `presa_il` che si contano le 24 ore oltre le quali un
    # passaggio dimenticato torna al bot.
    assert conversazione["stato"] == "presa"
    assert conversazione["presa_il"] is not None


@pytest.mark.asyncio
async def test_non_si_avvisa_il_salone_di_quello_che_ha_scritto_il_salone():
    """L'avviso serve a chi non sta guardando: qui ha il telefono in mano."""
    backends = FakeBackends()

    await registra_risposta_dal_telefono(CLIENTE, "Arrivo", backends=backends)

    assert backends.email_handoff == []


@pytest.mark.asyncio
async def test_due_risposte_di_fila_non_aprono_due_passaggi():
    """Chi scrive tre messaggi dal telefono non deve produrre tre righe."""
    backends = FakeBackends()

    await registra_risposta_dal_telefono(CLIENTE, "Buongiorno", backends=backends)
    await registra_risposta_dal_telefono(CLIENTE, "Le confermo", backends=backends)

    assert len(backends.conversazioni_operatore) == 1
    conversazione = backends.conversazioni_operatore[0]
    assert len(conversazione["messaggi"]) == 2


@pytest.mark.asyncio
async def test_una_risposta_dal_telefono_si_aggancia_al_passaggio_gia_aperto():
    """Il cliente aveva chiesto una persona, e la persona risponde dall'app."""
    backends = FakeBackends()
    aperta = await backends.apri_conversazione_operatore(
        telefono=CLIENTE, motivo="Ha chiesto di parlare con qualcuno."
    )

    await registra_risposta_dal_telefono(CLIENTE, "Eccomi", backends=backends)

    assert len(backends.conversazioni_operatore) == 1
    assert backends.conversazioni_operatore[0]["id"] == aperta["id"]
    assert backends.conversazioni_operatore[0]["motivo"] == (
        "Ha chiesto di parlare con qualcuno."
    )


@pytest.mark.asyncio
async def test_se_il_database_non_risponde_il_bot_resta_in_piedi():
    """Una risposta doppia e' spiacevole, il silenzio totale e' peggio: il
    cliente non ha modo di sapere che qualcuno lo sta leggendo."""

    class BackendsRotti(FakeBackends):
        async def conversazione_operatore_aperta(self, telefono):
            raise RuntimeError("database non raggiungibile")

    backends = BackendsRotti()

    # Non deve propagare: il webhook ha gia' risposto a Meta da un pezzo.
    await registra_risposta_dal_telefono(CLIENTE, "Buongiorno", backends=backends)

    assert await risponde_una_persona(CLIENTE, backends=backends) is False


# --------------------------------------- quello che manda il bot non e' una persona


def test_un_messaggio_mandato_dal_bot_si_riconosce():
    """Se le eco comprendessero anche i nostri invii, il bot si zittirebbe da
    se' al primo messaggio: muto per 24 ore su ogni conversazione."""

    class RispostaFinta:
        is_success = True
        text = ""

        def json(self):
            return {"messages": [{"id": "wamid.nostro"}]}

    whatsapp_service._ricorda_invio(RispostaFinta())

    assert whatsapp_service.e_un_nostro_invio("wamid.nostro") is True
    assert whatsapp_service.e_un_nostro_invio("wamid.del-telefono") is False
    assert whatsapp_service.e_un_nostro_invio(None) is False


def test_una_risposta_senza_identificativo_non_fa_esplodere_niente():
    class RispostaMuta:
        is_success = True
        text = ""

        def json(self):
            raise ValueError("non e' JSON")

    whatsapp_service._ricorda_invio(RispostaMuta())  # non deve sollevare


# ------------------------------------------------------------- il webhook


def _payload_eco(
    message_id: str = "wamid.eco",
    testo: str = "Buongiorno, le confermo",
    a: str = CLIENTE,
    tipo: str = "text",
) -> dict:
    contenuto = {"text": {"body": testo}} if tipo == "text" else {tipo: {}}
    return {
        "entry": [
            {
                "changes": [
                    {
                        "field": "smb_message_echoes",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": NUMERO_SALONE},
                            "message_echoes": [
                                dict(
                                    {
                                        "from": "393510000000",
                                        "to": a,
                                        "id": message_id,
                                        "timestamp": "1760000000",
                                        "type": tipo,
                                    },
                                    **contenuto,
                                )
                            ],
                        },
                    }
                ]
            }
        ]
    }


def _payload_messaggio(phone_number_id: str = NUMERO_SALONE) -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": phone_number_id},
                            "contacts": [{"profile": {"name": "Mario"}}],
                            "messages": [
                                {
                                    "id": "wamid.1",
                                    "from": CLIENTE,
                                    "type": "text",
                                    "text": {"body": "vorrei un taglio"},
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
    """App col solo webhook: niente rete, niente database."""
    from config import settings

    eco = []
    elaborati = []

    async def finta_eco(phone, text=None, backends=None):
        eco.append((phone, text))

    async def finto_handle(redis, **argomenti):
        await asyncio.sleep(0)
        elaborati.append(argomenti)

    async def finto_segnale(message_id):
        return True

    async def finto_chi_risponde(phone, backends=None):
        return False

    monkeypatch.setattr(webhook, "registra_risposta_dal_telefono", finta_eco)
    monkeypatch.setattr(webhook, "handle_incoming_message", finto_handle)
    monkeypatch.setattr(webhook, "segna_letto_e_sta_scrivendo", finto_segnale)
    monkeypatch.setattr(webhook, "segna_letto", finto_segnale)
    monkeypatch.setattr(webhook, "risponde_una_persona", finto_chi_risponde)
    monkeypatch.setattr(settings, "meta_phone_number_id", NUMERO_SALONE)

    app = FastAPI()
    app.include_router(webhook.router)
    app.state.redis = FakeRedis()

    with TestClient(app) as c:
        c.eco = eco
        c.elaborati = elaborati
        yield c


def test_una_eco_mette_da_parte_il_bot_e_non_viene_elaborata_come_messaggio(client):
    risposta = client.post("/webhook/whatsapp", json=_payload_eco())

    assert risposta.status_code == 200
    assert client.eco == [(CLIENTE, "Buongiorno, le confermo")]
    # Non deve finire nel motore conversazionale: non e' un cliente che scrive.
    assert client.elaborati == []


def test_di_una_foto_mandata_dal_telefono_si_dice_almeno_che_c_era(client):
    """Tacere lascia la receptionist a rispondere una seconda volta."""
    client.post("/webhook/whatsapp", json=_payload_eco(tipo="image"))

    assert client.eco == [(CLIENTE, "[image inviato dal telefono]")]


def test_l_eco_di_un_messaggio_del_bot_non_zittisce_il_bot(client):
    class RispostaFinta:
        is_success = True
        text = ""

        def json(self):
            return {"messages": [{"id": "wamid.mandato-dal-bot"}]}

    whatsapp_service._ricorda_invio(RispostaFinta())

    client.post("/webhook/whatsapp", json=_payload_eco(message_id="wamid.mandato-dal-bot"))

    assert client.eco == []


def test_la_stessa_eco_non_viene_registrata_due_volte(client):
    """Meta rimanda quello che considera non consegnato."""
    client.post("/webhook/whatsapp", json=_payload_eco(message_id="wamid.ripetuta"))
    client.post("/webhook/whatsapp", json=_payload_eco(message_id="wamid.ripetuta"))

    assert len(client.eco) == 1


def test_una_eco_senza_destinatario_viene_lasciata_stare(client):
    """Senza il numero del cliente non si sa quale conversazione passare."""
    payload = _payload_eco()
    del payload["entry"][0]["changes"][0]["value"]["message_echoes"][0]["to"]

    risposta = client.post("/webhook/whatsapp", json=payload)

    assert risposta.status_code == 200
    assert client.eco == []


# ---------------------------------------------- un endpoint, due numeri


def test_un_messaggio_per_un_altro_numero_non_riceve_risposta(client):
    """Allo stesso endpoint arrivano due app Meta. Il bot risponde sempre dal
    numero in META_PHONE_NUMBER_ID: su un altro numero il cliente vedrebbe
    rispondere uno sconosciuto, che e' peggio del silenzio."""
    risposta = client.post(
        "/webhook/whatsapp", json=_payload_messaggio(phone_number_id="999999999")
    )

    assert risposta.json() == {"status": "ignored"}
    assert client.elaborati == []


def test_un_messaggio_per_il_nostro_numero_passa(client):
    client.post("/webhook/whatsapp", json=_payload_messaggio())

    assert len(client.elaborati) == 1
    assert client.elaborati[0]["phone"] == CLIENTE


def test_senza_numero_configurato_non_si_filtra_niente(client, monkeypatch):
    """Nei test e nel simulatore i payload non portano `metadata`: scartarli
    vorrebbe dire non elaborare piu' nulla."""
    from config import settings

    monkeypatch.setattr(settings, "meta_phone_number_id", "")

    client.post(
        "/webhook/whatsapp", json=_payload_messaggio(phone_number_id="999999999")
    )

    assert len(client.elaborati) == 1


# ------------------------------- le sincronizzazioni della coexistence


def test_la_cronologia_non_sembra_un_difetto_nostro(client):
    """Arriva in un'altra forma e non ci serve, ma dev'essere ignorata per
    scelta e non finire fra gli errori di lettura del payload."""
    risposta = client.post(
        "/webhook/whatsapp",
        json={"id": "DM1", "event": "history", "data": {"id": "1234"}},
    )

    assert risposta.status_code == 200
    assert risposta.json() == {"status": "ignored"}
    assert client.elaborati == []
    assert client.eco == []
