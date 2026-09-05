"""Quando ogni operatore è in salone.

Prima erano tutti disponibili in tutti gli orari di apertura, e chi quel
giorno non c'era si scopriva solo guardando il calendario: il cliente sceglieva
un nome e poi non trovava posto. Qui il salone dichiara le fasce di ciascuno, e
la disponibilità le rispetta.

**Chi non ha orari suoi lavora negli orari del salone.** È la regola che tiene
tranquillo l'aggiornamento: finché la receptionist non tocca niente, il bot si
comporta esattamente come prima. Distinguere i due casi richiede il flag
`orari_propri` sull'operatore, perché "non ho ancora configurato niente" e
"non lavora mai" sarebbero altrimenti la stessa tabella vuota — e attivare la
funzione avrebbe fatto sparire tutti insieme.

Come per listino e operatori, a runtime si legge una copia in memoria: il
motore conversazionale non conosce il database, e la copia si ricarica dopo
ogni modifica dal pannello.
"""

from __future__ import annotations

from services.slots import orari_salone

# nome operatore → {giorno della settimana: [(inizio, fine), ...]}
# Chi non compare qui dentro lavora negli orari del salone.
_cache: dict[str, dict[int, list[tuple[str, str]]]] = {}


def set_presenze_cache(presenze: dict[str, dict[int, list[tuple[str, str]]]]) -> None:
    """Sostituisce le presenze in memoria (all'avvio e dopo ogni modifica)."""
    global _cache
    _cache = presenze or {}


def presenze_note() -> dict[str, dict[int, list[tuple[str, str]]]]:
    """Le presenze attualmente in vigore, per nome."""
    return _cache


def fasce_di(nome: str, giorno: int) -> list[tuple[str, str]]:
    """Le fasce di un operatore in un giorno della settimana.

    Chi non ha orari suoi restituisce quelle del salone: è la condizione di
    partenza, non un caso limite.
    """
    suoi = _cache.get(nome)
    if suoi is None:
        return orari_salone().get(giorno, [])
    return suoi.get(giorno, [])


def e_in_salone(nome: str, quando: str) -> bool:
    """True se l'operatore è in salone a quell'istante ("2026-08-11T16:00")."""
    from datetime import datetime

    try:
        istante = datetime.strptime(quando, "%Y-%m-%dT%H:%M")
    except (TypeError, ValueError):
        # Un orario illeggibile è un problema di chi l'ha scritto: qui non si
        # decide, e togliere l'operatore nasconderebbe l'errore vero.
        return True

    ora = istante.strftime("%H:%M")
    return any(
        inizio <= ora < fine for inizio, fine in fasce_di(nome, istante.weekday())
    )


def solo_chi_e_in_salone(slots: list[dict]) -> list[dict]:
    """Scarta gli slot degli operatori che a quell'ora non ci sono.

    Si applica dopo Google e prima del raggruppamento: il calendario dice se
    l'operatore è occupato, non se quel giorno lavora.
    """
    return [
        slot
        for slot in slots
        if not slot.get("parrucchiere")
        or e_in_salone(slot["parrucchiere"], slot.get("slot") or "")
    ]
