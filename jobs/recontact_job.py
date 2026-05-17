from services.db_service import get_inactive_clients
from services.whatsapp_service import send_template
from config import settings
import logging

logger = logging.getLogger(__name__)


async def recontact_inactive():
    """Ricontatta clienti inattivi da più di N giorni."""
    clients = await get_inactive_clients(settings.inactivity_days)

    for client in clients:
        try:
            nome = client.nome or ""
            telefono = client.telefono_wa

            if telefono:
                await send_template(
                    to=telefono,
                    template_name="ricontatto_inattivo",
                    parameters=[nome],
                )
                logger.info(f"Ricontatto inviato a {telefono}")

        except Exception as e:
            logger.error(f"Errore ricontatto per {client.id}: {e}")
