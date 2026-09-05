from sqlalchemy import select, update
from models.orm import Cliente, Appuntamento, Parrucchiere
from models.database import async_session
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


def sovrascrive_il_calendario(in_tabella: str | None, da_configurazione: str) -> bool:
    """Se il calendario della configurazione deve rimpiazzare quello in tabella.

    Solo finché in tabella c'è un segnaposto. Quando c'è un calendario vero è
    il pannello a cambiarlo, e un riavvio non deve disfare quel lavoro.
    """
    from services.operatori import PREFISSO_NON_CONFIGURATO

    return (in_tabella or "").startswith(PREFISSO_NON_CONFIGURATO) and not (
        da_configurazione or ""
    ).startswith(PREFISSO_NON_CONFIGURATO)


async def seed_parrucchieri(parrucchieri_map: dict[str, str]):
    """Inserisce gli operatori mancanti, dal dizionario nome→cal_id.

    Riempie soltanto quello che manca, come fa `seed_servizi`. Prima invece, a
    ogni avvio, riattivava chi era nell'elenco del codice e disattivava chi non
    c'era: con un pannello di gestione vorrebbe dire vedersi sparire al deploy
    successivo l'operatore appena assunto, e tornare al lavoro quello appena
    messo a riposo. La fonte di verità è il database; da qui passa solo la
    prima configurazione.

    Il calendar ID della configurazione sovrascrive solo un segnaposto: quando
    in tabella c'è già un calendario vero, a cambiarlo è il pannello.
    """
    async with async_session() as db:
        for nome, cal_id in parrucchieri_map.items():
            result = await db.execute(
                select(Parrucchiere).where(Parrucchiere.nome == nome)
            )
            parr = result.scalar_one_or_none()
            if parr is None:
                db.add(Parrucchiere(nome=nome, gcal_calendar_id=cal_id, attivo=True))
                logger.info("Creato operatore: %s", nome)
                continue

            if sovrascrive_il_calendario(parr.gcal_calendar_id, cal_id):
                parr.gcal_calendar_id = cal_id
                logger.info("Configurato il calendario di %s", nome)

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


async def get_presenze() -> dict[str, dict[int, list[tuple[str, str]]]]:
    """Le fasce settimanali di chi ha orari suoi, per nome.

    Chi non compare qui dentro lavora negli orari del salone: l'assenza dalla
    mappa è il "non configurato", e va tenuta distinta da una mappa vuota.
    """
    from sqlalchemy.orm import selectinload

    from models.orm import Parrucchiere

    async with async_session() as db:
        result = await db.execute(
            select(Parrucchiere)
            .options(selectinload(Parrucchiere.presenze))
            .where(Parrucchiere.orari_propri == True)  # noqa: E712
        )
        presenze: dict[str, dict[int, list[tuple[str, str]]]] = {}
        for parr in result.scalars().all():
            per_giorno: dict[int, list[tuple[str, str]]] = {}
            for fascia in sorted(
                parr.presenze, key=lambda f: (f.giorno, f.ora_inizio)
            ):
                per_giorno.setdefault(fascia.giorno, []).append(
                    (fascia.ora_inizio, fascia.ora_fine)
                )
            presenze[parr.nome] = per_giorno
        return presenze


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


# --------------------------------------------------- conversazioni con una persona


def _conversazione_dict(riga) -> dict:
    """Riga ORM → dizionario. Solo colonne proprie, mai relazioni.

    Leggere una relazione caricata pigramente dentro una sessione asincrona
    solleva MissingGreenlet, e succede in produzione con la suite tutta verde:
    i test girano sui finti, dove le relazioni non esistono.
    """
    return {
        "id": riga.id,
        "telefono": riga.telefono,
        "canale": riga.canale,
        "cliente_id": riga.cliente_id,
        "nome_visualizzato": riga.nome_visualizzato,
        "stato": riga.stato,
        "motivo": riga.motivo,
        "aperta_il": riga.aperta_il,
        "ultimo_messaggio_cliente": riga.ultimo_messaggio_cliente,
        "presa_il": riga.presa_il,
        "chiusa_il": riga.chiusa_il,
    }


async def conversazione_operatore_aperta(telefono: str) -> dict | None:
    """Il passaggio ancora aperto per questo numero, se c'è.

    È questa riga a tenere zitto il bot: finché esiste, su quel numero risponde
    una persona. Una sola per numero, la più recente.
    """
    from models.orm import ConversazioneOperatore

    async with async_session() as db:
        risultato = await db.execute(
            select(ConversazioneOperatore)
            .where(
                ConversazioneOperatore.telefono == telefono,
                ConversazioneOperatore.stato != "chiusa",
            )
            .order_by(ConversazioneOperatore.aperta_il.desc())
            .limit(1)
        )
        riga = risultato.scalar_one_or_none()
        return _conversazione_dict(riga) if riga else None


async def apri_conversazione_operatore(
    telefono: str,
    canale: str = "whatsapp",
    nome_visualizzato: str | None = None,
    motivo: str | None = None,
    storico: list[tuple[str, str]] | None = None,
) -> dict:
    """Passa la conversazione a una persona e ci travasa gli ultimi scambi.

    Se ce n'è già una aperta si restituisce quella: un cliente che insiste
    ("c'è nessuno?") non deve produrre tre righe nel pannello.
    """
    from models.orm import Cliente, ConversazioneOperatore, MessaggioConversazione

    gia_aperta = await conversazione_operatore_aperta(telefono)
    if gia_aperta:
        return gia_aperta

    async with async_session() as db:
        cliente_id = None
        risultato = await db.execute(
            select(Cliente.id).where(Cliente.telefono_wa == telefono)
        )
        cliente_id = risultato.scalar_one_or_none()

        adesso = datetime.now()
        conversazione = ConversazioneOperatore(
            telefono=telefono,
            canale=canale,
            cliente_id=cliente_id,
            nome_visualizzato=nome_visualizzato,
            stato="attesa",
            motivo=motivo,
            aperta_il=adesso,
            ultimo_messaggio_cliente=adesso,
        )
        db.add(conversazione)
        await db.flush()

        for autore, testo in storico or ():
            db.add(
                MessaggioConversazione(
                    conversazione_id=conversazione.id,
                    autore=autore,
                    testo=testo,
                    creato_il=adesso,
                )
            )

        await db.commit()
        await db.refresh(conversazione)
        return _conversazione_dict(conversazione)


async def registra_messaggio_conversazione(
    conversazione_id: int, autore: str, testo: str
) -> None:
    """Aggiunge una riga allo scambio.

    Quando a scrivere è il cliente aggiorna anche `ultimo_messaggio_cliente`:
    è da lì che si calcola la finestra di 24 ore, e tenerla in due posti
    diversi vorrebbe dire vederla scadere in anticipo nel pannello.
    """
    from models.orm import ConversazioneOperatore, MessaggioConversazione

    async with async_session() as db:
        adesso = datetime.now()
        db.add(
            MessaggioConversazione(
                conversazione_id=conversazione_id,
                autore=autore,
                testo=testo,
                creato_il=adesso,
            )
        )
        if autore == "cliente":
            await db.execute(
                update(ConversazioneOperatore)
                .where(ConversazioneOperatore.id == conversazione_id)
                .values(ultimo_messaggio_cliente=adesso)
            )
        elif autore == "operatore":
            await db.execute(
                update(ConversazioneOperatore)
                .where(ConversazioneOperatore.id == conversazione_id)
                .values(stato="presa", presa_il=adesso)
            )
        await db.commit()


async def chiudi_conversazione_operatore(conversazione_id: int) -> None:
    """Restituisce la conversazione al bot."""
    from models.orm import ConversazioneOperatore

    async with async_session() as db:
        await db.execute(
            update(ConversazioneOperatore)
            .where(ConversazioneOperatore.id == conversazione_id)
            .values(stato="chiusa", chiusa_il=datetime.now())
        )
        await db.commit()


async def elenco_conversazioni_operatore(aperte: bool = True, limite: int = 50) -> list[dict]:
    """Le conversazioni per il pannello, con il nome del cliente se lo sappiamo.

    Il nome si prende con una join esplicita e non leggendo `riga.cliente`:
    quella è una relazione pigra e in sessione asincrona esplode.
    """
    from models.orm import Cliente, ConversazioneOperatore

    async with async_session() as db:
        query = (
            select(ConversazioneOperatore, Cliente.nome, Cliente.cognome)
            .outerjoin(Cliente, ConversazioneOperatore.cliente_id == Cliente.id)
            .order_by(ConversazioneOperatore.aperta_il.desc())
            .limit(limite)
        )
        if aperte:
            query = query.where(ConversazioneOperatore.stato != "chiusa")

        elenco = []
        for riga, nome, cognome in (await db.execute(query)).all():
            voce = _conversazione_dict(riga)
            intero = " ".join(p for p in (nome, cognome) if p)
            voce["nome"] = intero or riga.nome_visualizzato or riga.telefono
            elenco.append(voce)
        return elenco


async def conversazione_con_messaggi(conversazione_id: int) -> dict | None:
    """Una conversazione e il suo scambio, in ordine di tempo."""
    from models.orm import Cliente, ConversazioneOperatore, MessaggioConversazione

    async with async_session() as db:
        risultato = await db.execute(
            select(ConversazioneOperatore, Cliente.nome, Cliente.cognome)
            .outerjoin(Cliente, ConversazioneOperatore.cliente_id == Cliente.id)
            .where(ConversazioneOperatore.id == conversazione_id)
        )
        riga = risultato.first()
        if riga is None:
            return None

        conversazione, nome, cognome = riga
        voce = _conversazione_dict(conversazione)
        intero = " ".join(p for p in (nome, cognome) if p)
        voce["nome"] = intero or conversazione.nome_visualizzato or conversazione.telefono

        messaggi = await db.execute(
            select(MessaggioConversazione)
            .where(MessaggioConversazione.conversazione_id == conversazione_id)
            .order_by(MessaggioConversazione.creato_il, MessaggioConversazione.id)
        )
        # L'id serve al pannello per chiedere "cosa e' arrivato dopo questo"
        # senza riscaricare tutto lo scambio a ogni controllo.
        voce["messaggi"] = [
            {
                "id": m.id,
                "autore": m.autore,
                "testo": m.testo,
                "creato_il": m.creato_il,
            }
            for m in messaggi.scalars().all()
        ]
        return voce
