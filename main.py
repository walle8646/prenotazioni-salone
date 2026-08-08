import logging
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import redis.asyncio as aioredis
from config import settings
from models.database import engine, create_tables
from routers import webhook, admin, website, chat_ws
from jobs.scheduler import start_scheduler, shutdown_scheduler

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)

app_redis = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global app_redis
    # Inizializza PostgreSQL
    await create_tables()
    # Operatori e listino: il database è la fonte di verità, il codice fornisce
    # i valori iniziali al primo avvio. Entrambi finiscono in una cache in
    # memoria che il resto dell'applicazione legge a ogni messaggio.
    from services.db_service import (
        get_parrucchieri_map,
        get_servizi_attivi,
        seed_parrucchieri,
        seed_servizi,
    )
    from services.operatori import verifica_configurazione
    from services import catalogo
    from prompts.system_prompt import PARRUCCHIERI_MAP, set_parrucchieri_cache

    verifica_configurazione()
    if not settings.admin_password or not settings.secret_key_configurata:
        logging.getLogger(__name__).warning(
            "Pannello amministrativo non accessibile: ADMIN_PASSWORD o SECRET_KEY "
            "non sono configurate. Il resto del bot funziona."
        )
    await seed_parrucchieri(PARRUCCHIERI_MAP)
    set_parrucchieri_cache(await get_parrucchieri_map())

    await seed_servizi(catalogo.SERVIZI_INIZIALI)
    servizi = await get_servizi_attivi()
    catalogo.set_catalogo_cache(servizi)
    logging.getLogger(__name__).info(
        "Listino caricato: %s servizi attivi", len(servizi)
    )
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


@app.get("/health/detailed")
async def health_detailed(request=None):
    from fastapi import Request
    from datetime import datetime

    redis_ok = False
    try:
        await app_redis.ping()
        redis_ok = True
    except Exception:
        pass

    return {
        "status": "ok" if redis_ok else "degraded",
        "redis": redis_ok,
        "timestamp": datetime.now().isoformat(),
    }
