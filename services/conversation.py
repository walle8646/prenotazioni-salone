"""Orchestratore della conversazione.

È il cuore del bot: prende un messaggio in arrivo, ricostruisce la sessione,
chiede a Claude cosa rispondere ed esegue le azioni richieste (verifica
disponibilità, creazione o cancellazione appuntamento).

Volutamente non conosce né il canale né i servizi esterni: riceve un `Channel`
su cui scrivere, un `Backends` da cui leggere e una funzione `claude` da
chiamare. È questo che permette di far girare l'intero flusso di prenotazione
su WhatsApp, sul sito, in un test automatico o nel simulatore da terminale
senza cambiare una riga di questa logica.
"""

from __future__ import annotations

import json
import logging
import re
import secrets

from prompts.system_prompt import (
    build_system_prompt,
    get_cal_id_for_parrucchiere,
    get_parrucchieri_map_cached,
)
from services.channels import Channel, MetaWhatsAppChannel, WebChannel
from services.operatori import PREFISSO_NON_CONFIGURATO
from services.session_manager import get_session, new_session, save_session

logger = logging.getLogger(__name__)

# Quante volte al massimo Claude può chiedere un'azione prima di dover
# rispondere al cliente. Evita loop infiniti se il modello continua a
# richiedere azioni senza mai concludere.
#
# Tre erano poche: quando il cliente chiede "il primo posto libero" il modello
# interroga più giorni di fila e restava senza iterazioni prima di aver scritto
# qualcosa, facendo arrivare al cliente il messaggio di errore tecnico.
MAX_ITERATIONS = 5

# Oltre questa lunghezza una riga non è più una scelta ma un ragionamento, e
# come bottone non avrebbe senso. I limiti dei singoli canali (WhatsApp accorcia
# i titoli, il sito no) li dichiara il canale: qui non se ne sa nulla.
LUNGHEZZA_MASSIMA_OPZIONE = 120

MESSAGGIO_TIPO_NON_SUPPORTATO = (
    "Mi dispiace, al momento posso leggere solo messaggi di testo e foto. "
    "Puoi riscrivermi?"
)
MESSAGGIO_FALLBACK = (
    "Scusami, sto avendo un problema tecnico nel completare la richiesta. "
    "Puoi riprovare tra poco?"
)
SALUTO_INIZIALE = (
    "Ciao! Sono Nadia, l'assistente del salone. Come posso aiutarti? "
    "Vuoi prenotare un appuntamento?"
)
MESSAGGIO_RICOMINCIATO = (
    "Va bene, ricominciamo da capo. Dimmi pure, cosa posso fare per te?"
)

# La sessione dura due ore: senza una via d'uscita, chi lascia a metà una
# prenotazione se la ritrova addosso al messaggio dopo, e non ha modo di
# dire "lascia stare". Fra queste parole non c'è "annulla", e non va aggiunta:
# è quella con cui si disdice un appuntamento, e le due cose non si somigliano
# per niente.
_RICOMINCIARE = re.compile(
    r"^\W*("
    r"ricomincia(mo|re)?|"
    r"ripart(i|iamo|ire)|"
    r"azzera(re)?|"
    r"reset|"
    r"nuova conversazione"
    r")(\s+(da\s+capo|tutto))?\W*$",
    re.IGNORECASE,
)


def vuole_ricominciare(text: str | None) -> bool:
    """True se il cliente sta chiedendo di buttare via la conversazione.

    Deve corrispondere l'intero messaggio: "ricominciamo da capo" azzera,
    "ricominciamo dalla scelta dell'orario" no, perché lì il contesto serve.
    """
    return bool(text and _RICOMINCIARE.match(text.strip()))


async def _ricomincia(redis, session_key: str, channel: Channel) -> None:
    """Butta via la sessione e riparte, annotando il proprio messaggio.

    Il messaggio va anche nello storico della sessione nuova: se non ci fosse,
    a un "sì" successivo il modello riceverebbe una conversazione che comincia
    lì, senza sapere a cosa si riferisce.
    """
    sessione = new_session()
    sessione["history"].append(
        {"role": "assistant", "content": MESSAGGIO_RICOMINCIATO}
    )
    await save_session(redis, session_key, sessione)
    await channel.send_text(session_key, MESSAGGIO_RICOMINCIATO)


async def _claude_reale(system_prompt: str, history: list[dict]) -> str:
    from services.claude_client import call_claude

    return await call_claude(system_prompt, history)


def _backends_reali():
    from services.backends import RealBackends

    return RealBackends()


def _nome_della_voce(testo: str) -> str:
    """La parte di una scelta che la identifica, senza prezzo né durata.

    Claude scrive le scelte come "Taglio + Shampoo — 17,50 € — 30 min". Sul
    bottone serve solo "Taglio + Shampoo": il resto occupa i pochi caratteri
    che WhatsApp concede al titolo, ed è già scritto nel messaggio sopra.
    """
    separatore = re.search(r"\s[—–-]\s", testo)
    if not separatore:
        return testo
    return testo[: separatore.start()].strip() or testo


def parse_response_with_options(response: str) -> tuple[str, list[dict] | None]:
    """Estrae dalla risposta di Claude le eventuali opzioni cliccabili.

    Cerca righe che iniziano con - o • e le trasforma in opzioni selezionabili.
    Restituisce (testo_pulito, opzioni) oppure (testo_originale, None).
    """
    lines = response.strip().split("\n")
    options: list[dict] = []
    text_lines: list[str] = []
    tutte_convertibili = True

    for line in lines:
        stripped = line.strip()
        match = re.match(r"^[-•]\s*(.+)$", stripped)
        if match:
            option_text = match.group(1).strip()
            # Rimuovi eventuali emoji iniziali dal titolo del bottone
            clean_title = re.sub(
                r"^[\U0001F300-\U0001FAFF☀-➿\s✂️🚿🧔💈]+", "", option_text
            ).strip()
            # Claude scrive volentieri in markdown, che né WhatsApp né il widget
            # interpretano: sul bottone comparirebbe "Oggi alle **08:00**".
            clean_title = clean_title.replace("**", "").replace("__", "").strip()
            if clean_title and len(clean_title) <= LUNGHEZZA_MASSIMA_OPZIONE:
                nome = _nome_della_voce(clean_title)
                opzione = {"id": f"opt_{len(options)}", "title": nome}
                # La descrizione porta la riga per intero, e serve a due cose:
                # mostrare prezzo e durata sotto al titolo, ed essere ciò che
                # torna indietro quando il cliente tocca la riga, anche se il
                # titolo è stato accorciato. Quando coincide col titolo resta
                # vuota: WhatsApp le stampa entrambe, e al cliente arrivava
                # "Indifferente" scritto due volte.
                if clean_title != nome:
                    opzione["description"] = clean_title
                options.append(opzione)
                continue
            # Una voce troppo lunga per essere una scelta: se convertissimo solo
            # le altre, il cliente si troverebbe un elenco scritto e dei bottoni
            # che non gli corrispondono. Meglio lasciare tutto testo.
            tutte_convertibili = False
        text_lines.append(line)

    # Opzioni solo se ce ne sono almeno due e l'elenco è convertibile per intero
    if len(options) >= 2 and tutte_convertibili:
        clean_text = "\n".join(text_lines).strip() or "Scegli un'opzione:"
        # Togliendo le righe dell'elenco restano i buchi dove stavano: senza
        # questo il cliente legge "Ecco gli orari:" seguito da tre righe vuote.
        clean_text = re.sub(r"\n{3,}", "\n\n", clean_text)
        return clean_text, options

    return response, None


def try_parse_action(response: str) -> tuple[dict | None, str | None]:
    """Riconosce se la risposta di Claude contiene un'azione JSON.

    Gestisce sia le risposte interamente JSON sia quelle miste testo + JSON.
    Restituisce (azione, testo_prima_del_json); (None, None) se non è un'azione.
    """
    stripped = response.strip()

    # Caso 1: la risposta è interamente JSON
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            data = json.loads(stripped)
            if isinstance(data, dict) and "action" in data:
                return data, None
        except json.JSONDecodeError:
            pass

    # Caso 2: testo e JSON mescolati — cerca il blocco JSON dentro la risposta
    match = re.search(r'(\{[^{}]*"action"\s*:\s*"[^"]+?"[^{}]*\})', response)
    if match:
        try:
            data = json.loads(match.group(1))
            if isinstance(data, dict) and "action" in data:
                pre_text = response[: match.start()].strip()
                return data, pre_text or None
        except json.JSONDecodeError:
            pass

    return None, None


INDIFFERENTE = "Indifferente"


def con_indifferente(options: list[dict]) -> list[dict]:
    """Aggiunge "Indifferente" a un elenco di operatori che ne è sprovvisto.

    Il prompt lo chiede da sempre, e quasi sempre il modello obbedisce: ma
    "quasi" non basta per una voce che è l'unica via d'uscita di chi non ha
    preferenze. Quando manca, al cliente restano solo scelte impegnative e
    deve scrivere a mano che gli va bene chiunque.

    Si interviene solo quando le voci sono tutte e sole nomi di operatori:
    un elenco di orari o di servizi non c'entra nulla.
    """
    if len(options) < 2:
        return options
    titoli = [o["title"].strip().lower() for o in options]
    if INDIFFERENTE.lower() in titoli:
        return options
    operatori = {nome.strip().lower() for nome in get_parrucchieri_map_cached()}
    if not operatori or not all(titolo in operatori for titolo in titoli):
        return options
    return options + [{"id": f"opt_{len(options)}", "title": INDIFFERENTE}]


async def deliver(channel: Channel, to: str, response: str) -> None:
    """Consegna una risposta sul canale, con bottoni se il testo contiene opzioni.

    Quanto può essere lungo un titolo cliccabile lo sa solo il canale: WhatsApp
    ha limiti stretti, il widget del sito no. Se le opzioni non stanno nei
    limiti si consegna il testo originale, invece di mostrare bottoni che non
    corrispondono a quello che c'è scritto sopra.
    """
    text, options = parse_response_with_options(response)
    if options:
        options = con_indifferente(options)
    if options and channel.opzioni_sostenibili(options):
        await channel.send_options(to, text, options)
    else:
        await channel.send_text(to, response)


async def _run_turn(session_key, session, channel, backends, claude) -> None:
    """Esegue un turno di conversazione: chiama Claude ed esegue le sue azioni."""
    risposta_inviata = False

    for _ in range(MAX_ITERATIONS):
        # Il canale cambia cosa il bot sa già del cliente: da WhatsApp il numero
        # è il mittente, dal sito no.
        system_prompt = build_system_prompt(session, canale=channel.name)
        response = await claude(system_prompt, session["history"])
        action, pre_text = try_parse_action(response)

        if action is None:
            session["history"].append({"role": "assistant", "content": response})
            await deliver(channel, session_key, response)
            risposta_inviata = True
            break

        # Se Claude ha scritto qualcosa prima del JSON, il cliente lo deve vedere
        if pre_text:
            await deliver(channel, session_key, pre_text)
            risposta_inviata = True

        result = await execute_action(action, session_key, session, backends)
        session["history"].append({"role": "assistant", "content": response})
        session["history"].append(
            {
                "role": "user",
                "content": f"[SISTEMA] Risultato azione: {json.dumps(result, ensure_ascii=False)}",
            }
        )

    if not risposta_inviata:
        # Claude ha continuato a chiedere azioni senza mai rispondere al cliente:
        # meglio dire qualcosa che lasciare il messaggio senza risposta.
        logger.warning(
            "Nessuna risposta testuale dopo %s iterazioni per %s",
            MAX_ITERATIONS,
            session_key,
        )
        await channel.send_text(session_key, MESSAGGIO_FALLBACK)


async def handle_incoming_message(
    redis,
    phone: str,
    text: str,
    msg_type: str,
    media_id: str = None,
    contact_name: str = None,
    channel: Channel = None,
    backends=None,
    claude=None,
) -> None:
    """Punto di ingresso per ogni messaggio ricevuto da WhatsApp."""
    channel = channel or MetaWhatsAppChannel()
    backends = backends if backends is not None else _backends_reali()
    claude = claude or _claude_reale

    if msg_type not in ("text", "image", "interactive"):
        await channel.send_text(phone, MESSAGGIO_TIPO_NON_SUPPORTATO)
        return

    if vuole_ricominciare(text):
        await _ricomincia(redis, phone, channel)
        return

    session = await get_session(redis, phone)

    if msg_type == "image" and media_id:
        session["dati_temp"]["foto_media_id"] = media_id

    if contact_name and not session["dati_temp"].get("nome"):
        session["dati_temp"]["nome_profilo_wa"] = contact_name

    session["history"].append(
        {"role": "user", "content": text or "[immagine senza didascalia]"}
    )

    try:
        await _run_turn(phone, session, channel, backends, claude)
    finally:
        # La sessione va salvata anche se qualcosa è andato storto a metà turno,
        # altrimenti il cliente perde il contesto della conversazione.
        await save_session(redis, phone, session)


async def apri_conversazione_web(redis, session_id: str) -> str | None:
    """Registra il saluto come primo turno del bot, se la conversazione è nuova.

    Il saluto stava scritto a mano nella pagina: il cliente lo leggeva, ma per
    la conversazione non esisteva. Rispondendo "sì" il modello riceveva uno
    storico che cominciava lì, non sapeva a cosa si riferisse e si ripresentava
    da capo.

    Restituisce None se la sessione esiste già: chi si riconnette dopo una
    caduta sta riprendendo un discorso, e vedersi salutare di nuovo a metà
    conversazione è il sintomo da cui siamo partiti.
    """
    session = await get_session(redis, session_id)
    if session["history"]:
        return None

    session["history"].append({"role": "assistant", "content": SALUTO_INIZIALE})
    await save_session(redis, session_id, session)
    return SALUTO_INIZIALE


async def storico_visibile_web(redis, session_id: str) -> list[dict]:
    """I messaggi da rimostrare al browser che riprende una conversazione.

    Senza questo il riquadro appariva vuoto pur avendo il bot la memoria intatta:
    il cliente credeva di ricominciare da zero e il bot rispondeva come se il
    discorso fosse a metà.

    Salta la meccanica interna: i risultati delle azioni, che vengono iniettati
    nello storico come se fossero messaggi del cliente, e le azioni JSON del
    modello, che non sono mai state destinate a essere lette.
    """
    session = await get_session(redis, session_id)
    visibili: list[dict] = []

    for messaggio in session.get("history") or []:
        contenuto = messaggio.get("content")
        if not isinstance(contenuto, str) or not contenuto.strip():
            continue

        if messaggio.get("role") == "user":
            if contenuto.startswith("[SISTEMA]"):
                continue
            visibili.append({"role": "user", "text": contenuto})
            continue

        azione, testo_prima = try_parse_action(contenuto)
        if azione is not None:
            # Di un turno con azione si è visto solo l'eventuale testo davanti
            if testo_prima:
                visibili.append({"role": "assistant", "text": testo_prima})
            continue
        visibili.append({"role": "assistant", "text": contenuto})

    return visibili


async def handle_incoming_message_web(
    redis,
    session_id: str,
    text: str,
    email: str = None,
    backends=None,
    claude=None,
) -> dict:
    """Punto di ingresso per i messaggi dal widget di chat del sito.

    Restituisce il dict che il WebSocket manda al browser: {'text', 'options'}.
    """
    channel = WebChannel()
    backends = backends if backends is not None else _backends_reali()
    claude = claude or _claude_reale

    if vuole_ricominciare(text):
        await _ricomincia(redis, session_id, channel)
        return channel.payload()

    session = await get_session(redis, session_id)
    if email:
        session["dati_temp"]["email"] = email

    session["history"].append({"role": "user", "content": text})

    try:
        await _run_turn(session_id, session, channel, backends, claude)
    finally:
        await save_session(redis, session_id, session)

    return channel.payload()


async def execute_action(action: dict, phone: str, session: dict, backends=None) -> dict:
    """Esegue un'azione richiesta da Claude e restituisce il risultato."""
    backends = backends if backends is not None else _backends_reali()
    action_type = action.get("action")

    try:
        if action_type == "CHECK_DISPONIBILITA":
            return await _check_disponibilita(action, session, backends)
        if action_type == "CREA_APPUNTAMENTO":
            return await _crea_appuntamento(action, phone, session, backends)
        if action_type == "CANCELLA_APPUNTAMENTO":
            return await _cancella_appuntamento(action, phone, session, backends)
        if action_type == "SPOSTA_APPUNTAMENTO":
            return await _sposta_appuntamento(action, phone, session, backends)
        if action_type == "STORICO_APPUNTAMENTI":
            return await _storico_appuntamenti(phone, session, backends)
        if action_type == "INVIA_CODICE_VERIFICA":
            return await _invia_codice_verifica(action, phone, session, backends)
        if action_type == "VERIFICA_CODICE":
            return await _verifica_codice(action, session)
    except OperatoreSconosciuto as e:
        logger.warning("Operatore non risolto nell'azione %s: %s", action_type, e)
        return {"errore": str(e)}
    except KeyError as e:
        logger.error("Azione %s incompleta, manca il campo %s", action_type, e)
        return {"errore": f"Dato mancante nell'azione: {e}. Chiedilo al cliente."}
    except Exception as e:  # noqa: BLE001 - vogliamo che il bot sopravviva a qualsiasi errore
        logger.exception("Errore eseguendo l'azione %s", action_type)
        return {"errore": f"Il sistema non è riuscito a completare l'operazione: {e}"}

    logger.warning("Azione sconosciuta: %s", action_type)
    return {"errore": f"Azione '{action_type}' non riconosciuta"}


class OperatoreSconosciuto(Exception):
    """Il nome di operatore indicato non corrisponde a nessun calendario."""


def _risolvi_calendario(valore: str | None) -> str | None:
    """Trasforma il nome di un operatore nell'id del suo calendario Google.

    Claude indica l'operatore per nome: farfli ricopiare l'id del calendario
    (novanta caratteri opachi) significava vederlo troncato, e un calendario
    inesistente risponde 404, che il chiamante leggeva come "nessuno slot
    libero". Meglio risolvere qui e fallire in modo esplicito.

    None significa "nessuna preferenza": vanno controllati tutti i calendari.
    """
    if not valore:
        return None

    mappa = get_parrucchieri_map_cached()

    # Retrocompatibilità: se arriva già un id di calendario, lo si accetta.
    if valore in mappa.values():
        return valore

    cal_id = get_cal_id_for_parrucchiere(valore)
    if cal_id is None:
        raise OperatoreSconosciuto(
            f"'{valore}' non è un operatore del salone. "
            f"Operatori validi: {', '.join(mappa)}."
        )
    if cal_id.startswith(PREFISSO_NON_CONFIGURATO):
        raise OperatoreSconosciuto(
            f"L'operatore {valore} non ha ancora un calendario configurato: "
            "non è possibile verificare la sua disponibilità né prenotare."
        )
    return cal_id


# Fasi del flusso, nell'ordine in cui i dati si accumulano. Servono a tenere
# onesta la voce "FASE CORRENTE" del prompt, che altrimenti resta "saluto" per
# tutta la conversazione.
_FASI = (
    ("nome", "contatti"),
    ("slot", "intake"),
    ("parrucchiere", "scelta_slot"),
    ("servizio", "scelta_operatore"),
)


def _ricorda(session: dict, avanza_fase: bool = True, **campi) -> None:
    """Annota nella sessione quello che si è appena appreso.

    Lo storico viene troncato agli ultimi `max_history_messages` messaggi: dal
    sesto turno in poi la richiesta iniziale del cliente non c'è più. Questi
    dati sopravvivono alla troncatura e finiscono nel prompt, quindi vanno
    scritti appena si conoscono, non a prenotazione avvenuta.
    """
    dati = session.setdefault("dati_temp", {})
    cambiato = False
    for chiave, valore in campi.items():
        if valore and dati.get(chiave) != valore:
            dati[chiave] = valore
            cambiato = True

    # Riconoscere un cliente dallo storico non significa che la prenotazione
    # sia avanzata: sapere il suo nome non vuol dire che abbia scelto il servizio.
    if not cambiato or not avanza_fase or session.get("stato_flusso") == "confermato":
        return

    for chiave, fase in _FASI:
        if dati.get(chiave):
            session["stato_flusso"] = fase
            return
    session["stato_flusso"] = "scelta_servizio"


def _normalizza_telefono(valore) -> str | None:
    """Ripulisce un numero scritto a mano dal cliente.

    Lo scrive come gli viene: "347 123 45 67", "+39 347-1234567". In colonna
    ci stanno vent'anni di caratteri, quindi si conservano solo il prefisso
    internazionale e le cifre. Se non somiglia a un numero si restituisce None,
    invece di sporcare l'anagrafica con una frase.
    """
    if not valore:
        return None
    testo = str(valore).strip()
    cifre = re.sub(r"\D", "", testo)
    # E.164: al massimo quindici cifre, e sotto le otto non è un numero italiano
    if not 8 <= len(cifre) <= 15:
        return None
    return ("+" if testo.startswith("+") else "") + cifre


def _descrivi_servizi(servizi) -> str:
    """Nome leggibile dei servizi scelti, normalizzato sul listino."""
    from services import catalogo

    risolti = catalogo.risolvi(servizi)
    if risolti:
        return ", ".join(s.nome for s in risolti)
    if isinstance(servizi, str):
        return servizi
    return ", ".join(str(s) for s in servizi or [])


def _oltre_l_orizzonte(quando: str | None) -> str | None:
    """Messaggio se la data supera il limite di prenotazione, altrimenti None.

    `max_booking_days_ahead` esisteva in configurazione ma non lo leggeva
    nessuno: si poteva prenotare a qualunque distanza. Il salone non sa chi
    lavorerà fra otto mesi, e un appuntamento del genere resta sul calendario
    a invecchiare da solo.

    Accetta sia "2026-09-15" sia "2026-09-15T09:00".
    """
    from datetime import datetime, timedelta

    from config import settings
    from services.slots import adesso_salone

    if not quando:
        return None
    try:
        giorno = datetime.strptime(quando[:10], "%Y-%m-%d").date()
    except ValueError:
        # Una data che non si riesce a leggere è un problema diverso, e lo
        # segnala già chi prova a usarla.
        return None

    giorni = settings.max_booking_days_ahead
    ultimo = adesso_salone().date() + timedelta(days=giorni)
    if giorno <= ultimo:
        return None
    return (
        f"Non si prenota a più di {giorni} giorni di distanza. L'ultima data "
        f"disponibile è {ultimo.strftime('%d/%m/%Y')}: dillo al cliente e "
        "chiedigli se preferisce un giorno entro quella data."
    )


async def _check_disponibilita(action: dict, session: dict, backends) -> dict:
    from config import settings
    from services import catalogo

    servizi = action.get("servizi") or []

    # La durata la decide il catalogo anche in fase di ricerca, non solo di
    # creazione: se il modello sottostima (trenta minuti per un colore che ne
    # dura centoventi) verrebbero proposti slot liberi solo in apparenza, e la
    # prenotazione finirebbe sopra l'appuntamento successivo.
    if servizi:
        durata = catalogo.durata_totale(servizi)
    else:
        durata = action.get("durata_min") or settings.slot_duration_min

    _ricorda(
        session,
        servizio=_descrivi_servizi(servizi) if servizi else None,
        parrucchiere=action.get("parrucchiere"),
    )

    # Dopo `_ricorda` e prima di Google: la data si rifiuta, ma quello che il
    # cliente ha detto sul servizio e sull'operatore non va buttato via.
    troppo_lontano = _oltre_l_orizzonte(action.get("data"))
    if troppo_lontano:
        return {"errore": troppo_lontano}

    slots = await backends.check_availability(
        action.get("data"),
        _risolvi_calendario(action.get("parrucchiere")),
        durata,
    )
    if not slots:
        return {
            "slots_disponibili": [],
            "nota": "Nessuno slot libero in questa data. Proponi al cliente un altro giorno.",
        }
    return {"slots_disponibili": slots}


async def _crea_appuntamento(action: dict, phone: str, session: dict, backends) -> dict:
    from services import catalogo

    # Anche qui, non solo in fase di ricerca: uno slot può arrivare da uno
    # storico vecchio o da un'invenzione del modello, senza passare da
    # CHECK_DISPONIBILITA.
    troppo_lontano = _oltre_l_orizzonte(action.get("slot"))
    if troppo_lontano:
        return {"errore": troppo_lontano}

    dati = session["dati_temp"]
    nome = action.get("nome") or dati.get("nome") or ""
    cognome = action.get("cognome") or dati.get("cognome") or ""
    email = action.get("email") or dati.get("email") or ""
    richieste = action.get("richieste_spec") or dati.get("richieste_spec") or ""
    servizi = action.get("servizi") or []
    da_web = bool(phone) and phone.startswith("web_")
    # Dal sito il numero lo lascia il cliente, se vuole; da WhatsApp è il mittente.
    telefono = _normalizza_telefono(action.get("telefono") or dati.get("telefono"))

    # La durata la decide il catalogo, non Claude: se il modello sbaglia a
    # calcolarla il calendario resterebbe bloccato male.
    durata = catalogo.durata_totale(servizi) if servizi else action.get("durata_min")
    durata = durata or action.get("durata_min") or catalogo.DURATA_PREDEFINITA_MIN
    prezzo = catalogo.prezzo_formattato(servizi)

    nome_completo = f"{nome} {cognome}".strip() or "Cliente"

    descrizione_parts = []
    if prezzo:
        descrizione_parts.append(f"Totale: {prezzo}")
    if richieste:
        descrizione_parts.append(f"Richieste: {richieste}")
    if email:
        descrizione_parts.append(f"Email: {email}")
    # Alla receptionist serve un numero per chiamare, qualunque sia il canale
    contatto = telefono or (None if da_web else phone)
    if contatto:
        descrizione_parts.append(f"Telefono: {contatto}")

    # Il calendario si ricava dal nome dell'operatore; l'id esplicito resta
    # accettato per retrocompatibilità con le sessioni già in corso.
    cal_id = _risolvi_calendario(
        action.get("parrucchiere_cal_id") or action.get("parrucchiere")
    )
    if cal_id is None:
        raise OperatoreSconosciuto(
            "Manca l'operatore: non so su quale calendario scrivere l'appuntamento."
        )

    event_id = await backends.create_event(
        slot=action["slot"],
        parrucchiere_cal_id=cal_id,
        servizi=servizi,
        durata=durata,
        cliente_nome=nome_completo,
        descrizione="\n".join(descrizione_parts),
    )

    # Aggiorna la sessione con i dati confermati. Passa da _ricorda così i
    # campi vuoti non cancellano quello che si sapeva già.
    _ricorda(
        session,
        nome=nome,
        cognome=cognome,
        slot=action["slot"],
        parrucchiere=action.get("parrucchiere"),
        email=email,
        telefono=telefono,
        servizio=_descrivi_servizi(servizi) if servizi else None,
    )

    # Dal sito l'identificativo di sessione non dice niente su chi è la persona:
    # se ci ha lasciato il numero, quella è la sua identità vera, e permette di
    # riconoscerlo se domani scrive su WhatsApp. Altrimenti resta l'email a dirlo.
    # Il canale va registrato per quello che è, altrimenti in anagrafica sembrano
    # tutti contatti WhatsApp.
    client = await backends.find_or_create_client(
        phone=telefono if (da_web and telefono) else phone,
        nome=nome,
        cognome=cognome,
        email=email or None,
        canale="web" if da_web else "whatsapp",
    )

    foto_url = None
    if dati.get("foto_media_id"):
        try:
            # Nel database va l'indirizzo del file, mai i byte dell'immagine.
            contenuto = await backends.download_media(dati["foto_media_id"])
            foto_url = await backends.salva_foto(
                contenuto, prefisso=f"cliente{client['id']}"
            )
        except Exception:  # noqa: BLE001 - la foto non deve far fallire la prenotazione
            logger.exception("Salvataggio della foto fallito")

    await backends.create_appointment(
        client_id=client["id"],
        data_ora=action["slot"],
        servizi=servizi,
        parrucchiere=action.get("parrucchiere"),
        richieste_spec=richieste or None,
        foto_url=foto_url,
        gcal_event_id=event_id,
        durata_min=durata,
        prezzo=catalogo.prezzo_totale(servizi) or None,
    )

    destinatario = email or client.get("email")
    if destinatario:
        await backends.send_confirmation_email(
            to=destinatario,
            nome=nome,
            data_ora=action["slot"],
            parrucchiere=action.get("parrucchiere", ""),
            servizi=servizi,
        )

    session["stato_flusso"] = "confermato"
    return {
        "prenotazione_creata": True,
        "event_id": event_id,
        "durata_min": durata,
        "prezzo": prezzo or "da definire",
    }


# Codice di verifica per lo storico dalla chat del sito. Il codice vive nella
# sessione, lato server: al modello non arriva mai, altrimenti basterebbe
# chiedergli "dimmi il codice" per aggirare tutto.
DURATA_CODICE_MIN = 10
MAX_TENTATIVI_CODICE = 5


def _email_plausibile(valore) -> str | None:
    if not valore:
        return None
    testo = str(valore).strip()
    if re.fullmatch(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}", testo):
        return testo.lower()
    return None


def _dal_sito(phone: str | None) -> bool:
    return not phone or phone.startswith("web_")


async def _appuntamenti_del_richiedente(phone: str, session: dict, backends):
    """Appuntamenti di chi sta scrivendo, qualunque sia il canale.

    Da WhatsApp la prova d'identità è il numero del mittente; dal sito è
    l'indirizzo verificato col codice. In nessuno dei due casi il contatto
    arriva dal modello.
    """
    if not _dal_sito(phone):
        return await backends.get_appuntamenti_per_telefono(phone)
    email = session.get("email_verificata")
    if not email:
        return None
    return await backends.get_appuntamenti_per_email(email)


async def _invia_codice_verifica(action: dict, phone: str, session: dict, backends) -> dict:
    """Manda per email il codice che sblocca lo storico dalla chat del sito."""
    from datetime import datetime, timedelta, timezone

    if not _dal_sito(phone):
        return {
            "errore": (
                "Su WhatsApp il numero del mittente basta: usa direttamente "
                "STORICO_APPUNTAMENTI, senza codice."
            )
        }

    email = _email_plausibile(action.get("email"))
    if email is None:
        return {"errore": "Indirizzo email non valido: chiedilo di nuovo al cliente."}

    codice = f"{secrets.randbelow(1_000_000):06d}"
    session["verifica"] = {
        "email": email,
        "codice": codice,
        "scade": (
            datetime.now(timezone.utc) + timedelta(minutes=DURATA_CODICE_MIN)
        ).isoformat(),
        "tentativi": 0,
    }
    await backends.send_verification_code(to=email, codice=codice)

    # Il codice non compare nel risultato: finirebbe nello storico della
    # conversazione, che è la cosa da cui lo stiamo proteggendo.
    return {
        "codice_inviato": True,
        "email": email,
        "validita_minuti": DURATA_CODICE_MIN,
    }


async def _verifica_codice(action: dict, session: dict) -> dict:
    """Confronta il codice digitato dal cliente con quello mandato per email."""
    from datetime import datetime, timezone

    verifica = session.get("verifica")
    if not verifica:
        return {
            "errore": (
                "Non c'è nessun codice in attesa: prima mandane uno con "
                "INVIA_CODICE_VERIFICA."
            )
        }

    if datetime.now(timezone.utc) > datetime.fromisoformat(verifica["scade"]):
        session.pop("verifica", None)
        return {
            "verificato": False,
            "motivo": "Il codice è scaduto. Chiedi al cliente se ne vuole un altro.",
        }

    verifica["tentativi"] += 1
    if verifica["tentativi"] > MAX_TENTATIVI_CODICE:
        session.pop("verifica", None)
        return {
            "verificato": False,
            "motivo": "Troppi tentativi sbagliati: questo codice non vale più.",
        }

    digitato = "".join(str(action.get("codice") or "").split())
    if not secrets.compare_digest(digitato, verifica["codice"]):
        return {
            "verificato": False,
            "tentativi_rimasti": max(MAX_TENTATIVI_CODICE - verifica["tentativi"], 0),
        }

    session["email_verificata"] = verifica["email"]
    session.pop("verifica", None)
    return {"verificato": True, "email": session["email_verificata"]}


async def _storico_appuntamenti(phone: str, session: dict, backends) -> dict:
    """Appuntamenti di chi sta scrivendo, cercati col numero della conversazione.

    L'azione non accetta nessun contatto, ed è deliberato: usa il numero da cui
    arriva il messaggio, che su WhatsApp è verificato dal gestore. Così il
    modello non può nemmeno formulare la richiesta dello storico di un altro, e
    la riservatezza non dipende da una regola nel prompt che qualcuno potrebbe
    aggirare chiedendo "e gli appuntamenti di Mario Rossi?".
    """
    if _dal_sito(phone) and not session.get("email_verificata"):
        return {
            "errore": (
                "Dalla chat del sito non sappiamo chi sta scrivendo. Chiedi al "
                "cliente la sua email, mandagli un codice con INVIA_CODICE_VERIFICA "
                "e fattelo confermare: solo dopo puoi mostrare gli appuntamenti."
            )
        }

    trovato = await _appuntamenti_del_richiedente(phone, session, backends)
    if trovato is None:
        return {
            "cliente_conosciuto": False,
            "nota": "Questo numero non è in anagrafica: non ha appuntamenti passati.",
        }

    cliente = trovato["cliente"]
    # Il nome si annota, ma la fase del flusso non avanza: sapere chi è non
    # significa che abbia già scelto un servizio.
    _ricorda(
        session,
        avanza_fase=False,
        nome=cliente.get("nome"),
        cognome=cliente.get("cognome"),
        email=cliente.get("email"),
    )

    return {
        "cliente_conosciuto": True,
        "nome": cliente.get("nome"),
        "cognome": cliente.get("cognome"),
        "appuntamenti": trovato["appuntamenti"],
    }


def _preavviso_insufficiente(appuntamento: dict) -> str | None:
    """Messaggio da restituire se manca troppo poco all'appuntamento, altrimenti None.

    Vale sia per disdire sia per spostare: a poche ore di distanza l'operatore
    ha già organizzato la giornata, e la modifica la gestisce il salone.
    """
    from datetime import datetime, timedelta

    from config import settings
    from services.slots import FUSO_SALONE, adesso_salone

    quando = datetime.strptime(appuntamento["data_ora"], "%Y-%m-%dT%H:%M").replace(
        tzinfo=FUSO_SALONE
    )
    ore = settings.cancel_policy_hours
    if quando - adesso_salone() >= timedelta(hours=ore):
        return None

    come = (
        f"telefonare al salone allo {settings.salone_telefono}"
        if settings.salone_telefono
        else "telefonare al salone"
    )
    return (
        f"Mancano meno di {ore} ore all'appuntamento, quindi da qui non si può "
        f"più cambiare. Spiega al cliente che deve {come}."
    )


async def _sposta_appuntamento(action: dict, phone: str, session: dict, backends) -> dict:
    """Sposta un appuntamento esistente a un altro orario o operatore.

    Nel database la riga resta la stessa: nello storico il cliente vede un
    appuntamento spostato, non uno annullato più uno preso. Sul calendario
    invece si cancella e si ricrea, perché lì l'evento lo guarda solo il salone
    e un identificativo nuovo non cambia nulla.
    """
    from services import catalogo

    app_id = action["app_id"]
    nuovo_slot = action["slot"]

    troppo_lontano = _oltre_l_orizzonte(nuovo_slot)
    if troppo_lontano:
        return {"errore": troppo_lontano}

    trovato = await _appuntamenti_del_richiedente(phone, session, backends)
    suoi = {a["app_id"]: a for a in (trovato or {}).get("appuntamenti", [])}
    appuntamento = suoi.get(app_id)
    if appuntamento is None:
        return {
            "errore": (
                "Non trovo questo appuntamento fra quelli di chi sta scrivendo. "
                "Rileggi lo storico con STORICO_APPUNTAMENTI e usa gli id di lì."
            )
        }
    if appuntamento.get("stato") == "Cancellato":
        return {
            "errore": "Questo appuntamento è già annullato: se serve, prenotane uno nuovo."
        }

    troppo_tardi = _preavviso_insufficiente(appuntamento)
    if troppo_tardi:
        return {"errore": troppo_tardi}

    operatore = action.get("parrucchiere") or appuntamento.get("parrucchiere")
    if nuovo_slot == appuntamento["data_ora"] and operatore == appuntamento.get(
        "parrucchiere"
    ):
        return {"errore": "Il nuovo orario è identico a quello attuale."}

    servizi = appuntamento.get("servizi") or []
    durata = appuntamento.get("durata_min") or catalogo.durata_totale(servizi)

    cal_id = _risolvi_calendario(operatore)
    if cal_id is None:
        raise OperatoreSconosciuto(
            "Manca l'operatore: non so su quale calendario spostare l'appuntamento."
        )

    # Il nuovo orario dev'essere davvero libero, altrimenti si finirebbe sopra
    # a un altro cliente.
    liberi = {
        s["slot"]
        for s in await backends.check_availability(nuovo_slot.split("T")[0], cal_id, durata)
    }
    if nuovo_slot not in liberi:
        return {
            "errore": (
                f"L'orario {nuovo_slot} non è libero con {operatore}. "
                "Verifica la disponibilità e proponi al cliente un altro orario."
            )
        }

    cliente = (trovato or {}).get("cliente") or {}
    nome_completo = f"{cliente.get('nome') or ''} {cliente.get('cognome') or ''}".strip()

    # Prima si crea il nuovo evento, poi si cancella il vecchio: al contrario,
    # se la creazione fallisse, il cliente resterebbe senza né l'uno né l'altro.
    nuovo_event_id = await backends.create_event(
        slot=nuovo_slot,
        parrucchiere_cal_id=cal_id,
        servizi=servizi,
        durata=durata,
        cliente_nome=nome_completo or "Cliente",
        descrizione="Appuntamento spostato",
    )

    vecchio_event_id = appuntamento.get("gcal_event_id")
    if vecchio_event_id:
        try:
            await backends.delete_event(
                vecchio_event_id, _risolvi_calendario(appuntamento.get("parrucchiere"))
            )
        except Exception:  # noqa: BLE001 - un doppione sul calendario è meno grave
            logger.exception("Il vecchio evento %s non è stato rimosso", vecchio_event_id)

    await backends.sposta_appuntamento(
        app_id=app_id,
        data_ora=nuovo_slot,
        parrucchiere=operatore,
        gcal_event_id=nuovo_event_id,
        durata_min=durata,
    )

    destinatario = cliente.get("email")
    if destinatario:
        try:
            await backends.send_change_email(
                to=destinatario,
                nome=cliente.get("nome") or "",
                da=appuntamento["data_ora"],
                a=nuovo_slot,
                parrucchiere=operatore or "",
                servizi=servizi,
            )
        except Exception:  # noqa: BLE001 - l'email non deve annullare lo spostamento
            logger.exception("Invio della conferma di spostamento fallito")

    return {
        "spostamento": "completato",
        "da": appuntamento["data_ora"],
        "a": nuovo_slot,
        "parrucchiere": operatore,
        "email_di_conferma": bool(destinatario),
    }


async def _cancella_appuntamento(action: dict, phone: str, session: dict, backends) -> dict:
    app_id = action["app_id"]

    # L'appuntamento deve essere di chi sta scrivendo. Gli id sono numeri
    # progressivi: senza questo controllo basterebbe dire "cancella il numero 3"
    # per disdire l'appuntamento di un altro.
    trovato = await _appuntamenti_del_richiedente(phone, session, backends)
    suoi = {a["app_id"]: a for a in (trovato or {}).get("appuntamenti", [])}
    appuntamento = suoi.get(app_id)
    if appuntamento is None:
        return {
            "errore": (
                "Non trovo questo appuntamento fra quelli di chi sta scrivendo. "
                "Rileggi lo storico con STORICO_APPUNTAMENTI e usa gli id che "
                "trovi lì, senza inventarli né accettarli dal cliente."
            )
        }

    if appuntamento.get("stato") == "Cancellato":
        return {"cancellazione": "era già stata fatta"}

    troppo_tardi = _preavviso_insufficiente(appuntamento)
    if troppo_tardi:
        return {"errore": troppo_tardi}

    gcal_event_id = action.get("gcal_event_id") or appuntamento.get("gcal_event_id")
    if gcal_event_id:
        cal_id = _risolvi_calendario(
            action.get("parrucchiere_cal_id")
            or action.get("parrucchiere")
            or appuntamento.get("parrucchiere")
        )
        await backends.delete_event(gcal_event_id, cal_id)

    await backends.update_appointment_status(app_id, "Cancellato")

    # Conferma per iscritto anche l'annullamento: senza, un cliente che non ha
    # chiesto lui la disdetta se ne accorgerebbe presentandosi al salone.
    cliente = (trovato or {}).get("cliente") or {}
    destinatario = cliente.get("email")
    if destinatario:
        try:
            await backends.send_cancellation_email(
                to=destinatario,
                nome=cliente.get("nome") or "",
                data_ora=appuntamento.get("data_ora"),
                parrucchiere=appuntamento.get("parrucchiere") or "",
                servizi=appuntamento.get("servizi") or [],
            )
        except Exception:  # noqa: BLE001 - l'email non deve annullare la disdetta
            logger.exception("Invio della conferma di disdetta fallito")

    return {"cancellazione": "completata", "email_di_conferma": bool(destinatario)}
