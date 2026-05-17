from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["sito"])
templates = Jinja2Templates(directory="templates/sito")


@router.get("/", response_class=HTMLResponse)
async def homepage(request: Request):
    """Homepage pubblica del salone."""
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "orari": {
                "mar-ven": "08:00-12:00 / 14:30-19:30",
                "sabato": "08:00-18:00",
                "dom-lun": "Chiuso",
            },
            "servizi": [
                {"nome": "Taglio", "durata": "30 min"},
                {"nome": "Taglio + Shampoo", "durata": "30 min"},
                {"nome": "Taglio + Barba", "durata": "60 min"},
                {"nome": "Barba regolata", "durata": "30 min"},
                {"nome": "Taglio + Barba + Shampoo", "durata": "60 min"},
            ],
        },
    )


@router.get("/chi-siamo", response_class=HTMLResponse)
async def chi_siamo(request: Request):
    return templates.TemplateResponse("chi_siamo.html", {"request": request})
