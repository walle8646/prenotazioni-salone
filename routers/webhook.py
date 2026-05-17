from fastapi import APIRouter, Request, Query, HTTPException
from config import settings
from services.conversation import handle_incoming_message

router = APIRouter(prefix="/webhook")


# GET — Meta webhook verification (challenge handshake)
@router.get("/whatsapp")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_verify_token == settings.meta_verify_token:
        return int(hub_challenge)
    raise HTTPException(status_code=403, detail="Verification failed")


# POST — Riceve messaggi in entrata
@router.post("/whatsapp")
async def receive_message(request: Request):
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
        contact = value["contacts"][0]
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
                text = interactive["list_reply"]["title"]
            else:
                text = None
            media_id = None
            msg_type = "interactive"
        else:
            text = None
            media_id = None

    except (KeyError, IndexError):
        return {"status": "parse_error"}

    # Processa il messaggio
    redis = request.app.state.redis
    await handle_incoming_message(
        redis=redis,
        phone=phone_number,
        text=text,
        msg_type=msg_type,
        media_id=media_id,
        contact_name=contact.get("profile", {}).get("name"),
    )

    return {"status": "ok"}
