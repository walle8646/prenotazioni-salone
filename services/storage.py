"""Salvataggio dei file inviati dai clienti (le foto di riferimento).

Le foto arrivano da WhatsApp come byte grezzi. Nel database salviamo solo il
percorso del file, mai il contenuto: la colonna foto_riferimento è di testo e
il database non è il posto giusto per le immagini.

I file finiscono sotto static/foto/ e sono raggiungibili dal browser, così la
receptionist può aprirli dalla scheda del cliente.

Nota per la produzione: su Render il disco è effimero e si azzera a ogni deploy.
Va bene per iniziare; se le foto diventano importanti, questo è l'unico punto da
cambiare per spostarle su uno storage esterno (S3, Cloudflare R2, Google Cloud
Storage).
"""

from __future__ import annotations

import logging
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)

CARTELLA_FOTO = Path("static/foto")
URL_BASE = "/static/foto"


def _estensione(contenuto: bytes) -> str:
    """Riconosce il formato dai primi byte del file."""
    if contenuto.startswith(b"\x89PNG"):
        return ".png"
    if contenuto.startswith(b"GIF8"):
        return ".gif"
    if contenuto[:4] == b"RIFF" and contenuto[8:12] == b"WEBP":
        return ".webp"
    return ".jpg"


def salva_foto(contenuto: bytes, prefisso: str = "foto") -> str | None:
    """Salva l'immagine su disco e restituisce l'URL da mettere nel database."""
    if not contenuto:
        return None
    try:
        CARTELLA_FOTO.mkdir(parents=True, exist_ok=True)
        nome = f"{prefisso}_{uuid4().hex[:12]}{_estensione(contenuto)}"
        (CARTELLA_FOTO / nome).write_bytes(contenuto)
        return f"{URL_BASE}/{nome}"
    except OSError:
        logger.exception("Impossibile salvare la foto del cliente")
        return None
