"""Test sul riconoscimento delle azioni e sulla formattazione delle risposte."""

import pytest

from services.conversation import (
    handle_incoming_message,
    parse_response_with_options,
    try_parse_action,
)
from services.fakes import ScriptedClaude


# --------------------------------------------------------------- try_parse_action


def test_azione_json_pura():
    """Una risposta interamente JSON viene riconosciuta come azione."""
    risposta = '{"action": "CHECK_DISPONIBILITA", "data": "2026-05-20", "parrucchiere": null}'
    azione, pre_text = try_parse_action(risposta)
    assert azione is not None
    assert azione["action"] == "CHECK_DISPONIBILITA"
    assert azione["data"] == "2026-05-20"
    assert pre_text is None


def test_risposta_testuale_non_e_azione():
    azione, pre_text = try_parse_action("Ciao! Come posso aiutarti oggi?")
    assert azione is None
    assert pre_text is None


def test_json_senza_campo_action():
    azione, _ = try_parse_action('{"data": "2026-05-20"}')
    assert azione is None


def test_json_malformato():
    azione, _ = try_parse_action('{"action": "CHECK_DISPONIBILITA", data: rotto}')
    assert azione is None


def test_testo_prima_del_json_viene_conservato():
    """Se Claude scrive qualcosa prima del JSON, quel testo va mostrato al cliente."""
    risposta = (
        'Perfetto, controllo subito!\n'
        '{"action": "CHECK_DISPONIBILITA", "data": "2026-05-20", "durata_min": 30}'
    )
    azione, pre_text = try_parse_action(risposta)
    assert azione["action"] == "CHECK_DISPONIBILITA"
    assert pre_text == "Perfetto, controllo subito!"


# ------------------------------------------------------- parse_response_with_options


def test_opzioni_riconosciute():
    risposta = "Che servizio desideri?\n- Taglio\n- Barba regolata\n- Taglio + Barba"
    testo, opzioni = parse_response_with_options(risposta)
    assert testo == "Che servizio desideri?"
    assert [o["title"] for o in opzioni] == ["Taglio", "Barba regolata", "Taglio + Barba"]
    assert opzioni[0]["id"] == "opt_0"


def test_una_sola_opzione_resta_testo():
    """Con una riga sola non ha senso mostrare bottoni."""
    testo, opzioni = parse_response_with_options("Ecco:\n- Taglio")
    assert opzioni is None
    assert "Taglio" in testo


def test_testo_semplice_senza_opzioni():
    testo, opzioni = parse_response_with_options("A che ora preferisci?")
    assert opzioni is None
    assert testo == "A che ora preferisci?"


def test_opzioni_con_emoji():
    """Le emoji iniziali vengono tolte dal titolo del bottone."""
    _, opzioni = parse_response_with_options("Scegli:\n- ✂️ Taglio\n- 🧔 Barba")
    assert [o["title"] for o in opzioni] == ["Taglio", "Barba"]


# ------------------------------------------------------------------ flusso messaggi


@pytest.mark.asyncio
async def test_tipo_messaggio_non_supportato(mock_redis, canale, backends):
    """Un audio riceve una risposta di cortesia e non arriva mai a Claude."""
    claude = ScriptedClaude(["non dovrebbe essere chiamato"])

    await handle_incoming_message(
        redis=mock_redis,
        phone="393331234567",
        text=None,
        msg_type="audio",
        channel=canale,
        backends=backends,
        claude=claude,
    )

    assert len(canale.messages) == 1
    assert "testo e foto" in canale.messages[0]["text"]
    assert claude.chiamate == []


@pytest.mark.asyncio
async def test_risposta_con_opzioni_usa_i_bottoni(mock_redis, canale, backends):
    claude = ScriptedClaude(["Che servizio?\n- Taglio\n- Barba"])

    await handle_incoming_message(
        redis=mock_redis,
        phone="393331234567",
        text="ciao",
        msg_type="text",
        channel=canale,
        backends=backends,
        claude=claude,
    )

    ultimo = canale.ultimo()
    assert ultimo["options"] is not None
    assert [o["title"] for o in ultimo["options"]] == ["Taglio", "Barba"]


@pytest.mark.asyncio
async def test_sessione_persistita_tra_messaggi(mock_redis, canale, backends):
    """Lo storico si accumula: il secondo messaggio vede il primo."""
    claude = ScriptedClaude(["Ciao!", "Certo, che giorno preferisci?"])

    for testo in ("ciao", "vorrei un taglio"):
        await handle_incoming_message(
            redis=mock_redis,
            phone="393331234567",
            text=testo,
            msg_type="text",
            channel=canale,
            backends=backends,
            claude=claude,
        )

    ultimo_storico = claude.chiamate[-1]["history"]
    contenuti = [m["content"] for m in ultimo_storico]
    assert "ciao" in contenuti
    assert "Ciao!" in contenuti
    assert "vorrei un taglio" in contenuti


@pytest.mark.asyncio
async def test_il_cliente_riceve_sempre_una_risposta(mock_redis, canale, backends):
    """Se Claude chiede azioni all'infinito, il bot non lascia il cliente senza risposta."""
    azione = ScriptedClaude.azione(
        action="CHECK_DISPONIBILITA", data="2026-05-19", durata_min=30
    )
    claude = ScriptedClaude([azione, azione, azione])

    await handle_incoming_message(
        redis=mock_redis,
        phone="393331234567",
        text="ciao",
        msg_type="text",
        channel=canale,
        backends=backends,
        claude=claude,
    )

    assert canale.messages, "il cliente deve ricevere almeno un messaggio"
    assert "problema tecnico" in canale.ultimo()["text"]


@pytest.mark.asyncio
async def test_azione_sconosciuta_non_fa_crashare(mock_redis, canale, backends):
    claude = ScriptedClaude(
        [ScriptedClaude.azione(action="FAI_UN_CAFFE"), "Scusa, non ho capito."]
    )

    await handle_incoming_message(
        redis=mock_redis,
        phone="393331234567",
        text="ciao",
        msg_type="text",
        channel=canale,
        backends=backends,
        claude=claude,
    )

    assert canale.ultimo()["text"] == "Scusa, non ho capito."
