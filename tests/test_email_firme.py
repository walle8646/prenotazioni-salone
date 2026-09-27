"""I backend veri chiamano davvero le funzioni vere.

Questi test esistono per un guasto costato una serata. `RealBackends` passava
alla conferma un parametro che la funzione vera non accettava: ogni email di
conferma alzava `TypeError`, **per tutte le prenotazioni**, e per giorni il
cliente si è sentito dire "problema tecnico" su appuntamenti regolarmente
creati. La suite era verde: i test passano dai finti, e un finto con la firma
sbagliata non se ne accorge — anzi, la nasconde.

Qui i finti non ci sono. Le funzioni vengono chiamate davvero, con SMTP non
configurato: `_invia` esce prima di aprire qualsiasi connessione, quindi non
si tocca la rete, ma la firma sì.
"""

import pytest

from services.backends import RealBackends

QUANDO = "2026-09-29T18:30"


@pytest.fixture(autouse=True)
def smtp_spento(monkeypatch):
    """Nessuna credenziale: le email escono subito, senza rete."""
    from config import settings

    monkeypatch.setattr(settings, "smtp_user", "", raising=False)
    monkeypatch.setattr(settings, "smtp_password", "", raising=False)


@pytest.mark.asyncio
async def test_la_conferma_accetta_anche_per_chi_e():
    """Il parametro che mancava: è quello che dice al padre che
    l'appuntamento è del figlio."""
    await RealBackends().send_confirmation_email(
        to="cliente@example.invalid",
        nome="Valerio",
        data_ora=QUANDO,
        parrucchiere="Francesco",
        servizi=["Taglio"],
        per="Riccardo",
    )


@pytest.mark.asyncio
async def test_la_conferma_funziona_anche_senza_per():
    await RealBackends().send_confirmation_email(
        to="cliente@example.invalid",
        nome="Valerio",
        data_ora=QUANDO,
        parrucchiere="Francesco",
        servizi=["Taglio"],
    )


@pytest.mark.asyncio
async def test_tutte_le_altre_email_reggono_la_chiamata_vera():
    """Cinque messaggi partono da qui: se una firma si scolla, la suite sui
    finti continua a passare e se ne accorge il cliente."""
    backends = RealBackends()

    await backends.send_cancellation_email(
        to="c@example.invalid", nome="Valerio", data_ora=QUANDO,
        parrucchiere="Francesco", servizi=["Taglio"],
    )
    await backends.send_absence_email(
        to="c@example.invalid", nome="Valerio", data_ora=QUANDO,
        parrucchiere="Francesco", servizi=["Taglio"],
    )
    await backends.send_change_email(
        to="c@example.invalid", nome="Valerio", da=QUANDO, a=QUANDO,
        parrucchiere="Francesco", servizi=["Taglio"],
    )
    await backends.send_verification_code(to="c@example.invalid", codice="123456")
