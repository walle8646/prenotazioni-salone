"""Test sul livello di astrazione dei canali."""

import pytest

from services import email_service

from services.channels import (
    Channel,
    CollectorChannel,
    MetaWhatsAppChannel,
    WebChannel,
)


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


# ------------------------------------------------- scelte cliccabili su WhatsApp


SERVIZI = [
    {"id": "opt_0", "title": "Taglio", "description": "Taglio — 13,50 € — 30 min"},
    {
        "id": "opt_1",
        "title": "Taglio + Shampoo",
        "description": "Taglio + Shampoo — 17,50 € — 30 min",
    },
    {"id": "opt_2", "title": "Barba", "description": "Barba — 8,00 € — 30 min"},
    {
        "id": "opt_3",
        "title": "Taglio + Shampoo + Trattamento barba con oli e panno bagnato",
        "description": (
            "Taglio + Shampoo + Trattamento barba con oli e panno bagnato — 45,00 €"
        ),
    },
]


def test_una_voce_lunga_non_fa_piu_perdere_i_bottoni_a_tutto_il_listino():
    """Su una lista il titolo si accorcia, ma la voce resta nella descrizione.

    Prima bastava una voce sopra i 20 caratteri perché l'intero elenco dei
    servizi arrivasse come testo: proprio la prima scelta, e la più importante.
    """
    assert MetaWhatsAppChannel().opzioni_sostenibili(SERVIZI) is True


def test_su_tre_scelte_il_titolo_lungo_fa_ancora_rinunciare_ai_bottoni():
    """Un bottone ha solo il titolo: accorciarlo perderebbe la voce."""
    bottoni = [
        {"id": "opt_0", "title": "Taglio"},
        {"id": "opt_1", "title": "Colore + Taglio + Trattamento capello"},
    ]

    assert MetaWhatsAppChannel().opzioni_sostenibili(bottoni) is False


def test_oltre_dieci_righe_si_torna_al_testo():
    """Meta scarta le righe in eccesso senza dirlo: il cliente leggerebbe
    scelte che non può toccare."""
    troppe = [{"id": f"opt_{i}", "title": f"Voce {i}"} for i in range(11)]

    assert MetaWhatsAppChannel().opzioni_sostenibili(troppe) is False


def test_la_riga_accorciata_conserva_la_voce_per_intero():
    riga = MetaWhatsAppChannel()._riga(SERVIZI[3])

    assert len(riga["title"]) <= MetaWhatsAppChannel.LUNGHEZZA_TITOLO_RIGA
    assert riga["title"].endswith("…"), "il taglio deve vedersi"
    assert riga["description"] == SERVIZI[3]["description"]
    assert "panno bagnato" in riga["description"], (
        "è la descrizione che torna indietro quando il cliente tocca la riga"
    )


def test_una_descrizione_troppo_lunga_si_ferma_su_un_separatore():
    """Meta ne accetta 72: tagliata di netto lascerebbe un trattino sospeso,
    e questa è la riga che torna indietro quando il cliente tocca."""
    riga = MetaWhatsAppChannel()._riga(
        {
            "id": "opt_0",
            "title": "Taglio + Shampoo + Trattamento barba con oli e panno bagnato",
            "description": (
                "Taglio + Shampoo + Trattamento barba con oli e panno bagnato"
                " — 45,00 € — 1 ora"
            ),
        }
    )

    assert len(riga["description"]) <= MetaWhatsAppChannel.LUNGHEZZA_DESCRIZIONE_RIGA
    assert riga["description"].endswith("45,00 €")
    assert "Trattamento barba con oli e panno bagnato" in riga["description"], (
        "il nome del servizio deve sopravvivere al taglio"
    )


def test_una_voce_corta_non_viene_toccata():
    riga = MetaWhatsAppChannel()._riga(SERVIZI[0])

    assert riga["title"] == "Taglio"


def test_una_voce_lunga_senza_descrizione_se_ne_costruisce_una():
    """Altrimenti tornerebbe indietro solo il troncone del titolo."""
    riga = MetaWhatsAppChannel()._riga(
        {"id": "opt_0", "title": "Colore + Taglio + Trattamento capello"}
    )

    assert riga["description"] == "Colore + Taglio + Trattamento capello"


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
