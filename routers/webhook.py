from fastapi import APIRouter, BackgroundTasks, Request, Query, HTTPException
from fastapi.responses import PlainTextResponse
from config import settings
from services.conversation import (
    handle_incoming_message,
    registra_risposta_dal_telefono,
    risponde_una_persona,
)
from services.whatsapp_service import (
    e_un_nostro_invio,
    segna_letto,
    segna_letto_e_sta_scrivendo,
)
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook")

# Per quanto tempo ricordarsi di un messaggio già visto. Meta rimanda quelli
# che considera non consegnati, e senza memoria il cliente riceverebbe la
# stessa risposta due volte.
MEMORIA_MESSAGGI_SECONDI = 3600


def redis_di(request: Request):
    """La connessione a Redis dell'applicazione, se c'e'."""
    return getattr(request.app.state, "redis", None)


async def _gia_visto(redis, message_id: str) -> bool:
    """True se questo messaggio era già arrivato.

    Meta non garantisce una consegna sola: in caso di dubbio rimanda. Senza
    questo controllo il bot rielaborerebbe lo stesso messaggio, con una seconda
    chiamata a Claude e una seconda risposta al cliente.
    """
    if not message_id or redis is None:
        return False
    try:
        primo = await redis.set(
            f"wa:visto:{message_id}", "1", ex=MEMORIA_MESSAGGI_SECONDI, nx=True
        )
        return not primo
    except Exception:  # noqa: BLE001 - Redis giù non deve bloccare i messaggi
        logger.exception("Controllo dei messaggi già visti non riuscito")
        return False


def _per_il_nostro_numero(value: dict) -> bool:
    """Se questo messaggio riguarda il numero da cui il bot sa rispondere.

    Allo stesso endpoint arrivano i messaggi di piu' di un numero: quello
    dedicato di prima e quello del salone, che sono su due app Meta diverse
    iscritte entrambe qui. Il bot risponde pero' sempre e solo dal numero in
    `META_PHONE_NUMBER_ID`, quindi un messaggio arrivato su un altro numero
    riceverebbe la risposta da un numero diverso da quello a cui e' stato
    scritto: il cliente vede comparire uno sconosciuto che risponde a una cosa
    detta altrove, ed e' peggio che non ricevere niente.

    Senza `META_PHONE_NUMBER_ID` configurata non si filtra nulla: nei test e
    nel simulatore i payload non portano `metadata`, e scartarli vorrebbe dire
    non elaborare piu' niente.
    """
    nostro = settings.meta_phone_number_id
    arrivato = (value.get("metadata") or {}).get("phone_number_id")
    if not nostro or not arrivato or nostro == arrivato:
        return True

    logger.warning(
        "Messaggio per il numero %s ignorato: il bot risponde dal numero %s",
        arrivato,
        nostro,
    )
    return False


def _testo_della_eco(eco: dict) -> str | None:
    """Che cosa ha scritto il salone dal telefono, per il pannello.

    Nel pannello serve solo a far capire a chi legge cosa e' stato detto al
    cliente: di una foto o di un vocale basta dire che c'erano, mentre tacere
    lascia la receptionist a rispondere una seconda volta alla stessa domanda.
    """
    tipo = eco.get("type")
    if tipo == "text":
        return (eco.get("text") or {}).get("body")
    contenuto = eco.get(tipo) if isinstance(eco.get(tipo), dict) else {}
    didascalia = (contenuto or {}).get("caption")
    if didascalia:
        return didascalia
    return f"[{tipo} inviato dal telefono]" if tipo else None


# Le azioni con cui Meta dice che un contatto non c'e' piu'. Tutto il resto
# (aggiunta, modifica, o un nome nuovo che non conosciamo) e' una scrittura:
# un contatto in piu' non fa danno, uno perso si rivede solo riscollegando il
# numero.
AZIONI_DI_RIMOZIONE = {"remove", "removed", "delete", "deleted"}


async def _sincronizza_rubrica(sincronizzazioni: list) -> None:
    """Scrive in rubrica i contatti dell'app WhatsApp del salone.

    Arriva in due momenti: in blocco quando qualcuno chiede la
    sincronizzazione dal pannello — una volta sola, entro 24 ore dal
    collegamento — e poi uno per volta ogni volta che il salone aggiunge o
    cambia un contatto sul telefono.
    """
    from services.db_service import salva_contatti_rubrica, togli_contatto_rubrica

    da_salvare = []
    da_togliere = []
    for voce in sincronizzazioni or ():
        if not isinstance(voce, dict) or voce.get("type") != "contact":
            continue
        contatto = voce.get("contact") or {}
        if (voce.get("action") or "").lower() in AZIONI_DI_RIMOZIONE:
            da_togliere.append(contatto.get("phone_number"))
        else:
            da_salvare.append(contatto)

    try:
        if da_salvare:
            quanti = await salva_contatti_rubrica(da_salvare)
            logger.info("Rubrica: %s contatti salvati", quanti)
        for numero in da_togliere:
            await togli_contatto_rubrica(numero)
    except Exception:  # noqa: BLE001
        logger.exception("Sincronizzazione della rubrica non riuscita")


async def _registra_eco(phone: str, text: str | None) -> None:
    """Mette da parte il bot dopo che ha risposto una persona dal telefono."""
    try:
        await registra_risposta_dal_telefono(phone=phone, text=text)
    except Exception:  # noqa: BLE001
        logger.exception("Eco dell'app WhatsApp non registrata per %s", phone)


async def _elabora(redis, message_id: str = None, **argomenti) -> None:
    """Esegue la conversazione dopo che a Meta è già stato risposto.

    Gli errori si fermano qui: la risposta HTTP è partita da un pezzo, e
    lasciar propagare un'eccezione servirebbe solo a sporcare i log del server.
    """
    try:
        # Prima di tutto il resto: da qui in avanti si aspetta Claude e Google,
        # e il cliente deve vedere subito che il messaggio è arrivato. Se
        # fallisce non importa, è solo un segnale.
        #
        # "Sta scrivendo" però si mostra solo se a scrivere sarà davvero il
        # bot. Quando la conversazione è in mano a una persona i puntini
        # resterebbero lì mentre non scrive nessuno, promettendo una risposta
        # fra pochi secondi che arriverà quando il salone potrà: peggio di
        # nessun segnale, perché il cliente aspetta guardando lo schermo. Le
        # spunte blu restano, quelle dicono il vero.
        if await risponde_una_persona(argomenti.get("phone")):
            await segna_letto(message_id)
        else:
            await segna_letto_e_sta_scrivendo(message_id)
    except Exception:  # noqa: BLE001
        logger.warning("Indicatore di scrittura non inviato", exc_info=True)

    try:
        await handle_incoming_message(redis=redis, **argomenti)
    except Exception:  # noqa: BLE001
        logger.exception("Elaborazione del messaggio WhatsApp fallita")


# GET — Meta webhook verification (challenge handshake)
@router.get("/whatsapp")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """Risponde alla verifica con cui Meta controlla di parlare col server giusto.

    Il challenge va restituito com'è, in testo semplice: convertirlo a intero
    funzionava per caso, perché finora Meta ne manda di numerici, ma un valore
    non numerico avrebbe fatto fallire la verifica con un errore 500 — proprio
    nel momento in cui si preme "Verifica e salva" e non si capisce perché.
    """
    if not settings.meta_verify_token:
        logger.error("META_VERIFY_TOKEN non configurata: verifica rifiutata")
        raise HTTPException(status_code=403, detail="Verification failed")

    if hub_mode == "subscribe" and hub_verify_token == settings.meta_verify_token:
        return PlainTextResponse(hub_challenge or "")

    logger.warning("Verifica del webhook rifiutata: token non corrispondente")
    raise HTTPException(status_code=403, detail="Verification failed")


# POST — Riceve messaggi in entrata
@router.post("/whatsapp")
async def receive_message(request: Request, background: BackgroundTasks):
    """Prende in carico il messaggio e risponde subito.

    Meta aspetta pochi secondi: se non riceve conferma considera il messaggio
    non consegnato e lo rimanda. Interrogare Claude e Google prima di
    rispondere — una decina di secondi — significava farsi rimandare il
    messaggio e far arrivare al cliente due o tre volte la stessa risposta.
    Qui si conferma la ricezione e si lavora dopo.
    """
    body = await request.json()

    # La sincronizzazione dei contatti e della cronologia della coexistence
    # arriva in un'altra forma — `{"event": ..., "data": ...}` invece di
    # `entry`/`changes` — e non ci serve: il bot non tiene la rubrica del
    # salone ne' le conversazioni di prima. Si dichiara ignorata qui perche'
    # altrimenti finirebbe fra gli errori di lettura del payload, dove
    # sembrerebbe un difetto nostro ogni volta che Meta sincronizza.
    if isinstance(body, dict) and "entry" not in body and body.get("event"):
        evento = body.get("event")
        dati = body.get("data") or {}
        if evento == "smb_app_state_sync":
            background.add_task(_sincronizza_rubrica, dati.get("state_sync"))
            return {"status": "ok"}
        logger.info("Evento di coexistence ignorato: %s", evento)
        return {"status": "ignored"}

    # Estrai il messaggio dal payload Meta
    try:
        entry = body["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]

        if not _per_il_nostro_numero(value):
            return {"status": "ignored"}

        # Il salone ha scritto dall'app del telefono. Meta ce lo rimanda
        # indietro come eco, ed e' l'unico modo che abbiamo di sapere che su
        # quella conversazione sta rispondendo una persona: il numero e' sul
        # telefono del salone, e il bot non vede quello che parte da li'.
        # La rubrica del telefono: Meta la manda in due forme diverse a
        # seconda di come e' configurato il webhook, quindi si guardano
        # entrambe invece di indovinare quale.
        if "state_sync" in value:
            background.add_task(_sincronizza_rubrica, value.get("state_sync"))
            return {"status": "ok"}

        if "message_echoes" in value:
            for eco in value.get("message_echoes") or ():
                cliente = eco.get("to")
                if not cliente:
                    # Senza il numero del cliente non si sa quale
                    # conversazione mettere in mano a una persona.
                    continue
                # Fra le eco non deve finire quello che ha mandato il bot: si
                # metterebbe da parte da se' al primo messaggio.
                if e_un_nostro_invio(eco.get("id")):
                    continue
                if await _gia_visto(redis_di(request), eco.get("id")):
                    continue
                background.add_task(
                    _registra_eco, cliente, _testo_della_eco(eco)
                )
            return {"status": "ok"}

        # Ignora status updates (delivered, read, ecc.)
        if "messages" not in value:
            return {"status": "ignored"}

        message = value["messages"][0]
        # Il nome del profilo è un di più: se manca si prenota lo stesso, e
        # perdere il messaggio per quello sarebbe sproporzionato.
        contatti = value.get("contacts") or [{}]
        contact = contatti[0]
        phone_number = message["from"]  # numero WhatsApp del cliente
        msg_type = message["type"]  # text, image, audio, etc.

        # Estrai contenuto in base al tipo
        if msg_type == "text":
            text = message["text"]["body"]
            media_id = None
        elif msg_type == "image":
            text = message.get("image", {}).get("caption", "[foto inviata]")
            media_id = message["image"]["id"]
        elif msg_type == "interactive":
            # Risposta a bottone o lista
            interactive = message.get("interactive", {})
            itype = interactive.get("type")
            if itype == "button_reply":
                text = interactive["button_reply"]["title"]
            elif itype == "list_reply":
                scelta = interactive["list_reply"]
                # Il titolo di una riga si ferma a 24 caratteri, quindi le voci
                # lunghe del listino arrivano accorciate. La descrizione porta
                # la voce per intero ed è quella che il bot deve leggere.
                text = scelta.get("description") or scelta["title"]
            else:
                text = None
            media_id = None
            msg_type = "interactive"
        else:
            text = None
            media_id = None

    except (KeyError, IndexError):
        return {"status": "parse_error"}

    redis = redis_di(request)

    if await _gia_visto(redis, message.get("id")):
        logger.info("Messaggio %s già elaborato, ignorato", message.get("id"))
        return {"status": "duplicato"}

    # Dopo la risposta, non prima: è tutto il punto di questa funzione.
    background.add_task(
        _elabora,
        redis,
        message_id=message.get("id"),
        phone=phone_number,
        text=text,
        msg_type=msg_type,
        media_id=media_id,
        contact_name=contact.get("profile", {}).get("name"),
    )

    return {"status": "ok"}
