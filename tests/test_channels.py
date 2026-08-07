"""Test sul livello di astrazione dei canali."""

import pytest

from services.channels import Channel, CollectorChannel, WebChannel


class CanaleSenzaBottoni(Channel):
    """Un canale che sa solo mandare testo, come i gateway non ufficiali."""

    name = "solo-testo"

    def __init__(self):
        self.inviati = []

    async def send_text(self, to, text):
        self.inviati.append(text)


@pytest.mark.asyncio
async def test_canale_senza_bottoni_degrada_a_testo():
    """Chi non supporta i bottoni deve comunque mostrare le opzioni, come lista."""
    canale = CanaleSenzaBottoni()
    await canale.send_options(
        "393331234567",
        "Che servizio?",
        [{"id": "opt_0", "title": "Taglio"}, {"id": "opt_1", "title": "Barba"}],
    )

    assert len(canale.inviati) == 1
    assert canale.inviati[0] == "Che servizio?\n- Taglio\n- Barba"


@pytest.mark.asyncio
async def test_collector_registra_testo_e_opzioni():
    canale = CollectorChannel()
    await canale.send_text("393331234567", "ciao")
    await canale.send_options("393331234567", "scegli", [{"id": "opt_0", "title": "Taglio"}])

    assert canale.testi == ["ciao", "scegli"]
    assert canale.ultimo()["options"][0]["title"] == "Taglio"


@pytest.mark.asyncio
async def test_web_channel_accorpa_i_messaggi():
    """Il widget riceve un solo blocco di testo anche se il bot parla due volte."""
    canale = WebChannel()
    await canale.send_text("web_1", "Controllo subito!")
    await canale.send_options("web_1", "Ecco gli orari", [{"id": "opt_0", "title": "09:00"}])

    payload = canale.payload()
    assert payload["text"] == "Controllo subito!\n\nEcco gli orari"
    assert payload["options"] == [{"id": "opt_0", "title": "09:00"}]


@pytest.mark.asyncio
async def test_web_channel_senza_opzioni():
    canale = WebChannel()
    await canale.send_text("web_1", "A che ora preferisci?")
    assert canale.payload() == {"text": "A che ora preferisci?", "options": None}
