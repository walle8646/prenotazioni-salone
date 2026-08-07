#!/usr/bin/env python3
"""Invia al webhook payload identici a quelli di WhatsApp Cloud API.

Serve a testare `routers/webhook.py` sul serio — parsing del payload, gestione
dei tipi di messaggio, verifica del webhook — senza avere un account Meta.
Il server deve essere in esecuzione (per esempio `docker compose up`).

Esempi:

  # verifica del webhook (l'handshake che fa Meta al primo collegamento)
  python tools/fake_webhook.py verify

  # messaggio di testo
  python tools/fake_webhook.py text "Vorrei prenotare un taglio"

  # risposta a un bottone interattivo
  python tools/fake_webhook.py button "Taglio"

  # foto con didascalia
  python tools/fake_webhook.py image "Vorrei un taglio così"

  # notifica di stato (deve essere ignorata dal webhook)
  python tools/fake_webhook.py status

  # messaggio audio (deve ricevere la risposta di tipo non supportato)
  python tools/fake_webhook.py audio
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# Lo script sta in tools/, ma importa config.py dalla radice del progetto
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

PHONE_DEFAULT = "393331234567"
PROFILE_NAME = "Cliente Di Prova"


def _envelope(value: dict) -> dict:
    """Racchiude il contenuto nella struttura che usa Meta."""
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "0",
                "changes": [{"field": "messages", "value": value}],
            }
        ],
    }


def _base_value(phone: str) -> dict:
    return {
        "messaging_product": "whatsapp",
        "metadata": {"display_phone_number": "390000000000", "phone_number_id": "0"},
        "contacts": [{"profile": {"name": PROFILE_NAME}, "wa_id": phone}],
    }


def payload_text(phone: str, text: str) -> dict:
    value = _base_value(phone)
    value["messages"] = [
        {
            "from": phone,
            "id": "wamid.test.text",
            "timestamp": "1750000000",
            "type": "text",
            "text": {"body": text},
        }
    ]
    return _envelope(value)


def payload_button(phone: str, title: str) -> dict:
    value = _base_value(phone)
    value["messages"] = [
        {
            "from": phone,
            "id": "wamid.test.button",
            "timestamp": "1750000000",
            "type": "interactive",
            "interactive": {
                "type": "button_reply",
                "button_reply": {"id": "opt_0", "title": title},
            },
        }
    ]
    return _envelope(value)


def payload_list(phone: str, title: str) -> dict:
    value = _base_value(phone)
    value["messages"] = [
        {
            "from": phone,
            "id": "wamid.test.list",
            "timestamp": "1750000000",
            "type": "interactive",
            "interactive": {
                "type": "list_reply",
                "list_reply": {"id": "opt_0", "title": title, "description": ""},
            },
        }
    ]
    return _envelope(value)


def payload_image(phone: str, caption: str) -> dict:
    value = _base_value(phone)
    value["messages"] = [
        {
            "from": phone,
            "id": "wamid.test.image",
            "timestamp": "1750000000",
            "type": "image",
            "image": {"id": "media-id-di-prova", "mime_type": "image/jpeg", "caption": caption},
        }
    ]
    return _envelope(value)


def payload_audio(phone: str) -> dict:
    value = _base_value(phone)
    value["messages"] = [
        {
            "from": phone,
            "id": "wamid.test.audio",
            "timestamp": "1750000000",
            "type": "audio",
            "audio": {"id": "media-id-audio", "mime_type": "audio/ogg"},
        }
    ]
    return _envelope(value)


def payload_status(phone: str) -> dict:
    """Notifica di consegna: il webhook la deve ignorare senza chiamare Claude."""
    value = _base_value(phone)
    value.pop("contacts", None)
    value["statuses"] = [
        {
            "id": "wamid.test.text",
            "status": "delivered",
            "timestamp": "1750000000",
            "recipient_id": phone,
        }
    ]
    return _envelope(value)


COSTRUTTORI = {
    "text": lambda p, m: payload_text(p, m or "Vorrei prenotare un taglio"),
    "button": lambda p, m: payload_button(p, m or "Taglio"),
    "list": lambda p, m: payload_list(p, m or "Taglio"),
    "image": lambda p, m: payload_image(p, m or "Vorrei un taglio così"),
    "audio": lambda p, m: payload_audio(p),
    "status": lambda p, m: payload_status(p),
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Simulatore di webhook WhatsApp")
    parser.add_argument(
        "tipo",
        choices=[*COSTRUTTORI.keys(), "verify"],
        help="tipo di evento da simulare",
    )
    parser.add_argument("messaggio", nargs="?", help="testo del messaggio")
    parser.add_argument("--url", default="http://localhost:8000", help="base URL del server")
    parser.add_argument("--phone", default=PHONE_DEFAULT, help="numero mittente simulato")
    parser.add_argument("--dry-run", action="store_true", help="stampa il payload senza inviarlo")
    args = parser.parse_args()

    endpoint = f"{args.url.rstrip('/')}/webhook/whatsapp"

    if args.tipo == "verify":
        from config import settings

        params = {
            "hub.mode": "subscribe",
            "hub.verify_token": settings.meta_verify_token,
            "hub.challenge": "1234567890",
        }
        if args.dry_run:
            print(json.dumps(params, indent=2))
            return 0
        resp = httpx.get(endpoint, params=params, timeout=30)
        print(f"HTTP {resp.status_code} → {resp.text}")
        atteso = resp.status_code == 200 and resp.text.strip() == "1234567890"
        print("verifica superata" if atteso else "verifica NON superata")
        return 0 if atteso else 1

    payload = COSTRUTTORI[args.tipo](args.phone, args.messaggio)

    if args.dry_run:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    resp = httpx.post(endpoint, json=payload, timeout=60)
    print(f"HTTP {resp.status_code} → {resp.text}")
    print("\nLa risposta del bot arriva su WhatsApp, non qui: guarda i log del server.")
    return 0 if resp.status_code == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
