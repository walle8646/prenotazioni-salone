import pytest
from services.calendar_service import _generate_slots


def test_generate_slots_weekday():
    """Martedì-venerdì: mattina 08:00-12:00 + pomeriggio 14:30-19:30."""
    # Martedì 20 maggio 2026
    slots = _generate_slots("2026-05-19")  # martedì
    assert len(slots) > 0
    assert slots[0] == "2026-05-19T08:00"
    # Mattina: 08:00, 08:30, 09:00, ..., 11:30 = 8 slot
    # Pomeriggio: 14:30, 15:00, ..., 19:00 = 10 slot
    assert len(slots) == 18


def test_generate_slots_saturday():
    """Sabato: continuato 08:00-18:00."""
    # Sabato 23 maggio 2026
    slots = _generate_slots("2026-05-23")  # sabato
    assert len(slots) > 0
    assert slots[0] == "2026-05-23T08:00"
    # 08:00 a 17:30 = 20 slot
    assert len(slots) == 20


def test_generate_slots_sunday():
    """Domenica: chiuso."""
    slots = _generate_slots("2026-05-24")  # domenica
    assert len(slots) == 0


def test_generate_slots_monday():
    """Lunedì: chiuso."""
    slots = _generate_slots("2026-05-18")  # lunedì
    assert len(slots) == 0
