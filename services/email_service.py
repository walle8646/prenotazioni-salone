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


async def send_cancellation_email(
    to: str, nome: str, data_ora: str, parrucchiere: str, servizi: list
):
    """Conferma per iscritto che l'appuntamento è stato annullato.

    Serve soprattutto quando la disdetta non l'ha chiesta il cliente: senza
    questa email se ne accorgerebbe presentandosi al salone.
    """
    servizi_str = ", ".join(servizi or [])
    await _invia(
        to,
        "Appuntamento annullato - Salone Nadia",
        f"""
            <h2>Ciao {nome}!</h2>
            <p>Il tuo appuntamento è stato annullato:</p>
            <ul>
                <li><strong>Data e ora:</strong> {_quando(data_ora)}</li>
                <li><strong>Servizio:</strong> {servizi_str}</li>
                <li><strong>Parrucchiere:</strong> {parrucchiere}</li>
            </ul>
            <p>Se non l'hai chiesto tu, o se vuoi prenotare di nuovo, scrivici
            pure: ti troviamo un altro orario.</p>
            <p>A presto!<br>Salone Nadia</p>
        """,
    )


async def send_absence_email(
    to: str, nome: str, data_ora: str, parrucchiere: str, servizi: list
):
    """Annullamento deciso dal salone perché l'operatore non c'è.

    Diverso dalla disdetta chiesta dal cliente: qui la colpa non è sua, non
    deve sembrare che abbia fatto qualcosa lui, e il salone deve scusarsi e
    dire come rimediare.
    """
    servizi_str = ", ".join(servizi or [])
    contatto = (
        f"chiamaci allo {settings.salone_telefono}"
        if settings.salone_telefono
        else "scrivici qui"
    )
    await _invia(
        to,
        "Dobbiamo spostare il tuo appuntamento - Salone Nadia",
        f"""
            <h2>Ciao {nome},</h2>
            <p>ci dispiace: {parrucchiere} non sarà in salone e dobbiamo
            annullare il tuo appuntamento.</p>
            <ul>
                <li><strong>Data e ora:</strong> {_quando(data_ora)}</li>
                <li><strong>Servizio:</strong> {servizi_str}</li>
            </ul>
            <p>Ci scusiamo per il disagio. Per trovare subito un altro orario
            {contatto}, oppure rispondi a questo messaggio.</p>
            <p>A presto!<br>Salone Nadia</p>
        """,
    )


async def send_change_email(
    to: str, nome: str, da: str, a: str, parrucchiere: str, servizi: list
):
    """Un solo messaggio per lo spostamento, invece di annullato più confermato."""
    servizi_str = ", ".join(servizi or [])
    await _invia(
        to,
        "Appuntamento spostato - Salone Nadia",
        f"""
            <h2>Ciao {nome}!</h2>
            <p>Il tuo appuntamento è stato spostato.</p>
            <p><s>{_quando(da)}</s><br>
            <strong>{_quando(a)}</strong></p>
            <ul>
                <li><strong>Servizio:</strong> {servizi_str}</li>
                <li><strong>Parrucchiere:</strong> {parrucchiere}</li>
            </ul>
            <p>Se il nuovo orario non ti va bene, scrivici pure.</p>
            <p>A presto!<br>Salone Nadia</p>
        """,
    )


async def send_verification_code(to: str, codice: str):
    """Invia il codice che sblocca lo storico dalla chat del sito."""
    await _invia(
        to,
        f"{codice} è il tuo codice - Salone Nadia",
        f"""
            <h2>Il tuo codice è {codice}</h2>
            <p>Scrivilo nella chat per vedere i tuoi appuntamenti.</p>
            <p>Vale per pochi minuti. Se non l'hai chiesto tu, ignora questo
            messaggio: senza il codice nessuno può vedere i tuoi dati.</p>
            <p>Salone Nadia</p>
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
