from fastapi import APIRouter, BackgroundTasks, Request, Query, HTTPException
from fastapi.responses import PlainTextResponse
from config import settings
from services.conversation import handle_incoming_message, risponde_una_persona
from services.whatsapp_service import segna_letto, segna_letto_e_sta_scrivendo
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook")

# Per quanto tempo ricordarsi di un messaggio già visto. Meta rimanda quelli
# che considera non consegnati, e senza memoria il cliente riceverebbe la
# stessa risposta due volte.
MEMORIA_MESSAGGI_SECONDI = 3600


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

    # Estrai il messaggio dal payload Meta
    try:
        entry = body["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]

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

    redis = request.app.state.redis

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
