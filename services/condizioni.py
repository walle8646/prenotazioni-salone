"""L'avviso sulle condizioni, prima che il cliente confermi.

Lo mette il codice e non il modello, per la stessa ragione per cui ce lo mette
per "Indifferente": il prompt viene rispettato quasi sempre, e "quasi" non
basta per una cosa che deve esserci tutte le volte. Qui in piu' c'e' che a
mancare sarebbe proprio l'informazione da dare prima di raccogliere i dati di
qualcuno.

Arriva **prima** del riepilogo e non dopo. Un avviso che compare sotto ai
bottoni si tocca prima di leggerlo, e dire dopo quello che andava detto prima
vale come non averlo detto.

E va in un messaggio suo, non in coda al riepilogo. Due motivi, tutti e due
pratici: il testo del riepilogo su WhatsApp viaggia dentro un messaggio
interattivo, dove un indirizzo non e' detto che si possa toccare, e
`deliver()` ricava i bottoni leggendo le righe del testo — una riga in piu'
rischierebbe di diventare un bottone.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

PERCORSO = "/condizioni"

# Il cliente ha scelto tutto: il prossimo messaggio del bot e' il riepilogo da
# confermare. Sono le stesse chiavi delle fasi in `conversation.py`.
_DATI_COMPLETI = ("servizio", "slot", "parrucchiere")

TESTO = (
    "Prima di confermare: prenotando accetti le condizioni del servizio e "
    "l'informativa sui dati personali.\n{link}"
)


def indirizzo() -> str | None:
    """L'indirizzo pubblico della pagina, se l'applicazione ne ha uno.

    In locale non c'e' e non si manda nessun avviso: un avviso senza link non
    informa nessuno, e mandarlo servirebbe solo a sembrare in regola.
    """
    from config import settings

    base = (settings.public_base_url or "").rstrip("/")
    if not base:
        return None
    return f"{base}{PERCORSO}"


def frase() -> str | None:
    """L'avviso da mandare, o None se non c'e' un indirizzo da dare."""
    link = indirizzo()
    if not link:
        logger.info("PUBLIC_BASE_URL non configurata: avviso condizioni non inviato")
        return None
    return TESTO.format(link=link)


def serve_avviso(session: dict) -> bool:
    """Se questo e' il momento di avvisare, e non lo si e' gia' fatto.

    Vero quando il cliente ha gia' scelto servizio, orario e operatore: da li'
    il passo successivo e' confermare. Una volta sola per conversazione —
    ripeterlo a ogni messaggio sarebbe rumore, e il rumore si smette di
    leggerlo.
    """
    if not session or session.get("condizioni_avvisate"):
        return False
    dati = session.get("dati_temp") or {}
    return all(dati.get(chiave) for chiave in _DATI_COMPLETI)
