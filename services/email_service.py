import resend
from config import settings
import logging

logger = logging.getLogger(__name__)

resend.api_key = settings.resend_api_key


async def send_confirmation_email(
    to: str, nome: str, data_ora: str, parrucchiere: str, servizi: list
):
    """Invia email di conferma appuntamento."""
    if not to or not settings.resend_api_key:
        return

    servizi_str = ", ".join(servizi)
    try:
        resend.Emails.send({
            "from": f"Salone Nadia <{settings.email_from}>",
            "to": to,
            "subject": "Conferma appuntamento - Salone Nadia",
            "html": f"""
                <h2>Ciao {nome}!</h2>
                <p>Il tuo appuntamento è confermato:</p>
                <ul>
                    <li><strong>Data e ora:</strong> {data_ora}</li>
                    <li><strong>Servizio:</strong> {servizi_str}</li>
                    <li><strong>Parrucchiere:</strong> {parrucchiere}</li>
                </ul>
                <p>Per cancellare o modificare, scrivici su WhatsApp o rispondi a questa email.</p>
                <p>A presto!<br>Salone Nadia</p>
            """,
        })
        logger.info(f"Email conferma inviata a {to}")
    except Exception as e:
        logger.error(f"Errore invio email conferma a {to}: {e}")


async def send_reminder_email(to: str, nome: str, orario: str, parrucchiere: str):
    """Invia email di promemoria appuntamento."""
    if not to or not settings.resend_api_key:
        return

    try:
        resend.Emails.send({
            "from": f"Salone Nadia <{settings.email_from}>",
            "to": to,
            "subject": "Promemoria: appuntamento domani - Salone Nadia",
            "html": f"""
                <h2>Ciao {nome}!</h2>
                <p>Ti ricordiamo il tuo appuntamento di <strong>domani alle {orario}</strong>
                con <strong>{parrucchiere}</strong>.</p>
                <p>Per cancellare, scrivici su WhatsApp entro 12 ore.</p>
                <p>A domani!<br>Salone Nadia</p>
            """,
        })
        logger.info(f"Email reminder inviata a {to}")
    except Exception as e:
        logger.error(f"Errore invio email reminder a {to}: {e}")
