from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from datetime import datetime, timedelta
from config import settings
from prompts.system_prompt import get_parrucchieri_map_cached
from services.slots import FUSO_SALONE, adesso_salone
from services.slots import generate_slots as _generate_slots
import asyncio
import logging

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _inizio_slot(slot: str) -> datetime:
    """Istante di inizio di uno slot ('2026-11-10T15:00') nel fuso del salone."""
    return datetime.strptime(slot, "%Y-%m-%dT%H:%M").replace(tzinfo=FUSO_SALONE)


def _istante(punto: dict) -> datetime | None:
    """Converte lo start/end di un evento Google in un istante con fuso.

    Gli eventi su tutta la giornata portano solo 'date': valgono dalla
    mezzanotte del salone.
    """
    valore = punto.get("dateTime")
    if valore:
        return datetime.fromisoformat(valore)
    giorno = punto.get("date")
    if giorno:
        return datetime.strptime(giorno, "%Y-%m-%d").replace(tzinfo=FUSO_SALONE)
    return None


def _get_cal_id_to_name() -> dict[str, str]:
    """Reverse map cal_id → nome, sempre aggiornata dalla cache DB."""
    return {v: k for k, v in get_parrucchieri_map_cached().items()}


def _get_service():
    creds = service_account.Credentials.from_service_account_file(
        settings.google_credentials_path, scopes=SCOPES
    )
    return build("calendar", "v3", credentials=creds)


async def check_availability(
    date_str: str, parrucchiere_cal_id: str = None, durata_min: int = 30
) -> list[dict]:
    """Restituisce gli slot liberi per una data (e opzionalmente un parrucchiere).
    Per servizi da 60 min, verifica automaticamente 2 slot consecutivi.
    """
    service = _get_service()
    possible_slots = _generate_slots(
        date_str,
        adesso=adesso_salone(),
        anticipo_minimo_min=settings.min_booking_hours_ahead * 60,
    )

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
        if not cal_ids:
            raise RuntimeError(
                "Nessun calendario configurato: imposta GCAL_PARRUCCHIERE_IDS."
            )

        available = []
        non_leggibili = []
        for cal_id in cal_ids:
            try:
                events = service.events().list(
                    calendarId=cal_id,
                    timeMin=time_min, timeMax=time_max,
                    singleEvents=True, orderBy="startTime",
                ).execute().get("items", [])
            except HttpError as e:
                logger.warning(f"Calendario {cal_id} non accessibile: {e}")
                non_leggibili.append(f"{cal_id} (HTTP {e.resp.status})")
                continue

            busy_times = []
            for ev in events:
                inizio = _istante(ev["start"])
                fine = _istante(ev["end"])
                if inizio and fine:
                    busy_times.append((inizio, fine))

            # Trova slot liberi per questo parrucchiere
            free_slots = set()
            for slot in possible_slots:
                slot_start = _inizio_slot(slot)
                slot_end = slot_start + timedelta(minutes=settings.slot_duration_min)

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

        # Un calendario irraggiungibile restituiva una lista vuota, che il bot
        # riferiva al cliente come "nessuna disponibilità": il salone risultava
        # pieno mentre era solo mal configurato. Se non se ne è potuto leggere
        # nemmeno uno, è un guasto e va detto.
        if non_leggibili and len(non_leggibili) == len(cal_ids):
            raise RuntimeError(
                "Nessun calendario leggibile: " + "; ".join(non_leggibili)
            )

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
    """Cancella un evento da Google Calendar.

    Un evento già assente non è un errore: capita quando la receptionist lo ha
    rimosso a mano dal calendario. Fermarsi lì lascerebbe l'appuntamento
    "Confermato" nel database, cioè l'opposto di quello che il cliente ha
    chiesto disdicendo.
    """
    service = _get_service()

    def _delete():
        try:
            service.events().delete(
                calendarId=calendar_id, eventId=event_id
            ).execute()
        except HttpError as e:
            if e.resp.status in (404, 410):
                logger.info(
                    "Evento %s già assente dal calendario %s", event_id, calendar_id
                )
                return
            raise

    await asyncio.to_thread(_delete)
