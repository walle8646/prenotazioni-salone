"""Operatori del salone e collegamento con i calendari Google.

I nomi sono quelli forniti dal salone. Ogni operatore ha bisogno di un proprio
calendario Google condiviso con il service account: l'associazione nome →
calendar ID si configura con la variabile d'ambiente GCAL_PARRUCCHIERE_IDS,
scritta come oggetto JSON, per esempio:

    GCAL_PARRUCCHIERE_IDS={"Simone Big":"abc...@group.calendar.google.com", ...}

Finché un operatore non ha un calendario configurato il sistema gli assegna un
identificativo segnaposto: il simulatore e i test funzionano lo stesso, mentre
in produzione l'avvio scrive un avviso nei log e le chiamate a Google
falliscono in modo esplicito, invece di scrivere sul calendario sbagliato.
"""

from __future__ import annotations

import logging
import re

from config import settings

logger = logging.getLogger(__name__)

OPERATORI: tuple[str, ...] = (
    "Simone Big",
    "Simone Jr",
    "Francesco",
    "Andrea",
    "Giava",
    "Bario",
)

PREFISSO_NON_CONFIGURATO = "da-configurare-"


def _slug(nome: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", nome.lower()).strip("-")


def mappa_calendari() -> dict[str, str]:
    """Restituisce nome operatore → calendar ID, per tutti gli operatori."""
    configurati = settings.parrucchiere_calendar_map
    return {
        nome: configurati.get(nome) or f"{PREFISSO_NON_CONFIGURATO}{_slug(nome)}"
        for nome in OPERATORI
    }


def senza_calendario() -> list[str]:
    """Operatori per cui manca ancora il calendar ID."""
    return [
        nome
        for nome, cal_id in mappa_calendari().items()
        if cal_id.startswith(PREFISSO_NON_CONFIGURATO)
    ]


def verifica_configurazione() -> None:
    """Scrive nei log lo stato della configurazione dei calendari."""
    mancanti = senza_calendario()
    if not mancanti:
        logger.info("Calendari configurati per tutti i %s operatori", len(OPERATORI))
        return
    logger.warning(
        "Calendario Google non configurato per: %s. "
        "Le prenotazioni con questi operatori falliranno finché non imposti "
        "GCAL_PARRUCCHIERE_IDS con i rispettivi calendar ID.",
        ", ".join(mancanti),
    )
