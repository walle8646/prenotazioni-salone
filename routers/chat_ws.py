from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from services.conversation import handle_incoming_message_web
import json
import uuid

router = APIRouter()


@router.websocket("/ws/chat")
async def chat_websocket(websocket: WebSocket):
    """WebSocket per la chat dal sito web del salone."""
    await websocket.accept()
    redis = websocket.app.state.redis

    # Genera un ID sessione unico per il visitatore web
    session_id = f"web_{uuid.uuid4().hex[:12]}"

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
