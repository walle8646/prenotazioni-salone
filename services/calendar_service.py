from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from datetime import datetime, timedelta
from config import settings
from prompts.system_prompt import get_parrucchieri_map_cached
import asyncio
import logging

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _get_cal_id_to_name() -> dict[str, str]:
    """Reverse map cal_id → nome, sempre aggiornata dalla cache DB."""
    return {v: k for k, v in get_parrucchieri_map_cached().items()}


def _get_service():
    creds = service_account.Credentials.from_service_account_file(
        settings.google_credentials_path, scopes=SCOPES
    )
    return build("calendar", "v3", credentials=creds)


def _generate_slots(date_str: str) -> list[str]:
    """Genera tutti gli slot possibili per una data (rispettando orari salone)."""
    date = datetime.strptime(date_str, "%Y-%m-%d")
    weekday = date.weekday()  # 0=lun, 5=sab, 6=dom

    if weekday in (0, 6):  # lunedì o domenica → chiuso
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


async def check_availability(
    date_str: str, parrucchiere_cal_id: str = None, durata_min: int = 30
) -> list[dict]:
    """Restituisce gli slot liberi per una data (e opzionalmente un parrucchiere).
    Per servizi da 60 min, verifica automaticamente 2 slot consecutivi.
    """
    service = _get_service()
    possible_slots = _generate_slots(date_str)

    if not possible_slots:
        return []

    # Prima: controlla eccezioni salone
    time_min = f"{date_str}T00:00:00Z"
    time_max = f"{date_str}T23:59:59Z"

    def _check():
        # Eccezioni salone (se il calendario è condiviso)
        if settings.gcal_salone_id:
            try:
                eccezioni = service.events().list(
                    calendarId=settings.gcal_salone_id,
                    timeMin=time_min, timeMax=time_max,
                    singleEvents=True,
                ).execute().get("items", [])

                for ev in eccezioni:
                    if ev.get("summary", "").lower().startswith("chius"):
                        return []  # Giorno chiuso
            except HttpError as e:
                logger.warning(f"Calendario eccezioni non accessibile: {e}")

        # Calendari da controllare
        cal_ids = [parrucchiere_cal_id] if parrucchiere_cal_id else settings.parrucchiere_calendar_ids

        available = []
        for cal_id in cal_ids:
            try:
                events = service.events().list(
                    calendarId=cal_id,
                    timeMin=time_min, timeMax=time_max,
                    singleEvents=True, orderBy="startTime",
                ).execute().get("items", [])
            except HttpError as e:
                logger.warning(f"Calendario {cal_id} non accessibile: {e}")
                continue

            busy_times = []
            for ev in events:
                start = ev["start"].get("dateTime", ev["start"].get("date"))
                end = ev["end"].get("dateTime", ev["end"].get("date"))
                busy_times.append((start, end))

            # Trova slot liberi per questo parrucchiere
            free_slots = set()
            for slot in possible_slots:
                slot_start = f"{slot}:00+02:00"
                slot_end_dt = datetime.strptime(slot, "%Y-%m-%dT%H:%M") + timedelta(
                    minutes=settings.slot_duration_min
                )
                slot_end = slot_end_dt.strftime("%Y-%m-%dT%H:%M:00+02:00")

                is_busy = any(
                    not (slot_end <= bs or slot_start >= be)
                    for bs, be in busy_times
                )
                if not is_busy:
                    free_slots.add(slot)

            # Se durata > 30 min, verifica slot consecutivi
            slots_needed = durata_min // settings.slot_duration_min
            nome_parrucchiere = _get_cal_id_to_name().get(cal_id, "Sconosciuto")

            for slot in sorted(free_slots):
                if slots_needed > 1:
                    # Verifica che tutti gli slot consecutivi siano liberi
                    all_free = True
                    for i in range(1, slots_needed):
                        next_slot_dt = datetime.strptime(slot, "%Y-%m-%dT%H:%M") + timedelta(
                            minutes=settings.slot_duration_min * i
                        )
                        next_slot = next_slot_dt.strftime("%Y-%m-%dT%H:%M")
                        if next_slot not in free_slots:
                            all_free = False
                            break
                    if not all_free:
                        continue

                available.append({
                    "slot": slot,
                    "parrucchiere": nome_parrucchiere,
                    "parrucchiere_cal_id": cal_id,
                })

        return available

    return await asyncio.to_thread(_check)


async def create_event(
    slot: str, parrucchiere_cal_id: str,
    servizi: list, durata: int, cliente_nome: str,
    descrizione: str = ""
) -> str:
    """Crea un evento su Google Calendar. Restituisce l'event_id."""
    service = _get_service()
    start_dt = datetime.strptime(slot, "%Y-%m-%dT%H:%M")
    end_dt = start_dt + timedelta(minutes=durata)

    event = {
        "summary": f"{cliente_nome} - {', '.join(servizi)}",
        "start": {"dateTime": start_dt.strftime("%Y-%m-%dT%H:%M:00"), "timeZone": "Europe/Rome"},
        "end": {"dateTime": end_dt.strftime("%Y-%m-%dT%H:%M:00"), "timeZone": "Europe/Rome"},
    }
    if descrizione:
        event["description"] = descrizione

    def _create():
        result = service.events().insert(
            calendarId=parrucchiere_cal_id, body=event
        ).execute()
        return result["id"]

    return await asyncio.to_thread(_create)


async def delete_event(event_id: str, calendar_id: str):
    """Cancella un evento da Google Calendar."""
    service = _get_service()

    def _delete():
        service.events().delete(
            calendarId=calendar_id, eventId=event_id
        ).execute()

    await asyncio.to_thread(_delete)
