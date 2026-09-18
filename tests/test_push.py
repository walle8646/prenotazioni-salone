"""Test sulle notifiche al telefono di chi lavora in salone.

La notifica esiste perché senza, il passaggio a una persona funziona solo per
chi si ricorda di aprire il pannello. Ma è un di più: se non parte, la
conversazione è passata lo stesso ed è nel pannello. Questi test guardano
soprattutto che un guasto delle notifiche non si porti dietro niente.
"""

import pytest

from services import push


@pytest.fixture
def senza_chiavi(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "vapid_public_key", "")
    monkeypatch.setattr(settings, "vapid_private_key", "")


@pytest.fixture
def con_chiavi(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "vapid_public_key", "chiave-pubblica-finta")
    monkeypatch.setattr(settings, "vapid_private_key", "chiave-privata-finta")


def test_senza_chiavi_la_funzione_non_si_offre(senza_chiavi):
    """Un bottone che promette notifiche e non le manda è peggio di nessun bottone."""
    assert push.configurato() is False
    assert push.chiave_pubblica() == ""


def test_con_le_chiavi_si_offre(con_chiavi):
    assert push.configurato() is True


@pytest.mark.asyncio
async def test_senza_chiavi_non_si_prova_nemmeno(senza_chiavi, monkeypatch):
    def non_chiamare(*a, **k):
        raise AssertionError("non doveva cercare le iscrizioni")

    monkeypatch.setattr("services.db_service.iscrizioni_push", non_chiamare)
    assert await push.avvisa("titolo", "testo") == 0


@pytest.mark.asyncio
async def test_le_iscrizioni_scadute_si_cancellano(con_chiavi, monkeypatch):
    """404 e 410 sono definitivi: è un telefono che non c'è più.

    Tenerle vorrebbe dire ritentare per sempre, e un conto delle consegne che
    dice il falso.
    """
    iscritti = [
        {"endpoint": "https://push.example/viva", "p256dh": "a", "auth": "b"},
        {"endpoint": "https://push.example/morta", "p256dh": "c", "auth": "d"},
    ]
    tolte = []

    async def finte():
        return iscritti

    async def togli(endpoint):
        tolte.append(endpoint)

    monkeypatch.setattr("services.db_service.iscrizioni_push", finte)
    monkeypatch.setattr("services.db_service.togli_iscrizione_push", togli)
    monkeypatch.setattr(
        push, "_manda_una", lambda i, c: 410 if "morta" in i["endpoint"] else None
    )

    consegnate = await push.avvisa("titolo", "testo")

    assert consegnate == 1
    assert tolte == ["https://push.example/morta"]


@pytest.mark.asyncio
async def test_un_servizio_push_rotto_non_ferma_niente(con_chiavi, monkeypatch):
    """Chi manda la notifica sta facendo altro, e quell'altro deve riuscire."""
    async def esplode():
        raise RuntimeError("database giù")

    monkeypatch.setattr("services.db_service.iscrizioni_push", esplode)
    assert await push.avvisa("titolo", "testo") == 0


@pytest.mark.asyncio
async def test_il_passaggio_avviene_anche_se_la_notifica_esplode(
    mock_redis, backends, canale, con_chiavi, monkeypatch
):
    """La notifica è un di più: il cliente è già in coda nel pannello.

    Farla fallire di proposito è l'unico modo di sapere che non si porta
    dietro il passaggio — che è la cosa che al cliente serve davvero.
    """
    from services.conversation import handle_incoming_message
    from services.fakes import ScriptedClaude

    async def esplode(*argomenti, **parametri):
        raise RuntimeError("servizio push irraggiungibile")

    monkeypatch.setattr("services.push.avvisa", esplode)

    await handle_incoming_message(
        redis=mock_redis,
        phone="393331234567",
        text="voglio parlare con una persona",
        msg_type="text",
        channel=canale,
        backends=backends,
        claude=ScriptedClaude([]),
    )

    assert len(backends.conversazioni_operatore) == 1
    assert backends.email_handoff, "e l'email è partita lo stesso"
