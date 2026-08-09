"""Test sull'invio verso WhatsApp.

Le funzioni di invio ignoravano la risposta di Meta. Un messaggio rifiutato
sembrava consegnato: il cliente non riceveva nulla e nei log non restava il
motivo, che invece Meta scrive per esteso e in italiano.
"""

import json
import logging

import pytest

from services import whatsapp_service


class _RispostaFinta:
    """Il minimo che `_invia` guarda di una risposta httpx."""

    def __init__(self, status_code: int, corpo):
        self.status_code = status_code
        self._corpo = corpo
        self.text = corpo if isinstance(corpo, str) else json.dumps(corpo)

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self):
        if isinstance(self._corpo, str):
            raise ValueError("non è JSON")
        return self._corpo


@pytest.fixture
def meta(monkeypatch):
    """Sostituisce la rete e registra quello che sarebbe partito."""
    inviati = []
    risposte = []

    class ClientFinto:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def post(self, url, headers=None, json=None, timeout=None):
            inviati.append({"url": url, "headers": headers, "payload": json})
            return risposte.pop(0)

    monkeypatch.setattr(whatsapp_service.httpx, "AsyncClient", ClientFinto)

    class Banco:
        def rispondi(self, status_code, corpo):
            risposte.append(_RispostaFinta(status_code, corpo))

        @property
        def inviati(self):
            return inviati

    return Banco()


RIFIUTO = {
    "error": {
        "message": "(#131030) Recipient phone number not in allowed list",
        "code": 131030,
        "error_data": {
            "details": "Numero di telefono del destinatario non presente nella lista dei numeri consentiti."
        },
    }
}


async def test_un_messaggio_accettato_risulta_partito(meta):
    meta.rispondi(200, {"messages": [{"id": "wamid.1"}]})

    assert await whatsapp_service.send_text_message("393331234567", "ciao") is True


async def test_un_messaggio_rifiutato_non_risulta_partito(meta):
    meta.rispondi(400, RIFIUTO)

    assert await whatsapp_service.send_text_message("393331234567", "ciao") is False


async def test_il_motivo_del_rifiuto_finisce_nei_log(meta, caplog):
    meta.rispondi(400, RIFIUTO)

    with caplog.at_level(logging.ERROR):
        await whatsapp_service.send_text_message("393331234567", "ciao")

    registrato = caplog.text
    assert "131030" in registrato, "senza il codice non si cerca la causa"
    assert "lista dei numeri consentiti" in registrato
    assert "393331234567" in registrato, "serve sapere a chi non è arrivato"


async def test_un_rifiuto_senza_json_non_fa_esplodere_l_invio(meta, caplog):
    """Davanti a un guasto di Meta la risposta può non essere JSON."""
    meta.rispondi(502, "<html>Bad Gateway</html>")

    with caplog.at_level(logging.ERROR):
        assert await whatsapp_service.send_text_message("393331234567", "ciao") is False

    assert "Bad Gateway" in caplog.text


async def test_anche_bottoni_lista_e_template_dicono_se_sono_partiti(meta):
    meta.rispondi(400, RIFIUTO)
    meta.rispondi(400, RIFIUTO)
    meta.rispondi(400, RIFIUTO)

    assert await whatsapp_service.send_interactive_buttons(
        "393331234567", "Quale?", [{"id": "b1", "title": "Taglio"}]
    ) is False
    assert await whatsapp_service.send_interactive_list(
        "393331234567", "Quale?", "Scegli", [{"id": "i1", "title": "Taglio"}]
    ) is False
    assert await whatsapp_service.send_template("393331234567", "promemoria", []) is False


async def test_lettura_e_sta_scrivendo_viaggiano_insieme(meta):
    """Una chiamata sola fa le spunte blu e l'indicatore. La forma la valida
    Meta: `type` accetta solo "text", verificato contro le API vere."""
    meta.rispondi(200, {"success": True})

    assert await whatsapp_service.segna_letto_e_sta_scrivendo("wamid.42") is True
    assert meta.inviati[0]["payload"] == {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": "wamid.42",
        "typing_indicator": {"type": "text"},
    }


async def test_senza_id_del_messaggio_non_si_chiama_nessuno(meta):
    """Meta lo rifiuterebbe: tanto vale non disturbarla."""
    assert await whatsapp_service.segna_letto_e_sta_scrivendo("") is False
    assert meta.inviati == []


async def test_il_token_viene_riletto_a_ogni_invio(meta, monkeypatch):
    """Il token di Meta scade: congelarlo all'import lo lascerebbe quello vecchio."""
    from config import settings

    monkeypatch.setattr(settings, "meta_wa_token", "token-nuovo")
    meta.rispondi(200, {"messages": [{"id": "wamid.1"}]})

    await whatsapp_service.send_text_message("393331234567", "ciao")

    assert meta.inviati[0]["headers"]["Authorization"] == "Bearer token-nuovo"


async def test_anche_il_numero_del_mittente_viene_riletto(meta, monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "meta_phone_number_id", "999")
    meta.rispondi(200, {"messages": [{"id": "wamid.1"}]})

    await whatsapp_service.send_text_message("393331234567", "ciao")

    assert meta.inviati[0]["url"].endswith("/999/messages")
