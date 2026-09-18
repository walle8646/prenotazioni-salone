"""Notifiche sul telefono di chi lavora in salone.

Servono a una cosa sola: quando un cliente chiede di parlare con una persona,
il bot tace e lui aspetta. L'email c'era già, ma la posta si guarda la sera.
Una notifica arriva mentre il cliente sta ancora scrivendo.

Sono notifiche **di servizio fra noi e il salone**, non messaggi ai clienti:
non passano da WhatsApp e non costano niente.

Due scelte che valgono la pena di essere capite.

**Un invio fallito non è un errore da propagare.** Chi manda la notifica sta
facendo altro — sta passando una conversazione a una persona — e quella cosa
deve riuscire comunque. Qui dentro non esce mai un'eccezione.

**Un'iscrizione rifiutata si cancella.** Quando un telefono disinstalla
l'applicazione o revoca il permesso, il servizio push risponde 404 o 410: è
definitivo, e tenerla vorrebbe dire ritentare per sempre verso un telefono che
non c'è più.
"""

from __future__ import annotations

import asyncio
import json
import logging

logger = logging.getLogger(__name__)

# Il servizio push risponde così quando l'iscrizione non vale più: non è un
# guasto temporaneo, è un telefono che non la vuole più.
_SCADUTE = (404, 410)


def configurato() -> bool:
    """Se le chiavi ci sono. Senza, la funzione non si offre nemmeno."""
    from config import settings

    return bool(settings.vapid_public_key and settings.vapid_private_key)


def chiave_pubblica() -> str:
    from config import settings

    return settings.vapid_public_key


def _manda_una(iscrizione: dict, contenuto: str) -> int | None:
    """Manda a un dispositivo. Restituisce il codice se va rifiutata, altrimenti None."""
    from pywebpush import WebPushException, webpush

    from config import settings

    try:
        webpush(
            subscription_info={
                "endpoint": iscrizione["endpoint"],
                "keys": {"p256dh": iscrizione["p256dh"], "auth": iscrizione["auth"]},
            },
            data=contenuto,
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={
                "sub": settings.vapid_subject or "mailto:salone@example.invalid"
            },
            timeout=10,
        )
        return None
    except WebPushException as errore:
        stato = getattr(errore.response, "status_code", None)
        if stato in _SCADUTE:
            return stato
        logger.warning("Notifica non consegnata: %s", str(errore)[:200])
        return None
    except Exception:  # noqa: BLE001
        logger.warning("Notifica non consegnata", exc_info=True)
        return None


async def avvisa(titolo: str, testo: str, url: str = "/admin/conversazioni") -> int:
    """Manda la notifica a tutti i telefoni iscritti. Restituisce quanti l'hanno avuta.

    Le iscrizioni che il servizio push rifiuta come scadute vengono tolte:
    altrimenti a ogni notifica si riproverebbe verso telefoni che non
    esistono più, e il conto delle consegne direbbe il falso.
    """
    if not configurato():
        return 0

    from services.db_service import iscrizioni_push, togli_iscrizione_push

    try:
        iscritti = await iscrizioni_push()
    except Exception:  # noqa: BLE001
        logger.warning("Iscrizioni push non leggibili", exc_info=True)
        return 0

    if not iscritti:
        return 0

    contenuto = json.dumps({"titolo": titolo, "testo": testo, "url": url})

    # `webpush` è sincrona e fa una chiamata di rete: in un thread, altrimenti
    # blocca il ciclo degli eventi mentre il cliente aspetta una risposta.
    esiti = await asyncio.gather(
        *(asyncio.to_thread(_manda_una, i, contenuto) for i in iscritti)
    )

    consegnate = 0
    for iscrizione, scaduta in zip(iscritti, esiti):
        if scaduta:
            try:
                await togli_iscrizione_push(iscrizione["endpoint"])
            except Exception:  # noqa: BLE001
                logger.warning("Iscrizione scaduta non rimossa", exc_info=True)
        else:
            consegnate += 1

    logger.info("Notifica inviata a %s dispositivi su %s", consegnate, len(iscritti))
    return consegnate
