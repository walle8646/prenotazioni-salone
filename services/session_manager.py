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
            # Serve solo a chi scrive dal sito: da WhatsApp il numero è il
            # mittente stesso.
            "telefono": None,
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
