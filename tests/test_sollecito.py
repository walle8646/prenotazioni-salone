"""Il sollecito per chi aspetta una persona e non ha ancora risposta.

La notifica parte quando il cliente chiede di parlare con qualcuno, e poi a
ogni suo messaggio successivo. Ma chi aspetta smette di scrivere, e in quel
caso parte una notifica sola: se chi e' in salone in quel momento ha le mani
nei capelli di qualcuno, il cliente resta li' per 24 ore.

Due cose vanno provate piu' delle altre: che non solleciti **due volte** lo
stesso cliente, e che non suoni **a salone chiuso** — una notifica alle undici
di sera insegna solo a silenziare le notifiche.
"""

from datetime import datetime, timedelta

import pytest

from jobs import sollecito_job


@pytest.fixture
def salone(monkeypatch):
    """Orari veri in memoria: martedi'-sabato 9-19, niente chiusure."""
    from services import slots

    slots.set_orari_salone({g: [("09:00", "19:00")] for g in range(1, 6)})
    slots.set_chiusure(set())
    yield
    slots.set_orari_salone(None)
    slots.set_chiusure(set())


# --------------------------------------------------------- quando suonare


def test_a_salone_aperto_si_sollecita(salone):
    # Mercoledi' 21 ottobre 2026, alle 11.
    assert sollecito_job._salone_aperto(datetime(2026, 10, 21, 11, 0)) is True


def test_fuori_orario_non_si_sollecita(salone):
    """Non c'e' nessuno da richiamare, e la notifica insegna solo a
    silenziarle."""
    assert sollecito_job._salone_aperto(datetime(2026, 10, 21, 23, 0)) is False
    assert sollecito_job._salone_aperto(datetime(2026, 10, 21, 7, 30)) is False


def test_di_domenica_non_si_sollecita(salone):
    # Domenica 25 ottobre 2026: non c'e' nessuna fascia.
    assert sollecito_job._salone_aperto(datetime(2026, 10, 25, 11, 0)) is False


def test_un_giorno_di_chiusura_straordinaria_tace(salone):
    from services import slots

    slots.set_chiusure({"2026-10-21"})

    assert sollecito_job._salone_aperto(datetime(2026, 10, 21, 11, 0)) is False


# --------------------------------------------------------- la fascia


@pytest.mark.asyncio
async def test_si_chiede_solo_la_fascia_che_non_e_ancora_stata_sollecitata(
    salone, monkeypatch
):
    """Larga quanto l'intervallo fra due giri: ogni conversazione ci cade
    dentro esattamente una volta, e nessuno viene richiamato due volte."""
    chiesto = {}

    async def finta_query(da, a):
        chiesto["da"] = da
        chiesto["a"] = a
        return []

    adesso = datetime(2026, 10, 21, 11, 0)

    monkeypatch.setattr(
        "services.db_service.conversazioni_in_attesa_da", finta_query
    )
    monkeypatch.setattr("services.slots.adesso_salone", lambda: adesso)

    await sollecito_job.sollecita_conversazioni_in_attesa()

    assert chiesto["a"] == adesso - timedelta(minutes=sollecito_job.MINUTI_PRIMA)
    larghezza = chiesto["a"] - chiesto["da"]
    assert larghezza == timedelta(minutes=sollecito_job.INTERVALLO_MINUTI)


@pytest.mark.asyncio
async def test_chi_aspetta_riceve_una_notifica(salone, monkeypatch):
    avvisi = []

    async def finta_query(da, a):
        return [{"id": 3, "telefono": "393331234567", "nome": "Marco Rossi"}]

    async def finto_avviso(titolo, testo, url):
        avvisi.append({"titolo": titolo, "testo": testo, "url": url})

    monkeypatch.setattr("services.db_service.conversazioni_in_attesa_da", finta_query)
    monkeypatch.setattr("services.push.avvisa", finto_avviso)
    monkeypatch.setattr(
        "services.slots.adesso_salone", lambda: datetime(2026, 10, 21, 11, 0)
    )

    quanti = await sollecito_job.sollecita_conversazioni_in_attesa()

    assert quanti == 1
    assert "Marco Rossi" in avvisi[0]["titolo"]
    assert avvisi[0]["url"] == "/admin/conversazioni/3"


@pytest.mark.asyncio
async def test_a_salone_chiuso_non_si_interroga_nemmeno_il_database(
    salone, monkeypatch
):
    chiamate = []

    async def finta_query(da, a):
        chiamate.append((da, a))
        return []

    monkeypatch.setattr("services.db_service.conversazioni_in_attesa_da", finta_query)
    monkeypatch.setattr(
        "services.slots.adesso_salone", lambda: datetime(2026, 10, 21, 23, 0)
    )

    assert await sollecito_job.sollecita_conversazioni_in_attesa() == 0
    assert chiamate == []


@pytest.mark.asyncio
async def test_un_database_che_non_risponde_non_fa_esplodere_il_job(
    salone, monkeypatch
):
    """Gira ogni cinque minuti: un'eccezione qui riempirebbe i log senza che
    nessuno la legga, e non cambia niente per il cliente."""

    async def query_rotta(da, a):
        raise RuntimeError("database non raggiungibile")

    monkeypatch.setattr("services.db_service.conversazioni_in_attesa_da", query_rotta)
    monkeypatch.setattr(
        "services.slots.adesso_salone", lambda: datetime(2026, 10, 21, 11, 0)
    )

    assert await sollecito_job.sollecita_conversazioni_in_attesa() == 0


@pytest.mark.asyncio
async def test_una_notifica_non_partita_non_ferma_le_altre(salone, monkeypatch):
    avvisi = []

    async def finta_query(da, a):
        return [
            {"id": 1, "telefono": "1", "nome": "Primo"},
            {"id": 2, "telefono": "2", "nome": "Secondo"},
        ]

    async def avviso_capriccioso(titolo, testo, url):
        if "Primo" in titolo:
            raise RuntimeError("servizio push giu'")
        avvisi.append(titolo)

    monkeypatch.setattr("services.db_service.conversazioni_in_attesa_da", finta_query)
    monkeypatch.setattr("services.push.avvisa", avviso_capriccioso)
    monkeypatch.setattr(
        "services.slots.adesso_salone", lambda: datetime(2026, 10, 21, 11, 0)
    )

    await sollecito_job.sollecita_conversazioni_in_attesa()

    assert avvisi == ["Secondo aspetta ancora"]
