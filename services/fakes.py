"""Sostituti in memoria dei servizi esterni, per test e simulazioni.

Nulla qui viene usato in produzione: serve a far girare l'intero flusso di
prenotazione senza WhatsApp, senza Google Calendar, senza PostgreSQL e senza
Redis. È quello che rende possibile `python simulate.py --offline` e i test
automatici deterministici.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from config import settings
from services.backends import Backends
from services.slots import adesso_salone, generate_slots


class FakeRedis:
    """Redis in memoria: implementa solo get/set/delete, che è tutto ciò che usiamo."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None, nx=False):
        # Come Redis vero: con nx si scrive solo se la chiave non esiste, e in
        # caso contrario si restituisce None. Serve al webhook per riconoscere
        # i messaggi che Meta rimanda.
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def delete(self, key):
        self.store.pop(key, None)

    async def ping(self):
        return True

    async def close(self):
        return None


class FakeBackends(Backends):
    """Calendario, database ed email finti, tenuti in memoria.

    Il calendario parte vuoto (tutti gli slot liberi) e si riempie man mano che
    vengono creati appuntamenti, così il comportamento è realistico: se prenoti
    due volte lo stesso orario con lo stesso parrucchiere, il secondo tentativo
    non lo trova più libero.
    """

    def __init__(self, parrucchieri: dict[str, str] | None = None) -> None:
        if parrucchieri is None:
            from prompts.system_prompt import get_parrucchieri_map_cached

            parrucchieri = get_parrucchieri_map_cached()
        self.parrucchieri = parrucchieri
        # cal_id -> lista di (inizio, fine) occupati, come datetime
        self.occupati: dict[str, list[tuple[datetime, datetime]]] = {
            cal_id: [] for cal_id in parrucchieri.values()
        }
        self.eventi: dict[str, dict] = {}
        self.clienti: list[dict] = []
        self.appuntamenti: list[dict] = []
        self.email_inviate: list[dict] = []
        self.codici_inviati: list[dict] = []
        self.email_cancellazioni: list[dict] = []
        self.email_assenze: list[dict] = []
        self.email_spostamenti: list[dict] = []
        self.foto_salvate: list[str] = []
        self.giorni_chiusi: set[str] = set()
        self._contatore = 0

    # ---------------------------------------------------------------- utility

    def _nome_da_cal_id(self, cal_id: str) -> str:
        for nome, cid in self.parrucchieri.items():
            if cid == cal_id:
                return nome
        return "Sconosciuto"

    def occupa(self, cal_id: str, slot: str, durata_min: int = 30) -> None:
        """Segna manualmente uno slot come occupato (utile per preparare i test)."""
        inizio = datetime.strptime(slot, "%Y-%m-%dT%H:%M")
        self.occupati.setdefault(cal_id, []).append(
            (inizio, inizio + timedelta(minutes=durata_min))
        )

    def chiudi_giorno(self, date_str: str) -> None:
        """Simula una chiusura straordinaria del salone."""
        self.giorni_chiusi.add(date_str)

    # --------------------------------------------------------------- calendar

    async def check_availability(self, date_str, parrucchiere_cal_id, durata_min):
        if date_str in self.giorni_chiusi:
            return []

        # Come il calendario vero: niente slot già passati né troppo imminenti.
        possibili = generate_slots(
            date_str,
            adesso=adesso_salone(),
            anticipo_minimo_min=settings.min_booking_hours_ahead * 60,
        )
        if not possibili:
            return []

        cal_ids = (
            [parrucchiere_cal_id]
            if parrucchiere_cal_id
            else list(self.parrucchieri.values())
        )
        slot_necessari = max(1, durata_min // settings.slot_duration_min)

        disponibili = []
        for cal_id in cal_ids:
            occupati = self.occupati.get(cal_id, [])
            liberi = set()
            for slot in possibili:
                inizio = datetime.strptime(slot, "%Y-%m-%dT%H:%M")
                fine = inizio + timedelta(minutes=settings.slot_duration_min)
                if not any(not (fine <= bi or inizio >= bf) for bi, bf in occupati):
                    liberi.add(slot)

            for slot in sorted(liberi):
                if slot_necessari > 1:
                    inizio = datetime.strptime(slot, "%Y-%m-%dT%H:%M")
                    consecutivi = [
                        (
                            inizio + timedelta(minutes=settings.slot_duration_min * i)
                        ).strftime("%Y-%m-%dT%H:%M")
                        for i in range(1, slot_necessari)
                    ]
                    if any(s not in liberi for s in consecutivi):
                        continue
                disponibili.append(
                    {
                        "slot": slot,
                        "parrucchiere": self._nome_da_cal_id(cal_id),
                        "parrucchiere_cal_id": cal_id,
                    }
                )
        return disponibili

    async def create_event(
        self, slot, parrucchiere_cal_id, servizi, durata, cliente_nome, descrizione=""
    ):
        self._contatore += 1
        event_id = f"fake_evt_{self._contatore}"
        self.occupa(parrucchiere_cal_id, slot, durata)
        self.eventi[event_id] = {
            "slot": slot,
            "cal_id": parrucchiere_cal_id,
            "servizi": servizi,
            "durata": durata,
            "cliente": cliente_nome,
            "descrizione": descrizione,
        }
        return event_id

    async def delete_event(self, event_id, calendar_id):
        evento = self.eventi.pop(event_id, None)
        if evento:
            inizio = datetime.strptime(evento["slot"], "%Y-%m-%dT%H:%M")
            fine = inizio + timedelta(minutes=evento["durata"])
            self.occupati[evento["cal_id"]] = [
                t for t in self.occupati.get(evento["cal_id"], []) if t != (inizio, fine)
            ]

    # --------------------------------------------------------------- database

    async def find_or_create_client(
        self, phone, nome=None, cognome=None, email=None, canale="whatsapp"
    ):
        for cliente in self.clienti:
            if cliente["telefono"] == phone or (email and cliente.get("email") == email):
                if email and not cliente.get("email"):
                    cliente["email"] = email
                # Come il database vero: un numero reale sostituisce
                # l'identificativo di sessione di chi era nato dal sito.
                if (
                    phone
                    and not phone.startswith("web_")
                    and str(cliente.get("telefono") or "").startswith("web_")
                ):
                    cliente["telefono"] = phone
                return {**cliente, "is_new": False}

        cliente = {
            "id": len(self.clienti) + 1,
            "telefono": phone,
            "nome": nome,
            "cognome": cognome,
            "email": email,
            "canale": canale,
        }
        self.clienti.append(cliente)
        return {**cliente, "is_new": True}

    async def create_appointment(self, **kwargs):
        record = {"id": len(self.appuntamenti) + 1, "stato": "Confermato", **kwargs}
        self.appuntamenti.append(record)
        return {"id": record["id"], "gcal_event_id": kwargs.get("gcal_event_id")}

    async def update_appointment_status(self, app_id, status):
        for app in self.appuntamenti:
            if app["id"] == app_id:
                app["stato"] = status

    async def get_appuntamenti_per_telefono(self, telefono):
        return self._appuntamenti_di(
            next((c for c in self.clienti if c.get("telefono") == telefono), None)
        )

    async def get_appuntamenti_per_email(self, email):
        return self._appuntamenti_di(
            next((c for c in self.clienti if email and c.get("email") == email), None)
        )

    def _appuntamenti_di(self, cliente):
        if cliente is None:
            return None

        adesso = datetime.now()
        suoi = [a for a in self.appuntamenti if a.get("client_id") == cliente["id"]]
        return {
            "cliente": {
                "id": cliente["id"],
                "nome": cliente.get("nome"),
                "cognome": cliente.get("cognome"),
                "email": cliente.get("email"),
            },
            "appuntamenti": [
                {
                    "app_id": a["id"],
                    "data_ora": a.get("data_ora"),
                    "durata_min": a.get("durata_min"),
                    "servizi": a.get("servizi"),
                    "parrucchiere": a.get("parrucchiere"),
                    "prezzo": a.get("prezzo"),
                    "stato": a.get("stato"),
                    "gcal_event_id": a.get("gcal_event_id"),
                    "passato": bool(
                        a.get("data_ora")
                        and datetime.strptime(a["data_ora"], "%Y-%m-%dT%H:%M") < adesso
                    ),
                }
                for a in sorted(suoi, key=lambda a: a.get("data_ora") or "", reverse=True)
            ],
        }

    # ------------------------------------------------------------ media/email

    async def download_media(self, media_id):
        return b"fake-image-bytes"

    async def salva_foto(self, contenuto, prefisso="foto"):
        """Non scrive niente su disco: restituisce un URL finto."""
        if not contenuto:
            return None
        self.foto_salvate.append(prefisso)
        return f"/static/foto/{prefisso}_finta.jpg"

    async def send_confirmation_email(self, to, nome, data_ora, parrucchiere, servizi):
        self.email_inviate.append(
            {
                "to": to,
                "nome": nome,
                "data_ora": data_ora,
                "parrucchiere": parrucchiere,
                "servizi": servizi,
            }
        )

    async def send_verification_code(self, to, codice):
        self.codici_inviati.append({"to": to, "codice": codice})

    async def sposta_appuntamento(
        self, app_id, data_ora, parrucchiere=None, gcal_event_id=None, durata_min=None
    ):
        for app in self.appuntamenti:
            if app["id"] != app_id:
                continue
            app["data_ora"] = data_ora
            if parrucchiere:
                app["parrucchiere"] = parrucchiere
            if gcal_event_id:
                app["gcal_event_id"] = gcal_event_id
            if durata_min:
                app["durata_min"] = durata_min

    async def send_absence_email(self, to, nome, data_ora, parrucchiere, servizi):
        self.email_assenze.append(
            {
                "to": to,
                "nome": nome,
                "data_ora": data_ora,
                "parrucchiere": parrucchiere,
                "servizi": servizi,
            }
        )

    async def send_change_email(self, to, nome, da, a, parrucchiere, servizi):
        self.email_spostamenti.append(
            {
                "to": to,
                "nome": nome,
                "da": da,
                "a": a,
                "parrucchiere": parrucchiere,
                "servizi": servizi,
            }
        )

    async def send_cancellation_email(self, to, nome, data_ora, parrucchiere, servizi):
        self.email_cancellazioni.append(
            {
                "to": to,
                "nome": nome,
                "data_ora": data_ora,
                "parrucchiere": parrucchiere,
                "servizi": servizi,
            }
        )


class ScriptedClaude:
    """Claude finto: restituisce risposte prestabilite, una per turno.

    Serve nei test per verificare il flusso senza chiamare (e pagare) l'API.
    Le risposte possono essere testo normale oppure il JSON di un'azione.
    """

    def __init__(self, risposte: list[str]) -> None:
        self.risposte = list(risposte)
        self.chiamate: list[dict] = []

    async def __call__(self, system_prompt: str, history: list[dict]) -> str:
        self.chiamate.append({"system": system_prompt, "history": list(history)})
        if not self.risposte:
            return "Non ho altro da dire."
        return self.risposte.pop(0)

    @staticmethod
    def azione(**kwargs) -> str:
        """Comodità per scrivere l'azione JSON nei test."""
        return json.dumps(kwargs, ensure_ascii=False)
