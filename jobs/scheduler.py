from apscheduler.schedulers.asyncio import AsyncIOScheduler
from jobs.reminder_job import send_reminders
from jobs.recontact_job import recontact_inactive

scheduler = AsyncIOScheduler()


def start_scheduler():
    # Reminder: ogni 30 minuti
    scheduler.add_job(send_reminders, "interval", minutes=30, id="reminder_12h")

    # Ricontatto: ogni lunedì alle 10:00
    scheduler.add_job(
        recontact_inactive, "cron", day_of_week="mon", hour=10, id="recontact"
    )

    scheduler.start()


def shutdown_scheduler():
    scheduler.shutdown()
