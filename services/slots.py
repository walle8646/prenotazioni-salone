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

# Orari di apertura per giorno della settimana (0 = lunedì ... 6 = domenica).
# Una lista vuota significa chiuso.
ORARI_APERTURA: dict[int, list[tuple[str, str]]] = {
    0: [],                                      # lunedì: chiuso
    1: [("08:00", "12:00"), ("14:30", "19:30")],  # martedì
    2: [("08:00", "12:00"), ("14:30", "19:30")],  # mercoledì
    3: [("08:00", "12:00"), ("14:30", "19:30")],  # giovedì
    4: [("08:00", "12:00"), ("14:30", "19:30")],  # venerdì
    5: [("08:00", "18:00")],                    # sabato: orario continuato
    6: [],                                      # domenica: chiuso
}


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
    date = datetime.strptime(date_str, "%Y-%m-%d")
    ranges = ORARI_APERTURA.get(date.weekday(), [])

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
