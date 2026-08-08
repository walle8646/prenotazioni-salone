"""Accesso ai servizi esterni usati dalle azioni del bot.

Raccoglie dietro un'unica interfaccia tutto ciò che sta fuori dal processo:
Google Calendar, PostgreSQL, il download dei media da WhatsApp e l'invio delle
email. Il motore conversazionale parla solo con questa interfaccia, quindi lo
stesso flusso può girare con i servizi veri (RealBackends) oppure con quelli
finti (FakeBackends, in services/fakes.py) per test e simulazioni.

Gli import delle librerie pesanti (Google, SQLAlchemy, Resend) sono volutamente
dentro i metodi: così importare il motore conversazionale non richiede di avere
quelle dipendenze installate.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class Backends:
    """Interfaccia verso i servizi esterni."""

    async def check_availability(
        self, date_str: str, parrucchiere_cal_id: str | None, durata_min: int
    ) -> list[dict]:
        raise NotImplementedError

    async def create_event(
        self,
        slot: str,
        parrucchiere_cal_id: str,
        servizi: list,
        durata: int,
        cliente_nome: str,
        descrizione: str = "",
    ) -> str:
        raise NotImplementedError

    async def delete_event(self, event_id: str, calendar_id: str) -> None:
        raise NotImplementedError

    async def find_or_create_client(
        self,
        phone: str,
        nome: str | None = None,
        cognome: str | None = None,
        email: str | None = None,
        canale: str = "whatsapp",
    ) -> dict:
        raise NotImplementedError

    async def create_appointment(self, **kwargs) -> dict:
        raise NotImplementedError

    async def update_appointment_status(self, app_id: int, status: str) -> None:
        raise NotImplementedError

    async def get_appuntamenti_per_telefono(self, telefono: str) -> dict | None:
        """Cliente e suoi appuntamenti. None se quel numero non è in anagrafica."""
        raise NotImplementedError

    async def get_appuntamenti_per_email(self, email: str) -> dict | None:
        """Come sopra ma per email: è la strada del sito, dopo la verifica."""
        raise NotImplementedError

    async def send_verification_code(self, to: str, codice: str) -> None:
        raise NotImplementedError

    async def send_cancellation_email(
        self, to: str, nome: str, data_ora: str, parrucchiere: str, servizi: list
    ) -> None:
        raise NotImplementedError

    async def send_absence_email(
        self, to: str, nome: str, data_ora: str, parrucchiere: str, servizi: list
    ) -> None:
        """Annullamento deciso dal salone perché l'operatore non c'è."""
        raise NotImplementedError

    async def send_change_email(
        self, to: str, nome: str, da: str, a: str, parrucchiere: str, servizi: list
    ) -> None:
        raise NotImplementedError

    async def sposta_appuntamento(self, **kwargs) -> None:
        raise NotImplementedError

    async def download_media(self, media_id: str):
        raise NotImplementedError

    async def salva_foto(self, contenuto: bytes, prefisso: str = "foto") -> str | None:
        """Salva l'immagine e restituisce l'URL da scrivere nel database."""
        raise NotImplementedError

    async def send_confirmation_email(
        self, to: str, nome: str, data_ora: str, parrucchiere: str, servizi: list
    ) -> None:
        raise NotImplementedError


class RealBackends(Backends):
    """I servizi veri: Google Calendar, PostgreSQL, Resend, WhatsApp Cloud API."""

    async def check_availability(self, date_str, parrucchiere_cal_id, durata_min):
        from services.calendar_service import check_availability

        return await check_availability(date_str, parrucchiere_cal_id, durata_min)

    async def create_event(
        self, slot, parrucchiere_cal_id, servizi, durata, cliente_nome, descrizione=""
    ):
        from services.calendar_service import create_event

        return await create_event(
            slot=slot,
            parrucchiere_cal_id=parrucchiere_cal_id,
            servizi=servizi,
            durata=durata,
            cliente_nome=cliente_nome,
            descrizione=descrizione,
        )

    async def delete_event(self, event_id, calendar_id):
        from services.calendar_service import delete_event

        await delete_event(event_id, calendar_id)

    async def find_or_create_client(
        self, phone, nome=None, cognome=None, email=None, canale="whatsapp"
    ):
        from services.db_service import find_or_create_client

        return await find_or_create_client(
            phone=phone, nome=nome, cognome=cognome, email=email, canale=canale
        )

    async def create_appointment(self, **kwargs):
        from services.db_service import create_appointment

        return await create_appointment(**kwargs)

    async def update_appointment_status(self, app_id, status):
        from services.db_service import update_appointment_status

        await update_appointment_status(app_id, status)

    async def get_appuntamenti_per_telefono(self, telefono):
        from services.db_service import get_appuntamenti_per_telefono

        return await get_appuntamenti_per_telefono(telefono)

    async def get_appuntamenti_per_email(self, email):
        from services.db_service import get_appuntamenti_per_email

        return await get_appuntamenti_per_email(email)

    async def send_verification_code(self, to, codice):
        from services.email_service import send_verification_code

        await send_verification_code(to=to, codice=codice)

    async def send_cancellation_email(self, to, nome, data_ora, parrucchiere, servizi):
        from services.email_service import send_cancellation_email

        await send_cancellation_email(
            to=to,
            nome=nome,
            data_ora=data_ora,
            parrucchiere=parrucchiere,
            servizi=servizi,
        )

    async def send_absence_email(self, to, nome, data_ora, parrucchiere, servizi):
        from services.email_service import send_absence_email

        await send_absence_email(
            to=to,
            nome=nome,
            data_ora=data_ora,
            parrucchiere=parrucchiere,
            servizi=servizi,
        )

    async def send_change_email(self, to, nome, da, a, parrucchiere, servizi):
        from services.email_service import send_change_email

        await send_change_email(
            to=to, nome=nome, da=da, a=a, parrucchiere=parrucchiere, servizi=servizi
        )

    async def sposta_appuntamento(self, **kwargs):
        from services.db_service import sposta_appuntamento

        await sposta_appuntamento(**kwargs)

    async def download_media(self, media_id):
        from services.whatsapp_service import download_media

        return await download_media(media_id)

    async def salva_foto(self, contenuto, prefisso="foto"):
        from services.storage import salva_foto

        return salva_foto(contenuto, prefisso)

    async def send_confirmation_email(self, to, nome, data_ora, parrucchiere, servizi):
        from services.email_service import send_confirmation_email

        await send_confirmation_email(
            to=to,
            nome=nome,
            data_ora=data_ora,
            parrucchiere=parrucchiere,
            servizi=servizi,
        )
