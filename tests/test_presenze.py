"""Test sulle presenze settimanali degli operatori.

La regola che tiene insieme tutto: **chi non ha orari suoi lavora negli orari
del salone**. Senza, attivare la funzione avrebbe fatto sparire tutti gli
operatori insieme, perché "non ho ancora configurato niente" e "non lavora
mai" sarebbero la stessa tabella vuota.
"""

import pytest

from services.presenze import (
    e_in_salone,
    fasce_di,
    set_presenze_cache,
    solo_chi_e_in_salone,
)
from services.slots import ORARI_APERTURA

# Un martedì: gli orari iniziali lo danno aperto 9-19 continuato.
MARTEDI = "2026-08-11"
MERCOLEDI = "2026-08-12"


@pytest.fixture(autouse=True)
def presenze_pulite():
    """Ogni test parte da "nessuno ha orari suoi", come un salone appena
    aggiornato."""
    set_presenze_cache({})
    yield
    set_presenze_cache({})


# ------------------------------------------------- chi non è configurato


def test_senza_orari_suoi_valgono_quelli_del_salone():
    assert fasce_di("Francesco", 1) == ORARI_APERTURA[1]


def test_senza_orari_suoi_nessuno_slot_viene_scartato():
    """È la condizione dell'aggiornamento: finché il salone non tocca niente,
    il bot si comporta come prima."""
    slots = [
        {"slot": f"{MARTEDI}T09:00", "parrucchiere": "Francesco"},
        {"slot": f"{MARTEDI}T16:00", "parrucchiere": "Andrea"},
    ]

    assert solo_chi_e_in_salone(slots) == slots


# ------------------------------------------------------ chi ha orari suoi


def test_fuori_dalla_sua_fascia_l_operatore_sparisce():
    set_presenze_cache({"Francesco": {1: [("08:00", "12:00")]}})

    assert e_in_salone("Francesco", f"{MARTEDI}T09:00") is True
    assert e_in_salone("Francesco", f"{MARTEDI}T16:00") is False


def test_un_giorno_senza_fasce_vuol_dire_che_non_c_e():
    """Chi ha orari suoi e non ha righe per il mercoledì quel giorno non c'è —
    diverso da chi non ha orari suoi affatto."""
    set_presenze_cache({"Francesco": {1: [("08:00", "12:00")]}})

    assert e_in_salone("Francesco", f"{MERCOLEDI}T09:00") is False


def test_la_fine_della_fascia_non_e_prenotabile():
    """Alle 12:00 finisce il turno: un appuntamento che comincia lì sfora."""
    set_presenze_cache({"Francesco": {1: [("08:00", "12:00")]}})

    assert e_in_salone("Francesco", f"{MARTEDI}T11:30") is True
    assert e_in_salone("Francesco", f"{MARTEDI}T12:00") is False


def test_due_fasce_nello_stesso_giorno():
    set_presenze_cache(
        {"Andrea": {1: [("08:00", "12:00"), ("14:30", "19:30")]}}
    )

    assert e_in_salone("Andrea", f"{MARTEDI}T09:00") is True
    assert e_in_salone("Andrea", f"{MARTEDI}T13:00") is False
    assert e_in_salone("Andrea", f"{MARTEDI}T15:00") is True


def test_chi_ha_orari_suoi_non_tocca_gli_altri():
    set_presenze_cache({"Francesco": {1: [("08:00", "12:00")]}})

    slots = [
        {"slot": f"{MARTEDI}T16:00", "parrucchiere": "Francesco"},
        {"slot": f"{MARTEDI}T16:00", "parrucchiere": "Andrea"},
    ]

    assert solo_chi_e_in_salone(slots) == [
        {"slot": f"{MARTEDI}T16:00", "parrucchiere": "Andrea"}
    ]


# ------------------------------------------------------------- robustezza


def test_un_orario_illeggibile_non_fa_sparire_l_operatore():
    """Qui non si decide se una data è valida: toglierlo nasconderebbe
    l'errore vero, che sta a monte."""
    set_presenze_cache({"Francesco": {1: [("08:00", "12:00")]}})

    assert e_in_salone("Francesco", "domani mattina") is True
    assert e_in_salone("Francesco", "") is True


def test_uno_slot_senza_operatore_passa():
    assert solo_chi_e_in_salone([{"slot": f"{MARTEDI}T09:00"}]) == [
        {"slot": f"{MARTEDI}T09:00"}
    ]


# ------------------------------------------ il giro completo sulla ricerca


@pytest.mark.asyncio
async def test_la_ricerca_non_propone_chi_quel_giorno_non_c_e(backends):
    from services.conversation import execute_action

    from .conftest import prossimo_giorno_aperto

    giorno = prossimo_giorno_aperto()
    from datetime import date

    settimana = date.fromisoformat(giorno).weekday()
    # Solo Francesco ha orari suoi, e quel giorno non lavora.
    set_presenze_cache({"Francesco": {(settimana + 1) % 7: [("08:00", "12:00")]}})

    risultato = await execute_action(
        {"action": "CHECK_DISPONIBILITA", "data": giorno, "parrucchiere": None},
        "393331234567",
        {"stato_flusso": "scelta_slot", "dati_temp": {}},
        backends,
    )

    liberi = {n for riga in risultato["slots_disponibili"] for n in riga["liberi"]}
    assert "Francesco" not in liberi
    assert liberi, "gli altri operatori devono restare disponibili"


# ---------------------------------- gli orari del salone cambiano dal pannello


def test_chi_non_ha_orari_suoi_segue_quelli_cambiati(orari_del_salone):
    """La regola è "segue il salone", non "segue quello scritto nel codice".

    Leggere la costante iniziale invece della cache voleva dire che, cambiati
    gli orari dal pannello, gli operatori non configurati restavano sui vecchi
    — cioè quasi tutti, appena dopo l'aggiornamento.
    """
    orari_del_salone({1: [("10:00", "16:00")]})

    assert fasce_di("Francesco", 1) == [("10:00", "16:00")]


def test_chi_ha_orari_suoi_non_li_perde_se_il_salone_cambia(orari_del_salone):
    set_presenze_cache({"Francesco": {1: [("09:00", "12:00")]}})
    orari_del_salone({1: [("14:00", "19:00")]})

    assert fasce_di("Francesco", 1) == [("09:00", "12:00")]
