from sqlalchemy import select, update
from models.orm import Cliente, Appuntamento, Parrucchiere
from models.database import async_session
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


async def seed_parrucchieri(parrucchieri_map: dict[str, str]):
    """Inserisce o aggiorna gli operatori nel database dal dizionario nome→cal_id.

    Viene eseguita a ogni avvio: aggiunge i nuovi, aggiorna i calendari cambiati
    e disattiva quelli che non sono più in elenco (senza cancellarli, così lo
    storico degli appuntamenti resta leggibile).
    """
    async with async_session() as db:
        for nome, cal_id in parrucchieri_map.items():
            result = await db.execute(
                select(Parrucchiere).where(Parrucchiere.nome == nome)
            )
            parr = result.scalar_one_or_none()
            if parr:
                if parr.gcal_calendar_id != cal_id:
                    parr.gcal_calendar_id = cal_id
                    logger.info(f"Aggiornato calendar ID per {nome}")
                if not parr.attivo:
                    parr.attivo = True
                    logger.info(f"Riattivato operatore: {nome}")
            else:
                db.add(Parrucchiere(nome=nome, gcal_calendar_id=cal_id, attivo=True))
                logger.info(f"Creato operatore: {nome}")

        # Disattiva chi non è più nell'elenco degli operatori
        result = await db.execute(select(Parrucchiere).where(Parrucchiere.attivo == True))
        for parr in result.scalars().all():
            if parr.nome not in parrucchieri_map:
                parr.attivo = False
                logger.info(f"Disattivato operatore non più in elenco: {parr.nome}")

        await db.commit()


async def get_parrucchieri_attivi() -> list[dict]:
    """Restituisce tutti gli operatori attivi con nome e calendar ID."""
    async with async_session() as db:
        result = await db.execute(
            select(Parrucchiere).where(Parrucchiere.attivo == True)
        )
        return [
            {"id": p.id, "nome": p.nome, "gcal_calendar_id": p.gcal_calendar_id}
            for p in result.scalars().all()
        ]


async def get_parrucchieri_map() -> dict[str, str]:
    """Restituisce dizionario nome→cal_id per gli operatori attivi."""
    parrucchieri = await get_parrucchieri_attivi()
    return {p["nome"]: p["gcal_calendar_id"] for p in parrucchieri}


async def seed_servizi(servizi_iniziali) -> None:
    """Riempie la tabella `servizi` al primo avvio.

    Inserisce solo le voci mancanti: se il salone modifica un prezzo dal
    pannello di gestione, il riavvio non deve riportarlo a quello del codice.
    """
    from models.orm import ServizioListino

    async with async_session() as db:
        result = await db.execute(select(ServizioListino.codice))
        esistenti = set(result.scalars().all())

        for ordine, servizio in enumerate(servizi_iniziali):
            if servizio.codice in esistenti:
                continue
            db.add(
                ServizioListino(
                    codice=servizio.codice,
                    nome=servizio.nome,
                    prezzo=servizio.prezzo,
                    durata_min=servizio.durata_min,
                    alias=list(servizio.alias),
                    ordine=ordine,
                    attivo=True,
                )
            )
            logger.info(f"Creato servizio a listino: {servizio.nome}")
        await db.commit()


async def get_servizi_attivi() -> list:
    """Legge il listino dal database e lo restituisce come oggetti Servizio."""
    from models.orm import ServizioListino
    from services.catalogo import Servizio

    async with async_session() as db:
        result = await db.execute(
            select(ServizioListino)
            .where(ServizioListino.attivo == True)
            .order_by(ServizioListino.ordine, ServizioListino.id)
        )
        return [
            Servizio(
                codice=s.codice,
                nome=s.nome,
                prezzo=float(s.prezzo),
                durata_min=s.durata_min,
                alias=tuple(s.alias or ()),
            )
            for s in result.scalars().all()
        ]


async def find_or_create_client(
    phone: str = None, nome: str = None, cognome: str = None,
    email: str = None, canale: str = "whatsapp",
) -> dict:
    """Cerca un cliente per telefono, poi per email, altrimenti lo crea.

    La ricerca a due passaggi serve ai contatti dal sito: lì il "telefono" è un
    identificativo di sessione diverso a ogni visita, quindi è l'email a dire se
    è una persona già conosciuta.
    """
    async with async_session() as db:
        client = None

        if phone:
            result = await db.execute(
                select(Cliente).where(Cliente.telefono_wa == phone)
            )
            client = result.scalar_one_or_none()

        if client is None and email:
            result = await db.execute(select(Cliente).where(Cliente.email == email))
            client = result.scalar_one_or_none()

        if client:
            client.ultima_visita = datetime.now().date()
            # Completa i dati mancanti senza sovrascrivere quelli già noti
            if email and not client.email:
                client.email = email
            if nome and not client.nome:
                client.nome = nome
            if cognome and not client.cognome:
                client.cognome = cognome
            # Chi è nato dal sito ha come telefono l'identificativo di sessione,
            # che non identifica nessuno. Appena se ne conosce uno vero prende il
            # suo posto, altrimenti scrivendo da WhatsApp resterebbe uno
            # sconosciuto pur essendo già in anagrafica.
            if (
                phone
                and not phone.startswith("web_")
                and (client.telefono_wa or "").startswith("web_")
            ):
                client.telefono_wa = phone
                logger.info("Cliente %s ora identificato dal suo numero", client.id)
            await db.commit()
            return _cliente_dict(client, is_new=False)

        client = Cliente(
            telefono_wa=phone or f"sconosciuto:{datetime.now().timestamp()}",
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
        return _cliente_dict(client, is_new=True)


def _cliente_dict(client: Cliente, is_new: bool) -> dict:
    return {
        "id": client.id,
        "nome": client.nome,
        "cognome": client.cognome,
        "email": client.email,
        "telefono": client.telefono_wa,
        "canale": client.canale_origine,
        "parrucchiere_pref_id": client.parrucchiere_pref_id,
        "is_new": is_new,
    }


async def create_appointment(
    client_id: int, data_ora: str, servizi: list, parrucchiere: str,
    richieste_spec: str = None, foto_url: str = None,
    gcal_event_id: str = None, durata_min: int = 30, prezzo: float = None,
) -> dict:
    """Crea un appuntamento nel database.

    Il prezzo viene salvato così com'è al momento della prenotazione: è la cifra
    pattuita col cliente e non deve cambiare se domani il listino cambia.
    """
    async with async_session() as db:
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
            prezzo=prezzo,
            stato="Confermato",
            richieste_spec=richieste_spec,
            foto_riferimento=foto_url,
            gcal_event_id=gcal_event_id,
        )
        db.add(app)

        # La prima prenotazione fissa l'operatore preferito del cliente: serve a
        # riproporglielo la volta dopo senza doverlo richiedere ogni volta.
        if parrucchiere_id:
            result = await db.execute(select(Cliente).where(Cliente.id == client_id))
            cliente = result.scalar_one_or_none()
            if cliente is not None and cliente.parrucchiere_pref_id is None:
                cliente.parrucchiere_pref_id = parrucchiere_id

        await db.commit()
        await db.refresh(app)
        return {
            "id": app.id,
            "gcal_event_id": gcal_event_id,
            "prezzo": float(app.prezzo) if app.prezzo is not None else None,
        }


async def get_appuntamenti_per_telefono(telefono: str, limite: int = 10) -> dict | None:
    """Cliente e suoi appuntamenti, cercati per numero di telefono.

    Restituisce None se quel numero non è in anagrafica. Include l'id
    dell'appuntamento e quello dell'evento Google, che servono per cancellare.
    """
    if not telefono:
        return None
    return await _appuntamenti_del_cliente(Cliente.telefono_wa == telefono, limite)


async def get_appuntamenti_per_email(email: str, limite: int = 10) -> dict | None:
    """Come sopra, ma cercando per email: è la strada del sito, dopo la verifica."""
    if not email:
        return None
    return await _appuntamenti_del_cliente(Cliente.email == email, limite)


async def _appuntamenti_del_cliente(condizione, limite: int) -> dict | None:
    from sqlalchemy.orm import selectinload

    adesso = datetime.now()

    async with async_session() as db:
        cliente = (
            await db.execute(select(Cliente).where(condizione))
        ).scalars().first()
        if cliente is None:
            return None

        risultato = await db.execute(
            select(Appuntamento)
            .options(selectinload(Appuntamento.parrucchiere))
            .where(Appuntamento.cliente_id == cliente.id)
            .order_by(Appuntamento.data_ora.desc())
            .limit(limite)
        )
        appuntamenti = [
            {
                "app_id": a.id,
                "data_ora": a.data_ora.strftime("%Y-%m-%dT%H:%M"),
                "durata_min": a.durata_min,
                "servizi": a.servizi,
                "parrucchiere": a.parrucchiere.nome if a.parrucchiere else None,
                "prezzo": float(a.prezzo) if a.prezzo is not None else None,
                "stato": a.stato,
                "gcal_event_id": a.gcal_event_id,
                "passato": a.data_ora < adesso,
            }
            for a in risultato.scalars().all()
        ]

    return {
        "cliente": {
            "id": cliente.id,
            "nome": cliente.nome,
            "cognome": cliente.cognome,
            "email": cliente.email,
        },
        "appuntamenti": appuntamenti,
    }


async def sposta_appuntamento(
    app_id: int,
    data_ora: str,
    parrucchiere: str | None = None,
    gcal_event_id: str | None = None,
    durata_min: int | None = None,
) -> None:
    """Sposta un appuntamento esistente invece di crearne uno nuovo.

    La riga resta la stessa: nello storico del cliente si vede un appuntamento
    spostato, non uno annullato più uno preso.
    """
    async with async_session() as db:
        app = (
            await db.execute(select(Appuntamento).where(Appuntamento.id == app_id))
        ).scalar_one_or_none()
        if app is None:
            return

        if parrucchiere:
            parr = (
                await db.execute(
                    select(Parrucchiere).where(Parrucchiere.nome == parrucchiere)
                )
            ).scalar_one_or_none()
            if parr:
                app.parrucchiere_id = parr.id

        app.data_ora = datetime.strptime(data_ora, "%Y-%m-%dT%H:%M")
        if gcal_event_id:
            app.gcal_event_id = gcal_event_id
        if durata_min:
            app.durata_min = durata_min
        # Il promemoria va rimandato: quello già inviato parlava del vecchio orario
        app.reminder_inviato = False

        await db.commit()


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
    from sqlalchemy.orm import selectinload

    now = datetime.now()
    from_dt = now + timedelta(hours=hours_from)
    to_dt = now + timedelta(hours=hours_to)

    async with async_session() as db:
        result = await db.execute(
            select(Appuntamento)
            .options(
                selectinload(Appuntamento.cliente),
                selectinload(Appuntamento.parrucchiere),
            )
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
