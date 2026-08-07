"""Test sugli orari di apertura e sulla generazione degli slot.

Importa da services.slots (logica pura) e non da calendar_service, così girano
anche senza le librerie Google installate.
"""

from services.slots import generate_slots, is_open


def test_generate_slots_weekday():
    """Martedì-venerdì: mattina 08:00-12:00 + pomeriggio 14:30-19:30."""
    slots = generate_slots("2026-05-19")  # martedì
    assert slots[0] == "2026-05-19T08:00"
    # Mattina: 08:00 → 11:30 = 8 slot. Pomeriggio: 14:30 → 19:00 = 10 slot.
    assert len(slots) == 18
    assert "2026-05-19T12:00" not in slots  # la mattina finisce alle 12
    assert "2026-05-19T14:00" not in slots  # il pomeriggio inizia alle 14:30
    assert slots[-1] == "2026-05-19T19:00"  # ultimo slot che finisce entro le 19:30


def test_generate_slots_saturday():
    """Sabato: orario continuato 08:00-18:00."""
    slots = generate_slots("2026-05-23")  # sabato
    assert slots[0] == "2026-05-23T08:00"
    assert slots[-1] == "2026-05-23T17:30"
    assert len(slots) == 20
    assert "2026-05-23T13:00" in slots  # il sabato non c'è pausa pranzo


def test_generate_slots_sunday():
    """Domenica: chiuso."""
    assert generate_slots("2026-05-24") == []


def test_generate_slots_monday():
    """Lunedì: chiuso."""
    assert generate_slots("2026-05-18") == []


def test_is_open():
    assert is_open("2026-05-19") is True
    assert is_open("2026-05-18") is False
