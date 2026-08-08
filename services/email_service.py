"""Invio delle email di conferma e promemoria, via SMTP.

Si spedisce dalla casella del salone invece che da un servizio esterno: il
mittente è l'indirizzo che i clienti già conoscono, e soprattutto le risposte
arrivano dove qualcuno le legge — cosa che con un noreply@ non succede.

Nessuna dipendenza aggiuntiva: smtplib sta nella libreria standard, e la
chiamata bloccante finisce in un thread come già si fa per Google Calendar.

Un invio fallito non deve mai far fallire una prenotazione: l'appuntamento è
sul calendario e nel database comunque, e l'email è un di più. Per questo qui
gli errori si annotano nei log e basta.
"""

import asyncio
import logging
import smtplib
from datetime import datetime
from email.message import EmailMessage

from config import settings

logger = logging.getLogger(__name__)

# I nomi in italiano sono scritti qui invece di affidarsi al locale del sistema:
# nel container non c'è, e il cliente riceverebbe "Saturday".
GIORNI = (
    "lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica",
)
MESI = (
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
)


def _quando(data_ora: str) -> str:
    """Trasforma '2026-08-15T09:00' in 'sabato 15 agosto 2026 alle 09:00'.

    Se il formato non è quello atteso si restituisce il valore così com'è: una
    data scritta male è brutta, un'email non spedita è peggio.
    """
    try:
        quando = datetime.strptime(str(data_ora), "%Y-%m-%dT%H:%M")
    except (TypeError, ValueError):
        return str(data_ora)
    return (
        f"{GIORNI[quando.weekday()]} {quando.day} {MESI[quando.month - 1]} "
        f"{quando.year} alle {quando:%H:%M}"
    )


def _configurato() -> bool:
    return bool(settings.smtp_user and settings.smtp_password)


def _mittente() -> str:
    return settings.email_from or settings.smtp_user


async def _invia(destinatario: str, oggetto: str, html: str) -> None:
    if not destinatario:
        return
    if not _configurato():
        logger.info(
            "Email a %s non inviata: SMTP non configurato (SMTP_USER/SMTP_PASSWORD)",
            destinatario,
        )
        return

    messaggio = EmailMessage()
    messaggio["From"] = f"Salone Nadia <{_mittente()}>"
    messaggio["To"] = destinatario
    messaggio["Subject"] = oggetto
    messaggio.set_content(
        "Questo messaggio è in formato HTML: per leggerlo serve un programma "
        "di posta che sappia mostrarlo."
    )
    messaggio.add_alternative(html, subtype="html")

    def _spedisci() -> None:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(messaggio)

    try:
        await asyncio.to_thread(_spedisci)
        logger.info("Email inviata a %s: %s", destinatario, oggetto)
    except Exception as e:  # noqa: BLE001 - l'email non deve far fallire la prenotazione
        logger.error("Invio email a %s fallito: %s", destinatario, e)


async def send_confirmation_email(
    to: str, nome: str, data_ora: str, parrucchiere: str, servizi: list
):
    """Invia email di conferma appuntamento."""
    servizi_str = ", ".join(servizi or [])
    await _invia(
        to,
        "Conferma appuntamento - Salone Nadia",
        f"""
            <h2>Ciao {nome}!</h2>
            <p>Il tuo appuntamento è confermato:</p>
            <ul>
                <li><strong>Data e ora:</strong> {_quando(data_ora)}</li>
                <li><strong>Servizio:</strong> {servizi_str}</li>
                <li><strong>Parrucchiere:</strong> {parrucchiere}</li>
            </ul>
            <p>Per cancellare o modificare, scrivici su WhatsApp o rispondi a questa email.</p>
            <p>A presto!<br>Salone Nadia</p>
        """,
    )


async def send_reminder_email(to: str, nome: str, orario: str, parrucchiere: str):
    """Invia email di promemoria appuntamento."""
    await _invia(
        to,
        "Promemoria: appuntamento domani - Salone Nadia",
        f"""
            <h2>Ciao {nome}!</h2>
            <p>Ti ricordiamo il tuo appuntamento di <strong>domani alle {orario}</strong>
            con <strong>{parrucchiere}</strong>.</p>
            <p>Per cancellare, scrivici su WhatsApp entro 12 ore.</p>
            <p>A domani!<br>Salone Nadia</p>
        """,
    )
