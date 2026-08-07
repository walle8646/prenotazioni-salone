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

from prompts.system_prompt import build_system_prompt
from services.channels import Channel, MetaWhatsAppChannel, WebChannel
from services.session_manager import get_session, save_session

logger = logging.getLogger(__name__)

# Quante volte al massimo Claude può chiedere un'azione prima di dover
# rispondere al cliente. Evita loop infiniti se il modello continua a
# richiedere azioni senza mai concludere.
MAX_ITERATIONS = 3

MESSAGGIO_TIPO_NON_SUPPORTATO = (
    "Mi dispiace, al momento posso leggere solo messaggi di testo e foto. "
    "Puoi riscrivermi?"
)
MESSAGGIO_FALLBACK = (
    "Scusami, sto avendo un problema tecnico nel completare la richiesta. "
    "Puoi riprovare tra poco?"
)


async def _claude_reale(system_prompt: str, history: list[dict]) -> str:
    from services.claude_client import call_claude

    return await call_claude(system_prompt, history)


def _backends_reali():
    from services.backends import RealBackends

    return RealBackends()


def parse_response_with_options(response: str) -> tuple[str, list[dict] | None]:
    """Estrae dalla risposta di Claude le eventuali opzioni cliccabili.

    Cerca righe che iniziano con - o • e le trasforma in opzioni selezionabili.
    Restituisce (testo_pulito, opzioni) oppure (testo_originale, None).
    """
    lines = response.strip().split("\n")
    options: list[dict] = []
    text_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        match = re.match(r"^[-•]\s*(.+)$", stripped)
        if match:
            option_text = match.group(1).strip()
            # Rimuovi eventuali emoji iniziali dal titolo del bottone
            clean_title = re.sub(
                r"^[\U0001F300-\U0001FAFF☀-➿\s✂️🚿🧔💈]+", "", option_text
            ).strip()
            if clean_title and len(clean_title) <= 24:
                options.append(
                    {
                        "id": f"opt_{len(options)}",
                        "title": clean_title,
                        "description": option_text,
                    }
                )
                continue
        text_lines.append(line)

    # Trattiamo come opzioni solo se ce ne sono almeno due
    if len(options) >= 2:
        clean_text = "\n".join(text_lines).strip() or "Scegli un'opzione:"
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


async def deliver(channel: Channel, to: str, response: str) -> None:
    """Consegna una risposta sul canale, con bottoni se il testo contiene opzioni."""
    text, options = parse_response_with_options(response)
    if options:
        await channel.send_options(to, text, options)
    else:
        await channel.send_text(to, response)


async def _run_turn(session_key, session, channel, backends, claude) -> None:
    """Esegue un turno di conversazione: chiama Claude ed esegue le sue azioni."""
    risposta_inviata = False

    for _ in range(MAX_ITERATIONS):
        system_prompt = build_system_prompt(session)
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
            return await _check_disponibilita(action, backends)
        if action_type == "CREA_APPUNTAMENTO":
            return await _crea_appuntamento(action, phone, session, backends)
        if action_type == "CANCELLA_APPUNTAMENTO":
            return await _cancella_appuntamento(action, backends)
    except KeyError as e:
        logger.error("Azione %s incompleta, manca il campo %s", action_type, e)
        return {"errore": f"Dato mancante nell'azione: {e}. Chiedilo al cliente."}
    except Exception as e:  # noqa: BLE001 - vogliamo che il bot sopravviva a qualsiasi errore
        logger.exception("Errore eseguendo l'azione %s", action_type)
        return {"errore": f"Il sistema non è riuscito a completare l'operazione: {e}"}

    logger.warning("Azione sconosciuta: %s", action_type)
    return {"errore": f"Azione '{action_type}' non riconosciuta"}


async def _check_disponibilita(action: dict, backends) -> dict:
    from config import settings

    slots = await backends.check_availability(
        action.get("data"),
        action.get("parrucchiere"),
        action.get("durata_min") or settings.slot_duration_min,
    )
    if not slots:
        return {
            "slots_disponibili": [],
            "nota": "Nessuno slot libero in questa data. Proponi al cliente un altro giorno.",
        }
    return {"slots_disponibili": slots}


async def _crea_appuntamento(action: dict, phone: str, session: dict, backends) -> dict:
    from services import catalogo

    dati = session["dati_temp"]
    nome = action.get("nome") or dati.get("nome") or ""
    cognome = action.get("cognome") or dati.get("cognome") or ""
    email = action.get("email") or dati.get("email") or ""
    richieste = action.get("richieste_spec") or dati.get("richieste_spec") or ""
    servizi = action.get("servizi") or []

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
    if phone and not phone.startswith("web_"):
        descrizione_parts.append(f"WhatsApp: {phone}")

    event_id = await backends.create_event(
        slot=action["slot"],
        parrucchiere_cal_id=action["parrucchiere_cal_id"],
        servizi=servizi,
        durata=durata,
        cliente_nome=nome_completo,
        descrizione="\n".join(descrizione_parts),
    )

    # Aggiorna la sessione con i dati confermati
    dati["nome"] = nome
    dati["cognome"] = cognome
    dati["slot"] = action["slot"]
    dati["parrucchiere"] = action.get("parrucchiere")
    if email:
        dati["email"] = email

    # Dal sito l'identificativo di sessione cambia a ogni visita: è l'email a
    # dire se la persona è già conosciuta, e il canale va registrato per quello
    # che è, altrimenti in anagrafica sembrano tutti contatti WhatsApp.
    da_web = bool(phone) and phone.startswith("web_")
    client = await backends.find_or_create_client(
        phone=phone,
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


async def _cancella_appuntamento(action: dict, backends) -> dict:
    gcal_event_id = action.get("gcal_event_id")
    if gcal_event_id:
        await backends.delete_event(gcal_event_id, action.get("parrucchiere_cal_id"))
    await backends.update_appointment_status(action["app_id"], "Cancellato")
    return {"cancellazione": "completata"}
