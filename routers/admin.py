from fastapi import APIRouter, Request, Form, Depends, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import selectinload
from datetime import datetime, date, timedelta
from models.database import get_db
from models.orm import Appuntamento, Cliente, Parrucchiere, ServizioListino
from services import catalogo
from config import settings
import logging
import re

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="templates")

# Appesa agli indirizzi dei file statici: senza, dopo un deploy il browser
# continua a usare il foglio di stile che ha in cache.
from services.statici import VERSIONE as _VERSIONE_STATICI  # noqa: E402

templates.env.globals["v"] = _VERSIONE_STATICI


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
            "settimana": await _settimana(db, target_date),
            "settimana_prima": (target_date - timedelta(days=7)).isoformat(),
            "settimana_dopo": (target_date + timedelta(days=7)).isoformat(),
            "intestazione_settimana": _intestazione_settimana(target_date),
            "titolo_giornata": _in_italiano(target_date),
        },
    )


# I nomi stanno nel codice perché nel container non c'è il locale italiano.
GIORNI_LUNGHI = [
    "lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica",
]
MESI = [
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
]


def _in_italiano(giorno: date) -> str:
    """"domenica 9 agosto 2026" — si legge meglio di 09/08/2026."""
    return (
        f"{GIORNI_LUNGHI[giorno.weekday()].capitalize()} {giorno.day} "
        f"{MESI[giorno.month - 1]} {giorno.year}"
    )


def _intestazione_settimana(dal: date) -> str:
    """Il periodo coperto dalla striscia, es. "9 – 15 agosto 2026"."""
    al = dal + timedelta(days=6)
    if dal.month == al.month:
        return f"{dal.day} – {al.day} {MESI[al.month - 1]} {al.year}"
    if dal.year == al.year:
        return (
            f"{dal.day} {MESI[dal.month - 1]} – {al.day} {MESI[al.month - 1]} {al.year}"
        )
    return (
        f"{dal.day} {MESI[dal.month - 1]} {dal.year} – "
        f"{al.day} {MESI[al.month - 1]} {al.year}"
    )


async def _settimana(db, dal: date) -> list[dict]:
    """I sette giorni a partire da quello scelto, con quanti appuntamenti hanno.

    Un conteggio solo per tutta la striscia, non sette query: la giornata
    aperta si vede già nella tabella sotto, qui serve solo sapere dove
    guardare.
    """
    from sqlalchemy import func

    from services.slots import is_open

    giorni = [dal + timedelta(days=i) for i in range(7)]
    inizio = datetime.combine(giorni[0], datetime.min.time())
    fine = datetime.combine(giorni[-1], datetime.max.time())

    result = await db.execute(
        select(func.date(Appuntamento.data_ora), func.count())
        .where(
            Appuntamento.data_ora >= inizio,
            Appuntamento.data_ora <= fine,
            Appuntamento.stato == "Confermato",
        )
        .group_by(func.date(Appuntamento.data_ora))
    )
    quanti = {riga[0]: riga[1] for riga in result.all()}

    nomi = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]
    oggi = date.today()
    return [
        {
            "data": giorno,
            "iso": giorno.isoformat(),
            "nome": nomi[giorno.weekday()],
            "numero": giorno.day,
            "quanti": quanti.get(giorno, 0),
            "aperto": is_open(giorno.isoformat()),
            "oggi": giorno == oggi,
            "scelto": giorno == dal,
        }
        for giorno in giorni
    ]


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


# Quanto si accetta in ingresso. Le foto arrivano dal telefono e pesano
# qualche mega: le rimpicciolisce `normalizza_foto`, non chi le carica. Un
# limite serve comunque, perché il file viene letto tutto in memoria.
FOTO_MASSIMA_BYTE = 8 * 1024 * 1024


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
        from services.avatar import normalizza_foto

        contenuto = await foto.read()
        if len(contenuto) > FOTO_MASSIMA_BYTE:
            return RedirectResponse(
                "/admin/operatori?errore=La+foto+supera+8+MB", 303
            )
        try:
            # Quadrata e piccola prima di toccare il database: quello che
            # arriva dal telefono pesa mille volte tanto e verrebbe riletto a
            # ogni immagine di riepilogo.
            operatore.foto, operatore.foto_mime = normalizza_foto(contenuto)
        except Exception:  # noqa: BLE001
            logger.warning("Foto di %s non leggibile", operatore.nome, exc_info=True)
            return RedirectResponse(
                "/admin/operatori?errore=Non+riesco+a+leggere+questa+immagine", 303
            )

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


@router.post("/appuntamenti/{appuntamento_id}/annulla")
async def appuntamento_annulla(
    appuntamento_id: int,
    data: str = Form(...),
    utente=Depends(utente_del_pannello),
    db=Depends(get_db),
):
    """Disdice un appuntamento solo, come quando il cliente telefona.

    Dal pannello si poteva annullare solo una giornata intera (Assenze), che è
    un'altra cosa: lì manca l'operatore ed è il salone a scusarsi. Qui è il
    cliente che non viene, e riceve la normale email di disdetta.

    Ogni passo va per conto suo, come nelle assenze: se Google non trova
    l'evento l'appuntamento si annulla lo stesso, e un'email che non parte non
    lo lascia a metà.
    """
    from services.backends import RealBackends

    result = await db.execute(
        select(Appuntamento)
        .options(
            selectinload(Appuntamento.cliente),
            selectinload(Appuntamento.parrucchiere),
        )
        .where(Appuntamento.id == appuntamento_id)
    )
    appuntamento = result.scalar_one_or_none()
    if appuntamento is None:
        return RedirectResponse(f"/admin/dashboard?data={data}", 303)

    backends = RealBackends()
    cliente = appuntamento.cliente
    operatore = appuntamento.parrucchiere

    if appuntamento.gcal_event_id and operatore:
        try:
            await backends.delete_event(
                appuntamento.gcal_event_id, operatore.gcal_calendar_id
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "Disdetta: evento %s non rimosso da Google",
                appuntamento.gcal_event_id,
                exc_info=True,
            )

    appuntamento.stato = "Cancellato"
    await db.commit()

    if cliente and cliente.email:
        try:
            await backends.send_cancellation_email(
                to=cliente.email,
                nome=f"{cliente.nome or ''} {cliente.cognome or ''}".strip() or "Cliente",
                data_ora=appuntamento.data_ora.strftime("%Y-%m-%dT%H:%M"),
                parrucchiere=operatore.nome if operatore else "",
                servizi=appuntamento.servizi or [],
            )
        except Exception:  # noqa: BLE001
            logger.warning("Disdetta: email a %s non partita", cliente.email, exc_info=True)

    logger.info("Disdetto l'appuntamento %s", appuntamento_id)
    return RedirectResponse(f"/admin/dashboard?data={data}", 303)


# -------------------------------------------------------------------- presenze


async def _ricarica_presenze() -> None:
    """Stessa ragione del listino: la disponibilità legge una cache."""
    from services.db_service import get_presenze
    from services.presenze import set_presenze_cache

    set_presenze_cache(await get_presenze())


async def _ricarica_orari() -> None:
    """Rimette in memoria orari e chiusure appena cambiati.

    Stessa ragione del listino: la disponibilità legge una copia in memoria, e
    senza questa riga il bot continuerebbe a proporre gli orari vecchi fino al
    riavvio — cioè a dare appuntamenti a salone chiuso.
    """
    from datetime import date as _date

    from services.db_service import get_chiusure, get_orari_salone
    from services.slots import set_chiusure, set_orari_salone

    set_orari_salone(await get_orari_salone())
    chiusure = await get_chiusure(da=_date.today())
    set_chiusure({c["data"].isoformat() for c in chiusure})


def _giorni_di_apertura() -> list[tuple[int, str]]:
    """I giorni in cui il salone apre, come (numero, nome)."""
    from services.slots import NOMI_GIORNI, orari_salone

    orari = orari_salone()
    return [(g, NOMI_GIORNI[g]) for g in range(7) if orari.get(g)]


def _fasce_dal_form(modulo, giorno: int, prefisso: str = "g") -> list[tuple[str, str]]:
    """Le fasce di un giorno, lette dai campi del form.

    Una fascia entra solo se ha entrambi gli estremi e l'inizio viene prima
    della fine: mezzo orario scritto è quasi sempre un campo dimenticato, e
    salvarlo così toglierebbe l'operatore dalla giornata senza dirlo.

    Il prefisso distingue i campi dell'operatore da quelli del salone, che
    stanno nella stessa pagina.
    """
    if not modulo.get(f"{prefisso}{giorno}_lavora"):
        return []

    fasce = []
    for parte in ("m", "p"):
        dalle = (modulo.get(f"{prefisso}{giorno}_{parte}_dalle") or "").strip()
        alle = (modulo.get(f"{prefisso}{giorno}_{parte}_alle") or "").strip()
        if dalle and alle and dalle < alle:
            fasce.append((dalle, alle))
    return fasce


@router.get("/presenze", response_class=HTMLResponse)
async def presenze_elenco(
    request: Request,
    errore: str = None,
    utente=Depends(utente_del_pannello),
    db=Depends(get_db),
):
    from sqlalchemy.orm import selectinload

    from services.slots import orari_salone

    result = await db.execute(
        select(Parrucchiere)
        .options(selectinload(Parrucchiere.presenze))
        .where(Parrucchiere.attivo == True)  # noqa: E712
        .order_by(Parrucchiere.nome)
    )

    operatori = []
    for parr in result.scalars().all():
        per_giorno: dict[int, list[tuple[str, str]]] = {}
        for fascia in parr.presenze:
            per_giorno.setdefault(fascia.giorno, []).append(
                (fascia.ora_inizio, fascia.ora_fine)
            )
        for fasce in per_giorno.values():
            fasce.sort()

        giorni = []
        for numero, nome in _giorni_di_apertura():
            if parr.orari_propri:
                fasce = per_giorno.get(numero, [])
                lavora = bool(fasce)
            else:
                # Non ancora configurato: i campi mostrano gli orari del
                # salone, che è esattamente quello che sta facendo adesso.
                fasce = orari_salone().get(numero, [])
                lavora = True
            mattina = fasce[0] if fasce else ("", "")
            pomeriggio = fasce[1] if len(fasce) > 1 else ("", "")
            giorni.append(
                {
                    "numero": numero,
                    "nome": nome,
                    "lavora": lavora,
                    "mattina": mattina,
                    "pomeriggio": pomeriggio,
                }
            )
        operatori.append(
            {"id": parr.id, "nome": parr.nome,
             "orari_propri": parr.orari_propri, "giorni": giorni}
        )

    return templates.TemplateResponse(
        "presenze.html",
        {
            "request": request,
            "operatori": operatori,
            "errore": errore,
            "salone": _giorni_del_salone(),
            "chiusure": await _chiusure_future(),
            "oggi": date.today().isoformat(),
        },
    )


def _giorni_del_salone() -> list[dict]:
    """Tutti e sette i giorni, aperti o no.

    Qui non si filtra per giorno di apertura come si fa per gli operatori: è
    proprio la schermata da cui si riapre il lunedì, e un giorno chiuso che non
    compare non si può più riaprire.
    """
    from services.slots import NOMI_GIORNI, orari_salone

    orari = orari_salone()
    giorni = []
    for numero in range(7):
        fasce = orari.get(numero, [])
        giorni.append(
            {
                "numero": numero,
                "nome": NOMI_GIORNI[numero],
                "lavora": bool(fasce),
                "mattina": fasce[0] if fasce else ("", ""),
                "pomeriggio": fasce[1] if len(fasce) > 1 else ("", ""),
            }
        )
    return giorni


async def _chiusure_future() -> list[dict]:
    from services.db_service import get_chiusure

    chiusure = await get_chiusure(da=date.today())
    return [
        {"id": c["id"], "quando": _in_italiano(c["data"]), "motivo": c["motivo"]}
        for c in chiusure
    ]


@router.post("/presenze/{operatore_id}")
async def presenze_salva(
    operatore_id: int,
    request: Request,
    utente=Depends(utente_del_pannello),
    db=Depends(get_db),
):
    from models.orm import Presenza

    operatore = await db.get(Parrucchiere, operatore_id)
    if operatore is None:
        return RedirectResponse("/admin/presenze?errore=Operatore+non+trovato", 303)

    modulo = await request.form()
    nuove = {
        giorno: _fasce_dal_form(modulo, giorno)
        for giorno, _ in _giorni_di_apertura()
    }
    if not any(nuove.values()):
        return RedirectResponse(
            "/admin/presenze?errore=Segna+almeno+un+giorno:+per+togliere+"
            "un+operatore+dal+lavoro+mettilo+a+riposo+in+Operatori",
            303,
        )

    # Cancellate con una sola istruzione, senza passare da `operatore.presenze`:
    # è una relazione caricata pigramente, e leggerla qui solleva MissingGreenlet
    # perché in asincrono il caricamento differito non può partire da solo.
    await db.execute(delete(Presenza).where(Presenza.parrucchiere_id == operatore.id))

    for giorno, fasce in nuove.items():
        for inizio, fine in fasce:
            db.add(
                Presenza(
                    parrucchiere_id=operatore.id,
                    giorno=giorno,
                    ora_inizio=inizio,
                    ora_fine=fine,
                )
            )
    operatore.orari_propri = True
    await db.commit()
    await _ricarica_presenze()
    logger.info("Presenze: aggiornate quelle di %s", operatore.nome)
    return RedirectResponse("/admin/presenze", 303)


@router.post("/presenze/{operatore_id}/salone")
async def presenze_come_il_salone(
    operatore_id: int,
    utente=Depends(utente_del_pannello),
    db=Depends(get_db),
):
    """Rimette un operatore sugli orari del salone, cancellando le sue fasce."""
    from models.orm import Presenza

    operatore = await db.get(Parrucchiere, operatore_id)
    if operatore is None:
        return RedirectResponse("/admin/presenze?errore=Operatore+non+trovato", 303)

    await db.execute(delete(Presenza).where(Presenza.parrucchiere_id == operatore.id))
    operatore.orari_propri = False
    await db.commit()
    await _ricarica_presenze()
    logger.info("Presenze: %s torna agli orari del salone", operatore.nome)
    return RedirectResponse("/admin/presenze", 303)


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


# -------------------------------------------------------------- conversazioni


def _ore_e_minuti(quanto: timedelta) -> str:
    """Un'attesa detta come la direbbe una persona: "2 h 15 min", non 8100 s."""
    minuti = max(0, int(quanto.total_seconds() // 60))
    if minuti < 60:
        return f"{minuti} min"
    return f"{minuti // 60} h {minuti % 60:02d} min"


async def _conversazione_per_pannello(conversazione: dict, adesso: datetime) -> dict:
    """Aggiunge alla conversazione quello che serve a chi la guarda."""
    from services.operatore_umano import finestra_aperta, minuti_rimasti

    aperta = finestra_aperta(conversazione.get("ultimo_messaggio_cliente"), adesso)
    rimasti = minuti_rimasti(conversazione.get("ultimo_messaggio_cliente"), adesso)
    return {
        **conversazione,
        "attesa": _ore_e_minuti(adesso - conversazione["aperta_il"]),
        "finestra_aperta": aperta,
        "finestra_scade_fra": _ore_e_minuti(timedelta(minutes=rimasti)),
    }


@router.get("/conversazioni", response_class=HTMLResponse)
async def conversazioni_elenco(
    request: Request,
    tutte: int = 0,
    utente=Depends(utente_del_pannello),
):
    """Chi sta aspettando una risposta da una persona."""
    from services.db_service import elenco_conversazioni_operatore

    adesso = datetime.now()
    elenco = await elenco_conversazioni_operatore(aperte=not tutte)
    return templates.TemplateResponse(
        "conversazioni.html",
        {
            "request": request,
            "conversazioni": [
                await _conversazione_per_pannello(c, adesso) for c in elenco
            ],
            "tutte": bool(tutte),
        },
    )


@router.get("/conversazioni/{conversazione_id}", response_class=HTMLResponse)
async def conversazione_apri(
    request: Request,
    conversazione_id: int,
    esito: str = None,
    utente=Depends(utente_del_pannello),
):
    from services.db_service import conversazione_con_messaggi

    conversazione = await conversazione_con_messaggi(conversazione_id)
    if conversazione is None:
        return RedirectResponse("/admin/conversazioni", 303)

    return templates.TemplateResponse(
        "conversazione.html",
        {
            "request": request,
            "c": await _conversazione_per_pannello(conversazione, datetime.now()),
            "esito": esito,
        },
    )


@router.get("/conversazioni/{conversazione_id}/messaggi")
async def conversazione_messaggi(
    conversazione_id: int,
    dopo: int = 0,
    utente=Depends(utente_del_pannello),
):
    """Solo i messaggi arrivati dopo quello indicato.

    La pagina si aggiorna da sola chiamando qui, invece di ricaricarsi: un
    refresh dell'intera pagina cancellerebbe la risposta che la receptionist
    sta scrivendo nella casella, ed è l'unico momento in cui è al lavoro.

    Si chiede "cosa è arrivato dopo l'id X" e non tutto lo scambio: la pagina
    resta aperta anche un'ora, e il controllo si ripete da solo.
    """
    from services.db_service import conversazione_con_messaggi

    conversazione = await conversazione_con_messaggi(conversazione_id)
    if conversazione is None:
        return JSONResponse({"errore": "conversazione non trovata"}, status_code=404)

    dati = await _conversazione_per_pannello(conversazione, datetime.now())
    return {
        "stato": dati["stato"],
        "finestra_aperta": dati["finestra_aperta"],
        "finestra_scade_fra": dati["finestra_scade_fra"],
        "messaggi": [
            {
                "id": m["id"],
                "autore": m["autore"],
                "testo": m["testo"],
                "ora": m["creato_il"].strftime("%d/%m %H:%M"),
            }
            for m in dati["messaggi"]
            if m["id"] > dopo
        ],
    }


@router.post("/conversazioni/{conversazione_id}/rispondi")
async def conversazione_rispondi(
    conversazione_id: int,
    testo: str = Form(),
    utente=Depends(utente_del_pannello),
):
    """Scrive al cliente su WhatsApp e tiene traccia di cosa gli è stato detto.

    Il messaggio si registra **solo se è partito davvero**: una riga nel
    pannello che dice "risposto" quando Meta ha rifiutato è peggio di nessuna
    riga, perché nessuno lo richiamerà.
    """
    from services.db_service import (
        conversazione_con_messaggi,
        registra_messaggio_conversazione,
    )
    from services.whatsapp_service import send_text_message_con_motivo

    conversazione = await conversazione_con_messaggi(conversazione_id)
    if conversazione is None:
        return RedirectResponse("/admin/conversazioni", 303)

    testo = (testo or "").strip()
    if not testo:
        return RedirectResponse(f"/admin/conversazioni/{conversazione_id}", 303)

    if conversazione["canale"] != "whatsapp":
        return RedirectResponse(
            f"/admin/conversazioni/{conversazione_id}?esito=canale", 303
        )

    partito, motivo = await send_text_message_con_motivo(
        conversazione["telefono"], testo
    )
    if not partito:
        logger.error(
            "Risposta dal pannello non inviata a %s: %s",
            conversazione["telefono"],
            motivo,
        )
        return RedirectResponse(
            f"/admin/conversazioni/{conversazione_id}?esito=errore", 303
        )

    await registra_messaggio_conversazione(conversazione_id, "operatore", testo)
    return RedirectResponse(f"/admin/conversazioni/{conversazione_id}?esito=ok", 303)


@router.post("/conversazioni/{conversazione_id}/chiudi")
async def conversazione_chiudi(
    conversazione_id: int,
    utente=Depends(utente_del_pannello),
):
    """Restituisce la conversazione al bot.

    Non manda niente al cliente: un "da adesso ti risponde di nuovo il bot"
    scritto magari tre ore dopo l'ultimo scambio è un messaggio senza contesto.
    Al prossimo messaggio il bot risponde e basta.
    """
    from services.db_service import chiudi_conversazione_operatore

    await chiudi_conversazione_operatore(conversazione_id)
    return RedirectResponse("/admin/conversazioni", 303)


# ------------------------------------------------ orari del salone e chiusure


@router.post("/presenze/salone")
async def orari_salone_salva(
    request: Request,
    utente=Depends(utente_del_pannello),
):
    """Riscrive gli orari di apertura del salone.

    Cambiarli sposta tutto: la disponibilità che il bot propone, gli orari che
    dichiara a voce, quelli sul sito e le fasce di chi non ha orari suoi. Per
    questo alla fine si ricarica la cache — senza, il bot continuerebbe a dare
    appuntamenti negli orari vecchi fino al riavvio.
    """
    from services.db_service import salva_orari_salone

    modulo = await request.form()
    nuovi = {giorno: _fasce_dal_form(modulo, giorno, prefisso="s") for giorno in range(7)}

    if not any(nuovi.values()):
        return RedirectResponse(
            "/admin/presenze?errore=Il+salone+deve+essere+aperto+almeno+un+giorno",
            303,
        )

    await salva_orari_salone(nuovi)
    await _ricarica_orari()
    logger.info("Orari del salone aggiornati dal pannello")
    return RedirectResponse("/admin/presenze", 303)


@router.post("/chiusure")
async def chiusura_aggiungi(
    data: str = Form(),
    motivo: str = Form(""),
    utente=Depends(utente_del_pannello),
):
    """Segna un giorno in cui il salone non apre.

    Non manda niente ai clienti che avevano già preso appuntamento quel
    giorno: per quello c'è **Assenze**, che li avvisa uno per uno. Qui si
    chiude la porta ai nuovi, e gli appuntamenti già presi restano da
    gestire a mano — annullarli in silenzio sarebbe il danno peggiore.
    """
    from services.db_service import aggiungi_chiusura

    try:
        giorno = datetime.strptime(data, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return RedirectResponse("/admin/presenze?errore=Data+non+valida", 303)

    if giorno < date.today():
        return RedirectResponse(
            "/admin/presenze?errore=Si+chiude+da+oggi+in+avanti,+non+nel+passato",
            303,
        )

    if not await aggiungi_chiusura(giorno, motivo):
        return RedirectResponse(
            "/admin/presenze?errore=Quel+giorno+era+gia+segnato+come+chiuso", 303
        )

    await _ricarica_orari()
    logger.info("Chiusura del %s aggiunta dal pannello", giorno)
    return RedirectResponse("/admin/presenze", 303)


@router.post("/chiusure/{chiusura_id}/togli")
async def chiusura_togli(
    chiusura_id: int,
    utente=Depends(utente_del_pannello),
):
    """Il salone quel giorno riapre."""
    from services.db_service import togli_chiusura

    await togli_chiusura(chiusura_id)
    await _ricarica_orari()
    return RedirectResponse("/admin/presenze", 303)
