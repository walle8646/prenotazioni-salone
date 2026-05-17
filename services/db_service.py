from sqlalchemy import select, update
from models.orm import Cliente, Appuntamento, Parrucchiere
from models.database import async_session
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


async def seed_parrucchieri(parrucchieri_map: dict[str, str]):
    """Inserisce o aggiorna i parrucchieri nel database dal dizionario nome→cal_id.
    Viene eseguita al primo avvio."""
    async with async_session() as db:
        for nome, cal_id in parrucchieri_map.items():
            result = await db.execute(
                select(Parrucchiere).where(Parrucchiere.nome == nome)
            )
            parr = result.scalar_one_or_none()
            if parr:
                # Aggiorna cal_id se cambiato
                if parr.gcal_calendar_id != cal_id:
                    parr.gcal_calendar_id = cal_id
                    logger.info(f"Aggiornato calendar ID per {nome}")
            else:
                db.add(Parrucchiere(nome=nome, gcal_calendar_id=cal_id, attivo=True))
                logger.info(f"Creato parrucchiere: {nome}")
        await db.commit()


async def get_parrucchieri_attivi() -> list[dict]:
    """Restituisce tutti i parrucchieri attivi con nome e calendar ID."""
    async with async_session() as db:
        result = await db.execute(
            select(Parrucchiere).where(Parrucchiere.attivo == True)
        )
        return [
            {"id": p.id, "nome": p.nome, "gcal_calendar_id": p.gcal_calendar_id}
            for p in result.scalars().all()
        ]


async def get_parrucchieri_map() -> dict[str, str]:
    """Restituisce dizionario nome→cal_id per i parrucchieri attivi."""
    parrucchieri = await get_parrucchieri_attivi()
    return {p["nome"]: p["gcal_calendar_id"] for p in parrucchieri}


async def find_or_create_client(
    phone: str, nome: str = None, cognome: str = None,
    email: str = None, canale: str = "whatsapp",
) -> dict:
    """Cerca un cliente per telefono (o email se da web) o lo crea se nuovo."""
    async with async_session() as db:
        # Cerca per telefono o per email
        if phone:
            result = await db.execute(
                select(Cliente).where(Cliente.telefono_wa == phone)
            )
        elif email:
            result = await db.execute(
                select(Cliente).where(Cliente.email == email)
            )
        else:
            result = type("R", (), {"scalar_one_or_none": lambda: None})()

        client = result.scalar_one_or_none()

        if client:
            client.ultima_visita = datetime.now().date()
            # Aggiorna email se fornita e non presente
            if email and not client.email:
                client.email = email
            await db.commit()
            return {
                "id": client.id,
                "nome": client.nome,
                "cognome": client.cognome,
                "email": client.email,
                "is_new": False,
            }

        # Crea nuovo cliente
        client = Cliente(
            telefono_wa=phone or "",
            nome=nome,
            cognome=cognome,
            email=email,
            canale_origine=canale,
            prima_visita=datetime.now().date(),
            ultima_visita=datetime.now().date(),
        )
        db.add(client)
        await db.commit()
        await db.refresh(client)
        return {
            "id": client.id,
            "nome": client.nome,
            "cognome": client.cognome,
            "email": client.email,
            "is_new": True,
        }


async def create_appointment(
    client_id: int, data_ora: str, servizi: list, parrucchiere: str,
    richieste_spec: str = None, foto_url: str = None,
    gcal_event_id: str = None, durata_min: int = 30,
) -> dict:
    """Crea un appuntamento nel database."""
    async with async_session() as db:
        # Trova parrucchiere per nome
        parrucchiere_id = None
        if parrucchiere:
            result = await db.execute(
                select(Parrucchiere).where(Parrucchiere.nome == parrucchiere)
            )
            parr = result.scalar_one_or_none()
            if parr:
                parrucchiere_id = parr.id

        dt = datetime.strptime(data_ora, "%Y-%m-%dT%H:%M")
        app = Appuntamento(
            cliente_id=client_id,
            parrucchiere_id=parrucchiere_id,
            data_ora=dt,
            durata_min=durata_min,
            servizi=servizi,
            stato="Confermato",
            richieste_spec=richieste_spec,
            foto_riferimento=foto_url,
            gcal_event_id=gcal_event_id,
        )
        db.add(app)
        await db.commit()
        await db.refresh(app)
        return {"id": app.id, "gcal_event_id": gcal_event_id}


async def update_appointment_status(app_id: int, status: str):
    """Aggiorna lo stato di un appuntamento."""
    async with async_session() as db:
        await db.execute(
            update(Appuntamento)
            .where(Appuntamento.id == app_id)
            .values(stato=status)
        )
        await db.commit()


async def get_upcoming_appointments(hours_from: float, hours_to: float) -> list:
    """Trova appuntamenti in un range di ore da adesso (per reminder)."""
    now = datetime.now()
    from_dt = now + timedelta(hours=hours_from)
    to_dt = now + timedelta(hours=hours_to)

    async with async_session() as db:
        result = await db.execute(
            select(Appuntamento)
            .join(Cliente)
            .where(
                Appuntamento.data_ora.between(from_dt, to_dt),
                Appuntamento.stato == "Confermato",
                Appuntamento.reminder_inviato == False,
            )
        )
        return result.scalars().all()


async def get_inactive_clients(days: int) -> list:
    """Trova clienti con ultima_visita > N giorni fa."""
    cutoff = (datetime.now() - timedelta(days=days)).date()
    async with async_session() as db:
        result = await db.execute(
            select(Cliente).where(Cliente.ultima_visita < cutoff)
        )
        return result.scalars().all()
