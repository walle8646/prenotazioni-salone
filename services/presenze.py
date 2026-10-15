"""Quando ogni operatore è in salone, e quando invece non c'è.

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

**Le assenze di piu' giorni stanno qui e non in una tabella a parte di
schermata**: ferie, malattia, un corso sono le date in cui le fasce
settimanali non valgono, cioe' la stessa domanda — "quel giorno c'e'?" — vista
dall'altra parte. Tenerle fuori vorrebbe dire due moduli che rispondono alla
stessa cosa, e prima o poi uno dei due risponderebbe di si'.

Come per listino e operatori, a runtime si legge una copia in memoria: il
motore conversazionale non conosce il database, e la copia si ricarica dopo
ogni modifica dal pannello.
"""

from __future__ import annotations

from services.slots import orari_salone

# nome operatore → {giorno della settimana: [(inizio, fine), ...]}
# Chi non compare qui dentro lavora negli orari del salone.
_cache: dict[str, dict[int, list[tuple[str, str]]]] = {}

# nome operatore → ((dal, al), ...) in ISO, estremi compresi: ferie, malattia,
# un corso. Sono le date in cui gli orari qui sopra non valgono.
_assenze: dict[str, tuple[tuple[str, str], ...]] = {}


def set_presenze_cache(presenze: dict[str, dict[int, list[tuple[str, str]]]]) -> None:
    """Sostituisce le presenze in memoria (all'avvio e dopo ogni modifica)."""
    global _cache
    _cache = presenze or {}


def presenze_note() -> dict[str, dict[int, list[tuple[str, str]]]]:
    """Le presenze attualmente in vigore, per nome."""
    return _cache


def set_assenze_cache(assenze: dict[str, list[tuple[str, str]]]) -> None:
    """Sostituisce i periodi di assenza in memoria (all'avvio e a ogni modifica).

    Come le fasce, e per lo stesso motivo: la domanda "quel giorno c'e'?" si fa
    per ogni slot di ogni ricerca, e una query per slot si paga per sempre.
    """
    global _assenze
    _assenze = {
        nome: tuple((dal, al) for dal, al in periodi)
        for nome, periodi in (assenze or {}).items()
    }


def assenze_note() -> dict[str, tuple[tuple[str, str], ...]]:
    """I periodi di assenza in vigore, per nome."""
    return _assenze


def copre(periodi, giorno: str) -> bool:
    """Se uno dei periodi contiene quel giorno (tutto in ISO).

    Gli estremi sono **compresi**: "dal 20 al 24" sono cinque giorni, come li
    direbbe chiunque in salone. Il confronto e' fra stringhe perche' in ISO
    l'ordine alfabetico e' quello delle date, e una conversione in piu' per
    ogni slot di ogni ricerca si pagherebbe tutti i giorni.
    """
    return any(dal <= giorno <= al for dal, al in periodi or ())


def non_c_e(nome: str, giorno: str) -> bool:
    """Se quel giorno l'operatore e' in ferie, malato o comunque assente."""
    return copre(_assenze.get(nome), giorno)


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

    # Le ferie vengono prima degli orari: sono le date in cui gli orari di
    # tutte le settimane non valgono. Qui e non nei chiamanti perche' questa
    # funzione e' l'unico posto che risponde a "quel giorno lavora": da lei
    # passano la disponibilita' del bot, il verde del pannello, la griglia
    # della giornata e quella della settimana. Messa altrove, una delle
    # quattro continuerebbe a dare appuntamenti a chi e' al mare.
    if non_c_e(nome, istante.date().isoformat()):
        return False

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
