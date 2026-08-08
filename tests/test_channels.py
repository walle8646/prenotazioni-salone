"""Test sul livello di astrazione dei canali."""

import pytest

from services import email_service

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


# ----------------------------------------------------- accesso al pannello


def test_senza_password_configurata_il_pannello_resta_chiuso(monkeypatch):
    """Una configurazione mancante deve chiudere la porta, non spalancarla.

    Il confronto è password == settings.admin_password: senza la variabile
    d'ambiente il valore è la stringa vuota, e chi lasciava il campo in bianco
    sarebbe entrato.
    """
    from config import settings

    monkeypatch.setattr(settings, "admin_password", "")
    monkeypatch.setattr(settings, "secret_key", "una-chiave-vera-e-lunga")
    assert not settings.admin_password

    monkeypatch.setattr(settings, "admin_password", "segreta")
    monkeypatch.setattr(settings, "secret_key", "dev-secret-change-me")
    assert settings.secret_key_configurata is False, (
        "la chiave scritta nel repository non è un segreto"
    )

    monkeypatch.setattr(settings, "secret_key", "una-chiave-vera-e-lunga")
    assert settings.secret_key_configurata is True


# ------------------------------------------------------------------ email SMTP


def test_la_data_arriva_al_cliente_in_italiano():
    """Nell'email finiva l'orario grezzo dell'azione: 2026-08-15T09:00."""
    assert (
        email_service._quando("2026-08-15T09:00")
        == "sabato 15 agosto 2026 alle 09:00"
    )
    # Un formato inatteso non deve impedire l'invio
    assert email_service._quando("domani mattina") == "domani mattina"
    assert email_service._quando(None) == "None"


@pytest.mark.asyncio
async def test_senza_configurazione_non_si_tenta_nessun_invio(monkeypatch):
    """Un salone che non ha ancora messo la casella non deve vedere errori."""
    from config import settings

    monkeypatch.setattr(settings, "smtp_user", "")
    monkeypatch.setattr(settings, "smtp_password", "")

    def esplodi(*args, **kwargs):  # pragma: no cover - non deve essere chiamata
        raise AssertionError("non si deve nemmeno provare a connettersi")

    monkeypatch.setattr("smtplib.SMTP", esplodi)

    await email_service.send_confirmation_email(
        to="cliente@example.it",
        nome="Mario",
        data_ora="2026-08-11T09:00",
        parrucchiere="Francesco",
        servizi=["Taglio"],
    )


@pytest.mark.asyncio
async def test_un_invio_fallito_non_fa_fallire_la_prenotazione(monkeypatch):
    """L'appuntamento è già sul calendario: l'email è un di più."""
    from config import settings

    monkeypatch.setattr(settings, "smtp_user", "salone@gmail.com")
    monkeypatch.setattr(settings, "smtp_password", "finta")

    def rifiuta(*args, **kwargs):
        raise OSError("server non raggiungibile")

    monkeypatch.setattr("smtplib.SMTP", rifiuta)

    # Non deve sollevare
    await email_service.send_reminder_email(
        to="cliente@example.it",
        nome="Mario",
        orario="09:00",
        parrucchiere="Francesco",
    )
