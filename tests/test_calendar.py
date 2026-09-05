"""Test sugli orari di apertura e sulla generazione degli slot.

Importa da services.slots (logica pura) e non da calendar_service, così girano
anche senza le librerie Google installate.
"""

from datetime import datetime

from services.slots import FUSO_SALONE, generate_slots, is_open

MARTEDI = "2026-05-19"


def test_generate_slots_weekday():
    """Martedì-sabato: orario continuato 09:00-19:00."""
    slots = generate_slots("2026-05-19")  # martedì
    assert slots[0] == "2026-05-19T09:00"
    # 09:00 → 18:30 a mezz'ora l'uno.
    assert len(slots) == 20
    assert slots[-1] == "2026-05-19T18:30"  # ultimo slot che finisce entro le 19
    assert "2026-05-19T13:00" in slots, "il salone non chiude a mezzogiorno"
    assert "2026-05-19T08:30" not in slots  # prima dell'apertura
    assert "2026-05-19T19:00" not in slots  # finirebbe dopo la chiusura


def test_generate_slots_saturday():
    """Il sabato ha lo stesso orario degli altri giorni di apertura."""
    sabato = generate_slots("2026-05-23")
    assert sabato[0] == "2026-05-23T09:00"
    assert sabato[-1] == "2026-05-23T18:30"
    assert len(sabato) == len(generate_slots("2026-05-19"))


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
    assert slots[-1] == "2026-05-19T18:30"


def test_anticipo_minimo_rispettato():
    """Con due ore di anticipo richiesto non si prenota per il quarto d'ora dopo."""
    mattina = datetime(2026, 5, 19, 8, 0, tzinfo=FUSO_SALONE)
    slots = generate_slots(MARTEDI, adesso=mattina, anticipo_minimo_min=120)

    assert slots[0] == "2026-05-19T10:00"


def test_un_giorno_futuro_non_viene_toccato_dal_filtro():
    ieri = datetime(2026, 5, 18, 22, 0, tzinfo=FUSO_SALONE)
    assert generate_slots(MARTEDI, adesso=ieri) == generate_slots(MARTEDI)


# ------------------------------------------------- orari cambiati dal pannello
#
# Gli orari non sono più una costante: vivono in tabella e il pannello li
# cambia. Qui si verifica che chi genera gli slot legga davvero quelli in
# vigore, perché è l'unico punto in cui un errore si vede come "il bot dà
# appuntamenti a salone chiuso".


def test_gli_slot_seguono_gli_orari_in_vigore(orari_del_salone):
    orari_del_salone({1: [("10:00", "13:00")]})

    slots = generate_slots(MARTEDI)

    assert slots[0] == "2026-05-19T10:00"
    assert slots[-1] == "2026-05-19T12:30"
    assert len(slots) == 6


def test_un_giorno_tolto_dagli_orari_diventa_chiuso(orari_del_salone):
    orari_del_salone({5: [("09:00", "19:00")]})  # aperto solo il sabato

    assert generate_slots(MARTEDI) == []
    assert is_open(MARTEDI) is False


def test_una_chiusura_straordinaria_svuota_la_giornata(chiusure_del_salone):
    """Vale più dell'orario settimanale: è per questo che esiste."""
    assert is_open(MARTEDI) is True

    chiusure_del_salone({MARTEDI})

    assert generate_slots(MARTEDI) == []
    assert is_open(MARTEDI) is False


def test_una_chiusura_non_tocca_gli_altri_giorni(chiusure_del_salone):
    chiusure_del_salone({MARTEDI})

    assert is_open("2026-05-20") is True  # il mercoledì apre lo stesso


# ------------------------------------------------------- orari detti a parole


def test_i_giorni_uguali_si_accorpano():
    from services.slots import orari_in_parole

    assert orari_in_parole() == "martedì-sabato 09:00-19:00"


def test_un_orario_spezzato_si_legge_intero():
    from services.slots import orari_in_parole

    detto = orari_in_parole({1: [("08:00", "12:00"), ("14:30", "19:30")]})
    assert detto == "martedì 08:00-12:00 e 14:30-19:30"


def test_il_weekend_lungo_non_si_spezza_in_due():
    """Chiuso domenica e lunedì è una cosa sola, non due righe lontane."""
    from services.slots import orari_a_coppie

    assert orari_a_coppie()["domenica-lunedì"] == "Chiuso"
