import hashlib
import logging

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from services import catalogo
from services.avatar import avatar_svg
from services.operatori import OPERATORI

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sito"])
templates = Jinja2Templates(directory="templates/sito")

from services.statici import VERSIONE as _VERSIONE_STATICI  # noqa: E402

templates.env.globals["v"] = _VERSIONE_STATICI

def _orari_del_salone() -> dict[str, str]:
    """Gli orari da mostrare, dagli stessi dati che usa la disponibilità.

    Erano scritti a mano qui dentro, e quando il salone li ha cambiati dal
    pannello il sito ha continuato a dichiarare i vecchi: un cliente leggeva
    un orario e il bot gliene proponeva un altro.
    """
    from services.slots import orari_a_coppie

    return orari_a_coppie()


def _operatori_in_servizio() -> list[str]:
    """Gli operatori che il bot propone davvero.

    Dalla stessa cache che legge il system prompt, non dalla costante del
    codice: chi viene assunto dal pannello deve comparire anche sul sito, e
    chi è a riposo sparire da entrambi.
    """
    from prompts.system_prompt import get_parrucchieri_map_cached

    return list(get_parrucchieri_map_cached()) or list(OPERATORI)


# Il messaggio con cui si apre la chat su WhatsApp. Già scritto, al cliente
# basta premere invio: il bot parte dalla prenotazione invece che da un
# "ciao" a cui deve chiedere cosa serve.
TESTO_WHATSAPP = "Ciao, vorrei prenotare un appuntamento"


def _contatto_whatsapp() -> dict | None:
    """Il link che apre WhatsApp sul numero del salone, e il numero leggibile.

    Il numero arriva da `SALONE_TELEFONO`, lo stesso che usano le email e le
    pagine sulla privacy: scritto nel template, al primo cambio di numero il
    sito manderebbe i clienti a scrivere a un telefono che nessuno legge.
    Senza numero configurato non si mostra niente: un link rotto è peggio di
    nessun link.
    """
    from urllib.parse import quote

    from config import settings

    cifre = "".join(c for c in (settings.salone_telefono or "") if c.isdigit())
    if len(cifre) < 8:
        return None

    if cifre.startswith("39") and len(cifre) == 12:
        leggibile = f"+39 {cifre[2:5]} {cifre[5:8]} {cifre[8:]}"
    else:
        leggibile = f"+{cifre}"

    return {
        "link": f"https://wa.me/{cifre}?text={quote(TESTO_WHATSAPP)}",
        "numero": leggibile,
    }


@router.get("/", response_class=HTMLResponse)
async def homepage(request: Request):
    """Homepage pubblica del salone."""
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "whatsapp": _contatto_whatsapp(),
            "orari": _orari_del_salone(),
            # Listino e durate arrivano dal catalogo: una sola fonte di verità
            # condivisa con il bot, così sito e chat non possono divergere.
            "servizi": catalogo.elenco_per_sito(),
            "operatori": _operatori_in_servizio(),
        },
    )


@router.get("/operatori/{nome}/foto")
async def foto_operatore(nome: str, request: Request):
    """La foto di un operatore, o l'avatar con le iniziali se non ce l'ha.

    Cercata per nome e non per id perché chi la chiede — il widget della chat
    e la pagina del team — conosce il nome e non l'identificativo. Non
    restituisce mai 404: senza foto si disegna l'avatar, e se il database non
    risponde pure. Un buco al posto della faccia sarebbe un guasto visibile
    per una cosa che è decorativa.
    """
    contenuto, tipo = await _immagine_operatore(nome)

    # L'avatar cambia solo se cambia la foto: l'ETag lo dice al browser, che
    # smette di riscaricarla a ogni messaggio della conversazione.
    etag = '"' + hashlib.sha256(contenuto).hexdigest()[:32] + '"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})

    return Response(
        content=contenuto,
        media_type=tipo,
        headers={"ETag": etag, "Cache-Control": "public, max-age=300"},
    )


@router.get("/operatori/scelta.png")
async def scelta_operatori(nomi: str, request: Request):
    """Una sola immagine con le facce degli operatori indicati.

    Serve a WhatsApp, dove una faccia accanto a ogni riga non esiste: le liste
    ammettono solo testo e i messaggi a bottoni una sola immagine di
    intestazione. Meta viene a prendersela da qui, quindi deve stare su un
    indirizzo pubblico e in PNG — l'SVG non lo accetta.
    """
    from services.avatar import griglia_operatori_png

    elenco = [n.strip() for n in (nomi or "").split(",") if n.strip()][:12]
    if not elenco:
        return Response(status_code=404)

    immagine = griglia_operatori_png(elenco, await _foto_di(elenco))
    etag = '"' + hashlib.sha256(immagine).hexdigest()[:32] + '"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})

    return Response(
        content=immagine,
        media_type="image/png",
        headers={"ETag": etag, "Cache-Control": "public, max-age=300"},
    )


async def _foto_di(nomi: list[str]) -> dict[str, bytes]:
    """Le foto vere di questi operatori, per chi ce l'ha."""
    try:
        from sqlalchemy import select

        from models.database import async_session
        from models.orm import Parrucchiere

        async with async_session() as db:
            result = await db.execute(
                select(Parrucchiere).where(Parrucchiere.nome.in_(nomi))
            )
            return {p.nome: p.foto for p in result.scalars().all() if p.foto}
    except Exception as errore:  # noqa: BLE001
        # Senza database si disegnano tutti gli avatar: meglio una griglia di
        # iniziali che nessuna immagine.
        logger.warning("Foto non leggibili dal database: %s", errore)
        return {}


async def _immagine_operatore(nome: str) -> tuple[bytes, str]:
    try:
        from sqlalchemy import select

        from models.database import async_session
        from models.orm import Parrucchiere

        async with async_session() as db:
            result = await db.execute(
                select(Parrucchiere).where(Parrucchiere.nome == nome)
            )
            operatore = result.scalar_one_or_none()
            if operatore is not None and operatore.foto:
                return operatore.foto, operatore.foto_mime or "image/jpeg"
    except Exception as errore:  # noqa: BLE001
        logger.warning("Foto di %s non leggibile dal database: %s", nome, errore)

    return avatar_svg(nome).encode("utf-8"), "image/svg+xml"


@router.get("/manifest.webmanifest", include_in_schema=False)
async def manifest():
    """Cosa diventa il pannello quando lo si aggiunge alla schermata Home.

    `start_url` è Conversazioni e non la dashboard: chi installa questa
    applicazione lo fa per rispondere a chi aspetta, e deve trovarsi davanti
    quella schermata senza cercarla.
    """
    return JSONResponse(
        {
            "name": "Salone Nadia — Conversazioni",
            "short_name": "Salone Nadia",
            "description": "Rispondi ai clienti che chiedono di parlare con una persona.",
            "start_url": "/admin/conversazioni",
            "scope": "/admin/",
            "display": "standalone",
            "background_color": "#f5f7fa",
            "theme_color": "#2c3e50",
            "lang": "it",
            "icons": [
                {"src": "/static/img/app-192.png", "sizes": "192x192", "type": "image/png"},
                {"src": "/static/img/app-512.png", "sizes": "512x512", "type": "image/png"},
                {
                    "src": "/static/img/app-maskable.png",
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "maskable",
                },
            ],
        },
        media_type="application/manifest+json",
    )


@router.get("/sw.js", include_in_schema=False)
async def service_worker():
    """Servito dalla radice, non da /static/.

    Un service worker comanda solo sul percorso da cui è stato scaricato: da
    `/static/sw.js` non vedrebbe `/admin`, cioè proprio le pagine per cui
    esiste.
    """
    from fastapi.responses import FileResponse

    return FileResponse(
        "static/sw.js",
        media_type="application/javascript",
        # Zero cache: un service worker vecchio resta al comando per ore, e
        # sarebbe quello che non sa ancora mostrare le notifiche.
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/chat/{gettone}")
async def entra_in_chat(gettone: str, request: Request):
    """Apre la chat del sito già riconoscendo chi arriva da WhatsApp.

    Il gettone è la prova d'identità: l'ha ricevuto su WhatsApp il titolare di
    quel numero, e vale una volta sola. Da qui in poi la sessione del sito sa
    chi sta scrivendo esattamente come dopo il codice via email.

    Un gettone scaduto o già usato non è un errore da spiegare: si apre la
    chat normale, dove il bot chiede chi è. Una pagina di errore lascerebbe il
    cliente fermo, e l'unica cosa che ha fatto è stato aspettare troppo.
    """
    import uuid

    from services.link_chat import consuma_gettone
    from services.session_manager import new_session, save_session

    redis = request.app.state.redis
    telefono = await consuma_gettone(redis, gettone)
    if not telefono:
        logger.info("Gettone della chat scaduto o già usato")
        return RedirectResponse("/?chat=1", status_code=303)

    # Lo stesso formato che il WebSocket accetta: web_ più dodici esadecimali.
    sessione = f"web_{uuid.uuid4().hex[:12]}"
    dati = new_session()
    # Non "email_verificata": qui la prova è il numero, e chiamarla col nome
    # sbagliato farebbe credere a un indirizzo che non abbiamo.
    dati["telefono_verificato"] = telefono
    dati["dati_temp"]["telefono"] = telefono
    await save_session(redis, sessione, dati)

    logger.info("Chat aperta da link per un numero verificato")
    return RedirectResponse(f"/?sessione={sessione}", status_code=303)


@router.get("/chi-siamo", response_class=HTMLResponse)
async def chi_siamo(request: Request):
    return templates.TemplateResponse("chi_siamo.html", {"request": request})


# Denominazione da esporre nell'informativa. Scritta qui e non nel template
# perché è un dato dell'attività, non una scelta di impaginazione: va
# completata con ragione sociale, sede e partita IVA reali.
TITOLARE_PRIVACY = "Salone Nadia"

# Fissa e non calcolata da `date.today()`: la data dice quando l'informativa è
# stata cambiata l'ultima volta, non quando la si sta leggendo. Aggiornarla a
# ogni visita farebbe credere a una revisione che non c'è stata.
PRIVACY_AGGIORNATA = "5 settembre 2026"


@router.get("/privacy", response_class=HTMLResponse)
async def privacy(request: Request):
    """Informativa sul trattamento dei dati.

    Deve esistere a un indirizzo pubblico e stabile: Meta la pretende per
    pubblicare l'app, e finché l'app non è pubblicata non consegna al webhook
    nessun messaggio di produzione — nemmeno quelli dell'amministratore.

    I contatti si leggono dalla configurazione invece di essere scritti nel
    template: l'indirizzo a cui un cliente chiede la cancellazione dei propri
    dati deve essere lo stesso da cui partono le email, altrimenti la richiesta
    arriva in una casella che nessuno guarda.
    """
    from config import settings

    return templates.TemplateResponse(
        "privacy.html",
        {
            "request": request,
            "titolare": TITOLARE_PRIVACY,
            "email_salone": settings.smtp_user,
            "telefono_salone": settings.salone_telefono,
            "aggiornata": PRIVACY_AGGIORNATA,
        },
    )


@router.get("/cancellazione-dati", response_class=HTMLResponse)
async def cancellazione_dati(request: Request):
    """Istruzioni per farsi cancellare.

    Pagina separata dall'informativa e non un suo paragrafo: Meta chiede i due
    indirizzi e **rifiuta lo stesso URL per entrambi**, quindi un'ancora
    `/privacy#cancellazione` non basterebbe.
    """
    from config import settings

    return templates.TemplateResponse(
        "cancellazione_dati.html",
        {
            "request": request,
            "email_salone": settings.smtp_user,
            "telefono_salone": settings.salone_telefono,
        },
    )
