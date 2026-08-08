from pydantic_settings import BaseSettings
from typing import List
import json
import os
import tempfile


class Settings(BaseSettings):
    # Claude
    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-6"

    # WhatsApp
    meta_wa_token: str = ""
    meta_phone_number_id: str = ""
    meta_verify_token: str = ""
    meta_api_url: str = "https://graph.facebook.com/v21.0"

    # Google Calendar
    google_credentials_json: str = ""
    gcal_salone_id: str = ""
    gcal_parrucchiere_ids: str = "[]"

    # PostgreSQL
    database_url: str = "postgresql+asyncpg://localhost:5432/salone_nadia"

    @property
    def async_database_url(self) -> str:
        """Converte l'URL del database per asyncpg.
        Render fornisce postgresql://, noi usiamo postgresql+asyncpg://"""
        url = self.database_url
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        return url

    # Admin pannello
    admin_username: str = "nadia"
    admin_password: str = ""
    secret_key: str = "dev-secret-change-me"

    # Email
    resend_api_key: str = ""
    email_from: str = "noreply@salonenadia.it"

    # Numero del salone, dato al cliente quando non può disdire da solo perché
    # è troppo tardi. Vuoto: il bot dice genericamente di telefonare.
    salone_telefono: str = ""

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Business config
    slot_duration_min: int = 30
    max_booking_days_ahead: int = 30
    # Entro quante ore dall'appuntamento non si può più disdire dalla chat:
    # sotto questa soglia il cliente deve telefonare al salone.
    cancel_policy_hours: int = 2
    inactivity_days: int = 60
    min_booking_hours_ahead: int = 2
    session_ttl_seconds: int = 7200
    max_history_messages: int = 20

    @property
    def parrucchiere_calendar_map(self) -> dict:
        """Associazione nome operatore → calendar ID.

        GCAL_PARRUCCHIERE_IDS può essere scritta come oggetto JSON
        ({"Simone Big": "abc@group.calendar.google.com", ...}) oppure, per
        retrocompatibilità, come semplice lista di ID: in quel caso i nomi non
        sono noti e la mappa risulta vuota.
        """
        try:
            raw = json.loads(self.gcal_parrucchiere_ids or "{}")
        except json.JSONDecodeError:
            return {}
        return raw if isinstance(raw, dict) else {}

    @property
    def parrucchiere_calendar_ids(self) -> List[str]:
        """Elenco dei calendar ID, qualunque sia il formato usato nella env var."""
        try:
            raw = json.loads(self.gcal_parrucchiere_ids or "[]")
        except json.JSONDecodeError:
            return []
        if isinstance(raw, dict):
            return list(raw.values())
        return list(raw)

    @property
    def google_credentials_path(self) -> str:
        """Se GOOGLE_CREDENTIALS_JSON è un path a file, usalo.
        Se è una stringa JSON, scrivi un file temporaneo."""
        val = self.google_credentials_json
        if os.path.isfile(val):
            return val
        # È una stringa JSON → scrivi file temporaneo
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        tmp.write(val)
        tmp.close()
        return tmp.name

    class Config:
        env_file = ".env"


settings = Settings()
