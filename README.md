# Salone Nadia — Bot Prenotazioni

Sistema AI per prenotazioni automatizzate via WhatsApp e sito web.

## Stack

- **Backend:** FastAPI + Uvicorn
- **AI:** Claude API (Anthropic)
- **Calendario:** Google Calendar API
- **Database:** PostgreSQL (SQLAlchemy async + asyncpg)
- **Sessioni:** Redis
- **WhatsApp:** Cloud API Meta (diretto, no BSP)
- **Email:** Resend (piano free, 100/giorno)
- **Chat web:** WebSocket
- **Deploy:** Render

## Setup locale

```bash
# 1. Clona il repo
git clone https://github.com/walle8646/prenotazioni-salone.git
cd prenotazioni-salone

# 2. Crea virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# 3. Installa dipendenze
pip install -r requirements.txt

# 4. Configura variabili ambiente
cp .env.example .env
# Modifica .env con le tue credenziali

# 5. Avvia (richiede PostgreSQL e Redis in esecuzione)
uvicorn main:app --reload
```

## Deploy su Render

1. Push su GitHub
2. Render → New → Blueprint → collega il repo
3. Render rileva `render.yaml` e crea web service + Redis + PostgreSQL
4. Inserisci le variabili d'ambiente in Dashboard → Environment
5. URL: `https://salone-nadia-bot.onrender.com`

## Test

```bash
pytest tests/
```

## Struttura

```
├── main.py              # Entrypoint FastAPI
├── config.py            # Settings (Pydantic BaseSettings)
├── routers/             # Webhook WA, admin, sito, WebSocket
├── services/            # Business logic (Claude, Calendar, DB, WA, Email)
├── models/              # ORM + Pydantic schemas
├── jobs/                # Scheduler (reminder, recontact)
├── prompts/             # System prompt builder
├── templates/           # HTML (admin + sito pubblico)
├── static/              # CSS + JS
├── alembic/             # Migrazioni DB
├── tests/               # Test suite
└── render.yaml          # Deploy config
```
