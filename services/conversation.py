from services.session_manager import get_session, save_session
from services.claude_client import call_claude
from services.calendar_service import check_availability, create_event, delete_event
from services.db_service import (
    find_or_create_client, create_appointment, update_appointment_status
)
from services.whatsapp_service import (
    send_text_message, download_media,
    send_interactive_buttons, send_interactive_list,
)
from services.email_service import send_confirmation_email
from prompts.system_prompt import build_system_prompt
from config import settings
import json
import re
import logging

logger = logging.getLogger(__name__)


def parse_response_with_options(response: str) -> tuple[str, list[dict] | None]:
    """Analizza la risposta di Claude per estrarre eventuali opzioni cliccabili.
    Cerca pattern tipo:
      - Opzione 1
      - Opzione 2
    oppure emoji + testo su righe separate.
    Restituisce (testo_pulito, lista_opzioni) oppure (testo, None).
    """
    lines = response.strip().split("\n")
    options = []
    text_lines = []

    for line in lines:
        stripped = line.strip()
        # Cerca righe che iniziano con - o • seguite da testo (opzioni lista)
        match = re.match(r'^[-•]\s*(.+)$', stripped)
        if match:
            option_text = match.group(1).strip()
            # Rimuovi emoji iniziali per il titolo del bottone
            clean_title = re.sub(r'^[\U0001F300-\U0001FAFF☀-➿\s✂️🚿🧔💈]+', '', option_text).strip()
            if clean_title and len(clean_title) <= 24:
                options.append({
                    "id": f"opt_{len(options)}",
                    "title": clean_title,
                    "description": option_text,
                })
                continue
        text_lines.append(line)

    # Solo se abbiamo trovato almeno 2 opzioni
    if len(options) >= 2:
        clean_text = "\n".join(text_lines).strip()
        if not clean_text:
            clean_text = "Scegli un'opzione:"
        return clean_text, options

    return response, None


async def send_wa_response(phone: str, response: str):
    """Invia risposta su WhatsApp, con bottoni interattivi se ci sono opzioni."""
    text, options = parse_response_with_options(response)

    if options is None:
        await send_text_message(phone, response)
        return

    if len(options) <= 3:
        # Bottoni inline (max 3)
        buttons = [{"id": opt["id"], "title": opt["title"]} for opt in options]
        await send_interactive_buttons(phone, text, buttons)
    else:
        # Lista espandibile (4-10 opzioni)
        await send_interactive_list(phone, text, "Scegli", options)


async def handle_incoming_message(
    redis, phone: str, text: str, msg_type: str,
    media_id: str = None, contact_name: str = None,
):
    """Punto di ingresso per ogni messaggio WhatsApp ricevuto."""

    # 1. Tipo non supportato
    if msg_type not in ("text", "image", "interactive"):
        await send_text_message(
            phone,
            "Mi dispiace, al momento posso leggere solo messaggi di testo e foto. Puoi riscrivermi?",
        )
        return

    # 2. Carica sessione
    session = await get_session(redis, phone)

    # 3. Se è un'immagine, salva il media_id per dopo
    if msg_type == "image" and media_id:
        session["dati_temp"]["foto_media_id"] = media_id

    # 4. Aggiungi messaggio alla history
    user_content = text or "[immagine senza didascalia]"
    session["history"].append({"role": "user", "content": user_content})

    # 5. Loop azione: Claude potrebbe richiedere più round-trip
    max_iterations = 3
    for _ in range(max_iterations):
        system_prompt = build_system_prompt(session)
        response = await call_claude(system_prompt, session["history"])
        action, pre_text = try_parse_action(response)

        if action is None:
            session["history"].append({"role": "assistant", "content": response})
            await send_wa_response(phone, response)
            break

        # Se c'è testo prima del JSON, invialo al cliente
        if pre_text:
            await send_wa_response(phone, pre_text)

        result = await execute_action(action, phone, session)
        session["history"].append({"role": "assistant", "content": response})
        session["history"].append({
            "role": "user",
            "content": f"[SISTEMA] Risultato azione: {json.dumps(result, ensure_ascii=False)}",
        })

    # 6. Salva sessione aggiornata
    await save_session(redis, phone, session)


async def handle_incoming_message_web(
    redis, session_id: str, text: str, email: str = None
) -> dict:
    """Punto di ingresso per messaggi dalla chat web.
    Restituisce dict con 'text' e opzionalmente 'options' per i bottoni.
    """
    session = await get_session(redis, session_id)

    if email:
        session["dati_temp"]["email"] = email

    session["history"].append({"role": "user", "content": text})

    response_data = {"text": "", "options": None}
    max_iterations = 3
    for _ in range(max_iterations):
        system_prompt = build_system_prompt(session)
        response = await call_claude(system_prompt, session["history"])
        action, pre_text = try_parse_action(response)

        if action is None:
            session["history"].append({"role": "assistant", "content": response})
            clean_text, options = parse_response_with_options(response)
            response_data["text"] = clean_text
            if options:
                response_data["options"] = [
                    {"id": opt["id"], "title": opt["title"]} for opt in options
                ]
            break

        result = await execute_action(action, session_id, session)
        session["history"].append({"role": "assistant", "content": response})
        session["history"].append({
            "role": "user",
            "content": f"[SISTEMA] Risultato azione: {json.dumps(result, ensure_ascii=False)}",
        })

    await save_session(redis, session_id, session)
    return response_data


def try_parse_action(response: str) -> tuple[dict | None, str | None]:
    """Tenta di parsare la risposta come azione JSON.
    Gestisce sia risposte pure JSON che risposte miste testo+JSON.
    Restituisce (action, testo_prima_del_json) oppure (None, None).
    """
    stripped = response.strip()

    # Caso 1: risposta interamente JSON
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            data = json.loads(stripped)
            if "action" in data:
                return data, None
        except (json.JSONDecodeError, KeyError):
            pass

    # Caso 2: testo + JSON mescolati — cerca un blocco JSON nella risposta
    match = re.search(r'(\{[^{}]*"action"\s*:\s*"[^"]+?"[^{}]*\})', response)
    if match:
        try:
            data = json.loads(match.group(1))
            if "action" in data:
                # Estrai il testo prima del JSON
                pre_text = response[:match.start()].strip()
                return data, pre_text if pre_text else None
        except (json.JSONDecodeError, KeyError):
            pass

    return None, None


async def execute_action(action: dict, phone: str, session: dict) -> dict:
    """Esegue un'azione richiesta da Claude e restituisce il risultato."""
    action_type = action["action"]

    if action_type == "CHECK_DISPONIBILITA":
        date = action.get("data")
        parrucchiere = action.get("parrucchiere")
        durata = action.get("durata_min", settings.slot_duration_min)
        slots = await check_availability(date, parrucchiere, durata)
        return {"slots_disponibili": slots}

    elif action_type == "CREA_APPUNTAMENTO":
        # Prendi nome/cognome/email/richieste dall'azione (Claude li passa)
        # con fallback ai dati sessione
        cliente_nome = action.get("nome") or session["dati_temp"].get("nome") or ""
        cliente_cognome = action.get("cognome") or session["dati_temp"].get("cognome") or ""
        cliente_email = action.get("email") or session["dati_temp"].get("email") or ""
        richieste = action.get("richieste_spec") or session["dati_temp"].get("richieste_spec") or ""

        nome_completo = f"{cliente_nome} {cliente_cognome}".strip() or "Cliente"

        # Costruisci descrizione per Google Calendar
        descrizione_parts = []
        if richieste:
            descrizione_parts.append(f"Richieste: {richieste}")
        if cliente_email:
            descrizione_parts.append(f"Email: {cliente_email}")
        descrizione = "\n".join(descrizione_parts)

        event_id = await create_event(
            slot=action["slot"],
            parrucchiere_cal_id=action["parrucchiere_cal_id"],
            servizi=action.get("servizi", []),
            durata=action.get("durata_min", settings.slot_duration_min),
            cliente_nome=nome_completo,
            descrizione=descrizione,
        )

        # Salva dati nella sessione per uso futuro
        session["dati_temp"]["nome"] = cliente_nome
        session["dati_temp"]["cognome"] = cliente_cognome
        if cliente_email:
            session["dati_temp"]["email"] = cliente_email

        client = await find_or_create_client(
            phone=phone,
            nome=cliente_nome,
            cognome=cliente_cognome,
            email=cliente_email,
        )
        foto_url = None
        if session["dati_temp"].get("foto_media_id"):
            foto_url = await download_media(session["dati_temp"]["foto_media_id"])

        app_record = await create_appointment(
            client_id=client["id"],
            data_ora=action["slot"],
            servizi=action.get("servizi", []),
            parrucchiere=action.get("parrucchiere"),
            richieste_spec=richieste,
            foto_url=foto_url,
            gcal_event_id=event_id,
            durata_min=action.get("durata_min", settings.slot_duration_min),
        )

        email = cliente_email or client.get("email")
        if email:
            await send_confirmation_email(
                to=email,
                nome=cliente_nome,
                data_ora=action["slot"],
                parrucchiere=action.get("parrucchiere", ""),
                servizi=action.get("servizi", []),
            )

        session["stato_flusso"] = "confermato"
        return {"prenotazione_creata": True, "event_id": event_id}

    elif action_type == "CANCELLA_APPUNTAMENTO":
        app_id = action["app_id"]
        gcal_event_id = action.get("gcal_event_id")
        if gcal_event_id:
            await delete_event(gcal_event_id, action.get("parrucchiere_cal_id"))
        await update_appointment_status(app_id, "Cancellato")
        return {"cancellazione": "completata"}

    else:
        logger.warning(f"Azione sconosciuta: {action_type}")
        return {"errore": f"Azione '{action_type}' non riconosciuta"}
