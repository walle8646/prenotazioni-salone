"""Un cliente per volta ha un appuntamento solo.

Successo davvero: la stessa persona è finita due volte sulla stessa mezz'ora,
con due operatori diversi. Due poltrone occupate per un cliente solo, e il
salone se ne accorgeva guardando l'agenda.

Il controllo sta nel codice e non nel prompt: "mai" non può dipendere da
quanto bene il modello se lo ricorda.
"""

from datetime import timedelta

import pytest

from services.conversation import _primo_appuntamento_futuro, execute_action
from services.slots import adesso_salone

from .conftest import prossimo_giorno_aperto

NUMERO = "393331234567"
GIORNO = prossimo_giorno_aperto()


def _quando(giorni_avanti: int, ora: str = "09:00") -> str:
    giorno = (adesso_salone() + timedelta(days=giorni_avanti)).strftime("%Y-%m-%d")
    return f"{giorno}T{ora}"


@pytest.fixture
def con_appuntamento(backends):
    """Un cliente che ha già un appuntamento fra tre giorni."""
    backends.clienti.append(
        {"id": 1, "nome": "Valerio", "cognome": "Di Dio",
         "telefono": NUMERO, "email": "valerio@example.it"}
    )
    backends.appuntamenti.append(
        {"id": 7, "client_id": 1, "data_ora": _quando(3, "18:30"),
         "servizi": ["Barba"], "parrucchiere": "Francesco",
         "stato": "Confermato", "gcal_event_id": "evt7"}
    )
    return backends


async def _prenota(backends, phone=NUMERO, **extra):
    azione = {
        "action": "CREA_APPUNTAMENTO",
        "slot": f"{GIORNO}T09:00",
        "parrucchiere": "Andrea",
        "servizi": ["Taglio"],
        "nome": "Valerio",
        "cognome": "Di Dio",
    }
    azione.update(extra)
    return await execute_action(
        azione, phone, {"stato_flusso": "confermato", "dati_temp": {}}, backends
    )


# ------------------------------------------------------------------ WhatsApp


@pytest.mark.asyncio
async def test_chi_ha_gia_un_appuntamento_non_ne_prende_un_altro(con_appuntamento):
    risultato = await _prenota(con_appuntamento)

    assert "errore" in risultato
    assert con_appuntamento.eventi == {}, "non deve finire sul calendario"


@pytest.mark.asyncio
async def test_il_bot_riceve_i_dati_per_proporre_lo_spostamento(con_appuntamento):
    """Senza app_id e gcal_event_id non potrebbe spostarlo né disdirlo."""
    risultato = await _prenota(con_appuntamento)

    gia = risultato["appuntamento_gia_preso"]
    assert gia["app_id"] == 7
    assert gia["gcal_event_id"] == "evt7"
    assert gia["parrucchiere"] == "Francesco"
    assert "SPOSTA_APPUNTAMENTO" in risultato["errore"]


@pytest.mark.asyncio
async def test_lo_stesso_orario_due_volte_e_lo_stesso_rifiuto(con_appuntamento):
    """Il caso visto in agenda: stessa persona, stessa mezz'ora, due operatori."""
    risultato = await _prenota(
        con_appuntamento, slot=_quando(3, "18:30"), parrucchiere="Andrea"
    )

    assert "errore" in risultato
    assert con_appuntamento.eventi == {}


@pytest.mark.asyncio
async def test_chi_non_ha_appuntamenti_prenota_normalmente(backends):
    risultato = await _prenota(backends)

    assert "errore" not in risultato
    assert backends.eventi, "l'appuntamento deve essere creato"


@pytest.mark.asyncio
async def test_un_appuntamento_passato_non_blocca_niente(backends):
    """Chi è venuto la settimana scorsa deve poter tornare."""
    backends.clienti.append(
        {"id": 1, "nome": "Valerio", "cognome": "Di Dio", "telefono": NUMERO}
    )
    backends.appuntamenti.append(
        {"id": 3, "client_id": 1, "data_ora": _quando(-7), "servizi": ["Taglio"],
         "parrucchiere": "Francesco", "stato": "Confermato"}
    )

    assert "errore" not in await _prenota(backends)


@pytest.mark.asyncio
async def test_un_appuntamento_annullato_non_blocca_niente(backends):
    """L'ha disdetto lui: deve poterne prendere un altro."""
    backends.clienti.append(
        {"id": 1, "nome": "Valerio", "cognome": "Di Dio", "telefono": NUMERO}
    )
    backends.appuntamenti.append(
        {"id": 4, "client_id": 1, "data_ora": _quando(3), "servizi": ["Taglio"],
         "parrucchiere": "Francesco", "stato": "Cancellato"}
    )

    assert "errore" not in await _prenota(backends)


# ---------------------------------------------------------------------- sito


@pytest.mark.asyncio
async def test_dal_sito_il_doppione_e_bloccato_lo_stesso(con_appuntamento):
    """Senza verifica non sappiamo chi è, ma il contatto che lascia adesso
    basta a impedire la seconda prenotazione."""
    risultato = await _prenota(
        con_appuntamento, phone="web_abc123", email="valerio@example.it"
    )

    assert "errore" in risultato
    assert con_appuntamento.eventi == {}


@pytest.mark.asyncio
async def test_dal_sito_non_si_racconta_l_appuntamento_di_un_altro(con_appuntamento):
    """Altrimenti basterebbe scrivere l'email di un conoscente per sapere
    quando va dal barbiere."""
    risultato = await _prenota(
        con_appuntamento, phone="web_abc123", email="valerio@example.it"
    )

    assert "appuntamento_gia_preso" not in risultato
    assert "Francesco" not in risultato["errore"]
    assert "18:30" not in risultato["errore"]
    assert "INVIA_CODICE_VERIFICA" in risultato["errore"]


@pytest.mark.asyncio
async def test_dal_sito_verificato_si_raccontano_i_dettagli(con_appuntamento):
    risultato = await execute_action(
        {
            "action": "CREA_APPUNTAMENTO",
            "slot": f"{GIORNO}T09:00",
            "parrucchiere": "Andrea",
            "servizi": ["Taglio"],
            "nome": "Valerio",
        },
        "web_abc123",
        {
            "stato_flusso": "confermato",
            "dati_temp": {},
            "email_verificata": "valerio@example.it",
        },
        con_appuntamento,
    )

    assert risultato["appuntamento_gia_preso"]["app_id"] == 7


# ------------------------------------------------------- scelta del prossimo


def test_fra_piu_appuntamenti_futuri_si_indica_il_primo():
    prossimo = _primo_appuntamento_futuro(
        [
            {"data_ora": _quando(9), "stato": "Confermato", "app_id": 2},
            {"data_ora": _quando(2), "stato": "Confermato", "app_id": 1},
        ]
    )

    assert prossimo["app_id"] == 1


def test_senza_appuntamenti_futuri_non_si_indica_niente():
    assert _primo_appuntamento_futuro([]) is None
    assert _primo_appuntamento_futuro(None) is None
