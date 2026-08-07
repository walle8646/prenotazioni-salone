from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from datetime import datetime, date
from models.database import get_db
from models.orm import Appuntamento, Cliente, Parrucchiere
from services import catalogo
from config import settings

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="templates")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
async def login(request: Request, username: str = Form(), password: str = Form()):
    if username == settings.admin_username and password == settings.admin_password:
        response = RedirectResponse(url="/admin/dashboard", status_code=303)
        from itsdangerous import URLSafeSerializer

        s = URLSafeSerializer(settings.secret_key)
        token = s.dumps({"user": username})
        response.set_cookie("session", token, httponly=True, max_age=86400)
        return response
    return templates.TemplateResponse(
        "login.html", {"request": request, "error": "Credenziali errate"}
    )


def verify_session(request: Request):
    """Verifica cookie di sessione."""
    from itsdangerous import URLSafeSerializer, BadSignature

    token = request.cookies.get("session")
    if not token:
        return None
    try:
        s = URLSafeSerializer(settings.secret_key)
        return s.loads(token)
    except BadSignature:
        return None


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, data: str = None, db=Depends(get_db)):
    user = verify_session(request)
    if not user:
        return RedirectResponse(url="/admin/login")

    # Data selezionata o oggi
    target_date = (
        datetime.strptime(data, "%Y-%m-%d").date() if data else date.today()
    )

    # Query appuntamenti del giorno con relazioni
    result = await db.execute(
        select(Appuntamento)
        .options(
            selectinload(Appuntamento.cliente),
            selectinload(Appuntamento.parrucchiere),
        )
        .where(
            Appuntamento.data_ora >= datetime.combine(target_date, datetime.min.time()),
            Appuntamento.data_ora < datetime.combine(target_date, datetime.max.time()),
            Appuntamento.stato == "Confermato",
        )
        .order_by(Appuntamento.data_ora)
    )
    appuntamenti = result.scalars().all()

    def prezzo_di(app) -> str:
        """Prezzo pattuito alla prenotazione; per i vecchi record lo ricava dal listino."""
        valore = (
            float(app.prezzo)
            if app.prezzo is not None
            else catalogo.prezzo_totale(app.servizi)
        )
        return f"{valore:.2f}".replace(".", ",") + " €" if valore else "-"

    incasso_previsto = sum(
        float(a.prezzo) if a.prezzo is not None else catalogo.prezzo_totale(a.servizi)
        for a in appuntamenti
    )

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "appuntamenti": appuntamenti,
            "data_selezionata": target_date,
            "prezzo_di": prezzo_di,
            "incasso_previsto": f"{incasso_previsto:.2f}".replace(".", ",") + " €",
        },
    )


@router.get("/cliente/{cliente_id}", response_class=HTMLResponse)
async def scheda_cliente(request: Request, cliente_id: int, db=Depends(get_db)):
    user = verify_session(request)
    if not user:
        return RedirectResponse(url="/admin/login")

    result = await db.execute(
        select(Cliente)
        .options(selectinload(Cliente.appuntamenti))
        .where(Cliente.id == cliente_id)
    )
    cliente = result.scalar_one_or_none()
    if not cliente:
        return HTMLResponse("Cliente non trovato", status_code=404)

    return templates.TemplateResponse(
        "cliente.html",
        {"request": request, "cliente": cliente},
    )


@router.post("/cancel-notify")
async def cancel_notify(request: Request):
    """Endpoint per notifica cancellazione per assenza parrucchiere."""
    user = verify_session(request)
    if not user:
        return {"error": "Non autorizzato"}
    body = await request.json()
    # TODO: implementare logica notifica cancellazione
    return {"status": "notifiche inviate"}
