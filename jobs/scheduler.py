from apscheduler.schedulers.asyncio import AsyncIOScheduler
from jobs.reminder_job import send_reminders
from jobs.recontact_job import recontact_inactive
from jobs.sollecito_job import (
    INTERVALLO_MINUTI,
    sollecita_conversazioni_in_attesa,
)

scheduler = AsyncIOScheduler()


def start_scheduler():
    # Reminder: ogni 30 minuti
    scheduler.add_job(send_reminders, "interval", minutes=30, id="reminder_12h")

    # Ricontatto: ogni lunedì alle 10:00
    scheduler.add_job(
        recontact_inactive, "cron", day_of_week="mon", hour=10, id="recontact"
    )

    # Sollecito: chi ha chiesto una persona e aspetta ancora. L'intervallo lo
    # dichiara il job, perche' decide anche la larghezza della fascia che gli
    # evita di sollecitare due volte lo stesso cliente.
    scheduler.add_job(
        sollecita_conversazioni_in_attesa,
        "interval",
        minutes=INTERVALLO_MINUTI,
        id="sollecito_attesa",
    )

    scheduler.start()


def shutdown_scheduler():
    scheduler.shutdown()
