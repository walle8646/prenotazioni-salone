"""Test sul riconoscimento di chi ha già prenotato.

Su WhatsApp il numero del mittente è verificato dal gestore: chiedere nome e
cognome a chi è in anagrafica è una domanda di cui sappiamo la risposta.

Dal sito no, e la differenza è il punto: lì l'identità arriva solo dal codice
mandato per email, e un numero di sessione del browser non prova niente.
"""

import pytest

from prompts.system_prompt import build_system_prompt
from services.conversation import _ultimo_operatore, handle_incoming_message
from services.fakes import ScriptedClaude

from .conftest import prossimo_giorno_aperto

GIORNO = prossimo_giorno_aperto()
NUMERO = "393331234567"


@pytest.fixture
def abituale(backends):
    """Un cliente che ha già prenotato due volte, l'ultima con Andrea."""
    backends.clienti.append(
        {
            "id": 1,
            "nome": "Mario",
            "cognome": "Rossi",
            "telefono": NUMERO,
            "email": "mario@example.it",
        }
    )
    backends.appuntamenti.extend(
        [
            {
                "id": 1,
                "client_id": 1,
                "data_ora": "2026-01-10T09:00",
                "servizi": ["Taglio"],
                "parrucchiere": "Francesco",
                "stato": "Completato",
            },
            {
                "id": 2,
                "client_id": 1,
                "data_ora": "2026-06-20T10:00",
                "servizi": ["Taglio + Barba"],
                "parrucchiere": "Andrea",
                "stato": "Completato",
            },
        ]
    )
    return backends


async def _primo_messaggio(redis, canale, backends, claude, telefono=NUMERO):
    await handle_incoming_message(
        redis=redis,
        phone=telefono,
        text="vorrei prenotare",
        msg_type="text",
        channel=canale,
        backends=backends,
        claude=claude,
    )


# ------------------------------------------------------------------ WhatsApp


@pytest.mark.asyncio
async def test_chi_ha_gia_prenotato_viene_riconosciuto_subito(
    mock_redis, canale, abituale
):
    """Prima ci si arrivava solo se il modello sceglieva di chiedere lo
    storico: quando non lo faceva, il cliente di tre anni si sentiva chiedere
    di nuovo come si chiama."""
    claude = ScriptedClaude(["Ciao Mario! Che servizio ti serve?"])

    await _primo_messaggio(mock_redis, canale, abituale, claude)

    prompt = claude.chiamate[0]["system"]
    assert "QUESTO CLIENTE LO CONOSCIAMO GIÀ" in prompt
    assert "Mario" in prompt and "Rossi" in prompt
    assert "mario@example.it" in prompt


@pytest.mark.asyncio
async def test_il_riconoscimento_avviene_prima_che_il_modello_parli(
    mock_redis, canale, abituale
):
    """Se arrivasse dopo, il primo messaggio sarebbe già stato composto
    chiedendo il nome."""
    claude = ScriptedClaude(["Ciao!"])

    await _primo_messaggio(mock_redis, canale, abituale, claude)

    assert claude.chiamate, "il modello deve essere stato chiamato una volta"
    assert "Mario" in claude.chiamate[0]["system"]


@pytest.mark.asyncio
async def test_viene_ricordato_anche_l_ultimo_operatore(mock_redis, canale, abituale):
    claude = ScriptedClaude(["Ciao Mario!"])

    await _primo_messaggio(mock_redis, canale, abituale, claude)

    prompt = claude.chiamate[0]["system"]
    assert "Andrea" in prompt, "l'ultimo in ordine di data, non il primo trovato"
    assert "non darlo per scontato" in prompt


@pytest.mark.asyncio
async def test_un_numero_sconosciuto_non_inventa_nessun_nome(
    mock_redis, canale, abituale
):
    claude = ScriptedClaude(["Ciao! Come ti chiami?"])

    await _primo_messaggio(mock_redis, canale, abituale, claude, telefono="393339999999")

    prompt = claude.chiamate[0]["system"]
    assert "QUESTO CLIENTE LO CONOSCIAMO GIÀ" not in prompt
    # "Mario" da solo non basta: compare in un esempio dentro il prompt.
    assert "Nome: non ancora raccolto" in prompt
    assert "mario@example.it" not in prompt


@pytest.mark.asyncio
async def test_l_anagrafica_si_legge_una_volta_sola(mock_redis, canale, abituale):
    """Una lettura per conversazione, non per messaggio: quello che si trova
    resta nella sessione."""
    letture = []
    vera = abituale.get_appuntamenti_per_telefono

    async def conta(telefono):
        letture.append(telefono)
        return await vera(telefono)

    abituale.get_appuntamenti_per_telefono = conta
    claude = ScriptedClaude(["Ciao Mario!", "Certo!", "Va bene!"])

    for _ in range(3):
        await _primo_messaggio(mock_redis, canale, abituale, claude)

    assert len(letture) == 1


@pytest.mark.asyncio
async def test_un_anagrafica_irraggiungibile_non_ferma_la_conversazione(
    mock_redis, canale, abituale
):
    """Si chiede il nome come a uno nuovo: è una scortesia, non un guasto."""

    async def esplode(telefono):
        raise RuntimeError("database irraggiungibile")

    abituale.get_appuntamenti_per_telefono = esplode
    claude = ScriptedClaude(["Ciao! Come ti chiami?"])

    await _primo_messaggio(mock_redis, canale, abituale, claude)

    assert canale.testi == ["Ciao! Come ti chiami?"]


# ---------------------------------------------------------------------- sito


@pytest.mark.asyncio
async def test_dal_sito_non_si_riconosce_nessuno(mock_redis, canale, abituale):
    """Il numero di sessione del browser non è una prova di identità: senza il
    codice via email, chiunque leggerebbe il nome di un altro."""
    claude = ScriptedClaude(["Ciao! Come ti chiami?"])

    await _primo_messaggio(mock_redis, canale, abituale, claude, telefono="web_abc123")

    prompt = claude.chiamate[0]["system"]
    assert "QUESTO CLIENTE LO CONOSCIAMO GIÀ" not in prompt
    assert "Nome: non ancora raccolto" in prompt
    assert "mario@example.it" not in prompt, (
        "l'email di un altro non deve arrivare a chi apre la chat del sito"
    )


# --------------------------------------------------------- ultimo operatore


def test_l_ultimo_operatore_e_quello_della_data_piu_recente():
    assert (
        _ultimo_operatore(
            [
                {"data_ora": "2026-01-10T09:00", "parrucchiere": "Francesco"},
                {"data_ora": "2026-06-20T10:00", "parrucchiere": "Andrea"},
            ]
        )
        == "Andrea"
    )


def test_un_appuntamento_annullato_non_conta():
    """Non ci è mai venuto: proporglielo sarebbe strano."""
    assert (
        _ultimo_operatore(
            [
                {"data_ora": "2026-01-10T09:00", "parrucchiere": "Francesco"},
                {
                    "data_ora": "2026-06-20T10:00",
                    "parrucchiere": "Andrea",
                    "stato": "Cancellato",
                },
            ]
        )
        == "Francesco"
    )


@pytest.mark.parametrize(
    "appuntamenti", [None, [], [{"data_ora": "2026-01-10T09:00"}]]
)
def test_senza_appuntamenti_utili_non_si_inventa_un_operatore(appuntamenti):
    assert _ultimo_operatore(appuntamenti) is None


# ------------------------------------------------------------------- prompt


def test_senza_riconoscimento_il_blocco_non_compare():
    prompt = build_system_prompt({"stato_flusso": "saluto", "dati_temp": {}})

    assert "QUESTO CLIENTE LO CONOSCIAMO" not in prompt


def test_il_blocco_regge_anche_senza_ultimo_operatore():
    prompt = build_system_prompt(
        {
            "stato_flusso": "saluto",
            "dati_temp": {"nome": "Mario"},
            "cliente_conosciuto": True,
        }
    )

    assert "QUESTO CLIENTE LO CONOSCIAMO GIÀ" in prompt
    assert "L'ultima volta è venuto da" not in prompt
