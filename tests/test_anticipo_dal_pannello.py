"""Dal pannello si prenota anche per fra mezz'ora.

L'anticipo minimo (`MIN_BOOKING_HOURS_AHEAD`) esiste per chi scrive al bot:
nessuno deve potersi prendere da solo un posto per fra dieci minuti, con il
salone che se lo trova davanti senza saperlo. Applicato anche al pannello
diventa il contrario di quello che serve — li' il cliente e' al telefono e chi
risponde sa che ore sono.

Visto il 15 ottobre alle 18:05: aperto un appuntamento di oggi e premuto
Sposta, la pagina diceva "Nessuna mezz'ora libera in questa giornata" mentre
in salone c'erano le poltrone vuote. Google aveva risposto a dovere: erano i
120 minuti di anticipo a mangiarsi tutto quello che restava della giornata.
"""

from datetime import datetime, timedelta

import pytest

from services.conversation import _slot_ancora_libero
from services.fakes import FakeBackends

APERTO = ("09:00", "19:00")


@pytest.fixture
def sera(monkeypatch):
    """Sono le 18:05 di una giornata che chiude alle 19:00.

    Niente date fisse: si parte da oggi e si sposta solo l'ora, cosi' il test
    non invecchia. Gli orari si aprono tutti i giorni perche' oggi potrebbe
    cadere di domenica, quando il salone e' chiuso davvero.
    """
    adesso = datetime.now().replace(hour=18, minute=5, second=0, microsecond=0)
    monkeypatch.setattr("services.slots.orari_salone", lambda: {g: [APERTO] for g in range(7)})
    monkeypatch.setattr("services.fakes.adesso_salone", lambda: adesso)
    monkeypatch.setattr("services.slots._chiusure", set())
    return adesso


def _ore(slot: list[dict]) -> set[str]:
    return {s["slot"][11:] for s in slot}


@pytest.mark.asyncio
async def test_con_l_anticipo_del_bot_la_sera_non_resta_niente(sera):
    """Il difetto, messo nero su bianco: alle 18:05 con due ore di anticipo
    la giornata e' finita un'ora fa."""
    backends = FakeBackends()

    liberi = await backends.check_availability(sera.date().isoformat(), None, 30)

    assert liberi == []


@pytest.mark.asyncio
async def test_senza_anticipo_le_ultime_mezz_ore_ci_sono(sera):
    backends = FakeBackends()

    liberi = await backends.check_availability(sera.date().isoformat(), None, 30, 0)

    assert _ore(liberi) == {"18:30"}, "l'unica mezz'ora che comincia dopo le 18:05"


@pytest.mark.asyncio
async def test_quello_che_e_gia_cominciato_resta_fuori(sera):
    """Senza anticipo non vuol dire senza orologio: alle 18:05 le 18:00 sono
    passate, e sedere qualcuno li' vorrebbe dire prometterglielo in ritardo."""
    backends = FakeBackends()

    liberi = await backends.check_availability(sera.date().isoformat(), None, 30, 0)

    assert "18:00" not in _ore(liberi)


@pytest.mark.asyncio
async def test_il_controllo_finale_dice_quello_che_diceva_il_verde(sera):
    """Il controllo prima di scrivere deve usare **lo stesso** anticipo con
    cui lo slot e' stato offerto. Senza, una casella verde toccata alle 18:05
    risponderebbe "quel posto non e' piu' libero": non e' vero, e chi lo legge
    chiama il cliente per disdire."""
    backends = FakeBackends()
    quando = sera.replace(hour=18, minute=30).strftime("%Y-%m-%dT%H:%M")
    cal_id = next(iter(backends.parrucchieri.values()))

    assert await _slot_ancora_libero(quando, cal_id, 30, backends, anticipo_min=0)
    assert not await _slot_ancora_libero(quando, cal_id, 30, backends)


@pytest.mark.asyncio
async def test_al_bot_l_anticipo_resta(sera):
    """La regola non cambia per chi scrive da solo: e' il pannello a essere
    un caso a parte, non il contrario."""
    backends = FakeBackends()
    domani = (sera + timedelta(days=1)).date().isoformat()

    assert await backends.check_availability(sera.date().isoformat(), None, 30) == []
    assert await backends.check_availability(domani, None, 30), "domani si prenota"
