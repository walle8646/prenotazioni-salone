"""Test sugli orari di apertura e sulla generazione degli slot.

Importa da services.slots (logica pura) e non da calendar_service, così girano
anche senza le librerie Google installate.
"""

from datetime import datetime

from services.slots import FUSO_SALONE, generate_slots, is_open

MARTEDI = "2026-05-19"


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


# ------------------------------------------------- slot già passati o imminenti
#
# Un cliente che scriveva alle dieci di sera si sentiva proporre le otto del
# mattino dello stesso giorno: il salone in quella fascia è aperto, ma è già
# passata. L'istante è un parametro, così il test non dipende dall'orologio.


def test_gli_slot_gia_passati_non_vengono_proposti():
    sera = datetime(2026, 5, 19, 22, 0, tzinfo=FUSO_SALONE)
    assert generate_slots(MARTEDI, adesso=sera) == []


def test_restano_solo_gli_slot_ancora_da_venire():
    pomeriggio = datetime(2026, 5, 19, 15, 10, tzinfo=FUSO_SALONE)
    slots = generate_slots(MARTEDI, adesso=pomeriggio)

    assert slots[0] == "2026-05-19T15:30"
    assert "2026-05-19T09:00" not in slots
    assert slots[-1] == "2026-05-19T19:00"


def test_anticipo_minimo_rispettato():
    """Con due ore di anticipo richiesto non si prenota per il quarto d'ora dopo."""
    mattina = datetime(2026, 5, 19, 8, 0, tzinfo=FUSO_SALONE)
    slots = generate_slots(MARTEDI, adesso=mattina, anticipo_minimo_min=120)

    assert slots[0] == "2026-05-19T10:00"


def test_un_giorno_futuro_non_viene_toccato_dal_filtro():
    ieri = datetime(2026, 5, 18, 22, 0, tzinfo=FUSO_SALONE)
    assert generate_slots(MARTEDI, adesso=ieri) == generate_slots(MARTEDI)
