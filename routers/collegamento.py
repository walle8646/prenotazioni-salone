"""Collega il numero del salone alla Cloud API lasciandolo sul telefono.

Si usa una volta per numero, e serve una persona del salone col telefono in
mano: il flusso di Meta (Embedded Signup) chiede di confermare dall'app
WhatsApp Business, e quella conferma non e' delegabile.

Perche' sta dietro la password del pannello: la pagina mostra il token che
Meta restituisce, cioe' la chiave per scrivere a nome del salone.

Perche' e' una pagina e non uno script: il flusso vive in una finestra del
browser, e deve aprirsi da un dominio dichiarato fra gli "Allowed domains"
dell'app Meta — da riga di comando non si fa.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

import logging

from config import settings
from routers.admin import utente_del_pannello
from services.statici import VERSIONE as _VERSIONE_STATICI

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/collega-whatsapp", tags=["collegamento"])
templates = Jinja2Templates(directory="templates")
templates.env.globals["v"] = _VERSIONE_STATICI
# Anche qui, perche' la pagina estende lo stesso base.html: senza, la fascia
# che avverte del bot spento sparirebbe proprio su una schermata di lavoro.
from services.interruttore import bot_attivo as _bot_attivo  # noqa: E402

templates.env.globals["bot_attivo"] = _bot_attivo


@router.get("", response_class=HTMLResponse, include_in_schema=False)
@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def pagina(
    request: Request, feature: str | None = None, utente=Depends(utente_del_pannello)
):
    """La pagina da cui si avvia il collegamento.

    `feature` scavalca il valore in configurazione, per provare un'altra
    variante senza riavviare: Meta quel nome lo ha gia' cambiato una volta.
    """
    return templates.TemplateResponse(
        "collega_whatsapp.html",
        {
            "request": request,
            "configurato": settings.collegamento_configurato,
            "app_id": settings.meta_app_id,
            "config_id": settings.meta_es_config_id,
            "versione_graph": settings.meta_graph_version,
            # Una stringa vuota nella URL (`?feature=`) vuol dire "non
            # mandarlo affatto", che e' una delle varianti da poter provare.
            "feature_type": (
                settings.meta_es_feature_type if feature is None else feature
            ),
            "numero_attuale": settings.meta_phone_number_id,
        },
    )


async def _chiedi(metodo: str, url: str, **argomenti) -> tuple[bool, dict | str]:
    """Una chiamata a Graph, con il motivo del rifiuto scritto da Meta.

    Meta scrive sempre perche' rifiuta, in chiaro: buttare via la risposta
    lascia in mano un errore senza causa, proprio nel momento in cui c'e' una
    persona che aspetta davanti al telefono.
    """
    import httpx

    try:
        async with httpx.AsyncClient() as client:
            risposta = await client.request(metodo, url, timeout=20, **argomenti)
    except Exception as errore:  # noqa: BLE001
        logger.exception("Chiamata a Graph non riuscita: %s", url)
        return False, f"Non sono riuscito a contattare Meta: {errore}"

    try:
        corpo = risposta.json()
    except ValueError:
        return risposta.is_success, risposta.text[:400]

    if risposta.is_success:
        return True, corpo

    errore = (corpo or {}).get("error", {})
    pezzi = [
        errore.get("message", ""),
        (errore.get("error_data") or {}).get("details", ""),
        f"codice {errore.get('code')}" if errore.get("code") else "",
    ]
    return False, " — ".join(p for p in pezzi if p) or risposta.text[:400]


@router.post("/scambia", include_in_schema=False)
async def scambia(request: Request, utente=Depends(utente_del_pannello)):
    """Trasforma il codice del flusso nelle credenziali da mettere su Render.

    Tre cose in fila, e l'ordine conta.

    Il **codice dura 30 secondi**: lo scambio parte da qui appena il browser
    lo consegna, senza passaggi in mezzo.

    Poi si **iscrive l'app** all'account del cliente. Configurare la URL del
    webhook e iscrivere l'app sono due passaggi distinti, e col secondo
    mancante Meta prende in carico i messaggi senza inoltrarne nessuno: non
    arriva niente e sembra un guasto del server. Subito dopo si rilegge
    l'elenco delle app iscritte, perche' l'unico modo di sapere che e' andata
    e' vedersi nell'elenco.

    Il numero **non si registra**: e' gia' registrato, resta sull'app del
    salone, ed e' tutto il punto della coexistence.

    Si restituisce anche l'id del numero letto da Meta e non quello che il
    browser ha riferito: l'id del numero e quello dell'account si somigliano e
    stanno nella stessa schermata, e con quello sbagliato ogni invio viene
    rifiutato mentre tutto sembra configurato.
    """
    if not settings.collegamento_configurato:
        return JSONResponse(
            {"ok": False, "errore": "Mancano META_APP_ID, META_APP_SECRET o META_ES_CONFIG_ID."},
            status_code=400,
        )

    dati = await request.json()
    codice = (dati or {}).get("code")
    waba_id = (dati or {}).get("waba_id")
    if not codice:
        return JSONResponse({"ok": False, "errore": "Il flusso non ha restituito un codice."}, status_code=400)

    base = settings.meta_graph_url

    riuscito, risultato = await _chiedi(
        "GET",
        f"{base}/oauth/access_token",
        params={
            "client_id": settings.meta_app_id,
            "client_secret": settings.meta_app_secret,
            "code": codice,
        },
    )
    if not riuscito:
        return JSONResponse({"ok": False, "errore": f"Scambio del codice: {risultato}"}, status_code=400)

    token = (risultato or {}).get("access_token")
    if not token:
        return JSONResponse({"ok": False, "errore": "Meta non ha restituito nessun token."}, status_code=400)
    # Nei log va il principio e basta: serve a riconoscerlo, non a usarlo.
    logger.info("Token del cliente ottenuto (inizia per %s)", token[:8])

    autorizzazione = {"Authorization": f"Bearer {token}"}
    esito: dict = {"ok": True, "token": token, "waba_id": waba_id}

    if not waba_id:
        esito["avvisi"] = [
            "Il flusso non ha riferito l'id dell'account: iscrizione e lettura del numero saltate."
        ]
        return JSONResponse(esito)

    avvisi: list[str] = []

    iscritto, dettaglio = await _chiedi(
        "POST", f"{base}/{waba_id}/subscribed_apps", headers=autorizzazione
    )
    if not iscritto:
        avvisi.append(f"Iscrizione dell'app non riuscita: {dettaglio}")

    letto, elenco = await _chiedi(
        "GET", f"{base}/{waba_id}/subscribed_apps", headers=autorizzazione
    )
    if letto and isinstance(elenco, dict):
        esito["app_iscritte"] = [
            (voce.get("whatsapp_business_api_data") or {}).get("name")
            for voce in elenco.get("data") or ()
        ]
    else:
        avvisi.append(f"Non ho potuto rileggere le app iscritte: {elenco}")

    letto, numeri = await _chiedi(
        "GET",
        f"{base}/{waba_id}/phone_numbers",
        headers=autorizzazione,
        params={"fields": "id,display_phone_number,verified_name,platform_type"},
    )
    if letto and isinstance(numeri, dict):
        esito["numeri"] = numeri.get("data") or []
    else:
        avvisi.append(f"Non ho potuto leggere i numeri dell'account: {numeri}")

    if avvisi:
        esito["avvisi"] = avvisi
    return JSONResponse(esito)
