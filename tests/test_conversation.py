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


def test_un_opzione_non_porta_una_descrizione_uguale_al_titolo():
    """Nelle liste di WhatsApp titolo e descrizione finiscono uno sotto l'altro.

    Riempire la descrizione con la stessa riga faceva arrivare al cliente
    "Indifferente" scritto due volte.
    """
    _, opzioni = parse_response_with_options("Preferenze?\n- Francesco\n- Indifferente")

    for opzione in opzioni:
        assert not opzione.get("description")


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


# ------------------------------------------------------- saluto del widget web


@pytest.mark.asyncio
async def test_il_saluto_iniziale_entra_nello_storico(mock_redis):
    from services.conversation import SALUTO_INIZIALE, apri_conversazione_web
    from services.session_manager import get_session

    assert await apri_conversazione_web(mock_redis, "web_prova") == SALUTO_INIZIALE

    sessione = await get_session(mock_redis, "web_prova")
    assert sessione["history"] == [{"role": "assistant", "content": SALUTO_INIZIALE}]

    # Chi si riconnette sta riprendendo un discorso: niente saluto bis
    assert await apri_conversazione_web(mock_redis, "web_prova") is None
    sessione = await get_session(mock_redis, "web_prova")
    assert len(sessione["history"]) == 1


@pytest.mark.asyncio
async def test_chi_riprende_la_conversazione_rivede_i_messaggi(mock_redis):
    """Il riquadro del browser è vuoto dopo un ricaricamento, la memoria del bot no."""
    from prompts.system_prompt import set_parrucchieri_cache
    from services.conversation import (
        SALUTO_INIZIALE,
        apri_conversazione_web,
        handle_incoming_message_web,
        storico_visibile_web,
    )
    from services.fakes import FakeBackends

    set_parrucchieri_cache(MAPPA_FINTA)
    backends = FakeBackends(MAPPA_FINTA)

    claude = ScriptedClaude(
        [
            ScriptedClaude.azione(
                action="CHECK_DISPONIBILITA",
                data=GIORNO,
                parrucchiere="Francesco",
                servizi=["Taglio"],
            ),
            "Ecco gli orari liberi.",
        ]
    )

    await apri_conversazione_web(mock_redis, "web_0123456789ab")
    await handle_incoming_message_web(
        redis=mock_redis,
        session_id="web_0123456789ab",
        text="vorrei un taglio",
        backends=backends,
        claude=claude,
    )

    storico = await storico_visibile_web(mock_redis, "web_0123456789ab")
    testi = [m["text"] for m in storico]

    assert testi == [SALUTO_INIZIALE, "vorrei un taglio", "Ecco gli orari liberi."]
    assert [m["role"] for m in storico] == ["assistant", "user", "assistant"]

    # La meccanica interna non deve finire sotto gli occhi del cliente
    assert not any("[SISTEMA]" in t for t in testi)
    assert not any("CHECK_DISPONIBILITA" in t for t in testi)


def test_il_browser_non_puo_chiedere_la_sessione_di_un_altro():
    """L'identificativo arriva dal client e diventa una chiave in Redis.

    Le conversazioni WhatsApp sono indicizzate per numero di telefono: senza
    un vincolo di formato, dal sito si potrebbe chiedere la sessione di un
    cliente e leggersi il suo storico.
    """
    from routers.chat_ws import _sessione_richiesta

    class FintoWebSocket:
        def __init__(self, valore):
            self.query_params = {"sessione": valore} if valore else {}

    valido = "web_0123456789ab"
    assert _sessione_richiesta(FintoWebSocket(valido)) == valido

    for tentativo in [
        "393331234567",
        "web_../393331234567",
        "WEB_0123456789AB",
        "web_zzzzzzzzzzzz",
        "session:393331234567",
        "",
    ]:
        ottenuto = _sessione_richiesta(FintoWebSocket(tentativo))
        assert ottenuto != tentativo
        assert ottenuto.startswith("web_")


@pytest.mark.asyncio
async def test_chi_risponde_si_al_saluto_viene_capito(mock_redis, backends):
    """Il saluto scritto nella pagina non esisteva per il bot, che si ripresentava."""
    from services.conversation import (
        SALUTO_INIZIALE,
        apri_conversazione_web,
        handle_incoming_message_web,
    )

    claude = ScriptedClaude(["Perfetto! Quale servizio desideri?"])

    await apri_conversazione_web(mock_redis, "web_prova")
    await handle_incoming_message_web(
        redis=mock_redis,
        session_id="web_prova",
        text="si",
        backends=backends,
        claude=claude,
    )

    storico = claude.chiamate[0]["history"]
    assert storico[0]["content"] == SALUTO_INIZIALE
    assert storico[1]["content"] == "si"


# ------------------------------------------------------ numero di telefono
#
# Da WhatsApp il numero è il mittente. Dal sito no, e alla receptionist serve
# per avvisare in caso di imprevisti: va chiesto, senza obbligare.


def test_il_numero_si_chiede_solo_a_chi_scrive_dal_sito(sample_session):
    from prompts.system_prompt import build_system_prompt

    dal_sito = build_system_prompt(sample_session, canale="web")
    assert "non ci è noto" in dal_sito
    assert "NON è obbligatorio" in dal_sito

    da_whatsapp = build_system_prompt(sample_session, canale="whatsapp")
    assert "NON chiederglielo" in da_whatsapp


def test_i_numeri_scritti_a_mano_vengono_ripuliti():
    from services.conversation import _normalizza_telefono

    assert _normalizza_telefono("+39 347 123 45 67") == "+393471234567"
    assert _normalizza_telefono("347-123-4567") == "3471234567"
    # Quello che non è un numero non deve finire in anagrafica
    assert _normalizza_telefono("non te lo dico") is None
    assert _normalizza_telefono("123") is None
    assert _normalizza_telefono("") is None
    assert _normalizza_telefono(None) is None


@pytest.mark.asyncio
async def test_il_numero_lasciato_dal_sito_diventa_l_identita_del_cliente(mock_redis):
    """Così chi prenota dal sito viene riconosciuto se domani scrive su WhatsApp."""
    from prompts.system_prompt import set_parrucchieri_cache
    from services.conversation import handle_incoming_message_web
    from services.fakes import FakeBackends

    set_parrucchieri_cache(MAPPA_FINTA)
    backends = FakeBackends(MAPPA_FINTA)

    claude = ScriptedClaude(
        [
            ScriptedClaude.azione(
                action="CREA_APPUNTAMENTO",
                slot=f"{GIORNO}T09:00",
                parrucchiere="Francesco",
                servizi=["Taglio"],
                nome="Mario",
                cognome="Rossi",
                telefono="+39 347 123 45 67",
            ),
            "Prenotazione confermata!",
        ]
    )

    await handle_incoming_message_web(
        redis=mock_redis,
        session_id="web_0123456789ab",
        text="confermo",
        backends=backends,
        claude=claude,
    )

    assert backends.clienti, "il cliente deve essere stato creato"
    cliente = backends.clienti[0]
    assert cliente["telefono"] == "+393471234567"
    assert cliente["canale"] == "web"

    # Lo stesso numero da WhatsApp deve ritrovare la stessa persona
    ritrovato = await backends.find_or_create_client(phone="+393471234567")
    assert ritrovato["is_new"] is False
    assert ritrovato["nome"] == "Mario"


# --------------------------------------------------- storico degli appuntamenti
#
# L'azione non accetta nessun contatto: usa il numero della conversazione, che
# su WhatsApp è verificato dal gestore. Così non è nemmeno formulabile la
# richiesta dello storico di un altro.


async def _cliente_con_appuntamento(backends, telefono="393331234567"):
    cliente = await backends.find_or_create_client(
        phone=telefono, nome="Mario", cognome="Rossi"
    )
    event_id = await backends.create_event(
        slot=f"{GIORNO}T09:00",
        parrucchiere_cal_id=MAPPA_FINTA["Francesco"],
        servizi=["Taglio"],
        durata=30,
        cliente_nome="Mario Rossi",
    )
    await backends.create_appointment(
        client_id=cliente["id"],
        data_ora=f"{GIORNO}T09:00",
        servizi=["Taglio"],
        parrucchiere="Francesco",
        gcal_event_id=event_id,
        durata_min=30,
        prezzo=13.5,
    )
    return event_id


@pytest.mark.asyncio
async def test_lo_storico_arriva_dal_numero_di_chi_scrive():
    from prompts.system_prompt import set_parrucchieri_cache
    from services.conversation import execute_action
    from services.fakes import FakeBackends

    set_parrucchieri_cache(MAPPA_FINTA)
    backends = FakeBackends(MAPPA_FINTA)
    event_id = await _cliente_con_appuntamento(backends)

    sessione = {"stato_flusso": "saluto", "dati_temp": {}}
    risultato = await execute_action(
        {"action": "STORICO_APPUNTAMENTI"}, "393331234567", sessione, backends
    )

    assert risultato["cliente_conosciuto"] is True
    assert risultato["nome"] == "Mario"
    assert len(risultato["appuntamenti"]) == 1

    appuntamento = risultato["appuntamenti"][0]
    assert appuntamento["gcal_event_id"] == event_id
    assert appuntamento["app_id"] == 1
    assert appuntamento["parrucchiere"] == "Francesco"

    # Il nome si annota, ma la fase non avanza: non ha ancora scelto niente
    assert sessione["dati_temp"]["nome"] == "Mario"
    assert sessione["stato_flusso"] == "saluto"


@pytest.mark.asyncio
async def test_dal_sito_lo_storico_non_si_puo_leggere():
    """Sul sito non sappiamo chi scrive: mostrarlo sarebbe darlo a chiunque."""
    from prompts.system_prompt import set_parrucchieri_cache
    from services.conversation import execute_action
    from services.fakes import FakeBackends

    set_parrucchieri_cache(MAPPA_FINTA)
    backends = FakeBackends(MAPPA_FINTA)
    await _cliente_con_appuntamento(backends)

    risultato = await execute_action(
        {"action": "STORICO_APPUNTAMENTI"},
        "web_0123456789ab",
        {"stato_flusso": "saluto", "dati_temp": {}},
        backends,
    )

    assert "errore" in risultato
    assert "appuntamenti" not in risultato


@pytest.mark.asyncio
async def test_un_numero_sconosciuto_non_ha_storico():
    from prompts.system_prompt import set_parrucchieri_cache
    from services.conversation import execute_action
    from services.fakes import FakeBackends

    set_parrucchieri_cache(MAPPA_FINTA)

    risultato = await execute_action(
        {"action": "STORICO_APPUNTAMENTI"},
        "393339999999",
        {"stato_flusso": "saluto", "dati_temp": {}},
        FakeBackends(MAPPA_FINTA),
    )

    assert risultato["cliente_conosciuto"] is False
    assert "appuntamenti" not in risultato


@pytest.mark.asyncio
async def test_si_puo_disdire_usando_i_dati_dello_storico(mock_redis, canale):
    """Prima era impossibile: al modello mancavano app_id e gcal_event_id."""
    from prompts.system_prompt import set_parrucchieri_cache
    from services.fakes import FakeBackends

    set_parrucchieri_cache(MAPPA_FINTA)
    backends = FakeBackends(MAPPA_FINTA)
    cal_id = MAPPA_FINTA["Francesco"]
    event_id = await _cliente_con_appuntamento(backends)

    occupati = [s["slot"] for s in await backends.check_availability(GIORNO, cal_id, 30)]
    assert f"{GIORNO}T09:00" not in occupati

    claude = ScriptedClaude(
        [
            ScriptedClaude.azione(action="STORICO_APPUNTAMENTI"),
            ScriptedClaude.azione(
                action="CANCELLA_APPUNTAMENTO",
                app_id=1,
                gcal_event_id=event_id,
                parrucchiere="Francesco",
            ),
            "Fatto, ho disdetto il tuo appuntamento.",
        ]
    )

    await handle_incoming_message(
        redis=mock_redis,
        phone="393331234567",
        text="devo disdire l'appuntamento",
        msg_type="text",
        channel=canale,
        backends=backends,
        claude=claude,
    )

    assert canale.ultimo()["text"] == "Fatto, ho disdetto il tuo appuntamento."
    assert backends.appuntamenti[0]["stato"] == "Cancellato"

    liberi = [s["slot"] for s in await backends.check_availability(GIORNO, cal_id, 30)]
    assert f"{GIORNO}T09:00" in liberi, "l'orario deve tornare prenotabile"


@pytest.mark.asyncio
async def test_il_numero_vero_sostituisce_l_identificativo_di_sessione():
    """Chi nasce dal sito è registrato con un identificativo che non identifica nessuno."""
    from prompts.system_prompt import set_parrucchieri_cache
    from services.fakes import FakeBackends

    set_parrucchieri_cache(MAPPA_FINTA)
    backends = FakeBackends(MAPPA_FINTA)

    # Prima visita dal sito: nessun numero, solo l'email
    await backends.find_or_create_client(
        phone="web_0123456789ab", nome="Mario", email="mario@example.it", canale="web"
    )
    assert backends.clienti[0]["telefono"] == "web_0123456789ab"

    # Torna e lascia il numero: da quel momento è quella la sua identità
    ritrovato = await backends.find_or_create_client(
        phone="393331234567", email="mario@example.it"
    )
    assert ritrovato["is_new"] is False
    assert backends.clienti[0]["telefono"] == "393331234567"

    # E scrivendo da WhatsApp viene riconosciuto
    da_whatsapp = await backends.find_or_create_client(phone="393331234567")
    assert da_whatsapp["is_new"] is False
    assert da_whatsapp["nome"] == "Mario"


@pytest.mark.asyncio
async def test_spostare_non_lascia_due_appuntamenti(monkeypatch):
    """Nel database la riga è la stessa: spostato, non annullato più preso."""
    from config import settings
    from prompts.system_prompt import set_parrucchieri_cache
    from services.conversation import execute_action
    from services.fakes import FakeBackends

    monkeypatch.setattr(settings, "cancel_policy_hours", 2)
    set_parrucchieri_cache(MAPPA_FINTA)

    backends = FakeBackends(MAPPA_FINTA)
    cal_id = MAPPA_FINTA["Francesco"]
    cliente = await backends.find_or_create_client(
        phone="393331234567", nome="Mario", cognome="Rossi", email="mario@example.it"
    )
    vecchio_evento = await backends.create_event(
        slot=f"{GIORNO}T09:00",
        parrucchiere_cal_id=cal_id,
        servizi=["Taglio"],
        durata=30,
        cliente_nome="Mario Rossi",
    )
    await backends.create_appointment(
        client_id=cliente["id"],
        data_ora=f"{GIORNO}T09:00",
        servizi=["Taglio"],
        parrucchiere="Francesco",
        gcal_event_id=vecchio_evento,
        durata_min=30,
    )

    esito = await execute_action(
        {
            "action": "SPOSTA_APPUNTAMENTO",
            "app_id": 1,
            "slot": f"{GIORNO}T11:00",
        },
        "393331234567",
        {"stato_flusso": "saluto", "dati_temp": {}},
        backends,
    )

    assert esito["spostamento"] == "completato"
    assert esito["da"] == f"{GIORNO}T09:00"
    assert esito["a"] == f"{GIORNO}T11:00"

    # Una riga sola, spostata
    assert len(backends.appuntamenti) == 1
    assert backends.appuntamenti[0]["data_ora"] == f"{GIORNO}T11:00"
    assert backends.appuntamenti[0]["stato"] == "Confermato"

    # Sul calendario il vecchio evento non c'è più e il vecchio orario è libero
    assert vecchio_evento not in backends.eventi
    liberi = [s["slot"] for s in await backends.check_availability(GIORNO, cal_id, 30)]
    assert f"{GIORNO}T09:00" in liberi
    assert f"{GIORNO}T11:00" not in liberi

    # Una sola email, quella di spostamento
    assert len(backends.email_spostamenti) == 1
    assert backends.email_spostamenti[0]["da"] == f"{GIORNO}T09:00"
    assert backends.email_spostamenti[0]["a"] == f"{GIORNO}T11:00"
    assert backends.email_cancellazioni == []


@pytest.mark.asyncio
async def test_non_si_sposta_su_un_orario_occupato(monkeypatch):
    """Altrimenti si finirebbe sopra a un altro cliente."""
    from config import settings
    from prompts.system_prompt import set_parrucchieri_cache
    from services.conversation import execute_action
    from services.fakes import FakeBackends

    monkeypatch.setattr(settings, "cancel_policy_hours", 2)
    set_parrucchieri_cache(MAPPA_FINTA)

    backends = FakeBackends(MAPPA_FINTA)
    cal_id = MAPPA_FINTA["Francesco"]
    await _cliente_con_appuntamento(backends)
    # Qualcun altro ha già preso le 11:00
    backends.occupa(cal_id, f"{GIORNO}T11:00", 30)

    esito = await execute_action(
        {"action": "SPOSTA_APPUNTAMENTO", "app_id": 1, "slot": f"{GIORNO}T11:00"},
        "393331234567",
        {"stato_flusso": "saluto", "dati_temp": {}},
        backends,
    )

    assert "errore" in esito
    assert backends.appuntamenti[0]["data_ora"] == f"{GIORNO}T09:00", (
        "l'appuntamento non si deve muovere"
    )


@pytest.mark.asyncio
async def test_la_disdetta_viene_confermata_per_email(monkeypatch):
    """Chi non ha chiesto lui la disdetta se ne accorgerebbe solo al salone."""
    from config import settings
    from prompts.system_prompt import set_parrucchieri_cache
    from services.conversation import execute_action
    from services.fakes import FakeBackends

    monkeypatch.setattr(settings, "cancel_policy_hours", 2)
    set_parrucchieri_cache(MAPPA_FINTA)

    backends = FakeBackends(MAPPA_FINTA)
    cliente = await backends.find_or_create_client(
        phone="393331234567", nome="Mario", cognome="Rossi", email="mario@example.it"
    )
    await backends.create_appointment(
        client_id=cliente["id"],
        data_ora=f"{GIORNO}T09:00",
        servizi=["Taglio + Barba"],
        parrucchiere="Francesco",
        gcal_event_id="evt_1",
        durata_min=30,
    )

    esito = await execute_action(
        {"action": "CANCELLA_APPUNTAMENTO", "app_id": 1, "gcal_event_id": "evt_1"},
        "393331234567",
        {"stato_flusso": "saluto", "dati_temp": {}},
        backends,
    )

    assert esito["cancellazione"] == "completata"
    assert len(backends.email_cancellazioni) == 1

    email = backends.email_cancellazioni[0]
    assert email["to"] == "mario@example.it"
    assert email["data_ora"] == f"{GIORNO}T09:00"
    assert email["servizi"] == ["Taglio + Barba"]


@pytest.mark.asyncio
async def test_senza_email_la_disdetta_si_fa_lo_stesso(monkeypatch):
    """L'indirizzo non è obbligatorio: chi non l'ha lasciato deve poter disdire."""
    from config import settings
    from prompts.system_prompt import set_parrucchieri_cache
    from services.conversation import execute_action
    from services.fakes import FakeBackends

    monkeypatch.setattr(settings, "cancel_policy_hours", 2)
    set_parrucchieri_cache(MAPPA_FINTA)

    backends = FakeBackends(MAPPA_FINTA)
    await _cliente_con_appuntamento(backends)  # senza email

    esito = await execute_action(
        {"action": "CANCELLA_APPUNTAMENTO", "app_id": 1},
        "393331234567",
        {"stato_flusso": "saluto", "dati_temp": {}},
        backends,
    )

    assert esito["cancellazione"] == "completata"
    assert backends.email_cancellazioni == []


@pytest.mark.asyncio
async def test_non_si_disdice_a_ridosso_dell_appuntamento(monkeypatch):
    """Sotto il preavviso minimo la disdetta la gestisce il salone al telefono."""
    from datetime import timedelta

    from config import settings
    from prompts.system_prompt import set_parrucchieri_cache
    from services.conversation import execute_action
    from services.fakes import FakeBackends
    from services.slots import adesso_salone

    monkeypatch.setattr(settings, "cancel_policy_hours", 2)
    monkeypatch.setattr(settings, "salone_telefono", "0123 456789")
    set_parrucchieri_cache(MAPPA_FINTA)

    backends = FakeBackends(MAPPA_FINTA)
    cliente = await backends.find_or_create_client(phone="393331234567", nome="Mario")
    fra_un_ora = (adesso_salone() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
    await backends.create_appointment(
        client_id=cliente["id"],
        data_ora=fra_un_ora,
        servizi=["Taglio"],
        parrucchiere="Francesco",
        gcal_event_id="evt_1",
        durata_min=30,
    )

    risultato = await execute_action(
        {"action": "CANCELLA_APPUNTAMENTO", "app_id": 1, "gcal_event_id": "evt_1"},
        "393331234567",
        {"stato_flusso": "saluto", "dati_temp": {}},
        backends,
    )

    assert "errore" in risultato
    assert "0123 456789" in risultato["errore"], "il numero del salone va riferito"
    assert backends.appuntamenti[0]["stato"] == "Confermato"


@pytest.mark.asyncio
async def test_non_si_disdice_l_appuntamento_di_un_altro(monkeypatch):
    """Gli id sono progressivi: senza controllo basterebbe indovinarne uno."""
    from config import settings
    from prompts.system_prompt import set_parrucchieri_cache
    from services.conversation import execute_action
    from services.fakes import FakeBackends

    monkeypatch.setattr(settings, "cancel_policy_hours", 2)
    set_parrucchieri_cache(MAPPA_FINTA)

    backends = FakeBackends(MAPPA_FINTA)
    await _cliente_con_appuntamento(backends, telefono="393331234567")

    # Scrive un altro numero, chiedendo di cancellare l'appuntamento numero 1
    risultato = await execute_action(
        {"action": "CANCELLA_APPUNTAMENTO", "app_id": 1},
        "393339999999",
        {"stato_flusso": "saluto", "dati_temp": {}},
        backends,
    )

    assert "errore" in risultato
    assert backends.appuntamenti[0]["stato"] == "Confermato"


# ------------------------------------------- codice di verifica dal sito web
#
# Dal sito non sappiamo chi scrive: l'identità la prova la casella di posta,
# come su WhatsApp la prova il numero. Il codice vive nella sessione, lato
# server, e non passa mai dal modello.


async def _cliente_con_email(backends, email="mario@example.it"):
    cliente = await backends.find_or_create_client(
        phone="web_vecchia_sessione", nome="Mario", cognome="Rossi", email=email
    )
    await backends.create_appointment(
        client_id=cliente["id"],
        data_ora=f"{GIORNO}T09:00",
        servizi=["Taglio"],
        parrucchiere="Francesco",
        gcal_event_id="evt_web",
        durata_min=30,
    )


@pytest.mark.asyncio
async def test_dal_sito_lo_storico_si_sblocca_col_codice():
    from prompts.system_prompt import set_parrucchieri_cache
    from services.conversation import execute_action
    from services.fakes import FakeBackends

    set_parrucchieri_cache(MAPPA_FINTA)
    backends = FakeBackends(MAPPA_FINTA)
    await _cliente_con_email(backends)

    sessione = {"stato_flusso": "saluto", "dati_temp": {}}
    web = "web_0123456789ab"

    # Senza verifica non si vede niente
    primo = await execute_action(
        {"action": "STORICO_APPUNTAMENTI"}, web, sessione, backends
    )
    assert "errore" in primo

    # Il codice parte per email
    invio = await execute_action(
        {"action": "INVIA_CODICE_VERIFICA", "email": "mario@example.it"},
        web,
        sessione,
        backends,
    )
    assert invio["codice_inviato"] is True
    assert backends.codici_inviati[0]["to"] == "mario@example.it"

    # Il codice non deve comparire nel risultato: finirebbe nello storico
    assert "codice" not in invio

    codice = backends.codici_inviati[0]["codice"]
    assert len(codice) == 6 and codice.isdigit()

    # Un codice sbagliato non sblocca
    sbagliato = await execute_action(
        {"action": "VERIFICA_CODICE", "codice": "000000"}, web, sessione, backends
    )
    if sbagliato.get("verificato") is not False:  # pragma: no cover - improbabile
        pytest.skip("il codice generato era proprio 000000")
    assert "email_verificata" not in sessione

    # Quello giusto sì
    giusto = await execute_action(
        {"action": "VERIFICA_CODICE", "codice": codice}, web, sessione, backends
    )
    assert giusto["verificato"] is True
    assert sessione["email_verificata"] == "mario@example.it"

    storico = await execute_action(
        {"action": "STORICO_APPUNTAMENTI"}, web, sessione, backends
    )
    assert storico["cliente_conosciuto"] is True
    assert len(storico["appuntamenti"]) == 1


@pytest.mark.asyncio
async def test_il_codice_scade_dopo_troppi_tentativi():
    from prompts.system_prompt import set_parrucchieri_cache
    from services.conversation import MAX_TENTATIVI_CODICE, execute_action
    from services.fakes import FakeBackends

    set_parrucchieri_cache(MAPPA_FINTA)
    backends = FakeBackends(MAPPA_FINTA)
    sessione = {"stato_flusso": "saluto", "dati_temp": {}}
    web = "web_0123456789ab"

    await execute_action(
        {"action": "INVIA_CODICE_VERIFICA", "email": "mario@example.it"},
        web,
        sessione,
        backends,
    )

    for _ in range(MAX_TENTATIVI_CODICE + 1):
        esito = await execute_action(
            {"action": "VERIFICA_CODICE", "codice": "999999"}, web, sessione, backends
        )

    assert esito["verificato"] is False
    assert "verifica" not in sessione, "il codice bruciato va buttato via"
    assert "email_verificata" not in sessione


@pytest.mark.asyncio
async def test_su_whatsapp_il_codice_non_serve():
    from prompts.system_prompt import set_parrucchieri_cache
    from services.conversation import execute_action
    from services.fakes import FakeBackends

    set_parrucchieri_cache(MAPPA_FINTA)
    backends = FakeBackends(MAPPA_FINTA)

    esito = await execute_action(
        {"action": "INVIA_CODICE_VERIFICA", "email": "mario@example.it"},
        "393331234567",
        {"stato_flusso": "saluto", "dati_temp": {}},
        backends,
    )

    assert "errore" in esito
    assert not backends.codici_inviati


def test_il_markdown_non_finisce_nelle_etichette():
    """Claude scrive **grassetto**, che nessuno dei due canali interpreta."""
    risposta = "Ecco gli orari:\n- Oggi alle **08:00**\n- Oggi alle **08:30**"

    _, opzioni = parse_response_with_options(risposta)

    assert [o["title"] for o in opzioni] == ["Oggi alle 08:00", "Oggi alle 08:30"]
