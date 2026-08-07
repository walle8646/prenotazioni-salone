"""Astrazione del canale di uscita.

Il motore conversazionale non sa su quale canale sta parlando: riceve un
oggetto Channel e ci scrive sopra. Lo stesso identico flusso di prenotazione
gira quindi su WhatsApp, sul widget del sito, in un test automatico o nel
simulatore da terminale.

Per aggiungere in futuro un provider diverso (Twilio, Green API, Telegram)
basta scrivere una nuova classe qui sotto: il resto del codice non cambia.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class Channel:
    """Interfaccia comune a tutti i canali."""

    name = "base"
    # I canali che sanno mostrare bottoni o liste cliccabili mettono True.
    supports_options = False

    async def send_text(self, to: str, text: str) -> None:
        raise NotImplementedError

    async def send_options(self, to: str, text: str, options: list[dict]) -> None:
        """Invia un messaggio con opzioni selezionabili.

        L'implementazione di default degrada elegantemente a testo semplice,
        così un canale che non supporta i bottoni resta comunque usabile.
        """
        righe = [text] + [f"- {opt['title']}" for opt in options]
        await self.send_text(to, "\n".join(righe))


class MetaWhatsAppChannel(Channel):
    """WhatsApp tramite Cloud API di Meta (il canale di produzione)."""

    name = "whatsapp"
    supports_options = True

    async def send_text(self, to: str, text: str) -> None:
        from services.whatsapp_service import send_text_message

        await send_text_message(to, text)

    async def send_options(self, to: str, text: str, options: list[dict]) -> None:
        from services.whatsapp_service import (
            send_interactive_buttons,
            send_interactive_list,
        )

        if len(options) <= 3:
            bottoni = [{"id": o["id"], "title": o["title"]} for o in options]
            await send_interactive_buttons(to, text, bottoni)
        else:
            await send_interactive_list(to, text, "Scegli", options)


class WebChannel(Channel):
    """Widget di chat del sito: accumula la risposta e la restituisce al WebSocket."""

    name = "web"
    supports_options = True

    def __init__(self) -> None:
        self._testi: list[str] = []
        self._options: list[dict] | None = None

    async def send_text(self, to: str, text: str) -> None:
        self._testi.append(text)

    async def send_options(self, to: str, text: str, options: list[dict]) -> None:
        self._testi.append(text)
        self._options = [{"id": o["id"], "title": o["title"]} for o in options]

    def payload(self) -> dict:
        """Il dict che il WebSocket manda al browser."""
        return {"text": "\n\n".join(t for t in self._testi if t), "options": self._options}


class CollectorChannel(Channel):
    """Canale di test: non invia nulla, tiene traccia di quello che il bot direbbe."""

    name = "collector"
    supports_options = True

    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_text(self, to: str, text: str) -> None:
        self.messages.append({"to": to, "text": text, "options": None})

    async def send_options(self, to: str, text: str, options: list[dict]) -> None:
        self.messages.append({"to": to, "text": text, "options": options})

    @property
    def testi(self) -> list[str]:
        return [m["text"] for m in self.messages]

    def ultimo(self) -> dict | None:
        return self.messages[-1] if self.messages else None


class ConsoleChannel(Channel):
    """Canale del simulatore: stampa a terminale invece di inviare messaggi."""

    name = "console"
    supports_options = True

    async def send_text(self, to: str, text: str) -> None:
        print(f"\n\033[92mNadia\033[0m: {text}\n")

    async def send_options(self, to: str, text: str, options: list[dict]) -> None:
        print(f"\n\033[92mNadia\033[0m: {text}")
        for i, opt in enumerate(options, 1):
            print(f"   \033[94m[{i}]\033[0m {opt['title']}")
        print()
