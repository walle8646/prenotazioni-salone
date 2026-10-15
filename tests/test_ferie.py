"""Chi e' in ferie non riceve appuntamenti, da nessuna parte.

Prima l'assenza non si salvava: `annulla_giornata()` cancellava gli eventi,
avvisava i clienti, e la richiesta finiva li'. Conseguenza misurata il 15
ottobre: annullata la giornata di un operatore alle nove, alle nove e un
quarto il bot poteva ridargli un appuntamento per lo stesso pomeriggio. Con
un giorno solo si nota — c'e' chi guarda l'agenda — ma una settimana di ferie
nessuno la controlla per sette giorni, e il rientro e' una giornata piena di
clienti che l'operatore non sa di avere.

Il filtro sta in `e_in_salone()`, che e' l'unico posto che risponde a "quel
giorno lavora": da li' passano la disponibilita' del bot, il verde del
pannello e le due griglie. Questi test guardano che ci passino davvero.
"""

from datetime import date, timedelta

import pytest

from services import presenze
from services.channels import CollectorChannel
from services.conversation import handle_incoming_message
from services.fakes import FakeBackends, FakeRedis, ScriptedClaude

CLIENTE = "393491021925"


@pytest.fixture(autouse=True)
def senza_assenze():
    """Ogni test parte senza ferie e rimette la copia com'era.

    La copia sta in una variabile di modulo: un test che la lascia sporca fa
    fallire quelli dopo, e il motivo non si legge da nessuna parte."""
    presenze.set_assenze_cache({})
    yield
    presenze.set_assenze_cache({})


# --------------------------------------------------- il periodo, giorno a giorno


def test_dentro_il_periodo_non_e_in_salone():
    presenze.set_assenze_cache({"Andrea": [("2026-10-20", "2026-10-24")]})

    assert presenze.e_in_salone("Andrea", "2026-10-22T10:00") is False


def test_gli_estremi_sono_compresi():
    """"Dal 20 al 24" sono cinque giorni: escluderli vorrebbe dire due giorni
    in cui qualcuno prenota e non trova nessuno."""
    presenze.set_assenze_cache({"Andrea": [("2026-10-20", "2026-10-24")]})

    assert presenze.e_in_salone("Andrea", "2026-10-20T09:00") is False
    assert presenze.e_in_salone("Andrea", "2026-10-24T18:00") is False


def test_il_giorno_prima_e_quello_dopo_lavora():
    """Un'assenza di una settimana non deve toglierlo dal calendario per
    sempre: al rientro dev'essere di nuovo prenotabile da solo."""
    presenze.set_assenze_cache({"Andrea": [("2026-10-20", "2026-10-24")]})

    # Sabato 17 e martedi' 27: due giorni in cui il salone e' aperto. Il 19 e
    # il 26 sono lunedi', e li' il falso lo direbbero gli orari, non le ferie.
    assert presenze.e_in_salone("Andrea", "2026-10-17T10:00") is True
    assert presenze.e_in_salone("Andrea", "2026-10-27T10:00") is True


def test_le_ferie_di_uno_non_toccano_gli_altri():
    presenze.set_assenze_cache({"Andrea": [("2026-10-20", "2026-10-24")]})

    assert presenze.e_in_salone("Bario", "2026-10-22T10:00") is True


def test_due_periodi_sullo_stesso_nome_valgono_tutti_e_due():
    presenze.set_assenze_cache(
        {"Andrea": [("2026-10-20", "2026-10-24"), ("2026-11-02", "2026-11-02")]}
    )

    # Il 2 novembre e' un lunedi', quindi qui si guarda solo che l'assenza
    # valga: a dire di no basterebbero gli orari. Il 28 e' un mercoledi'.
    assert presenze.non_c_e("Andrea", "2026-11-02") is True
    assert presenze.e_in_salone("Andrea", "2026-10-28T10:00") is True


def test_le_ferie_vengono_prima_degli_orari():
    """Anche chi ha le sue fasce in Presenze, in ferie non c'e': l'assenza
    sono le date in cui quegli orari non valgono."""
    presenze.set_presenze_cache({"Andrea": {g: [("09:00", "19:00")] for g in range(7)}})
    presenze.set_assenze_cache({"Andrea": [("2026-10-20", "2026-10-24")]})

    assert presenze.e_in_salone("Andrea", "2026-10-22T10:00") is False
    presenze.set_presenze_cache({})


def test_gli_slot_di_chi_non_c_e_spariscono():
    presenze.set_assenze_cache({"Andrea": [("2026-10-20", "2026-10-24")]})
    slot = [
        {"slot": "2026-10-22T10:00", "parrucchiere": "Andrea"},
        {"slot": "2026-10-22T10:00", "parrucchiere": "Bario"},
    ]

    restano = presenze.solo_chi_e_in_salone(slot)

    assert [s["parrucchiere"] for s in restano] == ["Bario"]


# ------------------------------------------- la conversazione vera, dal bot


def _giorno_aperto_fra_una_settimana() -> str:
    from .conftest import prossimo_giorno_aperto

    return prossimo_giorno_aperto()


@pytest.mark.asyncio
async def test_il_bot_non_propone_chi_e_in_ferie():
    """La prova che conta: non il filtro chiamato a mano, ma quello che il
    cliente si sente proporre. Il risultato dell'azione finisce nello storico
    della conversazione, ed e' li' che si guarda."""
    giorno = _giorno_aperto_fra_una_settimana()
    backends = FakeBackends()
    presenze.set_assenze_cache({"Andrea": [(giorno, giorno)]})

    claude = ScriptedClaude(
        [
            ScriptedClaude.azione(
                action="CHECK_DISPONIBILITA",
                data=giorno,
                servizi=["Taglio"],
                durata_min=30,
            ),
            "Ci sono questi orari. Quale preferisci?",
        ]
    )

    await handle_incoming_message(
        redis=FakeRedis(),
        phone=CLIENTE,
        text=f"vorrei un taglio il {giorno}",
        msg_type="text",
        channel=CollectorChannel(),
        backends=backends,
        claude=claude,
    )

    storico = str(claude.chiamate[-1]["history"])
    assert "Andrea" not in storico, "in ferie, e il bot lo stava offrendo"
    assert "Bario" in storico, "gli altri devono restare prenotabili"


@pytest.mark.asyncio
async def test_con_tutti_in_ferie_il_bot_lo_dice_invece_di_tacere():
    """Zero slot e zero operatori in salone si somigliano solo a guardarli:
    senza la nota, il modello riferirebbe "siamo pieni" per un giorno in cui
    semplicemente non c'e' nessuno."""
    giorno = _giorno_aperto_fra_una_settimana()
    backends = FakeBackends()
    presenze.set_assenze_cache({nome: [(giorno, giorno)] for nome in backends.parrucchieri})

    claude = ScriptedClaude(
        [
            ScriptedClaude.azione(
                action="CHECK_DISPONIBILITA",
                data=giorno,
                servizi=["Taglio"],
                durata_min=30,
            ),
            "Quel giorno non abbiamo nessuno, ti propongo un altro giorno.",
        ]
    )

    await handle_incoming_message(
        redis=FakeRedis(),
        phone=CLIENTE,
        text=f"vorrei un taglio il {giorno}",
        msg_type="text",
        channel=CollectorChannel(),
        backends=backends,
        claude=claude,
    )

    storico = str(claude.chiamate[-1]["history"])
    assert "nessun operatore è in salone" in storico


# ------------------------------------------------ cosa torna in memoria


def test_in_memoria_ci_vanno_i_periodi_non_ancora_finiti():
    """Le assenze passate restano in tabella — sono la storia di un buco in
    agenda — ma per sapere chi lavora domani non servono, e ogni periodo in
    piu' e' un confronto in piu' per ogni slot di ogni ricerca."""
    oggi = date.today()
    presenze.set_assenze_cache(
        {"Andrea": [((oggi - timedelta(days=2)).isoformat(), (oggi + timedelta(days=2)).isoformat())]}
    )

    assert presenze.non_c_e("Andrea", oggi.isoformat()) is True
    assert presenze.non_c_e("Andrea", (oggi + timedelta(days=9)).isoformat()) is False


# ------------------------------------------------------------- la schermata


@pytest.fixture
def pannello(monkeypatch):
    """La pagina con il database sostituito da una lista in memoria."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers import admin
    import services.db_service as db

    salvate: list[dict] = []
    prossimo = {"id": 1}

    async def finto_elenco(da=None):
        return [a for a in salvate if da is None or a["al"] >= da]

    async def finta_aggiunta(parrucchiere_id, dal, al, motivo=None):
        if any(
            a["parrucchiere_id"] == parrucchiere_id and a["dal"] <= al and a["al"] >= dal
            for a in salvate
        ):
            return False
        salvate.append(
            {
                "id": prossimo["id"],
                "parrucchiere_id": parrucchiere_id,
                "operatore": "Andrea",
                "dal": dal,
                "al": al,
                "motivo": motivo,
            }
        )
        prossimo["id"] += 1
        return True

    async def finta_rimozione(assenza_id):
        salvate[:] = [a for a in salvate if a["id"] != assenza_id]

    async def finta_memoria():
        return {
            a["operatore"]: [(a["dal"].isoformat(), a["al"].isoformat())]
            for a in salvate
        }

    async def niente_appuntamenti(*argomenti, **parametri):
        return []

    monkeypatch.setattr(db, "assenze_operatore", finto_elenco)
    monkeypatch.setattr(db, "aggiungi_assenza", finta_aggiunta)
    monkeypatch.setattr(db, "togli_assenza", finta_rimozione)
    monkeypatch.setattr(db, "assenze_in_memoria", finta_memoria)
    monkeypatch.setattr(db, "appuntamenti_nel_periodo", niente_appuntamenti)

    class _Nome:
        def scalar_one_or_none(self):
            return "Andrea"

    class _FintoDb:
        async def execute(self, *argomenti, **parametri):
            return _Nome()

    app = FastAPI()
    app.include_router(admin.router)
    app.dependency_overrides[admin.utente_del_pannello] = lambda: "nadia"
    app.dependency_overrides[admin.get_db] = lambda: _FintoDb()
    client = TestClient(app, follow_redirects=False)
    client.salvate = salvate
    return client


def _fra(giorni: int) -> str:
    return (date.today() + timedelta(days=giorni)).isoformat()


def test_le_ferie_valgono_dal_messaggio_dopo(pannello):
    """Senza ricaricare la copia in memoria varrebbero dal riavvio
    successivo — cioe' mai, nel momento in cui servono: il bot continuerebbe
    a dare appuntamenti a chi e' al mare."""
    pannello.post(
        "/admin/assenze/periodo",
        data={"operatore_id": "3", "dal": _fra(3), "al": _fra(9), "motivo": "ferie"},
    )

    assert presenze.non_c_e("Andrea", _fra(5)) is True
    assert presenze.non_c_e("Andrea", _fra(20)) is False


def test_un_giorno_solo_si_segna_lasciando_vuoto_il_secondo_campo(pannello):
    """La malattia di domani e la settimana di ferie devono essere la stessa
    schermata, o la prima si fa a mano e si dimentica."""
    pannello.post(
        "/admin/assenze/periodo",
        data={"operatore_id": "3", "dal": _fra(2), "al": "", "motivo": ""},
    )

    assert presenze.non_c_e("Andrea", _fra(2)) is True
    assert presenze.non_c_e("Andrea", _fra(3)) is False


def test_un_periodo_al_contrario_non_si_salva(pannello):
    risposta = pannello.post(
        "/admin/assenze/periodo",
        data={"operatore_id": "3", "dal": _fra(9), "al": _fra(3), "motivo": ""},
    )

    assert "errore=" in risposta.headers["location"]
    assert pannello.salvate == []


def test_due_periodi_sovrapposti_non_si_accavallano(pannello):
    """Due righe per gli stessi giorni non sbagliano il calcolo — basta che
    una copra — ma nell'elenco non si sa piu' quale togliere."""
    dati = {"operatore_id": "3", "dal": _fra(3), "al": _fra(9), "motivo": ""}
    pannello.post("/admin/assenze/periodo", data=dati)

    risposta = pannello.post(
        "/admin/assenze/periodo",
        data={"operatore_id": "3", "dal": _fra(5), "al": _fra(12), "motivo": ""},
    )

    assert "errore=" in risposta.headers["location"]
    assert len(pannello.salvate) == 1


def test_togliere_le_ferie_lo_rimette_subito_fra_i_disponibili(pannello):
    pannello.post(
        "/admin/assenze/periodo",
        data={"operatore_id": "3", "dal": _fra(3), "al": _fra(9), "motivo": ""},
    )

    pannello.post(f"/admin/assenze/periodo/{pannello.salvate[0]['id']}/togli")

    assert presenze.non_c_e("Andrea", _fra(5)) is False
