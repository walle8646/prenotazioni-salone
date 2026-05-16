# Salone Nadia — Guida di Implementazione

Sistema AI per prenotazioni automatizzate via WhatsApp e sito web.  
**Stack:** FastAPI · Claude API · Google Calendar · PostgreSQL · Redis · WhatsApp Cloud API (Meta) · WebSocket  
**Hosting:** Render (free per test, Starter per produzione)  
**Sito web:** Pagina pubblica del salone con widget chat integrato  
**Admin:** Mini pannello web per la receptionist (Jinja2 + HTMX)  
**Email:** Invio promemoria e conferme via email (Resend, piano free)

---

## 1. Struttura del progetto

```
salone-nadia-bot/
├── main.py                     # Entrypoint FastAPI + avvio scheduler
├── config.py                   # Settings da env vars (Pydantic BaseSettings)
├── routers/
│   ├── webhook.py              # POST/GET /webhook/whatsapp
│   ├── admin.py                # Pannello admin receptionist
│   ├── website.py              # Pagine pubbliche sito salone
│   └── chat_ws.py              # WebSocket per chat dal sito
├── services/
│   ├── conversation.py         # Orchestratore logica conversazionale
│   ├── claude_client.py        # Wrapper Anthropic SDK
│   ├── calendar_service.py     # Google Calendar API (check + create + delete)
│   ├── db_service.py           # CRUD PostgreSQL (clienti, appuntamenti, parrucchieri)
│   ├── whatsapp_service.py     # Invio messaggi + download media (Cloud API Meta)
│   ├── email_service.py        # Invio email (conferme, promemoria) via Resend
│   └── session_manager.py      # Redis get/set/delete sessioni
├── models/
│   ├── database.py             # Engine SQLAlchemy + sessionmaker async
│   ├── orm.py                  # Modelli ORM (Clienti, Appuntamenti, Parrucchieri)
│   └── schemas.py              # Pydantic models (request/response)
├── jobs/
│   ├── scheduler.py            # Configurazione APScheduler
│   ├── reminder_job.py         # Reminder 12h prima dell'appuntamento
│   └── recontact_job.py        # Ricontatto clienti inattivi
├── prompts/
│   └── system_prompt.py        # Builder dinamico system prompt Claude
├── tests/
│   ├── test_conversation.py
│   ├── test_calendar.py
│   ├── test_booking.py
│   └── conftest.py             # Fixtures (fake Redis, mock APIs)
├── templates/
│   ├── base.html               # Layout base pannello admin
│   ├── login.html              # Login receptionist
│   ├── dashboard.html          # Appuntamenti del giorno
│   ├── cliente.html            # Scheda singolo cliente
│   ├── sito/
│   │   ├── index.html          # Homepage salone (orari, servizi, contatti)
│   │   ├── chi_siamo.html      # Pagina chi siamo
│   │   └── chat_widget.html    # Widget chat embeddabile
├── static/
│   ├── style.css               # Stili pannello admin
│   ├── sito.css                # Stili sito pubblico
│   └── chat.js                 # Client WebSocket per chat widget
├── alembic/                    # Migrazioni database
│   ├── env.py
│   └── versions/
├── alembic.ini
├── render.yaml                 # Configurazione deploy Render
├── requirements.txt
├── .env.example
└── README.md
```

---

## 2. Setup iniziale

### 2.1 Prerequisiti

- Python 3.11+
- Docker e Docker Compose
- Account Meta Business Manager verificato + app Meta for Developers
- Account Google con accesso ai calendari del salone
- API key Anthropic (Claude)

### 2.2 File `.env.example`

```env
# Claude
ANTHROPIC_API_KEY=sk-ant-...

# WhatsApp Cloud API (Meta)
META_WA_TOKEN=EAAxxxxxxx
META_PHONE_NUMBER_ID=123456789012
META_VERIFY_TOKEN=mio_token_segreto_webhook

# Google Calendar
GOOGLE_CREDENTIALS_JSON=./credentials/google_service_account.json
GCAL_SALONE_ID=salone_eccezioni@group.calendar.google.com
GCAL_PARRUCCHIERE_IDS=["cal_id_1","cal_id_2","cal_id_3","cal_id_4","cal_id_5","cal_id_6"]

# PostgreSQL (Render)
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/salone_nadia

# Admin pannello
ADMIN_USERNAME=nadia
ADMIN_PASSWORD=password_sicura
SECRET_KEY=chiave_segreta_jwt

# Email (Resend — piano free 100 email/giorno)
RESEND_API_KEY=re_xxxxxxxxxxxx
EMAIL_FROM=noreply@salonenadia.it

# Redis
REDIS_URL=redis://redis:6379/0

# Configurazione business
SLOT_DURATION_MIN=30
MAX_BOOKING_DAYS_AHEAD=30
CANCEL_POLICY_HOURS=12
INACTIVITY_DAYS=60
MIN_BOOKING_HOURS_AHEAD=2
SESSION_TTL_SECONDS=7200
MAX_HISTORY_MESSAGES=20
```

### 2.3 `requirements.txt`

```
fastapi==0.115.*
uvicorn[standard]==0.30.*
redis==5.2.*
anthropic==0.42.*
google-api-python-client==2.160.*
google-auth==2.37.*
sqlalchemy[asyncio]==2.0.*
asyncpg==0.30.*
alembic==1.14.*
httpx==0.28.*
websockets==14.*
resend==2.*
apscheduler==3.10.*
pydantic-settings==2.7.*
python-dotenv==1.0.*
jinja2==3.1.*
python-multipart==0.0.*
itsdangerous==2.2.*
pytest==8.*
pytest-asyncio==0.24.*
```

---

## 3. Configurazione (`config.py`)

```python
from pydantic_settings import BaseSettings
from typing import List
import json

class Settings(BaseSettings):
    # Claude
    anthropic_api_key: str
    claude_model: str = "claude-sonnet-4-20250514"

    # WhatsApp
    meta_wa_token: str
    meta_phone_number_id: str
    meta_verify_token: str
    meta_api_url: str = "https://graph.facebook.com/v21.0"

    # Google Calendar
    google_credentials_json: str
    gcal_salone_id: str
    gcal_parrucchiere_ids: str  # JSON string, parsed below

    # PostgreSQL
    database_url: str

    # Admin pannello
    admin_username: str = "nadia"
    admin_password: str
    secret_key: str

    # Email
    resend_api_key: str = ""
    email_from: str = "noreply@salonenadia.it"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Business config
    slot_duration_min: int = 30
    max_booking_days_ahead: int = 30
    cancel_policy_hours: int = 12
    inactivity_days: int = 60
    min_booking_hours_ahead: int = 2
    session_ttl_seconds: int = 7200
    max_history_messages: int = 20

    @property
    def parrucchiere_calendar_ids(self) -> List[str]:
        return json.loads(self.gcal_parrucchiere_ids)

    class Config:
        env_file = ".env"

settings = Settings()
```

---

## 4. Entrypoint (`main.py`)

```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager
import redis.asyncio as aioredis
from config import settings
from models.database import engine, create_tables
from routers import webhook, admin, website, chat_ws
from jobs.scheduler import start_scheduler, shutdown_scheduler

app_redis = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global app_redis
    # Inizializza PostgreSQL
    await create_tables()
    # Inizializza Redis
    app_redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    app.state.redis = app_redis
    start_scheduler()
    yield
    shutdown_scheduler()
    await app_redis.close()
    await engine.dispose()

app = FastAPI(title="Salone Nadia Bot", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(webhook.router)
app.include_router(admin.router)
app.include_router(website.router)
app.include_router(chat_ws.router)

@app.get("/health")
async def health():
    return {"status": "ok"}
```

---

## 5. Webhook WhatsApp (`routers/webhook.py`)

```python
from fastapi import APIRouter, Request, Query, HTTPException
from config import settings
from services.conversation import handle_incoming_message

router = APIRouter(prefix="/webhook")

# GET — Meta webhook verification (challenge handshake)
@router.get("/whatsapp")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_verify_token == settings.meta_verify_token:
        return int(hub_challenge)
    raise HTTPException(status_code=403, detail="Verification failed")

# POST — Riceve messaggi in entrata
@router.post("/whatsapp")
async def receive_message(request: Request):
    body = await request.json()

    # Estrai il messaggio dal payload Meta
    try:
        entry = body["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]

        # Ignora status updates (delivered, read, ecc.)
        if "messages" not in value:
            return {"status": "ignored"}

        message = value["messages"][0]
        contact = value["contacts"][0]
        phone_number = message["from"]  # numero WhatsApp del cliente
        msg_type = message["type"]       # text, image, audio, etc.

        # Estrai contenuto in base al tipo
        if msg_type == "text":
            text = message["text"]["body"]
            media_id = None
        elif msg_type == "image":
            text = message.get("image", {}).get("caption", "[foto inviata]")
            media_id = message["image"]["id"]
        else:
            text = None
            media_id = None

    except (KeyError, IndexError):
        return {"status": "parse_error"}

    # Processa il messaggio
    redis = request.app.state.redis
    await handle_incoming_message(
        redis=redis,
        phone=phone_number,
        text=text,
        msg_type=msg_type,
        media_id=media_id,
        contact_name=contact.get("profile", {}).get("name"),
    )

    return {"status": "ok"}
```

---

## 6. Gestione sessioni (`services/session_manager.py`)

```python
import json
from datetime import datetime
from config import settings

SESS_PREFIX = "session:"

def _key(phone: str) -> str:
    return f"{SESS_PREFIX}{phone}"

async def get_session(redis, phone: str) -> dict:
    """Carica sessione da Redis, o crea una nuova."""
    raw = await redis.get(_key(phone))
    if raw:
        return json.loads(raw)
    return new_session()

def new_session() -> dict:
    return {
        "stato_flusso": "saluto",
        "history": [],
        "dati_temp": {
            "servizio": None,
            "parrucchiere": None,
            "slot": None,
            "nome": None,
            "cognome": None,
            "email": None,
            "richieste_spec": None,
        },
        "last_activity": datetime.now().isoformat(),
    }

async def save_session(redis, phone: str, session: dict):
    """Salva sessione con TTL automatico."""
    session["last_activity"] = datetime.now().isoformat()
    # Tronca history
    if len(session["history"]) > settings.max_history_messages:
        session["history"] = session["history"][-settings.max_history_messages:]
    await redis.set(
        _key(phone),
        json.dumps(session, ensure_ascii=False),
        ex=settings.session_ttl_seconds,
    )

async def delete_session(redis, phone: str):
    await redis.delete(_key(phone))
```

---

## 7. Orchestratore conversazione (`services/conversation.py`)

```python
from services.session_manager import get_session, save_session
from services.claude_client import call_claude
from services.calendar_service import check_availability, create_event, delete_event
from services.db_service import (
    find_or_create_client, create_appointment, update_appointment_status
)
from services.whatsapp_service import send_text_message, download_media, send_template
from prompts.system_prompt import build_system_prompt
from config import settings
import json
import logging

logger = logging.getLogger(__name__)

async def handle_incoming_message(
    redis, phone: str, text: str, msg_type: str,
    media_id: str = None, contact_name: str = None,
):
    """Punto di ingresso per ogni messaggio WhatsApp ricevuto."""

    # 1. Tipo non supportato
    if msg_type not in ("text", "image"):
        await send_text_message(phone, "Mi dispiace, al momento posso leggere solo messaggi di testo e foto. Puoi riscrivermi?")
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
        # Costruisci system prompt con contesto corrente
        system_prompt = build_system_prompt(session)

        # Chiama Claude
        response = await call_claude(system_prompt, session["history"])

        # Controlla se è un'azione JSON
        action = try_parse_action(response)

        if action is None:
            # Risposta testuale normale → invia al cliente
            session["history"].append({"role": "assistant", "content": response})
            await send_text_message(phone, response)
            break

        # Esegui l'azione
        result = await execute_action(action, phone, session)

        # Aggiungi il risultato come contesto per Claude
        session["history"].append({"role": "assistant", "content": response})
        session["history"].append({
            "role": "user",
            "content": f"[SISTEMA] Risultato azione: {json.dumps(result, ensure_ascii=False)}"
        })

    # 6. Salva sessione aggiornata
    await save_session(redis, phone, session)


def try_parse_action(response: str) -> dict | None:
    """Tenta di parsare la risposta come azione JSON."""
    try:
        stripped = response.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            data = json.loads(stripped)
            if "action" in data:
                return data
    except (json.JSONDecodeError, KeyError):
        pass
    return None


async def execute_action(action: dict, phone: str, session: dict) -> dict:
    """Esegue un'azione richiesta da Claude e restituisce il risultato."""
    action_type = action["action"]

    if action_type == "CHECK_DISPONIBILITA":
        date = action.get("data")
        parrucchiere = action.get("parrucchiere")  # None = tutti
        slots = await check_availability(date, parrucchiere)
        return {"slots_disponibili": slots}

    elif action_type == "CREA_APPUNTAMENTO":
        # Crea evento Google Calendar
        event_id = await create_event(
            slot=action["slot"],
            parrucchiere_cal_id=action["parrucchiere_cal_id"],
            servizi=action.get("servizi", []),
            durata=action.get("durata_min", settings.slot_duration_min),
            cliente_nome=session["dati_temp"].get("nome", ""),
        )
        # Salva in PostgreSQL
        client = await find_or_create_client(
            phone=phone,
            nome=session["dati_temp"].get("nome"),
            cognome=session["dati_temp"].get("cognome"),
        )
        # Scarica foto se presente
        foto_url = None
        if session["dati_temp"].get("foto_media_id"):
            foto_url = await download_media(session["dati_temp"]["foto_media_id"])

        app_record = await create_appointment(
            client_id=client["id"],
            data_ora=action["slot"],
            servizi=action.get("servizi", []),
            parrucchiere=action.get("parrucchiere"),
            richieste_spec=session["dati_temp"].get("richieste_spec"),
            foto_url=foto_url,
            gcal_event_id=event_id,
            durata_min=action.get("durata_min", settings.slot_duration_min),
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
```

---

## 8. Client Claude API (`services/claude_client.py`)

```python
import anthropic
from config import settings

client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

async def call_claude(system_prompt: str, history: list[dict]) -> str:
    """Chiama Claude API con system prompt e history."""

    # Converti history nel formato messages API
    messages = []
    for msg in history:
        messages.append({
            "role": msg["role"],
            "content": msg["content"],
        })

    response = await client.messages.create(
        model=settings.claude_model,
        max_tokens=1024,
        system=system_prompt,
        messages=messages,
    )

    return response.content[0].text
```

---

## 9. Google Calendar (`services/calendar_service.py`)

```python
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime, timedelta
from config import settings
import asyncio

SCOPES = ["https://www.googleapis.com/auth/calendar"]

def _get_service():
    creds = service_account.Credentials.from_service_account_file(
        settings.google_credentials_json, scopes=SCOPES
    )
    return build("calendar", "v3", credentials=creds)

def _generate_slots(date_str: str) -> list[str]:
    """Genera tutti gli slot possibili per una data (rispettando orari salone)."""
    date = datetime.strptime(date_str, "%Y-%m-%d")
    weekday = date.weekday()  # 0=lun, 5=sab, 6=dom

    if weekday in (0, 6):  # lunedì o domenica → chiuso (eccezioni gestite altrove)
        return []

    slots = []
    if weekday == 5:  # sabato: 08:00-18:00 continuato
        ranges = [("08:00", "18:00")]
    else:  # mar-ven: 08:00-12:00, 14:30-19:30
        ranges = [("08:00", "12:00"), ("14:30", "19:30")]

    for start_s, end_s in ranges:
        start = datetime.strptime(f"{date_str} {start_s}", "%Y-%m-%d %H:%M")
        end = datetime.strptime(f"{date_str} {end_s}", "%Y-%m-%d %H:%M")
        current = start
        while current + timedelta(minutes=settings.slot_duration_min) <= end:
            slots.append(current.strftime("%Y-%m-%dT%H:%M"))
            current += timedelta(minutes=settings.slot_duration_min)
    return slots


async def check_availability(date_str: str, parrucchiere_cal_id: str = None) -> list[dict]:
    """Restituisce gli slot liberi per una data (e opzionalmente un parrucchiere)."""
    service = _get_service()
    possible_slots = _generate_slots(date_str)

    if not possible_slots:
        return []

    # Prima: controlla eccezioni salone
    time_min = f"{date_str}T00:00:00Z"
    time_max = f"{date_str}T23:59:59Z"

    def _check():
        # Eccezioni salone
        eccezioni = service.events().list(
            calendarId=settings.gcal_salone_id,
            timeMin=time_min, timeMax=time_max,
            singleEvents=True,
        ).execute().get("items", [])

        # Se c'è un'eccezione che copre tutto il giorno → chiuso
        for ev in eccezioni:
            if ev.get("summary", "").lower().startswith("chius"):
                return []  # Giorno chiuso

        # Calendari da controllare
        cal_ids = [parrucchiere_cal_id] if parrucchiere_cal_id else settings.parrucchiere_calendar_ids

        available = []
        for cal_id in cal_ids:
            events = service.events().list(
                calendarId=cal_id,
                timeMin=time_min, timeMax=time_max,
                singleEvents=True, orderBy="startTime",
            ).execute().get("items", [])

            busy_times = []
            for ev in events:
                start = ev["start"].get("dateTime", ev["start"].get("date"))
                end = ev["end"].get("dateTime", ev["end"].get("date"))
                busy_times.append((start, end))

            for slot in possible_slots:
                slot_start = f"{slot}:00+02:00"  # timezone Italia
                slot_end_dt = datetime.strptime(slot, "%Y-%m-%dT%H:%M") + timedelta(minutes=settings.slot_duration_min)
                slot_end = slot_end_dt.strftime("%Y-%m-%dT%H:%M:00+02:00")

                is_busy = any(
                    not (slot_end <= bs or slot_start >= be)
                    for bs, be in busy_times
                )
                if not is_busy:
                    available.append({
                        "slot": slot,
                        "parrucchiere_cal_id": cal_id,
                    })

        return available

    return await asyncio.to_thread(_check)


async def create_event(slot: str, parrucchiere_cal_id: str,
                       servizi: list, durata: int, cliente_nome: str) -> str:
    """Crea un evento su Google Calendar. Restituisce l'event_id."""
    service = _get_service()
    start_dt = datetime.strptime(slot, "%Y-%m-%dT%H:%M")
    end_dt = start_dt + timedelta(minutes=durata)

    event = {
        "summary": f"{cliente_nome} - {', '.join(servizi)}",
        "start": {"dateTime": start_dt.strftime("%Y-%m-%dT%H:%M:00"), "timeZone": "Europe/Rome"},
        "end": {"dateTime": end_dt.strftime("%Y-%m-%dT%H:%M:00"), "timeZone": "Europe/Rome"},
    }

    def _create():
        result = service.events().insert(calendarId=parrucchiere_cal_id, body=event).execute()
        return result["id"]

    return await asyncio.to_thread(_create)


async def delete_event(event_id: str, calendar_id: str):
    service = _get_service()
    def _delete():
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
    await asyncio.to_thread(_delete)
```

---

## 10. Servizio WhatsApp (`services/whatsapp_service.py`)

```python
import httpx
from config import settings

BASE_URL = f"{settings.meta_api_url}/{settings.meta_phone_number_id}"
HEADERS = {
    "Authorization": f"Bearer {settings.meta_wa_token}",
    "Content-Type": "application/json",
}

async def send_text_message(to: str, text: str):
    """Invia un messaggio di testo via WhatsApp Cloud API."""
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{BASE_URL}/messages",
            headers=HEADERS,
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": text},
            },
            timeout=10,
        )

async def send_template(to: str, template_name: str, parameters: list[str]):
    """Invia un messaggio template (per messaggi proattivi: reminder, notifiche)."""
    components = []
    if parameters:
        components.append({
            "type": "body",
            "parameters": [{"type": "text", "text": p} for p in parameters],
        })

    async with httpx.AsyncClient() as client:
        await client.post(
            f"{BASE_URL}/messages",
            headers=HEADERS,
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "template",
                "template": {
                    "name": template_name,
                    "language": {"code": "it"},
                    "components": components,
                },
            },
            timeout=10,
        )

async def download_media(media_id: str) -> bytes:
    """Scarica un file media da WhatsApp Cloud API."""
    async with httpx.AsyncClient() as client:
        # Step 1: ottieni URL del media
        resp = await client.get(
            f"{settings.meta_api_url}/{media_id}",
            headers={"Authorization": f"Bearer {settings.meta_wa_token}"},
            timeout=10,
        )
        media_url = resp.json()["url"]

        # Step 2: scarica il file
        resp = await client.get(
            media_url,
            headers={"Authorization": f"Bearer {settings.meta_wa_token}"},
            timeout=30,
        )
        return resp.content
```

---

## 11. Database PostgreSQL

### 11.1 Engine e sessioni (`models/database.py`)

```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

async def create_tables():
    """Crea le tabelle se non esistono (solo per dev/primo avvio)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def get_db():
    """Dependency FastAPI per ottenere una sessione DB."""
    async with async_session() as session:
        yield session
```

### 11.2 Modelli ORM (`models/orm.py`)

```python
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean, ForeignKey, JSON, Date
)
from sqlalchemy.orm import relationship
from datetime import datetime
from models.database import Base


class Cliente(Base):
    __tablename__ = "clienti"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nome = Column(String(100))
    cognome = Column(String(100))
    telefono_wa = Column(String(20), unique=True, nullable=False, index=True)
    email = Column(String(255), nullable=True)  # opzionale, per conferme e promemoria
    canale_origine = Column(String(20), default="whatsapp")  # whatsapp | web
    note_private = Column(Text)  # allergie, preferenze, note parrucchiere
    parrucchiere_pref_id = Column(Integer, ForeignKey("parrucchieri.id"), nullable=True)
    prima_visita = Column(Date, default=datetime.now)
    ultima_visita = Column(Date, default=datetime.now)

    # Relazioni
    parrucchiere_pref = relationship("Parrucchiere", back_populates="clienti_pref")
    appuntamenti = relationship("Appuntamento", back_populates="cliente")


class Parrucchiere(Base):
    __tablename__ = "parrucchieri"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nome = Column(String(100), nullable=False)
    gcal_calendar_id = Column(String(255), nullable=False)
    attivo = Column(Boolean, default=True)

    # Relazioni
    clienti_pref = relationship("Cliente", back_populates="parrucchiere_pref")
    appuntamenti = relationship("Appuntamento", back_populates="parrucchiere")


class Appuntamento(Base):
    __tablename__ = "appuntamenti"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cliente_id = Column(Integer, ForeignKey("clienti.id"), nullable=False)
    parrucchiere_id = Column(Integer, ForeignKey("parrucchieri.id"), nullable=True)
    data_ora = Column(DateTime, nullable=False, index=True)
    durata_min = Column(Integer, default=30)
    servizi = Column(JSON)  # ["Taglio", "Barba"]
    stato = Column(String(20), default="Confermato")  # Confermato/Cancellato/Completato/No-show
    richieste_spec = Column(Text)
    foto_riferimento = Column(Text)  # URL o path file salvato
    gcal_event_id = Column(String(255))
    note_post_app = Column(Text)  # note del parrucchiere dopo il servizio
    reminder_inviato = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)

    # Relazioni
    cliente = relationship("Cliente", back_populates="appuntamenti")
    parrucchiere = relationship("Parrucchiere", back_populates="appuntamenti")
```

### 11.3 Servizio database (`services/db_service.py`)

```python
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from models.orm import Cliente, Appuntamento, Parrucchiere
from models.database import async_session
from datetime import datetime, timedelta


async def find_or_create_client(
    phone: str, nome: str = None, cognome: str = None,
    email: str = None, canale: str = "whatsapp",
) -> dict:
    """Cerca un cliente per telefono (o email se da web) o lo crea se nuovo."""
    async with async_session() as db:
        # Cerca per telefono o per email
        if phone:
            result = await db.execute(
                select(Cliente).where(Cliente.telefono_wa == phone)
            )
        elif email:
            result = await db.execute(
                select(Cliente).where(Cliente.email == email)
            )
        else:
            result = type('R', (), {'scalar_one_or_none': lambda: None})()

        client = result.scalar_one_or_none()

        if client:
            client.ultima_visita = datetime.now().date()
            # Aggiorna email se fornita e non presente
            if email and not client.email:
                client.email = email
            await db.commit()
            return {"id": client.id, "nome": client.nome, "cognome": client.cognome,
                    "email": client.email, "is_new": False}

        # Crea nuovo cliente
        client = Cliente(
            telefono_wa=phone or "",
            nome=nome,
            cognome=cognome,
            email=email,
            canale_origine=canale,
            prima_visita=datetime.now().date(),
            ultima_visita=datetime.now().date(),
        )
        db.add(client)
        await db.commit()
        await db.refresh(client)
        return {"id": client.id, "nome": client.nome, "cognome": client.cognome,
                "email": client.email, "is_new": True}


async def create_appointment(
    client_id: int, data_ora: str, servizi: list, parrucchiere: str,
    richieste_spec: str = None, foto_url: str = None,
    gcal_event_id: str = None, durata_min: int = 30,
) -> dict:
    """Crea un appuntamento nel database."""
    async with async_session() as db:
        # Trova parrucchiere per nome
        parrucchiere_id = None
        if parrucchiere:
            result = await db.execute(
                select(Parrucchiere).where(Parrucchiere.nome == parrucchiere)
            )
            parr = result.scalar_one_or_none()
            if parr:
                parrucchiere_id = parr.id

        dt = datetime.strptime(data_ora, "%Y-%m-%dT%H:%M")
        app = Appuntamento(
            cliente_id=client_id,
            parrucchiere_id=parrucchiere_id,
            data_ora=dt,
            durata_min=durata_min,
            servizi=servizi,
            stato="Confermato",
            richieste_spec=richieste_spec,
            foto_riferimento=foto_url,
            gcal_event_id=gcal_event_id,
        )
        db.add(app)
        await db.commit()
        await db.refresh(app)
        return {"id": app.id, "gcal_event_id": gcal_event_id}


async def update_appointment_status(app_id: int, status: str):
    """Aggiorna lo stato di un appuntamento."""
    async with async_session() as db:
        await db.execute(
            update(Appuntamento)
            .where(Appuntamento.id == app_id)
            .values(stato=status)
        )
        await db.commit()


async def get_upcoming_appointments(hours_from: float, hours_to: float) -> list:
    """Trova appuntamenti in un range di ore da adesso (per reminder)."""
    now = datetime.now()
    from_dt = now + timedelta(hours=hours_from)
    to_dt = now + timedelta(hours=hours_to)

    async with async_session() as db:
        result = await db.execute(
            select(Appuntamento)
            .join(Cliente)
            .where(
                Appuntamento.data_ora.between(from_dt, to_dt),
                Appuntamento.stato == "Confermato",
                Appuntamento.reminder_inviato == False,
            )
        )
        return result.scalars().all()


async def get_inactive_clients(days: int) -> list:
    """Trova clienti con ultima_visita > N giorni fa."""
    cutoff = (datetime.now() - timedelta(days=days)).date()
    async with async_session() as db:
        result = await db.execute(
            select(Cliente).where(Cliente.ultima_visita < cutoff)
        )
        return result.scalars().all()
```

### 11.4 Pannello Admin (`routers/admin.py`)

```python
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from datetime import datetime, date
from models.database import get_db
from models.orm import Appuntamento, Cliente, Parrucchiere
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
        # Cookie di sessione semplice (in produzione usare JWT o session middleware)
        from itsdangerous import URLSafeSerializer
        s = URLSafeSerializer(settings.secret_key)
        token = s.dumps({"user": username})
        response.set_cookie("session", token, httponly=True, max_age=86400)
        return response
    return templates.TemplateResponse("login.html", {"request": request, "error": "Credenziali errate"})


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
    target_date = datetime.strptime(data, "%Y-%m-%d").date() if data else date.today()

    # Query appuntamenti del giorno con relazioni
    result = await db.execute(
        select(Appuntamento)
        .options(selectinload(Appuntamento.cliente), selectinload(Appuntamento.parrucchiere))
        .where(
            Appuntamento.data_ora >= datetime.combine(target_date, datetime.min.time()),
            Appuntamento.data_ora < datetime.combine(target_date, datetime.max.time()),
            Appuntamento.stato == "Confermato",
        )
        .order_by(Appuntamento.data_ora)
    )
    appuntamenti = result.scalars().all()

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "appuntamenti": appuntamenti,
        "data_selezionata": target_date,
    })


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

    return templates.TemplateResponse("cliente.html", {
        "request": request,
        "cliente": cliente,
    })


@router.post("/cancel-notify")
async def cancel_notify(request: Request):
    """Endpoint per notifica cancellazione per assenza parrucchiere."""
    user = verify_session(request)
    if not user:
        return {"error": "Non autorizzato"}
    # Logica notifica cancellazione (invariata)
    body = await request.json()
    # ... gestione notifica
    return {"status": "notifiche inviate"}
```

---

## 11.5 Servizio Email (`services/email_service.py`)

```python
import resend
from config import settings
import logging

logger = logging.getLogger(__name__)

resend.api_key = settings.resend_api_key


async def send_confirmation_email(to: str, nome: str, data_ora: str, parrucchiere: str, servizi: list):
    """Invia email di conferma appuntamento."""
    if not to or not settings.resend_api_key:
        return

    servizi_str = ", ".join(servizi)
    try:
        resend.Emails.send({
            "from": f"Salone Nadia <{settings.email_from}>",
            "to": to,
            "subject": f"Conferma appuntamento - Salone Nadia",
            "html": f"""
                <h2>Ciao {nome}!</h2>
                <p>Il tuo appuntamento è confermato:</p>
                <ul>
                    <li><strong>Data e ora:</strong> {data_ora}</li>
                    <li><strong>Servizio:</strong> {servizi_str}</li>
                    <li><strong>Parrucchiere:</strong> {parrucchiere}</li>
                </ul>
                <p>Per cancellare o modificare, scrivici su WhatsApp o rispondi a questa email.</p>
                <p>A presto!<br>Salone Nadia</p>
            """,
        })
        logger.info(f"Email conferma inviata a {to}")
    except Exception as e:
        logger.error(f"Errore invio email conferma a {to}: {e}")


async def send_reminder_email(to: str, nome: str, orario: str, parrucchiere: str):
    """Invia email di promemoria appuntamento."""
    if not to or not settings.resend_api_key:
        return

    try:
        resend.Emails.send({
            "from": f"Salone Nadia <{settings.email_from}>",
            "to": to,
            "subject": f"Promemoria: appuntamento domani - Salone Nadia",
            "html": f"""
                <h2>Ciao {nome}!</h2>
                <p>Ti ricordiamo il tuo appuntamento di <strong>domani alle {orario}</strong>
                con <strong>{parrucchiere}</strong>.</p>
                <p>Per cancellare, scrivici su WhatsApp entro 12 ore.</p>
                <p>A domani!<br>Salone Nadia</p>
            """,
        })
        logger.info(f"Email reminder inviata a {to}")
    except Exception as e:
        logger.error(f"Errore invio email reminder a {to}: {e}")
```

---

## 11.6 Chat WebSocket per il sito (`routers/chat_ws.py`)

```python
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from services.session_manager import get_session, save_session, new_session
from services.conversation import handle_incoming_message_web
import json
import uuid

router = APIRouter()


@router.websocket("/ws/chat")
async def chat_websocket(websocket: WebSocket):
    """WebSocket per la chat dal sito web del salone."""
    await websocket.accept()
    redis = websocket.app.state.redis

    # Genera un ID sessione unico per il visitatore web
    session_id = f"web_{uuid.uuid4().hex[:12]}"

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            text = msg.get("text", "")

            if not text.strip():
                continue

            # Processa il messaggio con la stessa logica conversazionale
            response = await handle_incoming_message_web(
                redis=redis,
                session_id=session_id,
                text=text,
                email=msg.get("email"),  # il widget può mandare l'email
            )

            await websocket.send_text(json.dumps({
                "type": "message",
                "text": response,
            }))

    except WebSocketDisconnect:
        pass
```

---

## 11.7 Sito web del salone (`routers/website.py`)

```python
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["sito"])
templates = Jinja2Templates(directory="templates/sito")


@router.get("/", response_class=HTMLResponse)
async def homepage(request: Request):
    """Homepage pubblica del salone."""
    return templates.TemplateResponse("index.html", {
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
    })


@router.get("/chi-siamo", response_class=HTMLResponse)
async def chi_siamo(request: Request):
    return templates.TemplateResponse("chi_siamo.html", {"request": request})
```

Il widget di chat è un componente HTML/JS che si include in tutte le pagine del sito. Si connette via WebSocket a `/ws/chat` e offre la stessa esperienza conversazionale di WhatsApp. Il visitatore può prenotare direttamente dalla chat del sito.

---

## 12. System prompt builder (`prompts/system_prompt.py`)

```python
from config import settings

PARRUCCHIERI_INFO = """
Parrucchieri: Marco, Luca, Gianni, Alessandro, Roberto, Davide
(Nota: la lista va aggiornata con i nomi reali forniti da Nadia)
"""

# Regole di assegnazione - DA PERSONALIZZARE CON NADIA
REGOLE_ASSEGNAZIONE = """
## REGOLE DI ASSEGNAZIONE (da completare con Nadia)
- Bambini sotto i 12 anni: [operatore dedicato]
- Tagli classici over 50: [operatore dedicato]
- Tagli moderni/giovanili: [operatore dedicato]
- Barba/rasatura: [operatore dedicato]
"""

def build_system_prompt(session: dict) -> str:
    stato = session["stato_flusso"]
    dati = session["dati_temp"]

    prompt = f"""Sei Nadia, l'assistente virtuale del Salone Nadia.
Sei cordiale, amichevole e professionale. Parli in italiano.
Il tuo compito è gestire le prenotazioni degli appuntamenti via WhatsApp.

## INFORMAZIONI SUL SALONE
Orari: martedì-venerdì 8:00-12:00 e 14:30-19:30, sabato 8:00-18:00.
Chiuso domenica e lunedì (tranne aperture straordinarie a dicembre).
Durata ogni servizio: 30 minuti. Slot ogni 30 minuti.

Servizi disponibili:
- Taglio (30 min)
- Taglio + Shampoo (30 min)
- Taglio + Barba (60 min — 2 slot)
- Barba regolata (30 min)
- Taglio + Barba + Shampoo (60 min — 2 slot)

{PARRUCCHIERI_INFO}
{REGOLE_ASSEGNAZIONE}

## FASE CORRENTE: {stato}

## DATI GIÀ RACCOLTI
Servizio scelto: {dati.get('servizio', 'non ancora scelto')}
Parrucchiere: {dati.get('parrucchiere', 'non ancora scelto')}
Slot: {dati.get('slot', 'non ancora scelto')}
Nome: {dati.get('nome', 'non ancora raccolto')}
Cognome: {dati.get('cognome', 'non ancora raccolto')}
Email: {dati.get('email', 'non ancora raccolta')}

## REGOLE
1. Non inventare mai disponibilità. Se devi verificare uno slot, rispondi con l'azione CHECK_DISPONIBILITA.
2. Se il parrucchiere preferito non è disponibile, offri alternative.
3. Per clienti nuovi senza preferenza, chiedi età e tipo di taglio desiderato.
4. Se il cliente invia una foto, conferma che l'hai ricevuta e salvata.
5. Se non capisci la richiesta, chiedi gentilmente di ripetere.
6. Non rispondere a domande non legate al salone o alle prenotazioni.
7. Rispondi nella lingua usata dal cliente.
8. Tieni le risposte brevi e conversazionali (è WhatsApp, non un'email).

## FLUSSO DA SEGUIRE
- saluto → chiedi cosa desidera
- scelta_servizio → chiedi quale servizio
- scelta_operatore → chiedi se ha un parrucchiere preferito
- scelta_slot → usa CHECK_DISPONIBILITA poi proponi slot
- intake → raccogli nome, cognome, richieste speciali
- email → dopo la conferma, chiedi se vuole lasciare la mail per ricevere conferma e promemoria (NON obbligatoria, se rifiuta procedi senza insistere)
- confermato → usa CREA_APPUNTAMENTO poi conferma

## AZIONI SPECIALI
Quando hai bisogno di dati dal sistema, rispondi SOLO con il JSON dell'azione:
{{"action": "CHECK_DISPONIBILITA", "data": "2026-05-10", "parrucchiere": "Marco"}}
{{"action": "CREA_APPUNTAMENTO", "slot": "2026-05-10T09:00", "parrucchiere": "Marco", "parrucchiere_cal_id": "cal_id", "servizi": ["Taglio"], "durata_min": 30}}
{{"action": "CANCELLA_APPUNTAMENTO", "app_id": "rec123", "gcal_event_id": "evt123", "parrucchiere_cal_id": "cal_id"}}

Rispondi SOLO con il JSON quando serve un'azione. Non aggiungere testo prima o dopo il JSON.
Per tutto il resto, rispondi in linguaggio naturale al cliente.
"""
    return prompt
```

---

## 13. Job schedulati (`jobs/`)

### `jobs/scheduler.py`

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from jobs.reminder_job import send_reminders
from jobs.recontact_job import recontact_inactive

scheduler = AsyncIOScheduler()

def start_scheduler():
    # Reminder: ogni 30 minuti
    scheduler.add_job(send_reminders, "interval", minutes=30, id="reminder_12h")

    # Ricontatto: ogni lunedì alle 10:00
    scheduler.add_job(recontact_inactive, "cron", day_of_week="mon", hour=10, id="recontact")

    scheduler.start()

def shutdown_scheduler():
    scheduler.shutdown()
```

### `jobs/reminder_job.py`

```python
from services.db_service import get_upcoming_appointments
from services.whatsapp_service import send_template
from services.email_service import send_reminder_email
from models.database import async_session
from models.orm import Appuntamento
from sqlalchemy import update
import logging

logger = logging.getLogger(__name__)

async def send_reminders():
    """Invia reminder per appuntamenti tra 11.5 e 12.5 ore da adesso.
    Logica doppio canale:
    - Se il cliente ha email → invia via email (gratuito)
    - Se il cliente ha WhatsApp → invia anche via WhatsApp (template)
    - Se ha entrambi → invia su entrambi i canali
    """
    appointments = await get_upcoming_appointments(hours_from=11.5, hours_to=12.5)

    async with async_session() as db:
        for app in appointments:
            try:
                nome = app.cliente.nome or ""
                orario = app.data_ora.strftime("%H:%M")
                parrucchiere = app.parrucchiere.nome if app.parrucchiere else ""
                telefono = app.cliente.telefono_wa
                email = app.cliente.email

                # Invia via email se disponibile (gratuito)
                if email:
                    await send_reminder_email(email, nome, orario, parrucchiere)

                # Invia via WhatsApp se disponibile
                if telefono:
                    await send_template(
                        to=telefono,
                        template_name="reminder_12h",
                        parameters=[nome, orario, parrucchiere],
                    )

                # Segna come inviato
                await db.execute(
                    update(Appuntamento)
                    .where(Appuntamento.id == app.id)
                    .values(reminder_inviato=True)
                )
                await db.commit()
                logger.info(f"Reminder inviato per app {app.id} (email={bool(email)}, wa={bool(telefono)})")

            except Exception as e:
                logger.error(f"Errore invio reminder per {app.id}: {e}")
```

### `jobs/recontact_job.py`

```python
from services.db_service import get_inactive_clients
from services.whatsapp_service import send_template
from config import settings
import logging

logger = logging.getLogger(__name__)

async def recontact_inactive():
    """Ricontatta clienti inattivi da più di N giorni."""
    clients = await get_inactive_clients(settings.inactivity_days)

    for client in clients:
        try:
            nome = client.nome or ""
            telefono = client.telefono_wa

            if telefono:
                await send_template(
                    to=telefono,
                    template_name="ricontatto_inattivo",
                    parameters=[nome],
                )
                logger.info(f"Ricontatto inviato a {telefono}")

        except Exception as e:
            logger.error(f"Errore ricontatto per {client.id}: {e}")
```

---

## 14. Deploy su Render

### Perché Render

Render è una piattaforma PaaS che elimina la gestione server: HTTPS automatico, deploy da Git, Redis integrato, log e metriche inclusi. Piano gratuito per test, Starter (~7$/mese) per produzione.

### `render.yaml`

```yaml
services:
  - type: web
    name: salone-nadia-bot
    runtime: python
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn main:app --host 0.0.0.0 --port $PORT
    envVars:
      - key: ANTHROPIC_API_KEY
        sync: false
      - key: META_WA_TOKEN
        sync: false
      - key: META_PHONE_NUMBER_ID
        sync: false
      - key: META_VERIFY_TOKEN
        sync: false
      - key: GOOGLE_CREDENTIALS_JSON
        sync: false
      - key: GCAL_SALONE_ID
        sync: false
      - key: GCAL_PARRUCCHIERE_IDS
        sync: false
      - key: DATABASE_URL
        fromDatabase:
          name: salone-nadia-db
          property: connectionString
      - key: ADMIN_USERNAME
        value: "nadia"
      - key: ADMIN_PASSWORD
        sync: false
      - key: SECRET_KEY
        generateValue: true
      - key: RESEND_API_KEY
        sync: false
      - key: EMAIL_FROM
        value: "noreply@salonenadia.it"
      - key: REDIS_URL
        fromService:
          name: salone-nadia-redis
          type: redis
          property: connectionString
      - key: SLOT_DURATION_MIN
        value: "30"
      - key: MAX_BOOKING_DAYS_AHEAD
        value: "30"
      - key: CANCEL_POLICY_HOURS
        value: "12"
      - key: INACTIVITY_DAYS
        value: "60"

  - type: redis
    name: salone-nadia-redis
    plan: free
    maxmemoryPolicy: allkeys-lru

databases:
  - name: salone-nadia-db
    plan: free
    databaseName: salone_nadia
    postgresMajorVersion: "16"
```

### Primo deploy

```bash
# 1. Pusha il progetto su GitHub
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/tuo-utente/salone-nadia-bot.git
git push -u origin main

# 2. Vai su render.com → New → Blueprint
#    Collega il repository GitHub
#    Render rileva render.yaml e crea automaticamente:
#    - Web Service (salone-nadia-bot)
#    - Redis (salone-nadia-redis)

# 3. In Dashboard → salone-nadia-bot → Environment
#    Inserisci tutte le variabili sensibili (API keys, token, credenziali Google)
#    Nota: le credenziali Google vanno come stringa JSON nella variabile GOOGLE_CREDENTIALS_JSON

# 4. Il deploy parte automaticamente
#    URL: https://salone-nadia-bot.onrender.com

# 5. Verifica
curl https://salone-nadia-bot.onrender.com/health
# → {"status": "ok"}

# 6. Configura questo URL come webhook in Meta for Developers
```

### Aggiornamenti successivi

```bash
# Basta un push — Render rideploya automaticamente
git add .
git commit -m "Aggiornamento"
git push
```

### Nota sul piano Free

Il piano gratuito mette in sleep l'istanza dopo 15 minuti di inattività. Al risveglio servono 30-50 secondi. Per test va bene. Per produzione, attivare il piano Starter ($7/mese) che mantiene l'istanza sempre attiva.

### Credenziali Google su Render

Su Render non puoi caricare file, quindi le credenziali del service account Google vanno inserite come stringa JSON nella variabile d'ambiente `GOOGLE_CREDENTIALS_JSON`. Aggiorna `config.py` per gestire entrambi i casi:

```python
import json
import tempfile
import os

@property
def google_credentials_path(self) -> str:
    """Se GOOGLE_CREDENTIALS_JSON è un path a file, usalo. 
    Se è una stringa JSON, scrivi un file temporaneo."""
    val = self.google_credentials_json
    if os.path.isfile(val):
        return val
    # È una stringa JSON → scrivi file temporaneo
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
    tmp.write(val)
    tmp.close()
    return tmp.name
```

---

## 16. Configurazione WhatsApp Cloud API (Meta)

### Step-by-step

1. Vai su [developers.facebook.com](https://developers.facebook.com)
2. Crea una nuova app → tipo "Business"
3. Aggiungi il prodotto "WhatsApp"
4. Nella sezione WhatsApp → Setup:
   - Genera un access token permanente (System User token dal Business Manager)
   - Annota il Phone Number ID
5. Configura il webhook:
   - URL: `https://tuodominio.com/webhook/whatsapp`
   - Verify token: il valore di `META_VERIFY_TOKEN` nel tuo `.env`
   - Sottoscrivi il campo: `messages`
6. Nella sezione "Message Templates":
   - Crea i 4 template (conferma, reminder, cancellazione, ricontatto)
   - Lingua: italiano
   - Attendi approvazione (24-48h)

### Migrazione numero esistente

Se il salone ha già un numero su WhatsApp Business (app mobile):
1. De-registra il numero dall'app mobile (Impostazioni → Account → Elimina account)
2. Aggiungi il numero nella sezione WhatsApp dell'app Meta
3. Verifica via SMS o chiamata
4. Il numero è ora collegato alla Cloud API

**Attenzione:** durante la migrazione il numero non sarà raggiungibile. Pianificare in orario di chiusura.

---

## 17. Test

### Strategia di test

```python
# tests/conftest.py
import pytest
from unittest.mock import AsyncMock

@pytest.fixture
def mock_redis():
    """Redis mock che simula get/set/delete."""
    redis = AsyncMock()
    store = {}

    async def mock_get(key):
        return store.get(key)

    async def mock_set(key, value, ex=None):
        store[key] = value

    async def mock_delete(key):
        store.pop(key, None)

    redis.get = mock_get
    redis.set = mock_set
    redis.delete = mock_delete
    return redis
```

### Scenari da testare

1. **Nuovo cliente, prenotazione completa** — saluto → scelta servizio → scelta operatore → scelta slot → intake → conferma
2. **Cliente abituale con preferenza** — riconoscimento numero → proposta parrucchiere preferito
3. **Slot non disponibile** — verifica che proponga alternative
4. **Cancellazione > 12h** — accettata automaticamente
5. **Cancellazione < 12h** — warning + conferma + segnalazione receptionist
6. **Messaggio fuori tema** — rifiuto gentile
7. **Foto inviata** — conferma ricezione e salvataggio
8. **Servizi multipli** — calcolo durata corretta e slot consecutivi

---

## 18. Monitoraggio e logging

### Configurazione logging

```python
# In main.py, prima di tutto
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/app/logs/bot.log"),
    ],
)
```

### Cosa monitorare

- **Errori Claude API:** timeout, rate limit, risposte malformate
- **Errori Google Calendar:** permessi, quota, eventi duplicati
- **Errori WhatsApp:** messaggi non consegnati, webhook failures
- **Metriche business:** n. prenotazioni/giorno, n. cancellazioni, tempo medio conversazione
- **Costi API:** token Claude consumati per conversazione

### Health check avanzato

```python
@app.get("/health/detailed")
async def health_detailed(request: Request):
    redis_ok = False
    try:
        await request.app.state.redis.ping()
        redis_ok = True
    except Exception:
        pass

    return {
        "status": "ok" if redis_ok else "degraded",
        "redis": redis_ok,
        "timestamp": datetime.now().isoformat(),
    }
```

---

## 19. Checklist pre-lancio

- [ ] Account Meta Business Manager verificato
- [ ] App Meta creata con prodotto WhatsApp
- [ ] Numero WhatsApp migrato/configurato
- [ ] Token permanente generato (System User)
- [ ] Webhook configurato e verificato
- [ ] Template messaggi approvati da Meta (tutti e 4)
- [ ] Google Calendar: calendari creati per ogni parrucchiere + eccezioni
- [ ] Google Calendar: service account con accesso ai calendari
- [ ] PostgreSQL: database creato su Render (piano free)
- [ ] PostgreSQL: migrazioni eseguite (tabelle Clienti, Appuntamenti, Parrucchieri)
- [ ] Pannello admin: pagina dashboard funzionante per la receptionist
- [ ] Sito web: homepage con orari, servizi, contatti
- [ ] Sito web: widget chat funzionante (WebSocket)
- [ ] Email: account Resend configurato (piano free)
- [ ] Email: dominio verificato per invio email
- [ ] File .env completo con tutte le credenziali
- [ ] Test end-to-end con numero di test WhatsApp
- [ ] Test end-to-end chat dal sito web
- [ ] Test invio email conferma e promemoria
- [ ] System prompt affinato con regole specifiche di Nadia
- [ ] Chiusure annuali inserite nel calendario eccezioni
- [ ] Training receptionist su pannello admin e gestione assenze
- [ ] Comunicazione ai clienti sulla novità (WhatsApp + sito)
