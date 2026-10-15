import logging

import httpx
from config import settings

logger = logging.getLogger(__name__)


def _base_url() -> str:
    # Letto a ogni invio e non una volta all'import: il token di Meta scade e
    # viene sostituito, e un valore congelato all'avvio resterebbe quello vecchio.
    return f"{settings.meta_api_url}/{settings.meta_phone_number_id}"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.meta_wa_token}",
        "Content-Type": "application/json",
    }


def _spiegazione(risposta: httpx.Response) -> str:
    """Il motivo del rifiuto secondo Meta, che lo scrive per esteso."""
    try:
        errore = risposta.json().get("error", {})
    except ValueError:
        return risposta.text[:300]

    pezzi = [errore.get("message", "")]
    dettagli = errore.get("error_data", {}).get("details")
    if dettagli:
        pezzi.append(dettagli)
    return " — ".join(p for p in pezzi if p) or risposta.text[:300]


# Gli identificativi dei messaggi che abbiamo mandato noi, con l'istante in cui
# sono partiti. Serve a una cosa sola: in coexistence Meta ci rimanda indietro,
# come `smb_message_echoes`, i messaggi che il salone scrive dall'app del
# telefono — e quell'eco mette il bot da parte, perche' significa che sta
# rispondendo una persona. Se fra le eco finisse anche quello che ha mandato il
# bot, il bot si zittirebbe da se' al primo messaggio: muto per 24 ore su ogni
# conversazione, fino alla riapertura automatica. La documentazione dice che le
# eco riguardano solo l'app, ma il danno e' troppo grosso per fidarsi di una
# riga di documentazione, e il controllo costa un dizionario in memoria.
#
# Sta in memoria di processo e non su Redis perche' la finestra utile e' di
# secondi: l'eco, se arriva, arriva subito dopo l'invio. Con piu' worker
# uvicorn un'eco potrebbe capitare al processo che non ha inviato, e allora si
# aprirebbe un passaggio di troppo: visibile nel pannello, non silenzioso.
# Oggi il processo e' uno solo.
_NOSTRI_INVII: dict[str, float] = {}
MEMORIA_INVII_SECONDI = 600


def _ricorda_invio(risposta: httpx.Response) -> None:
    """Annota l'id che Meta assegna al messaggio appena partito."""
    import time

    try:
        messaggi = risposta.json().get("messages") or []
        identificativo = messaggi[0].get("id") if messaggi else None
    except (ValueError, AttributeError, IndexError):
        return
    if not identificativo:
        return

    adesso = time.time()
    # Pulizia pigra: senza, il dizionario crescerebbe per tutta la vita del
    # processo. Si fa qui e non con un job perche' gli invii sono l'unico
    # momento in cui serve che sia in ordine.
    scaduti = [
        chiave
        for chiave, quando in _NOSTRI_INVII.items()
        if adesso - quando > MEMORIA_INVII_SECONDI
    ]
    for chiave in scaduti:
        _NOSTRI_INVII.pop(chiave, None)

    _NOSTRI_INVII[identificativo] = adesso


def e_un_nostro_invio(message_id: str | None) -> bool:
    """True se questo messaggio l'ha mandato il bot e non una persona.

    Chiamata sulle eco dell'app WhatsApp Business: quelle che corrispondono a
    un nostro invio non sono una persona che risponde, e non devono mettere da
    parte il bot.
    """
    import time

    if not message_id:
        return False
    quando = _NOSTRI_INVII.get(message_id)
    if quando is None:
        return False
    return time.time() - quando <= MEMORIA_INVII_SECONDI


async def _invia_con_motivo(
    payload: dict, descrizione: str, percorso: str = "messages"
) -> tuple[bool, str]:
    """Manda il payload a Meta e restituisce esito e motivo del rifiuto.

    Ignorare la risposta faceva credere consegnato un messaggio che Meta aveva
    rifiutato: il cliente non riceveva nulla e nei log non restava traccia del
    perché. Meta il perché lo scrive, basta leggerlo.

    Il motivo esce da qui e non resta solo nei log perché quando a scrivere è
    la receptionist dal pannello, la persona che può rimediare sta guardando lo
    schermo in quel momento: dirle "non inviato" e basta la lascia senza sapere
    se riprovare o telefonare.
    """
    async with httpx.AsyncClient() as client:
        risposta = await client.post(
            f"{_base_url()}/{percorso}",
            headers=_headers(),
            json=payload,
            timeout=10,
        )

    if risposta.is_success:
        _ricorda_invio(risposta)
        return True, ""

    motivo = _spiegazione(risposta)
    logger.error(
        "WhatsApp ha rifiutato %s verso %s (HTTP %s): %s",
        descrizione,
        payload.get("to"),
        risposta.status_code,
        motivo,
    )
    return False, motivo


async def _invia(payload: dict, descrizione: str) -> bool:
    """Come sopra, per chi del motivo non sa che farsene."""
    partito, _ = await _invia_con_motivo(payload, descrizione)
    return partito


def _payload_testo(to: str, text: str) -> dict:
    return {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }


async def send_text_message(to: str, text: str) -> bool:
    """Invia un messaggio di testo via WhatsApp Cloud API."""
    return await _invia(_payload_testo(to, text), "un messaggio di testo")


async def send_text_message_con_motivo(to: str, text: str) -> tuple[bool, str]:
    """Come `send_text_message`, ma dice anche perché Meta ha detto di no."""
    return await _invia_con_motivo(_payload_testo(to, text), "un messaggio di testo")


async def segna_letto(message_id: str) -> bool:
    """Solo le spunte blu, senza "sta scrivendo…".

    Serve quando a rispondere sarà una persona e non il bot: "letto" è vero e
    utile, "sta scrivendo" prometterebbe una risposta fra pochi secondi che non
    arriva. I puntini che restano lì mentre non scrive nessuno sono peggio di
    nessun segnale: il cliente aspetta guardando lo schermo.
    """
    if not message_id:
        return False
    return await _invia(
        {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        },
        "la conferma di lettura",
    )


async def segna_letto_e_sta_scrivendo(message_id: str) -> bool:
    """Spunte blu e "sta scrivendo…" sul messaggio appena arrivato.

    Fra Claude e i calendari una risposta può richiedere qualche secondo, e su
    Render appena risvegliato anche una trentina: senza nessun segnale il
    cliente crede di aver scritto nel vuoto e riscrive, o se ne va.

    Una sola chiamata fa le due cose. L'indicatore sparisce quando rispondiamo,
    o da solo dopo venticinque secondi.
    """
    if not message_id:
        return False
    return await _invia(
        {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
            "typing_indicator": {"type": "text"},
        },
        "la conferma di lettura",
    )


async def send_image(to: str, link: str, caption: str = "") -> bool:
    """Invia un'immagine presa da un indirizzo pubblico.

    Meta se la viene a prendere da sola, quindi `link` deve essere
    raggiungibile da fuori: un percorso relativo non serve a niente.
    """
    immagine = {"link": link}
    if caption:
        immagine["caption"] = caption
    return await _invia(
        {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "image",
            "image": immagine,
        },
        "un'immagine",
    )


async def send_interactive_buttons(
    to: str, body_text: str, buttons: list[dict], header_image: str | None = None
) -> bool:
    """Invia un messaggio con bottoni cliccabili (max 3 bottoni).
    buttons = [{"id": "btn_1", "title": "Taglio"}, ...]

    `header_image` è l'unico posto in cui WhatsApp accetta un'immagine dentro
    un messaggio di scelta, e vale una sola per messaggio: non una per
    bottone. Le liste non l'ammettono affatto.
    """
    interattivo = {
        "type": "button",
        "body": {"text": body_text},
        "action": {
            "buttons": [
                {
                    "type": "reply",
                    "reply": {"id": btn["id"], "title": btn["title"][:20]},
                }
                for btn in buttons[:3]
            ]
        },
    }
    if header_image:
        interattivo["header"] = {"type": "image", "image": {"link": header_image}}

    return await _invia(
        {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": interattivo,
        },
        "dei bottoni",
    )


async def send_interactive_list(
    to: str, body_text: str, button_text: str, items: list[dict]
) -> bool:
    """Invia un messaggio con lista espandibile (max 10 opzioni).
    items = [{"id": "item_1", "title": "Taglio", "description": "30 min"}, ...]
    """
    return await _invia(
        {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": body_text},
                "action": {
                    "button": button_text[:20],
                    "sections": [
                        {
                            "title": "Opzioni",
                            "rows": [
                                {
                                    "id": item["id"],
                                    "title": item["title"][:24],
                                    "description": item.get("description", "")[:72],
                                }
                                for item in items[:10]
                            ],
                        }
                    ],
                },
            },
        },
        "una lista di opzioni",
    )


async def send_template(to: str, template_name: str, parameters: list[str]) -> bool:
    """Invia un messaggio template (per messaggi proattivi: reminder, notifiche)."""
    components = []
    if parameters:
        components.append({
            "type": "body",
            "parameters": [{"type": "text", "text": p} for p in parameters],
        })

    return await _invia(
        {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": "it"},
                "components": components,
            },
        },
        f"il template {template_name}",
    )


async def chiedi_sincronizzazione_rubrica() -> tuple[bool, str]:
    """Chiede a Meta i contatti dell'app WhatsApp Business del salone.

    Si puo' chiedere **una volta sola e entro 24 ore** dal collegamento del
    numero: dopo, per riaverli, bisognerebbe scollegare e rifare tutto. Per
    questo non parte da sola da nessuna parte — la preme una persona, quando
    sa che le variabili su Render sono gia' quelle nuove.

    La risposta dice solo che la richiesta e' stata presa in carico: i
    contatti arrivano dopo, sul webhook, come `smb_app_state_sync`. Una
    risposta positiva qui non vuol dire che siano arrivati.
    """
    partito, motivo = await _invia_con_motivo(
        {"messaging_product": "whatsapp", "sync_type": "smb_app_state_sync"},
        "richiesta della rubrica",
        percorso="smb_app_data",
    )
    return partito, motivo


async def download_media(media_id: str) -> bytes:
    """Scarica un file media da WhatsApp Cloud API."""
    async with httpx.AsyncClient() as client:
        # Step 1: ottieni URL del media
        resp = await client.get(
            f"{settings.meta_api_url}/{media_id}",
            headers={"Authorization": f"Bearer {settings.meta_wa_token}"},
            timeout=10,
        )
        if not resp.is_success:
            raise RuntimeError(
                f"WhatsApp non dà il media {media_id}: {_spiegazione(resp)}"
            )
        media_url = resp.json()["url"]

        # Step 2: scarica il file
        resp = await client.get(
            media_url,
            headers={"Authorization": f"Bearer {settings.meta_wa_token}"},
            timeout=30,
        )
        return resp.content
