"""Test sullo strumento che riempie l'agenda di appuntamenti finti.

Non è codice di produzione, ma sbagliarlo costa caro lo stesso: scrive sui
calendari veri e nel database vero, e un difetto lo si scopre con duemila
eventi già dentro. Qui si prova la parte che decide — quella pura — prima che
tocchi qualcosa.
"""

import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from random import Random

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from dati_di_prova import (  # noqa: E402
    DOMINIO_EMAIL,
    PREFISSO_TELEFONO,
    _clienti_per,
    _giorni_aperti,
    _piano,
)

OGGI = date(2026, 9, 5)
DA = date(2026, 9, 1)
A = date(2026, 10, 31)
OPERATORI = ["Simone Big", "Simone Jr", "Francesco", "Andrea", "Giava", "Bario"]


@pytest.fixture
def agenda():
    giorni = _giorni_aperti(DA, A)
    appuntamenti = _piano(giorni, OPERATORI, 0.45, Random(7))
    return giorni, appuntamenti, _clienti_per(appuntamenti, Random(7), OGGI)


def test_si_riempiono_solo_i_giorni_di_apertura(agenda):
    giorni, _, _ = agenda
    for giorno in giorni:
        assert datetime.strptime(giorno, "%Y-%m-%d").weekday() not in (0, 6), giorno


def test_un_operatore_non_sta_in_due_posti_insieme(agenda):
    """Il difetto che renderebbe inutile tutto il resto.

    Con due appuntamenti sovrapposti l'agenda finta non somiglierebbe a
    nessuna agenda vera, e il bot verrebbe provato contro uno stato che non
    potrebbe mai esistere.
    """
    _, appuntamenti, _ = agenda

    occupati = defaultdict(set)
    for a in appuntamenti:
        inizio = datetime.strptime(a["slot"], "%Y-%m-%dT%H:%M")
        for i in range(max(1, a["durata"] // 30)):
            quando = (inizio + timedelta(minutes=30 * i)).strftime("%Y-%m-%dT%H:%M")
            assert quando not in occupati[a["operatore"]], (
                f"{a['operatore']} è occupato due volte alle {quando}"
            )
            occupati[a["operatore"]].add(quando)


def test_un_cliente_ha_al_massimo_un_appuntamento_futuro(agenda):
    """Il bot lo impedisce: darne due a un cliente finto farebbe sembrare un
    difetto il rifiuto che riceverebbe provando a prenotare."""
    _, _, clienti = agenda

    for cliente in clienti:
        futuri = [
            a for a in cliente["appuntamenti"] if a["slot"][:10] >= OGGI.isoformat()
        ]
        assert len(futuri) <= 1


def test_qualcuno_ha_uno_storico(agenda):
    """Senza clienti già visti non si prova il riconoscimento degli abituali."""
    _, _, clienti = agenda

    con_storico = [c for c in clienti if len(c["appuntamenti"]) > 1]
    assert con_storico, "nessun cliente con appuntamenti passati"


def test_i_contatti_non_possono_raggiungere_nessuno(agenda):
    """È la garanzia che rende innocui questi dati.

    Un telefono che comincia per 39000000 non è assegnabile e un dominio
    .invalid non esiste per definizione: nemmeno sbagliando si scrive a una
    persona vera.
    """
    _, _, clienti = agenda

    for cliente in clienti:
        assert cliente["telefono"].startswith(PREFISSO_TELEFONO)
        assert cliente["email"].endswith(f"@{DOMINIO_EMAIL}")


def test_l_agenda_non_e_ne_vuota_ne_piena(agenda):
    """Un'agenda piena non lascia niente da prenotare, una vuota non prova
    niente: i difetti stanno nel mezzo."""
    giorni, appuntamenti, _ = agenda

    slot_occupati = sum(max(1, a["durata"] // 30) for a in appuntamenti)
    slot_totali = len(giorni) * len(OPERATORI) * 20  # 09:00-19:00 a mezz'ora
    riempimento = slot_occupati / slot_totali

    assert 0.25 < riempimento < 0.75, f"riempimento {riempimento:.0%}"


def test_le_giornate_non_sono_tutte_uguali(agenda):
    """Un'agenda uniforme è proprio il caso in cui il bot non sbaglia mai."""
    _, appuntamenti, _ = agenda

    per_giorno = defaultdict(int)
    for a in appuntamenti:
        per_giorno[a["slot"][:10]] += 1
    quanti = sorted(per_giorno.values())

    assert quanti[-1] > quanti[0] * 1.4, "giornate troppo simili fra loro"


def test_lo_stesso_seme_dà_la_stessa_agenda():
    """Serve a ripetere una prova andata storta con gli stessi dati."""
    giorni = _giorni_aperti(DA, date(2026, 9, 15))
    primo = _piano(giorni, OPERATORI, 0.4, Random(99))
    secondo = _piano(giorni, OPERATORI, 0.4, Random(99))

    assert primo == secondo
