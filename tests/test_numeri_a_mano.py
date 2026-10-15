"""I numeri a cui risponde solo una persona.

Quello che conta davvero e' la forma del numero. In tabella deve finire
**come lo manda WhatsApp** — solo cifre, col prefisso e senza il piu' —
perche' scritto in un altro modo starebbe li' senza corrispondere a nessun
mittente: l'elenco sembrerebbe a posto e il bot continuerebbe a rispondere.
E' lo stesso guasto silenzioso gia' visto con le eco, il 15 ottobre.
"""

import pytest

from services import numeri_a_mano
from services.channels import CollectorChannel
from services.conversation import (
    MOTIVO_SOLO_A_MANO,
    handle_incoming_message,
    risponde_una_persona,
)
from services.fakes import FakeBackends, FakeRedis, ScriptedClaude

CLIENTE = "393491021925"


@pytest.fixture(autouse=True)
def elenco_vuoto():
    """Ogni test parte senza numeri e rimette la copia com'era.

    La copia sta in una variabile di modulo: un test che la lascia sporca
    farebbe fallire quelli dopo, e il motivo non si leggerebbe da nessuna
    parte."""
    numeri_a_mano.set_cache(())
    yield
    numeri_a_mano.set_cache(())


# ------------------------------------------------------ come si scrive


@pytest.mark.parametrize(
    "scritto",
    [
        "393491021925",
        "+393491021925",
        "0039 349 102 1925",
        "349 102 1925",
        "349-102-1925",
        "349.102.1925",
        "  +39 349/102 19 25  ",
        "3491021925",
    ],
)
def test_lo_stesso_numero_in_tutti_i_modi_in_cui_lo_si_scrive(scritto):
    """Chi lavora in salone lo scrive come ce l'ha in rubrica, non come lo
    manda Meta."""
    assert numeri_a_mano.normalizza(scritto) == CLIENTE


def test_il_prefisso_lo_aggiunge_il_codice():
    """Senza, l'elenco si riempirebbe di numeri che non corrispondono a
    nessun mittente e il bot continuerebbe a rispondere."""
    assert numeri_a_mano.normalizza("3491021925") == "393491021925"


def test_un_fisso_tiene_lo_zero():
    """+39 0362 123456 e' 390362123456: lo zero non si toglie."""
    assert numeri_a_mano.normalizza("0362 123456") == "390362123456"


def test_un_numero_straniero_si_prende_com_e():
    """Col prefisso del paese non si tocca niente: indovinarlo sarebbe
    peggio."""
    assert numeri_a_mano.normalizza("+33 6 12 34 56 78") == "33612345678"


@pytest.mark.parametrize(
    "scritto", ["", None, "   ", "non un numero", "349 ABC 1925", "12", "1" * 20]
)
def test_quello_che_non_e_un_numero_si_rifiuta(scritto):
    """Rifiutare e' meglio che salvare com'e': un numero storto in elenco e'
    un elenco che sembra a posto e non funziona."""
    assert numeri_a_mano.normalizza(scritto) is None


# ------------------------------------------------------- la copia in memoria


def test_chi_e_in_elenco_si_riconosce():
    numeri_a_mano.set_cache([CLIENTE])

    assert numeri_a_mano.risponde_solo_una_persona(CLIENTE) is True
    assert numeri_a_mano.risponde_solo_una_persona("393331234567") is False


def test_il_piu_davanti_non_inganna():
    """Meta i numeri li manda in cifre, ma difendersi costa una riga."""
    numeri_a_mano.set_cache([CLIENTE])

    assert numeri_a_mano.risponde_solo_una_persona("+" + CLIENTE) is True


def test_senza_numero_non_si_blocca_nessuno():
    numeri_a_mano.set_cache([CLIENTE])

    assert numeri_a_mano.risponde_solo_una_persona(None) is False
    assert numeri_a_mano.risponde_solo_una_persona("") is False


# --------------------------------------------------- cosa fa il bot


@pytest.mark.asyncio
async def test_a_chi_e_in_elenco_il_bot_non_risponde():
    numeri_a_mano.set_cache([CLIENTE])
    backends = FakeBackends()
    channel = CollectorChannel()

    await handle_incoming_message(
        redis=FakeRedis(),
        phone=CLIENTE,
        text="vorrei un taglio",
        msg_type="text",
        channel=channel,
        backends=backends,
        claude=ScriptedClaude(["non dovrei parlare"]),
    )

    assert channel.messages == []


@pytest.mark.asyncio
async def test_il_messaggio_arriva_comunque_nel_pannello():
    """Altrimenti mettere un numero in elenco sarebbe un modo di perdere
    clienti senza accorgersene."""
    numeri_a_mano.set_cache([CLIENTE])
    backends = FakeBackends()

    await handle_incoming_message(
        redis=FakeRedis(),
        phone=CLIENTE,
        text="siete aperti domani?",
        msg_type="text",
        channel=CollectorChannel(),
        backends=backends,
        claude=ScriptedClaude([]),
    )

    assert len(backends.conversazioni_operatore) == 1
    conversazione = backends.conversazioni_operatore[0]
    assert conversazione["motivo"] == MOTIVO_SOLO_A_MANO
    assert [(m["autore"], m["testo"]) for m in conversazione["messaggi"]] == [
        ("cliente", "siete aperti domani?")
    ]


@pytest.mark.asyncio
async def test_claude_non_viene_mai_chiamato():
    """Il controllo sta prima di spendere un token."""
    numeri_a_mano.set_cache([CLIENTE])
    claude = ScriptedClaude(["non dovrei essere chiamato"])

    await handle_incoming_message(
        redis=FakeRedis(),
        phone=CLIENTE,
        text="vorrei un taglio",
        msg_type="text",
        channel=CollectorChannel(),
        backends=FakeBackends(),
        claude=claude,
    )

    assert claude.chiamate == []


@pytest.mark.asyncio
async def test_non_si_promettono_risposte_in_arrivo():
    """I puntini dicono "fra pochi secondi": su questi numeri la promessa non
    la mantiene nessuno."""
    numeri_a_mano.set_cache([CLIENTE])

    assert await risponde_una_persona(CLIENTE, backends=FakeBackends()) is True


@pytest.mark.asyncio
async def test_chi_non_e_in_elenco_riceve_risposta():
    numeri_a_mano.set_cache([CLIENTE])
    backends = FakeBackends()
    channel = CollectorChannel()

    await handle_incoming_message(
        redis=FakeRedis(),
        phone="393331234567",
        text="buongiorno",
        msg_type="text",
        channel=channel,
        backends=backends,
        claude=ScriptedClaude(["Buongiorno! Come posso aiutarti?"]),
    )

    assert channel.messages
    assert backends.conversazioni_operatore == []


@pytest.mark.asyncio
async def test_l_elenco_vince_sul_passaggio_dimenticato():
    """Un passaggio a una persona torna al bot dopo 24 ore senza risposta.
    Un numero in elenco no: deve restare fuori finche' qualcuno lo toglie."""
    from datetime import datetime, timedelta

    numeri_a_mano.set_cache([CLIENTE])
    backends = FakeBackends()
    conversazione = await backends.apri_conversazione_operatore(
        telefono=CLIENTE, motivo=MOTIVO_SOLO_A_MANO
    )
    # Aperta due giorni fa e mai presa in mano: per le regole del passaggio
    # sarebbe scaduta.
    conversazione["aperta_il"] = datetime.now() - timedelta(days=2)

    channel = CollectorChannel()
    await handle_incoming_message(
        redis=FakeRedis(),
        phone=CLIENTE,
        text="c'e' nessuno?",
        msg_type="text",
        channel=channel,
        backends=backends,
        claude=ScriptedClaude(["non dovrei parlare"]),
    )

    assert channel.messages == []


# ----------------------------------------------------------- la schermata


@pytest.fixture
def pannello(monkeypatch):
    """La pagina col database sostituito da una lista in memoria."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers import admin
    import services.db_service as db

    elenco = []

    async def finto_elenco():
        return list(elenco)

    async def finto_aggiungi(telefono, nota=None):
        if any(n["telefono"] == telefono for n in elenco):
            return False
        elenco.append({"telefono": telefono, "nota": nota, "creato_il": None})
        return True

    async def finto_togli(telefono):
        elenco[:] = [n for n in elenco if n["telefono"] != telefono]

    monkeypatch.setattr(db, "numeri_a_mano", finto_elenco)
    monkeypatch.setattr(db, "aggiungi_numero_a_mano", finto_aggiungi)
    monkeypatch.setattr(db, "togli_numero_a_mano", finto_togli)

    app = FastAPI()
    app.include_router(admin.router)
    app.dependency_overrides[admin.utente_del_pannello] = lambda: "nadia"
    client = TestClient(app, follow_redirects=False)
    client.elenco = elenco
    return client


def test_il_numero_si_salva_nella_forma_che_usa_whatsapp(pannello):
    pannello.post("/admin/numeri-a-mano", data={"telefono": "349 102 1925", "nota": ""})

    assert [n["telefono"] for n in pannello.elenco] == [CLIENTE]


def test_un_numero_storto_viene_rifiutato_e_non_salvato(pannello):
    """Salvarlo com'e' vorrebbe dire un elenco che sembra a posto e non
    funziona."""
    risposta = pannello.post(
        "/admin/numeri-a-mano", data={"telefono": "non un numero", "nota": ""}
    )

    assert risposta.status_code == 303
    assert "errore=" in risposta.headers["location"]
    assert pannello.elenco == []


def test_aggiungere_vale_dal_messaggio_dopo(pannello):
    """Il bot legge una copia in memoria: senza ricaricarla, il numero
    varrebbe solo dal riavvio successivo — cioe' mai, quando serve."""
    pannello.post("/admin/numeri-a-mano", data={"telefono": CLIENTE, "nota": ""})

    assert numeri_a_mano.risponde_solo_una_persona(CLIENTE) is True


def test_togliere_vale_dal_messaggio_dopo(pannello):
    pannello.post("/admin/numeri-a-mano", data={"telefono": CLIENTE, "nota": ""})
    pannello.post(f"/admin/numeri-a-mano/{CLIENTE}/togli")

    assert numeri_a_mano.risponde_solo_una_persona(CLIENTE) is False


def test_la_pagina_spiega_come_si_scrive_il_numero(pannello):
    pagina = pannello.get("/admin/numeri-a-mano").text

    assert "prefisso internazionale" in pagina
    assert "0362" in pagina  # l'esempio del fisso
