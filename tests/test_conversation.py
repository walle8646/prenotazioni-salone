"""Test sul riconoscimento delle azioni e sulla formattazione delle risposte."""

import pytest

from services.conversation import (
    MAX_ITERATIONS,
    handle_incoming_message,
    parse_response_with_options,
    try_parse_action,
)
from services.fakes import ScriptedClaude

from .conftest import prossimo_giorno_aperto

# Vedi la nota in conftest: le date fisse invecchiano e la disponibilità non
# propone più slot già trascorsi.
GIORNO = prossimo_giorno_aperto()


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
    # Tante azioni quante sono le iterazioni concesse: il modello non arriva
    # mai a scrivere al cliente. Legato alla costante, così alzare il limite
    # non falsa il test invece di romperlo.
    claude = ScriptedClaude([azione] * MAX_ITERATIONS)

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


# --------------------------------------------- operatore indicato per nome
#
# Prima Claude doveva ricopiare l'id del calendario, novanta caratteri opachi:
# lo restituiva troncato, Google rispondeva 404, l'errore veniva ingoiato e il
# cliente si sentiva dire che non c'era disponibilità. Ora passa il nome.

MAPPA_FINTA = {"Francesco": "cal-francesco@group.calendar.google.com"}


def test_operatore_risolto_dal_nome():
    from prompts.system_prompt import set_parrucchieri_cache
    from services.conversation import _risolvi_calendario

    set_parrucchieri_cache(MAPPA_FINTA)

    assert _risolvi_calendario("Francesco") == MAPPA_FINTA["Francesco"]
    # Il confronto ignora le maiuscole: Claude non sempre rispetta il caso
    assert _risolvi_calendario("francesco") == MAPPA_FINTA["Francesco"]
    # Nessuna preferenza: si controllano tutti i calendari
    assert _risolvi_calendario(None) is None
    # Se arriva già un id di calendario viene accettato comunque
    assert _risolvi_calendario(MAPPA_FINTA["Francesco"]) == MAPPA_FINTA["Francesco"]


def test_nome_di_operatore_inesistente_da_errore_esplicito():
    from prompts.system_prompt import set_parrucchieri_cache
    from services.conversation import OperatoreSconosciuto, _risolvi_calendario

    set_parrucchieri_cache(MAPPA_FINTA)

    with pytest.raises(OperatoreSconosciuto):
        _risolvi_calendario("Gigi")


def test_operatore_senza_calendario_configurato_da_errore():
    """Un segnaposto non deve produrre una richiesta a Google destinata a fallire."""
    from prompts.system_prompt import set_parrucchieri_cache
    from services.conversation import OperatoreSconosciuto, _risolvi_calendario

    set_parrucchieri_cache({"Andrea": "da-configurare-andrea"})

    with pytest.raises(OperatoreSconosciuto):
        _risolvi_calendario("Andrea")


@pytest.mark.asyncio
async def test_check_disponibilita_accetta_il_nome_dell_operatore():
    from prompts.system_prompt import set_parrucchieri_cache
    from services.conversation import execute_action
    from services.fakes import FakeBackends

    set_parrucchieri_cache(MAPPA_FINTA)
    backends = FakeBackends(MAPPA_FINTA)

    risultato = await execute_action(
        {
            "action": "CHECK_DISPONIBILITA",
            "data": GIORNO,
            "parrucchiere": "Francesco",
            "durata_min": 30,
        },
        "393331234567",
        {},
        backends,
    )

    assert risultato["slots_disponibili"], "gli slot devono essere trovati"
    assert risultato["slots_disponibili"][0]["parrucchiere"] == "Francesco"


@pytest.mark.asyncio
async def test_operatore_sbagliato_non_sembra_agenda_piena():
    """Il caso che mandava via i clienti: errore esplicito, non lista vuota."""
    from prompts.system_prompt import set_parrucchieri_cache
    from services.conversation import execute_action
    from services.fakes import FakeBackends

    set_parrucchieri_cache(MAPPA_FINTA)
    backends = FakeBackends(MAPPA_FINTA)

    risultato = await execute_action(
        {
            "action": "CHECK_DISPONIBILITA",
            "data": GIORNO,
            "parrucchiere": "Franc",  # nome troncato
            "durata_min": 30,
        },
        "393331234567",
        {},
        backends,
    )

    assert "errore" in risultato
    assert "slots_disponibili" not in risultato


# ------------------------------------------------ memoria della conversazione
#
# Lo storico viene troncato agli ultimi max_history_messages messaggi: ogni
# turno ne aggiunge quattro, quindi dal sesto la richiesta iniziale del cliente
# sparisce. Quello che il bot ha capito deve sopravvivere in dati_temp.


@pytest.mark.asyncio
async def test_la_scelta_del_cliente_viene_annotata_subito():
    from prompts.system_prompt import set_parrucchieri_cache
    from services.conversation import execute_action
    from services.fakes import FakeBackends

    set_parrucchieri_cache(MAPPA_FINTA)
    sessione = {"stato_flusso": "saluto", "dati_temp": {}}

    await execute_action(
        {
            "action": "CHECK_DISPONIBILITA",
            "data": GIORNO,
            "parrucchiere": "Francesco",
            "servizi": ["Taglio + Barba"],
            "durata_min": 30,
        },
        "393331234567",
        sessione,
        FakeBackends(MAPPA_FINTA),
    )

    assert sessione["dati_temp"]["servizio"] == "Taglio + Barba"
    assert sessione["dati_temp"]["parrucchiere"] == "Francesco"
    assert sessione["stato_flusso"] == "scelta_slot"


@pytest.mark.asyncio
async def test_la_durata_la_decide_il_catalogo_non_claude():
    """Con una durata sottostimata gli slot proposti sarebbero liberi solo in apparenza."""
    from prompts.system_prompt import set_parrucchieri_cache
    from services.conversation import execute_action
    from services.fakes import FakeBackends

    set_parrucchieri_cache(MAPPA_FINTA)

    class BackendsSpia(FakeBackends):
        def __init__(self, parrucchieri):
            super().__init__(parrucchieri)
            self.durata_richiesta = None

        async def check_availability(self, date_str, parrucchiere_cal_id, durata_min):
            self.durata_richiesta = durata_min
            return await super().check_availability(
                date_str, parrucchiere_cal_id, durata_min
            )

    backends = BackendsSpia(MAPPA_FINTA)

    await execute_action(
        {
            "action": "CHECK_DISPONIBILITA",
            "data": GIORNO,
            "parrucchiere": "Francesco",
            "servizi": ["Colore + Taglio + Trattamento capello"],
            "durata_min": 30,  # il modello sbaglia: il colore dura due ore
        },
        "393331234567",
        {"stato_flusso": "saluto", "dati_temp": {}},
        backends,
    )

    assert backends.durata_richiesta == 120


@pytest.mark.asyncio
async def test_la_scelta_sopravvive_alla_troncatura_dello_storico(mock_redis):
    from prompts.system_prompt import set_parrucchieri_cache
    from services.channels import CollectorChannel
    from services.fakes import FakeBackends
    from services.session_manager import get_session

    set_parrucchieri_cache(MAPPA_FINTA)
    backends = FakeBackends(MAPPA_FINTA)
    telefono = "393339999999"

    azione = ScriptedClaude.azione(
        action="CHECK_DISPONIBILITA",
        data=GIORNO,
        parrucchiere="Francesco",
        servizi=["Taglio + Barba"],
        durata_min=30,
    )
    copione = []
    for _ in range(8):
        copione += [azione, "Ecco gli orari."]
    claude = ScriptedClaude(copione)

    for i in range(8):
        await handle_incoming_message(
            redis=mock_redis,
            phone=telefono,
            text=f"messaggio {i}",
            msg_type="text",
            channel=CollectorChannel(),
            backends=backends,
            claude=claude,
        )

    sessione = await get_session(mock_redis, telefono)
    contenuti = " ".join(str(m["content"]) for m in sessione["history"])

    assert "messaggio 0" not in contenuti, "lo storico dev'essere stato troncato"
    assert sessione["dati_temp"]["servizio"] == "Taglio + Barba"
    assert sessione["dati_temp"]["parrucchiere"] == "Francesco"
    assert sessione["stato_flusso"] != "saluto"


@pytest.mark.asyncio
async def test_i_limiti_dei_bottoni_li_decide_il_canale():
    """Il widget del sito non ha limiti di lunghezza, WhatsApp sì."""
    from services.channels import CollectorChannel, MetaWhatsAppChannel
    from services.conversation import deliver

    risposta = (
        "Che servizio desideri?\n"
        "- Taglio\n"
        "- Colore + Taglio + Trattamento capello"
    )

    # Sul sito i bottoni sono elementi HTML: ci sta qualunque nome del listino
    sito = CollectorChannel()
    await deliver(sito, "web_1", risposta)
    assert sito.ultimo()["options"] is not None
    assert len(sito.ultimo()["options"]) == 2

    # Su WhatsApp un titolo lungo verrebbe tagliato, e tornerebbe indietro
    # tagliato anche nella risposta del cliente: meglio l'elenco come testo
    class WhatsAppFinto(CollectorChannel):
        lunghezza_massima_opzione = MetaWhatsAppChannel.lunghezza_massima_opzione

    whatsapp = WhatsAppFinto()
    await deliver(whatsapp, "393331234567", risposta)
    assert whatsapp.ultimo()["options"] is None
    assert whatsapp.ultimo()["text"] == risposta


def test_il_markdown_non_finisce_nelle_etichette():
    """Claude scrive **grassetto**, che nessuno dei due canali interpreta."""
    risposta = "Ecco gli orari:\n- Oggi alle **08:00**\n- Oggi alle **08:30**"

    _, opzioni = parse_response_with_options(risposta)

    assert [o["title"] for o in opzioni] == ["Oggi alle 08:00", "Oggi alle 08:30"]
