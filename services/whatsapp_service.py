import logging

import httpx
from config import settings

logger = logging.getLogger(__name__)


def _base_url() -> str:
    # Letto a ogni invio e non una volta all'import: il token di Meta scade e
    # viene sostituito, e un valore congelato all'avvio resterebbe quello vecchio.
    return f"{settings.meta_api_url}/{settings.meta_phone_number_id}"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.meta_wa_token}",
        "Content-Type": "application/json",
    }


def _spiegazione(risposta: httpx.Response) -> str:
    """Il motivo del rifiuto secondo Meta, che lo scrive per esteso."""
    try:
        errore = risposta.json().get("error", {})
    except ValueError:
        return risposta.text[:300]

    pezzi = [errore.get("message", "")]
    dettagli = errore.get("error_data", {}).get("details")
    if dettagli:
        pezzi.append(dettagli)
    return " — ".join(p for p in pezzi if p) or risposta.text[:300]


async def _invia(payload: dict, descrizione: str) -> bool:
    """Manda il payload a Meta e dice se è partito davvero.

    Ignorare la risposta faceva credere consegnato un messaggio che Meta aveva
    rifiutato: il cliente non riceveva nulla e nei log non restava traccia del
    perché. Meta il perché lo scrive, basta leggerlo.
    """
    async with httpx.AsyncClient() as client:
        risposta = await client.post(
            f"{_base_url()}/messages",
            headers=_headers(),
            json=payload,
            timeout=10,
        )

    if risposta.is_success:
        return True

    logger.error(
        "WhatsApp ha rifiutato %s verso %s (HTTP %s): %s",
        descrizione,
        payload.get("to"),
        risposta.status_code,
        _spiegazione(risposta),
    )
    return False


async def send_text_message(to: str, text: str) -> bool:
    """Invia un messaggio di testo via WhatsApp Cloud API."""
    return await _invia(
        {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": text},
        },
        "un messaggio di testo",
    )


async def send_interactive_buttons(to: str, body_text: str, buttons: list[dict]) -> bool:
    """Invia un messaggio con bottoni cliccabili (max 3 bottoni).
    buttons = [{"id": "btn_1", "title": "Taglio"}, ...]
    """
    return await _invia(
        {
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
        "dei bottoni",
    )


async def send_interactive_list(
    to: str, body_text: str, button_text: str, items: list[dict]
) -> bool:
    """Invia un messaggio con lista espandibile (max 10 opzioni).
    items = [{"id": "item_1", "title": "Taglio", "description": "30 min"}, ...]
    """
    return await _invia(
        {
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
        "una lista di opzioni",
    )


async def send_template(to: str, template_name: str, parameters: list[str]) -> bool:
    """Invia un messaggio template (per messaggi proattivi: reminder, notifiche)."""
    components = []
    if parameters:
        components.append({
            "type": "body",
            "parameters": [{"type": "text", "text": p} for p in parameters],
        })

    return await _invia(
        {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": "it"},
                "components": components,
            },
        },
        f"il template {template_name}",
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
        if not resp.is_success:
            raise RuntimeError(
                f"WhatsApp non dà il media {media_id}: {_spiegazione(resp)}"
            )
        media_url = resp.json()["url"]

        # Step 2: scarica il file
        resp = await client.get(
            media_url,
            headers={"Authorization": f"Bearer {settings.meta_wa_token}"},
            timeout=30,
        )
        return resp.content
