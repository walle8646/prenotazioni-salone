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
import re

logger = logging.getLogger(__name__)


class Channel:
    """Interfaccia comune a tutti i canali."""

    name = "base"
    # I canali che sanno mostrare bottoni o liste cliccabili mettono True.
    supports_options = False
    # Lunghezza massima di un titolo cliccabile. None significa nessun limite:
    # è il caso del widget del sito, dove il bottone è un elemento HTML e può
    # contenere quello che vuole.
    lunghezza_massima_opzione: int | None = None

    def opzioni_sostenibili(self, options: list[dict]) -> bool:
        """True se questo canale può mostrare tutte le opzioni senza storpiarle."""
        limite = self.lunghezza_massima_opzione
        if limite is None:
            return True
        return all(len(o["title"]) <= limite for o in options)

    async def send_text(self, to: str, text: str) -> None:
        raise NotImplementedError

    async def send_options(self, to: str, text: str, options: list[dict]) -> None:
        """Invia un messaggio con opzioni selezionabili.

        L'implementazione di default degrada elegantemente a testo semplice,
        così un canale che non supporta i bottoni resta comunque usabile.
        """
        righe = [text] + [f"- {opt['title']}" for opt in options]
        await self.send_text(to, "\n".join(righe))


def _accorcia(testo: str, limite: int) -> str:
    if len(testo) <= limite:
        return testo
    return testo[: limite - 1].rstrip() + "…"


def _accorcia_ai_separatori(testo: str, limite: int) -> str:
    """Come `_accorcia`, ma taglia dove finisce un pezzo dell'informazione.

    "Taglio + ... — 45,00 € — 1 ora" sfora di sei caratteri: tagliarlo di
    netto lascerebbe un trattino sospeso, e questa riga non serve solo a
    leggere, è quella che torna indietro quando il cliente la tocca.
    """
    if len(testo) <= limite:
        return testo
    separatori = [m.start() for m in re.finditer(r"\s[—–-]\s", testo)]
    validi = [pos for pos in separatori if pos <= limite]
    if validi:
        return testo[: validi[-1]].rstrip()
    return _accorcia(testo, limite)


class MetaWhatsAppChannel(Channel):
    """WhatsApp tramite Cloud API di Meta (il canale di produzione)."""

    name = "whatsapp"
    supports_options = True
    # Un bottone ha il solo titolo, lungo al massimo 20 caratteri. Se non ci
    # sta per intero tornerebbe indietro tagliato nella risposta del cliente, e
    # il listino non lo riconoscerebbe più: meglio rinunciare ai bottoni.
    lunghezza_massima_opzione = 20
    # Una riga di lista concede 24 caratteri al titolo, ma ne ha altri 72 per
    # la descrizione, che Meta ci restituisce insieme alla scelta. Lì la voce
    # sta per intero, quindi il titolo si può accorciare senza perdere nulla.
    LUNGHEZZA_TITOLO_RIGA = 24
    LUNGHEZZA_DESCRIZIONE_RIGA = 72
    MASSIMO_RIGHE = 10

    def _come_lista(self, options: list[dict]) -> bool:
        # Fino a tre scelte Meta vuole i bottoni, oltre serve una lista.
        return len(options) > 3

    def opzioni_sostenibili(self, options: list[dict]) -> bool:
        if not self._come_lista(options):
            return super().opzioni_sostenibili(options)
        # Oltre la decima riga Meta scarta le altre in silenzio: al cliente
        # resterebbero scelte che ha letto nel messaggio e non può toccare.
        return len(options) <= self.MASSIMO_RIGHE

    def _riga(self, opzione: dict) -> dict:
        titolo = _accorcia(opzione["title"], self.LUNGHEZZA_TITOLO_RIGA)
        descrizione = opzione.get("description") or ""
        if titolo != opzione["title"] and not descrizione:
            # Senza descrizione, di una voce accorciata tornerebbe indietro
            # solo il troncone: la voce per intero deve stare da qualche parte.
            descrizione = opzione["title"]
        return {
            "id": opzione["id"],
            "title": titolo,
            "description": _accorcia_ai_separatori(
                descrizione, self.LUNGHEZZA_DESCRIZIONE_RIGA
            ),
        }

    async def send_text(self, to: str, text: str) -> None:
        from services.whatsapp_service import send_text_message

        await send_text_message(to, text)

    async def send_options(self, to: str, text: str, options: list[dict]) -> None:
        from services.whatsapp_service import (
            send_interactive_buttons,
            send_interactive_list,
        )

        if not self._come_lista(options):
            bottoni = [{"id": o["id"], "title": o["title"]} for o in options]
            await send_interactive_buttons(to, text, bottoni)
        else:
            righe = [self._riga(o) for o in options]
            await send_interactive_list(to, text, "Scegli", righe)


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
