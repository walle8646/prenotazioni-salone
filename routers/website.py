import hashlib
import logging

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from services import catalogo
from services.avatar import avatar_svg
from services.operatori import OPERATORI

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sito"])
templates = Jinja2Templates(directory="templates/sito")

ORARI = {
    "mar-ven": "08:00-12:00 / 14:30-19:30",
    "sabato": "08:00-18:00",
    "dom-lun": "Chiuso",
}


def _operatori_in_servizio() -> list[str]:
    """Gli operatori che il bot propone davvero.

    Dalla stessa cache che legge il system prompt, non dalla costante del
    codice: chi viene assunto dal pannello deve comparire anche sul sito, e
    chi è a riposo sparire da entrambi.
    """
    from prompts.system_prompt import get_parrucchieri_map_cached

    return list(get_parrucchieri_map_cached()) or list(OPERATORI)


@router.get("/", response_class=HTMLResponse)
async def homepage(request: Request):
    """Homepage pubblica del salone."""
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "orari": ORARI,
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


@router.get("/chi-siamo", response_class=HTMLResponse)
async def chi_siamo(request: Request):
    return templates.TemplateResponse("chi_siamo.html", {"request": request})
