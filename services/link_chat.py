"""Il link che porta un cliente da WhatsApp alla chat del sito, già riconosciuto.

Serve a due cose insieme. Costa: dal 1° ottobre 2026 ogni risposta del bot su
WhatsApp si paga, mentre la chat del sito è gratuita — un messaggio solo con il
link ne risparmia i sei o sette che sarebbero seguiti. E si legge meglio: nel
browser gli orari stanno in una schermata invece che in una lista di bottoni.

**Nel link non c'è il numero di telefono, c'è un gettone.** Con il numero
scritto nell'indirizzo, chiunque avesse quel link *sarebbe* quel cliente: ne
vedrebbe gli appuntamenti e potrebbe disdirli. E i link si inoltrano, restano
nella cronologia del browser e nelle anteprime dei messaggi. È la stessa regola
per cui dal sito l'identità non arriva mai dalla pagina.

Il gettone ha tre proprietà, e servono tutte e tre:

- **casuale**, generato con `secrets` come il codice di verifica via email;
- **usa e getta**, bruciato al primo utilizzo: un link inoltrato al marito non
  apre gli appuntamenti della moglie;
- **a scadenza breve**, perché serve a continuare una conversazione in corso,
  non a fare da chiave permanente.

Lo consegna WhatsApp al numero del mittente, che il gestore telefonico ha già
verificato: è la stessa prova d'identità del codice via email, con un passaggio
in meno per il cliente.
"""

from __future__ import annotations

import logging
import secrets

logger = logging.getLogger(__name__)

# Quanto vive un gettone. Un quarto d'ora basta a chi sta scrivendo adesso e
# non lascia in giro una chiave utilizzabile domani.
DURATA_SECONDI = 15 * 60

_PREFISSO = "chat:link:"


def _chiave(gettone: str) -> str:
    return f"{_PREFISSO}{gettone}"


async def crea_gettone(redis, telefono: str) -> str | None:
    """Un gettone nuovo per questo numero. None se Redis non risponde.

    Il numero non compare mai nel gettone: sta solo dentro Redis, dove lo
    ritrova chi apre il link e nessun altro.
    """
    if not telefono or not redis:
        return None

    gettone = secrets.token_urlsafe(24)
    try:
        await redis.set(_chiave(gettone), telefono, ex=DURATA_SECONDI)
    except Exception:  # noqa: BLE001
        # Senza gettone il bot continua la conversazione su WhatsApp: è più
        # caro, non è rotto.
        logger.warning("Gettone per la chat non creato", exc_info=True)
        return None
    return gettone


async def consuma_gettone(redis, gettone: str) -> str | None:
    """Il numero associato al gettone, che da questo momento non vale più.

    La cancellazione avviene **prima** di restituire il numero: se il link
    viene aperto due volte insieme — l'anteprima del messaggio e il cliente —
    una sola delle due apre la sessione.
    """
    if not gettone or not redis:
        return None

    try:
        telefono = await redis.get(_chiave(gettone))
        if telefono is None:
            return None
        await redis.delete(_chiave(gettone))
    except Exception:  # noqa: BLE001
        logger.warning("Gettone della chat non verificabile", exc_info=True)
        return None

    return telefono


def indirizzo(gettone: str, base: str | None = None) -> str | None:
    """Il link da mandare al cliente. None senza un indirizzo pubblico.

    Senza `PUBLIC_BASE_URL` non si può comporre niente di cliccabile, e un
    link relativo dentro un messaggio WhatsApp non porta da nessuna parte.
    """
    from config import settings

    radice = (base if base is not None else settings.public_base_url or "").rstrip("/")
    if not radice or not gettone:
        return None
    return f"{radice}/chat/{gettone}"
