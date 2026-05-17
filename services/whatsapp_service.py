import httpx
from config import settings

BASE_URL = f"{settings.meta_api_url}/{settings.meta_phone_number_id}"
HEADERS = {
    "Authorization": f"Bearer {settings.meta_wa_token}",
    "Content-Type": "application/json",
}


async def send_text_message(to: str, text: str):
    """Invia un messaggio di testo via WhatsApp Cloud API."""
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{BASE_URL}/messages",
            headers=HEADERS,
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": text},
            },
            timeout=10,
        )


async def send_interactive_buttons(to: str, body_text: str, buttons: list[dict]):
    """Invia un messaggio con bottoni cliccabili (max 3 bottoni).
    buttons = [{"id": "btn_1", "title": "Taglio"}, ...]
    """
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{BASE_URL}/messages",
            headers=HEADERS,
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": body_text},
                    "action": {
                        "buttons": [
                            {
                                "type": "reply",
                                "reply": {"id": btn["id"], "title": btn["title"][:20]}
                            }
                            for btn in buttons[:3]
                        ]
                    },
                },
            },
            timeout=10,
        )


async def send_interactive_list(to: str, body_text: str, button_text: str, items: list[dict]):
    """Invia un messaggio con lista espandibile (max 10 opzioni).
    items = [{"id": "item_1", "title": "Taglio", "description": "30 min"}, ...]
    """
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{BASE_URL}/messages",
            headers=HEADERS,
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "interactive",
                "interactive": {
                    "type": "list",
                    "body": {"text": body_text},
                    "action": {
                        "button": button_text[:20],
                        "sections": [
                            {
                                "title": "Opzioni",
                                "rows": [
                                    {
                                        "id": item["id"],
                                        "title": item["title"][:24],
                                        "description": item.get("description", "")[:72],
                                    }
                                    for item in items[:10]
                                ],
                            }
                        ],
                    },
                },
            },
            timeout=10,
        )


async def send_template(to: str, template_name: str, parameters: list[str]):
    """Invia un messaggio template (per messaggi proattivi: reminder, notifiche)."""
    components = []
    if parameters:
        components.append({
            "type": "body",
            "parameters": [{"type": "text", "text": p} for p in parameters],
        })

    async with httpx.AsyncClient() as client:
        await client.post(
            f"{BASE_URL}/messages",
            headers=HEADERS,
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "template",
                "template": {
                    "name": template_name,
                    "language": {"code": "it"},
                    "components": components,
                },
            },
            timeout=10,
        )


async def download_media(media_id: str) -> bytes:
    """Scarica un file media da WhatsApp Cloud API."""
    async with httpx.AsyncClient() as client:
        # Step 1: ottieni URL del media
        resp = await client.get(
            f"{settings.meta_api_url}/{media_id}",
            headers={"Authorization": f"Bearer {settings.meta_wa_token}"},
            timeout=10,
        )
        media_url = resp.json()["url"]

        # Step 2: scarica il file
        resp = await client.get(
            media_url,
            headers={"Authorization": f"Bearer {settings.meta_wa_token}"},
            timeout=30,
        )
        return resp.content
