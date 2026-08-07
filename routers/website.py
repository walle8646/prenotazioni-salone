from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from services import catalogo
from services.operatori import OPERATORI

router = APIRouter(tags=["sito"])
templates = Jinja2Templates(directory="templates/sito")

ORARI = {
    "mar-ven": "08:00-12:00 / 14:30-19:30",
    "sabato": "08:00-18:00",
    "dom-lun": "Chiuso",
}


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
            "operatori": OPERATORI,
        },
    )


@router.get("/chi-siamo", response_class=HTMLResponse)
async def chi_siamo(request: Request):
    return templates.TemplateResponse("chi_siamo.html", {"request": request})
