"""Generazione degli slot orari del salone.

Logica pura: dipende solo da datetime e dalla configurazione, non da Google
Calendar. Sta in un modulo separato per poter essere usata (e testata) anche
dove le librerie Google non sono installate — per esempio nel simulatore
offline e nei test automatici.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from config import settings

# Il salone vive in un fuso solo. Tenerlo qui, invece di scrivere l'offset a
# mano, è ciò che fa reggere i conti anche dopo il cambio dell'ora.
FUSO_SALONE = ZoneInfo("Europe/Rome")


def adesso_salone() -> datetime:
    """L'ora corrente nel fuso del salone."""
    return datetime.now(FUSO_SALONE)

# Orari con cui la tabella viene riempita al primo avvio. A runtime valgono
# quelli del database, che il pannello può cambiare: qui restano come valori
# iniziali e come ripiego per test e simulatore, esattamente come il listino
# in `services/catalogo.py`.
#
# 0 = lunedì ... 6 = domenica. Una lista vuota significa chiuso.
ORARI_APERTURA: dict[int, list[tuple[str, str]]] = {
    0: [],                        # lunedì: chiuso
    1: [("09:00", "19:00")],      # martedì
    2: [("09:00", "19:00")],      # mercoledì
    3: [("09:00", "19:00")],      # giovedì
    4: [("09:00", "19:00")],      # venerdì
    5: [("09:00", "19:00")],      # sabato
    6: [],                        # domenica: chiuso
}

NOMI_GIORNI = (
    "lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica",
)

# La copia in memoria che vale davvero. `None` vuol dire "il database non ha
# ancora parlato": si usano gli orari iniziali, che è la condizione di test e
# simulatore. Un dizionario vuoto invece è una risposta vera, e vuol dire
# chiuso sempre.
_orari: dict[int, list[tuple[str, str]]] | None = None

# Le date in cui il salone è chiuso pur essendo un giorno di apertura: feste,
# ferie, la settimana di agosto. In formato "2026-08-15".
_chiusure: set[str] = set()


def set_orari_salone(orari: dict[int, list[tuple[str, str]]] | None) -> None:
    """Sostituisce gli orari in vigore (all'avvio e dopo ogni modifica)."""
    global _orari
    _orari = orari


def orari_salone() -> dict[int, list[tuple[str, str]]]:
    """Gli orari in vigore adesso."""
    return ORARI_APERTURA if _orari is None else _orari


def set_chiusure(date: set[str] | list[str] | None) -> None:
    """Sostituisce l'elenco delle chiusure straordinarie."""
    global _chiusure
    _chiusure = set(date or ())


def chiusure() -> set[str]:
    """Le date di chiusura straordinaria in vigore."""
    return _chiusure


def orari_in_parole(orari: dict[int, list[tuple[str, str]]] | None = None) -> str:
    """Gli orari come li direbbe una persona: "martedì-sabato 9:00-19:00".

    I giorni consecutivi con le stesse fasce si accorpano. Serve al prompt, che
    deve dire a voce la stessa cosa che la disponibilità propone: scritti a mano
    in due posti, prima o poi divergono e il bot promette un orario in cui il
    salone è chiuso.
    """
    orari = orari_salone() if orari is None else orari

    gruppi: list[tuple[list[int], list[tuple[str, str]]]] = []
    for giorno in range(7):
        fasce = list(orari.get(giorno, []))
        if not fasce:
            continue
        if gruppi and gruppi[-1][1] == fasce and gruppi[-1][0][-1] == giorno - 1:
            gruppi[-1][0].append(giorno)
        else:
            gruppi.append(([giorno], fasce))

    if not gruppi:
        return "chiuso tutti i giorni"

    pezzi = []
    for giorni, fasce in gruppi:
        if len(giorni) == 1:
            quando = NOMI_GIORNI[giorni[0]]
        else:
            quando = f"{NOMI_GIORNI[giorni[0]]}-{NOMI_GIORNI[giorni[-1]]}"
        ore = " e ".join(f"{d}-{a}" for d, a in fasce)
        pezzi.append(f"{quando} {ore}")
    return ", ".join(pezzi)


def generate_slots(
    date_str: str,
    adesso: datetime | None = None,
    anticipo_minimo_min: int = 0,
) -> list[str]:
    """Restituisce tutti gli slot teorici di una data, es. ['2026-05-19T08:00', ...].

    Non tiene conto delle prenotazioni già esistenti né delle chiusure
    straordinarie: dice solo quando il salone sarebbe aperto.

    Passando `adesso` vengono scartati gli slot già trascorsi e quelli troppo
    imminenti (`anticipo_minimo_min`). Senza quel filtro, un cliente che scrive
    alle dieci di sera si sentiva proporre le otto del mattino dello stesso
    giorno: il salone è aperto in quella fascia, ma è già passata.

    Il parametro è esplicito e non è l'orologio di sistema, così la funzione
    resta pura e verificabile con un istante fissato.
    """
    # Una chiusura straordinaria vale più dell'orario settimanale: è proprio
    # per dire "quel giorno no" che esiste. Sta qui e non nel chiamante perché
    # tutto il resto passa da questa funzione — `is_open()` compreso — e un
    # controllo in più altrove sarebbe uno da dimenticare.
    if date_str in _chiusure:
        return []

    date = datetime.strptime(date_str, "%Y-%m-%d")
    ranges = orari_salone().get(date.weekday(), [])

    limite = None
    if adesso is not None:
        if adesso.tzinfo is None:
            adesso = adesso.replace(tzinfo=FUSO_SALONE)
        limite = adesso + timedelta(minutes=anticipo_minimo_min)

    slots: list[str] = []
    for start_s, end_s in ranges:
        start = datetime.strptime(f"{date_str} {start_s}", "%Y-%m-%d %H:%M")
        end = datetime.strptime(f"{date_str} {end_s}", "%Y-%m-%d %H:%M")
        current = start
        while current + timedelta(minutes=settings.slot_duration_min) <= end:
            if limite is None or current.replace(tzinfo=FUSO_SALONE) >= limite:
                slots.append(current.strftime("%Y-%m-%dT%H:%M"))
            current += timedelta(minutes=settings.slot_duration_min)
    return slots


def is_open(date_str: str) -> bool:
    """True se il salone è aperto in quella data (esclusi giorni di chiusura straordinaria)."""
    return bool(generate_slots(date_str))


def orari_a_coppie(
    orari: dict[int, list[tuple[str, str]]] | None = None,
) -> dict[str, str]:
    """Gli orari come li mostra il sito: etichetta → orario.

    Es. {"martedì-sabato": "09:00-19:00", "domenica-lunedì": "Chiuso"}.

    I giorni di chiusura a cavallo della domenica si accorpano: leggere
    "lunedì: chiuso" in cima e "domenica: chiuso" in fondo, con in mezzo i
    giorni aperti, fa sembrare due cose diverse quello che è un weekend lungo.
    """
    orari = orari_salone() if orari is None else orari

    gruppi: list[tuple[list[int], list[tuple[str, str]]]] = []
    for giorno in range(7):
        fasce = list(orari.get(giorno, []))
        if gruppi and gruppi[-1][1] == fasce:
            gruppi[-1][0].append(giorno)
        else:
            gruppi.append(([giorno], fasce))

    # La settimana è un cerchio: se il primo e l'ultimo gruppo dicono la stessa
    # cosa sono lo stesso gruppo, spezzato solo da dove abbiamo iniziato a
    # contare.
    if len(gruppi) > 1 and gruppi[0][1] == gruppi[-1][1]:
        ultimo = gruppi.pop()
        gruppi[0] = (ultimo[0] + gruppi[0][0], gruppi[0][1])

    coppie: dict[str, str] = {}
    for giorni, fasce in gruppi:
        if len(giorni) == 1:
            etichetta = NOMI_GIORNI[giorni[0]]
        else:
            etichetta = f"{NOMI_GIORNI[giorni[0]]}-{NOMI_GIORNI[giorni[-1]]}"
        coppie[etichetta] = (
            " / ".join(f"{d}-{a}" for d, a in fasce) if fasce else "Chiuso"
        )
    return coppie
