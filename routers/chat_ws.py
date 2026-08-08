from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from services.conversation import (
    apri_conversazione_web,
    handle_incoming_message_web,
    storico_visibile_web,
)
import json
import re
import uuid

router = APIRouter()

# L'identificativo arriva dal browser, quindi non è affidabile: diventa una
# chiave in Redis, e le sessioni di WhatsApp sono indicizzate per numero di
# telefono. Senza questo vincolo un visitatore potrebbe chiedere la sessione
# "393331234567" e leggersi la conversazione di un cliente.
FORMATO_SESSIONE = re.compile(r"^web_[0-9a-f]{12}$")


def _sessione_richiesta(websocket: WebSocket) -> str:
    """Riprende la sessione indicata dal browser, se è plausibile; altrimenti ne apre una."""
    richiesta = websocket.query_params.get("sessione")
    if richiesta and FORMATO_SESSIONE.match(richiesta):
        return richiesta
    return f"web_{uuid.uuid4().hex[:12]}"


@router.websocket("/ws/chat")
async def chat_websocket(websocket: WebSocket):
    """WebSocket per la chat dal sito web del salone."""
    await websocket.accept()
    redis = websocket.app.state.redis

    session_id = _sessione_richiesta(websocket)

    # Il browser deve sapere quale sessione sta usando, per ritrovarla dopo un
    # ricaricamento o una caduta di connessione.
    await websocket.send_text(json.dumps({"type": "sessione", "id": session_id}))

    # Il saluto lo dice il bot, non la pagina: così resta nello storico e la
    # risposta del cliente ("sì") ha un contesto a cui riferirsi. Chi si
    # riconnette non viene salutato di nuovo.
    saluto = await apri_conversazione_web(redis, session_id)
    if saluto:
        await websocket.send_text(
            json.dumps({"type": "message", "text": saluto, "options": None})
        )
    else:
        # Conversazione ripresa: il riquadro del browser è vuoto ma la memoria
        # del bot no, quindi si rimette in pagina quello che ci si era detti.
        for messaggio in await storico_visibile_web(redis, session_id):
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "storico",
                        "role": messaggio["role"],
                        "text": messaggio["text"],
                    }
                )
            )

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            text = msg.get("text", "")

            if not text.strip():
                continue

            # Processa il messaggio con la stessa logica conversazionale
            response = await handle_incoming_message_web(
                redis=redis,
                session_id=session_id,
                text=text,
                email=msg.get("email"),
            )

            # response è un dict con 'text' e opzionalmente 'options'
            await websocket.send_text(json.dumps({
                "type": "message",
                "text": response["text"],
                "options": response.get("options"),
            }))

    except WebSocketDisconnect:
        pass
