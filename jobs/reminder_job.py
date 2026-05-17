from services.db_service import get_upcoming_appointments
from services.whatsapp_service import send_template
from services.email_service import send_reminder_email
from models.database import async_session
from models.orm import Appuntamento
from sqlalchemy import update
import logging

logger = logging.getLogger(__name__)


async def send_reminders():
    """Invia reminder per appuntamenti tra 11.5 e 12.5 ore da adesso.
    Logica doppio canale:
    - Se il cliente ha email → invia via email (gratuito)
    - Se il cliente ha WhatsApp → invia anche via WhatsApp (template)
    - Se ha entrambi → invia su entrambi i canali
    """
    appointments = await get_upcoming_appointments(hours_from=11.5, hours_to=12.5)

    async with async_session() as db:
        for app in appointments:
            try:
                nome = app.cliente.nome or ""
                orario = app.data_ora.strftime("%H:%M")
                parrucchiere = app.parrucchiere.nome if app.parrucchiere else ""
                telefono = app.cliente.telefono_wa
                email = app.cliente.email

                # Invia via email se disponibile (gratuito)
                if email:
                    await send_reminder_email(email, nome, orario, parrucchiere)

                # Invia via WhatsApp se disponibile
                if telefono:
                    await send_template(
                        to=telefono,
                        template_name="reminder_12h",
                        parameters=[nome, orario, parrucchiere],
                    )

                # Segna come inviato
                await db.execute(
                    update(Appuntamento)
                    .where(Appuntamento.id == app.id)
                    .values(reminder_inviato=True)
                )
                await db.commit()
                logger.info(
                    f"Reminder inviato per app {app.id} (email={bool(email)}, wa={bool(telefono)})"
                )

            except Exception as e:
                logger.error(f"Errore invio reminder per {app.id}: {e}")
