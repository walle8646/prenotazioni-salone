from fastapi import APIRouter, Request, Form, Depends, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload
from datetime import datetime, date
from models.database import get_db
from models.orm import Appuntamento, Cliente, Parrucchiere, ServizioListino
from services import catalogo
from config import settings
import logging
import re

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="templates")


@router.get("/", include_in_schema=False)
async def admin_home():
    """`/admin` da solo rispondeva 404: non esisteva nessuna rotta per il
    prefisso, e l'indirizzo che viene naturale scrivere non portava da nessuna
    parte. Chi è già entrato finisce sugli appuntamenti, gli altri al login."""
    return RedirectResponse("/admin/dashboard", 303)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
async def login(request: Request, username: str = Form(), password: str = Form()):
    # Senza ADMIN_PASSWORD configurata il confronto riuscirebbe con la password
    # vuota, e il pannello resterebbe aperto a chiunque conosca il nome utente.
    # Una configurazione mancante deve chiudere la porta, non spalancarla.
    if not settings.admin_password or not settings.secret_key_configurata:
        logger.error(
            "Accesso al pannello rifiutato: ADMIN_PASSWORD o SECRET_KEY non configurate"
        )
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "Pannello non configurato: contatta chi gestisce il sistema.",
            },
        )

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


def utente_del_pannello(request: Request):
    """Dipendenza: sessione valida, altrimenti si torna al login.

    Ripetere il controllo in ogni funzione significa prima o poi dimenticarlo
    in una, e quella diventa una porta aperta sui dati dei clienti.
    """
    utente = verify_session(request)
    if not utente:
        raise HTTPException(status_code=303, headers={"Location": "/admin/login"})
    return utente


async def _ricarica_listino() -> None:
    """Rimette in memoria il listino appena modificato.

    Il bot legge il catalogo dalla cache, non dal database: senza questo un
    prezzo corretto dal pannello resterebbe quello vecchio in bocca al bot
    fino al riavvio dell'applicazione.
    """
    from services.db_service import get_servizi_attivi

    catalogo.set_catalogo_cache(await get_servizi_attivi())


async def _ricarica_operatori() -> None:
    """Stessa ragione del listino: il system prompt legge una cache."""
    from prompts.system_prompt import set_parrucchieri_cache
    from services.db_service import get_parrucchieri_map

    set_parrucchieri_cache(await get_parrucchieri_map())


def _decimale(testo: str) -> float:
    """Legge un prezzo scritto all'italiana o all'inglese: 13,50 o 13.50."""
    return float((testo or "").strip().replace(",", ".").replace("€", "").strip())


def _codice_da_nome(nome: str, gia_presi: set[str]) -> str:
    """Codice interno derivato dal nome, garantito diverso dagli altri."""
    base = re.sub(r"[^a-z0-9]+", "_", nome.lower()).strip("_") or "servizio"
    codice = base
    contatore = 2
    while codice in gia_presi:
        codice = f"{base}_{contatore}"
        contatore += 1
    return codice


def _alias_da_testo(testo: str) -> list[str]:
    """Gli altri modi in cui i clienti chiamano un servizio, uno per riga o
    separati da virgola."""
    pezzi = re.split(r"[,\n]", testo or "")
    return [p.strip() for p in pezzi if p.strip()]


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


# --------------------------------------------------------------------- listino


@router.get("/servizi", response_class=HTMLResponse)
async def servizi_elenco(
    request: Request,
    errore: str = None,
    utente=Depends(utente_del_pannello),
    db=Depends(get_db),
):
    result = await db.execute(
        select(ServizioListino).order_by(ServizioListino.ordine, ServizioListino.id)
    )
    return templates.TemplateResponse(
        "servizi.html",
        {"request": request, "servizi": result.scalars().all(), "errore": errore},
    )


@router.post("/servizi")
async def servizio_nuovo(
    nome: str = Form(),
    prezzo: str = Form(),
    durata_min: int = Form(),
    alias: str = Form(""),
    ordine: int = Form(0),
    utente=Depends(utente_del_pannello),
    db=Depends(get_db),
):
    nome = nome.strip()
    if not nome:
        return RedirectResponse("/admin/servizi?errore=Il+nome+è+obbligatorio", 303)
    try:
        valore = _decimale(prezzo)
    except ValueError:
        return RedirectResponse("/admin/servizi?errore=Prezzo+non+valido", 303)
    if valore < 0 or durata_min <= 0:
        return RedirectResponse(
            "/admin/servizi?errore=Prezzo+e+durata+devono+essere+positivi", 303
        )

    result = await db.execute(select(ServizioListino.codice))
    db.add(
        ServizioListino(
            codice=_codice_da_nome(nome, set(result.scalars().all())),
            nome=nome,
            prezzo=valore,
            durata_min=durata_min,
            alias=_alias_da_testo(alias),
            ordine=ordine,
            attivo=True,
        )
    )
    await db.commit()
    await _ricarica_listino()
    logger.info("Listino: aggiunto %s", nome)
    return RedirectResponse("/admin/servizi", 303)


@router.post("/servizi/{servizio_id}")
async def servizio_modifica(
    servizio_id: int,
    nome: str = Form(),
    prezzo: str = Form(),
    durata_min: int = Form(),
    alias: str = Form(""),
    ordine: int = Form(0),
    utente=Depends(utente_del_pannello),
    db=Depends(get_db),
):
    servizio = await db.get(ServizioListino, servizio_id)
    if servizio is None:
        return RedirectResponse("/admin/servizi?errore=Servizio+non+trovato", 303)
    try:
        valore = _decimale(prezzo)
    except ValueError:
        return RedirectResponse("/admin/servizi?errore=Prezzo+non+valido", 303)
    if not nome.strip() or valore < 0 or durata_min <= 0:
        return RedirectResponse("/admin/servizi?errore=Dati+non+validi", 303)

    servizio.nome = nome.strip()
    servizio.prezzo = valore
    servizio.durata_min = durata_min
    servizio.alias = _alias_da_testo(alias)
    servizio.ordine = ordine
    await db.commit()
    await _ricarica_listino()
    logger.info("Listino: modificato %s", servizio.nome)
    return RedirectResponse("/admin/servizi", 303)


@router.post("/servizi/{servizio_id}/stato")
async def servizio_stato(
    servizio_id: int,
    utente=Depends(utente_del_pannello),
    db=Depends(get_db),
):
    """Toglie o rimette a listino una voce.

    Non si cancella: gli appuntamenti passati ne conservano il nome, e uno
    storico con un servizio scomparso non si legge più.
    """
    servizio = await db.get(ServizioListino, servizio_id)
    if servizio is None:
        return RedirectResponse("/admin/servizi?errore=Servizio+non+trovato", 303)
    servizio.attivo = not servizio.attivo
    await db.commit()
    await _ricarica_listino()
    logger.info(
        "Listino: %s %s", "riattivato" if servizio.attivo else "sospeso", servizio.nome
    )
    return RedirectResponse("/admin/servizi", 303)


# ------------------------------------------------------------------- operatori


@router.get("/operatori", response_class=HTMLResponse)
async def operatori_elenco(
    request: Request,
    errore: str = None,
    utente=Depends(utente_del_pannello),
    db=Depends(get_db),
):
    from services.operatori import PREFISSO_NON_CONFIGURATO

    result = await db.execute(select(Parrucchiere).order_by(Parrucchiere.id))
    return templates.TemplateResponse(
        "operatori.html",
        {
            "request": request,
            "operatori": result.scalars().all(),
            "errore": errore,
            "prefisso_non_configurato": PREFISSO_NON_CONFIGURATO,
        },
    )


@router.post("/operatori")
async def operatore_nuovo(
    nome: str = Form(),
    gcal_calendar_id: str = Form(),
    utente=Depends(utente_del_pannello),
    db=Depends(get_db),
):
    nome = nome.strip()
    cal_id = gcal_calendar_id.strip()
    if not nome or not cal_id:
        return RedirectResponse(
            "/admin/operatori?errore=Nome+e+calendario+sono+obbligatori", 303
        )

    esiste = await db.execute(select(Parrucchiere).where(Parrucchiere.nome == nome))
    if esiste.scalar_one_or_none() is not None:
        return RedirectResponse(
            "/admin/operatori?errore=Esiste+già+un+operatore+con+questo+nome", 303
        )

    db.add(Parrucchiere(nome=nome, gcal_calendar_id=cal_id, attivo=True))
    await db.commit()
    await _ricarica_operatori()
    logger.info("Operatori: aggiunto %s", nome)
    return RedirectResponse("/admin/operatori", 303)


# Foto piccole: stanno nel database e viaggiano a ogni messaggio della chat.
# Mezzo mega è già abbondante per una faccia da 96 pixel.
FOTO_MASSIMA_BYTE = 500 * 1024


@router.post("/operatori/{operatore_id}")
async def operatore_modifica(
    operatore_id: int,
    nome: str = Form(),
    gcal_calendar_id: str = Form(),
    foto: UploadFile = File(None),
    togli_foto: str = Form(None),
    utente=Depends(utente_del_pannello),
    db=Depends(get_db),
):
    operatore = await db.get(Parrucchiere, operatore_id)
    if operatore is None:
        return RedirectResponse("/admin/operatori?errore=Operatore+non+trovato", 303)
    if not nome.strip() or not gcal_calendar_id.strip():
        return RedirectResponse(
            "/admin/operatori?errore=Nome+e+calendario+sono+obbligatori", 303
        )

    if togli_foto:
        # Si torna all'avatar con le iniziali, che non manca mai.
        operatore.foto = None
        operatore.foto_mime = None
    elif foto is not None and foto.filename:
        contenuto = await foto.read()
        if len(contenuto) > FOTO_MASSIMA_BYTE:
            return RedirectResponse(
                "/admin/operatori?errore=La+foto+supera+500+KB:+rimpiccioliscila", 303
            )
        if not (foto.content_type or "").startswith("image/"):
            return RedirectResponse(
                "/admin/operatori?errore=Serve+un+file+immagine", 303
            )
        operatore.foto = contenuto
        operatore.foto_mime = foto.content_type

    operatore.nome = nome.strip()
    operatore.gcal_calendar_id = gcal_calendar_id.strip()
    await db.commit()
    await _ricarica_operatori()
    logger.info("Operatori: modificato %s", operatore.nome)
    return RedirectResponse("/admin/operatori", 303)


@router.post("/operatori/{operatore_id}/stato")
async def operatore_stato(
    operatore_id: int,
    utente=Depends(utente_del_pannello),
    db=Depends(get_db),
):
    """Mette a riposo un operatore o lo rimette in servizio.

    Chi è a riposo sparisce dalle scelte del bot, ma resta negli appuntamenti
    già fatti: cancellarlo renderebbe illeggibile lo storico.
    """
    operatore = await db.get(Parrucchiere, operatore_id)
    if operatore is None:
        return RedirectResponse("/admin/operatori?errore=Operatore+non+trovato", 303)

    operatore.attivo = not operatore.attivo
    await db.commit()
    await _ricarica_operatori()
    logger.info(
        "Operatori: %s %s",
        "rientrato" if operatore.attivo else "a riposo",
        operatore.nome,
    )
    return RedirectResponse("/admin/operatori", 303)


# --------------------------------------------------------------------- clienti


@router.get("/clienti", response_class=HTMLResponse)
async def clienti_elenco(
    request: Request,
    q: str = "",
    utente=Depends(utente_del_pannello),
    db=Depends(get_db),
):
    cerca = (q or "").strip()
    query = select(Cliente)
    if cerca:
        like = f"%{cerca}%"
        query = query.where(
            or_(
                Cliente.nome.ilike(like),
                Cliente.cognome.ilike(like),
                Cliente.telefono_wa.ilike(like),
                Cliente.email.ilike(like),
            )
        )
    query = query.order_by(Cliente.ultima_visita.desc().nulls_last()).limit(200)
    result = await db.execute(query)

    return templates.TemplateResponse(
        "clienti.html",
        {"request": request, "clienti": result.scalars().all(), "q": cerca},
    )


# --------------------------------------------------------------------- assenze


async def _appuntamenti_da_annullare(db, operatore_id: int, giorno: date) -> list[dict]:
    """Gli appuntamenti ancora buoni di un operatore in un giorno."""
    result = await db.execute(
        select(Appuntamento)
        .options(
            selectinload(Appuntamento.cliente),
            selectinload(Appuntamento.parrucchiere),
        )
        .where(
            Appuntamento.parrucchiere_id == operatore_id,
            Appuntamento.data_ora >= datetime.combine(giorno, datetime.min.time()),
            Appuntamento.data_ora < datetime.combine(giorno, datetime.max.time()),
            Appuntamento.stato == "Confermato",
        )
        .order_by(Appuntamento.data_ora)
    )

    appuntamenti = []
    for app in result.scalars().all():
        cliente = app.cliente
        telefono = cliente.telefono_wa if cliente else None
        appuntamenti.append(
            {
                "app_id": app.id,
                "gcal_event_id": app.gcal_event_id,
                "cal_id": app.parrucchiere.gcal_calendar_id if app.parrucchiere else None,
                "data_ora": app.data_ora.strftime("%Y-%m-%dT%H:%M"),
                "ora": app.data_ora.strftime("%H:%M"),
                "servizi": app.servizi or [],
                "cliente_nome": (
                    f"{cliente.nome or ''} {cliente.cognome or ''}".strip()
                    if cliente
                    else ""
                ),
                "cliente_email": cliente.email if cliente else None,
                # I clienti del sito senza numero hanno un segnaposto "web_":
                # metterlo nel resoconto farebbe comporre un numero inesistente.
                "cliente_telefono": (
                    telefono if telefono and not telefono.startswith("web_") else None
                ),
                "parrucchiere": app.parrucchiere.nome if app.parrucchiere else None,
            }
        )
    return appuntamenti


@router.get("/assenze", response_class=HTMLResponse)
async def assenze_form(
    request: Request,
    operatore_id: int = None,
    data: str = None,
    utente=Depends(utente_del_pannello),
    db=Depends(get_db),
):
    """Mostra chi verrebbe annullato, prima di annullare davvero."""
    result = await db.execute(
        select(Parrucchiere).where(Parrucchiere.attivo == True).order_by(Parrucchiere.nome)
    )
    operatori = result.scalars().all()

    giorno = datetime.strptime(data, "%Y-%m-%d").date() if data else date.today()
    appuntamenti = (
        await _appuntamenti_da_annullare(db, operatore_id, giorno)
        if operatore_id
        else None
    )

    return templates.TemplateResponse(
        "assenze.html",
        {
            "request": request,
            "operatori": operatori,
            "operatore_id": operatore_id,
            "giorno": giorno,
            "appuntamenti": appuntamenti,
            "resoconto": None,
        },
    )


@router.post("/assenze")
async def assenze_annulla(
    request: Request,
    operatore_id: int = Form(),
    data: str = Form(),
    utente=Depends(utente_del_pannello),
    db=Depends(get_db),
):
    """Annulla la giornata di un operatore e avvisa i clienti.

    Si arriva qui solo dal bottone che sta sotto l'elenco: annullare senza
    aver visto chi si sta annullando non deve essere possibile.
    """
    from services.assenze import annulla_giornata
    from services.backends import RealBackends

    giorno = datetime.strptime(data, "%Y-%m-%d").date()
    appuntamenti = await _appuntamenti_da_annullare(db, operatore_id, giorno)
    resoconto = await annulla_giornata(appuntamenti, RealBackends())

    logger.info(
        "Assenza operatore %s del %s: %s appuntamenti annullati, %s avvisati",
        operatore_id,
        giorno,
        resoconto["annullati"],
        len(resoconto["avvisati"]),
    )

    result = await db.execute(
        select(Parrucchiere).where(Parrucchiere.attivo == True).order_by(Parrucchiere.nome)
    )
    return templates.TemplateResponse(
        "assenze.html",
        {
            "request": request,
            "operatori": result.scalars().all(),
            "operatore_id": operatore_id,
            "giorno": giorno,
            "appuntamenti": [],
            "resoconto": resoconto,
        },
    )
