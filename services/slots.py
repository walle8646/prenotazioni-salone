"""Generazione degli slot orari del salone.

Logica pura: dipende solo da datetime e dalla configurazione, non da Google
Calendar. Sta in un modulo separato per poter essere usata (e testata) anche
dove le librerie Google non sono installate — per esempio nel simulatore
offline e nei test automatici.
"""

from datetime import datetime, timedelta

from config import settings

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


def generate_slots(date_str: str) -> list[str]:
    """Restituisce tutti gli slot teorici di una data, es. ['2026-05-19T08:00', ...].

    Non tiene conto delle prenotazioni già esistenti né delle chiusure
    straordinarie: dice solo quando il salone sarebbe aperto.
    """
    date = datetime.strptime(date_str, "%Y-%m-%d")
    ranges = ORARI_APERTURA.get(date.weekday(), [])

    slots: list[str] = []
    for start_s, end_s in ranges:
        start = datetime.strptime(f"{date_str} {start_s}", "%Y-%m-%d %H:%M")
        end = datetime.strptime(f"{date_str} {end_s}", "%Y-%m-%d %H:%M")
        current = start
        while current + timedelta(minutes=settings.slot_duration_min) <= end:
            slots.append(current.strftime("%Y-%m-%dT%H:%M"))
            current += timedelta(minutes=settings.slot_duration_min)
    return slots


def is_open(date_str: str) -> bool:
    """True se il salone è aperto in quella data (esclusi giorni di chiusura straordinaria)."""
    return bool(generate_slots(date_str))
