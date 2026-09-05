#!/usr/bin/env python3
"""Riempie l'agenda di appuntamenti finti, per provare il bot su dati veri.

Un'agenda vuota non mette alla prova niente: il bot propone il primo orario
libero e ha sempre ragione. I difetti si vedono quando le giornate sono piene a
macchie, un operatore è più richiesto degli altri, e certi orari sono tolti solo
per alcuni.

Scrive **sia nel database sia sui calendari Google**, come farebbe una
prenotazione vera: se scrivesse solo da una parte, i due sistemi divergerebbero
e ogni prova successiva mentirebbe.

    python tools/dati_di_prova.py                    # mostra il piano, non scrive
    python tools/dati_di_prova.py --conferma         # crea davvero
    python tools/dati_di_prova.py --pulisci --conferma   # toglie tutto

Va lanciato dove il database e Google sono raggiungibili: sulla Shell di
Render, non dal proprio computer.

## Come si riconoscono i dati finti

Il telefono dei clienti comincia per `39000000`, che non è un numero
assegnabile: nessuna prova potrà mai scrivere a una persona vera. Sulla
descrizione degli eventi Google c'è `[DATI DI PROVA]`. Sono i due appigli con
cui `--pulisci` li ritrova tutti, anche quelli rimasti orfani.

Le email finiscono in `@example.invalid`, dominio che per RFC 6761 non esiste e
non esisterà: una conferma spedita per sbaglio non raggiunge nessuno.

## Cosa rispetta

Gli orari del salone, le chiusure, le presenze dei singoli operatori e le
durate del listino: gli appuntamenti finti stanno dove ne starebbero di veri.
E **un cliente ha al massimo un appuntamento futuro**, come impone il bot:
averne due lo farebbe rispondere in modo che, provando, sembrerebbe un difetto.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PREFISSO_TELEFONO = "39000000"
DOMINIO_EMAIL = "example.invalid"
MARCATORE = "[DATI DI PROVA]"

NOMI = [
    "Marco", "Luca", "Giuseppe", "Andrea", "Francesco", "Alessandro", "Matteo",
    "Davide", "Simone", "Federico", "Lorenzo", "Stefano", "Roberto", "Paolo",
    "Antonio", "Giovanni", "Riccardo", "Gabriele", "Emanuele", "Nicola",
    "Giulia", "Chiara", "Sara", "Martina", "Elena", "Valentina", "Alessia",
    "Francesca", "Silvia", "Laura", "Anna", "Claudia", "Ilaria", "Beatrice",
]
COGNOMI = [
    "Rossi", "Russo", "Ferrari", "Esposito", "Bianchi", "Romano", "Colombo",
    "Ricci", "Marino", "Greco", "Bruno", "Gallo", "Conti", "De Luca", "Costa",
    "Giordano", "Mancini", "Rizzo", "Lombardi", "Moretti", "Barbieri", "Fontana",
    "Santoro", "Mariani", "Rinaldi", "Caruso", "Ferrara", "Galli", "Martini",
]

# Quello che i clienti chiedono davvero, con la frequenza con cui lo chiedono:
# un'agenda fatta solo di colori da due ore non somiglia a un barbiere.
PESI_SERVIZI = {
    "Taglio": 34,
    "Taglio + Barba": 22,
    "Taglio + Shampoo": 14,
    "Barba": 12,
    "Taglio + Shampoo + Barba": 10,
    "Taglio + Shampoo + Trattamento barba con oli e panno bagnato": 5,
    "Colore + Taglio + Trattamento capello": 3,
}

RICHIESTE = [
    None, None, None, None,
    "Corto ai lati", "Sfumatura alta", "Non troppo corto sopra",
    "Come l'ultima volta", "Barba squadrata", "Riga a sinistra",
]


def _argomenti():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--da", help="prima data, es. 2026-09-01")
    p.add_argument("--a", help="ultima data, es. 2026-10-31")
    p.add_argument(
        "--densita",
        type=float,
        default=0.45,
        help="quanta parte dell'agenda riempire, da 0 a 1 (predefinito 0.45)",
    )
    p.add_argument("--pulisci", action="store_true", help="toglie i dati finti")
    p.add_argument(
        "--conferma",
        action="store_true",
        help="senza questo mostra solo il piano e non scrive niente",
    )
    p.add_argument(
        "--senza-google",
        action="store_true",
        help="scrive solo nel database (più veloce, ma i due sistemi divergono)",
    )
    p.add_argument("--seme", type=int, default=20260905, help="per ripetere la stessa agenda")
    p.add_argument(
        "--parallele",
        type=int,
        default=6,
        help="quante scritture insieme (predefinito 6): alzarlo va più veloce "
             "ma avvicina il limite per minuto di Google",
    )
    return p.parse_args()


async def _prepara_cache() -> None:
    """Carica quello che l'applicazione carica all'avvio.

    Senza, gli appuntamenti finiscono negli orari scritti nel codice invece che
    in quelli veri, e metà cadono a salone chiuso.
    """
    from prompts.system_prompt import set_parrucchieri_cache
    from services import catalogo
    from services.db_service import (
        get_chiusure,
        get_orari_salone,
        get_parrucchieri_map,
        get_presenze,
        get_servizi_attivi,
    )
    from services.presenze import set_presenze_cache
    from services.slots import set_chiusure, set_orari_salone

    set_parrucchieri_cache(await get_parrucchieri_map())
    catalogo.set_catalogo_cache(await get_servizi_attivi())
    set_orari_salone(await get_orari_salone())
    set_chiusure({c["data"].isoformat() for c in await get_chiusure()})
    set_presenze_cache(await get_presenze())


def _giorni_aperti(da: date, a: date) -> list[str]:
    from services.slots import is_open

    giorni, giorno = [], da
    while giorno <= a:
        if is_open(giorno.isoformat()):
            giorni.append(giorno.isoformat())
        giorno += timedelta(days=1)
    return giorni


def _servizio_a_caso(rnd: random.Random) -> tuple[list[str], int, float]:
    from services import catalogo

    disponibili = {
        nome: peso
        for nome, peso in PESI_SERVIZI.items()
        if catalogo.durata_totale([nome])
    }
    if not disponibili:  # listino diverso da quello previsto: si prende quello che c'è
        nomi = [s["nome"] for s in catalogo.elenco_per_sito()]
        scelto = rnd.choice(nomi)
    else:
        scelto = rnd.choices(list(disponibili), weights=list(disponibili.values()))[0]
    return [scelto], catalogo.durata_totale([scelto]), catalogo.prezzo_totale([scelto])


def _libero_per_tutta_la_durata(
    slot: str, durata: int, liberi: set[str], occupati: set[str]
) -> list[str]:
    """Gli slot che l'appuntamento occuperebbe, o [] se non ci sta.

    Un colore da due ore prenotato come mezz'ora finisce sopra l'appuntamento
    successivo: è lo stesso motivo per cui la durata la decide il listino e non
    chi prenota.
    """
    inizio = datetime.strptime(slot, "%Y-%m-%dT%H:%M")
    quanti = max(1, durata // 30)
    serve = [
        (inizio + timedelta(minutes=30 * i)).strftime("%Y-%m-%dT%H:%M")
        for i in range(quanti)
    ]
    if any(s in occupati or s not in liberi for s in serve):
        return []
    return serve


def _piano(giorni: list[str], operatori: list[str], densita: float, rnd: random.Random):
    """Decide chi sta con chi e quando, senza scrivere niente.

    Le giornate non sono tutte uguali e gli operatori non sono ugualmente
    richiesti: un'agenda uniforme non somiglia a nessun salone, e sarebbe
    proprio il caso in cui il bot non sbaglia mai.
    """
    from services.presenze import e_in_salone
    from services.slots import generate_slots

    # Quanto è richiesto ciascuno. Chi ha 1.2 riempie di più, chi ha 0.7 meno.
    popolarita = {nome: rnd.uniform(0.65, 1.3) for nome in operatori}

    appuntamenti = []
    for giorno in giorni:
        # Sabato pieno, martedì fiacco: la stessa differenza che c'è davvero.
        affluenza = rnd.uniform(0.6, 1.35)
        if datetime.strptime(giorno, "%Y-%m-%d").weekday() == 5:
            affluenza *= 1.3

        for operatore in operatori:
            tutti = [s for s in generate_slots(giorno) if e_in_salone(operatore, s)]
            if not tutti:
                continue

            liberi = set(tutti)
            occupati: set[str] = set()
            quota = min(0.95, densita * affluenza * popolarita[operatore])

            for slot in tutti:
                if slot in occupati or rnd.random() > quota:
                    continue
                servizi, durata, prezzo = _servizio_a_caso(rnd)
                presi = _libero_per_tutta_la_durata(slot, durata, liberi, occupati)
                if not presi:
                    continue
                occupati.update(presi)
                appuntamenti.append(
                    {
                        "slot": slot,
                        "operatore": operatore,
                        "servizi": servizi,
                        "durata": durata,
                        "prezzo": prezzo,
                        "richiesta": rnd.choice(RICHIESTE),
                    }
                )
    return appuntamenti


def _clienti_per(appuntamenti: list[dict], rnd: random.Random, oggi: date) -> list[dict]:
    """Un cliente per ogni appuntamento futuro, riusati per quelli passati.

    Il bot impedisce a una persona di avere due appuntamenti futuri: darne due
    a un cliente finto vorrebbe dire, provando, vedere un rifiuto e crederlo un
    difetto. Nel passato invece si accumulano, ed è quello che rende
    riconoscibile un cliente abituale.
    """
    futuri = [a for a in appuntamenti if a["slot"][:10] >= oggi.isoformat()]
    passati = [a for a in appuntamenti if a["slot"][:10] < oggi.isoformat()]

    clienti = []
    for indice, appuntamento in enumerate(futuri, start=1):
        nome = rnd.choice(NOMI)
        cognome = rnd.choice(COGNOMI)
        cliente = {
            "nome": nome,
            "cognome": cognome,
            "telefono": f"{PREFISSO_TELEFONO}{indice:04d}",
            "email": f"{nome}.{cognome}".lower().replace(" ", "")
            + f".{indice:04d}@{DOMINIO_EMAIL}",
            "appuntamenti": [appuntamento],
        }
        clienti.append(cliente)

    # Gli appuntamenti già passati diventano storia di clienti che esistono già.
    for appuntamento in passati:
        if not clienti:
            break
        rnd.choice(clienti)["appuntamenti"].append(appuntamento)

    return clienti


async def crea(args) -> None:
    from services import catalogo
    from services.calendar_service import create_event
    from services.db_service import create_appointment, find_or_create_client
    from services.operatori import mappa_calendari

    rnd = random.Random(args.seme)
    oggi = date.today()
    da = datetime.strptime(args.da, "%Y-%m-%d").date() if args.da else date(oggi.year, 9, 1)
    a = datetime.strptime(args.a, "%Y-%m-%d").date() if args.a else date(oggi.year, 10, 31)

    await _prepara_cache()
    giorni = _giorni_aperti(da, a)
    operatori = list(mappa_calendari())
    calendari = mappa_calendari()

    if not giorni:
        print("Nessun giorno di apertura nell'intervallo: controlla gli orari del salone.")
        return

    appuntamenti = _piano(giorni, operatori, args.densita, rnd)
    clienti = _clienti_per(appuntamenti, rnd, oggi)

    futuri = sum(1 for a_ in appuntamenti if a_["slot"][:10] >= oggi.isoformat())
    print(f"Dal {da} al {a}: {len(giorni)} giorni di apertura, {len(operatori)} operatori.")
    print(f"Appuntamenti da creare: {len(appuntamenti)} ({futuri} futuri, "
          f"{len(appuntamenti) - futuri} già passati).")
    print(f"Clienti da creare: {len(clienti)}, telefoni {PREFISSO_TELEFONO}xxxx.")
    per_operatore = {}
    for a_ in appuntamenti:
        per_operatore[a_["operatore"]] = per_operatore.get(a_["operatore"], 0) + 1
    print("Per operatore: " + ", ".join(f"{n} {q}" for n, q in sorted(per_operatore.items())))
    print(f"Su Google Calendar: {'no' if args.senza_google else 'sì'}.")

    if not args.conferma:
        print("\nNiente è stato scritto. Rilancia con --conferma per farlo davvero.")
        return

    # In fila indiana duemila eventi sono mezz'ora buona, e mezz'ora è tempo in
    # cui qualcosa si interrompe. In parallelo si va in pochi minuti, ma il
    # limite di Google è per minuto: la corsia stretta serve a starci dentro.
    corsia = asyncio.Semaphore(args.parallele)
    conteggio = {"creati": 0, "falliti": 0}

    async def scrivi(cliente: dict) -> None:
        async with corsia:
            anagrafica = await find_or_create_client(
                phone=cliente["telefono"],
                nome=cliente["nome"],
                cognome=cliente["cognome"],
                email=cliente["email"],
                canale="whatsapp",
            )
            for appuntamento in cliente["appuntamenti"]:
                gcal_id = None
                if not args.senza_google:
                    gcal_id = await _evento_con_pazienza(
                        create_event,
                        slot=appuntamento["slot"],
                        parrucchiere_cal_id=calendari[appuntamento["operatore"]],
                        servizi=appuntamento["servizi"],
                        durata=appuntamento["durata"],
                        cliente_nome=f"{cliente['nome']} {cliente['cognome']}",
                        descrizione=(
                            f"{MARCATORE} {appuntamento['richiesta'] or ''}".strip()
                        ),
                    )
                    if gcal_id is None:
                        # Un evento che non parte non deve fermare i mille dopo,
                        # ma nemmeno lasciare in database un appuntamento che sul
                        # calendario non esiste: quello sarebbe uno slot occupato
                        # per il bot e libero per il salone.
                        conteggio["falliti"] += 1
                        continue

                await create_appointment(
                    client_id=anagrafica["id"],
                    data_ora=appuntamento["slot"],
                    servizi=appuntamento["servizi"],
                    parrucchiere=appuntamento["operatore"],
                    richieste_spec=appuntamento["richiesta"],
                    gcal_event_id=gcal_id,
                    durata_min=appuntamento["durata"],
                    prezzo=appuntamento["prezzo"],
                )
                conteggio["creati"] += 1
                if conteggio["creati"] % 200 == 0:
                    print(f"  … {conteggio['creati']} appuntamenti creati")

    await asyncio.gather(*(scrivi(c) for c in clienti))

    print(f"\nFatto: {conteggio['creati']} appuntamenti, {len(clienti)} clienti."
          + (f" {conteggio['falliti']} non creati su Google." if conteggio["falliti"] else ""))


async def _evento_con_pazienza(create_event, tentativi: int = 4, **argomenti):
    """Crea l'evento riprovando quando Google dice di rallentare.

    Con duemila richieste ravvicinate qualche `rateLimitExceeded` è normale e
    non è un errore: è Google che chiede di aspettare. Arrendersi al primo
    lascerebbe buchi sparsi nell'agenda proprio dove il traffico era più fitto.
    """
    attesa = 1.0
    for tentativo in range(tentativi):
        try:
            return await create_event(**argomenti)
        except Exception as errore:  # noqa: BLE001
            testo = str(errore)
            transitorio = any(
                s in testo
                for s in ("rateLimit", "userRateLimit", "quotaExceeded", "backendError", "503", "429")
            )
            if not transitorio or tentativo == tentativi - 1:
                print(f"  ! Google ha rifiutato {argomenti.get('slot')}: {testo}"[:160])
                return None
            await asyncio.sleep(attesa)
            attesa *= 2
    return None


async def pulisci(args) -> None:
    """Toglie tutto quello che questo strumento ha creato, e solo quello."""
    from sqlalchemy import delete, select

    from models.database import async_session
    from models.orm import Appuntamento, Cliente
    from services.calendar_service import delete_event
    from services.operatori import mappa_calendari

    async with async_session() as db:
        finti = await db.execute(
            select(Cliente.id).where(Cliente.telefono_wa.like(f"{PREFISSO_TELEFONO}%"))
        )
        ids = [r for r in finti.scalars().all()]

        eventi = []
        if ids:
            righe = await db.execute(
                select(Appuntamento.gcal_event_id, Appuntamento.parrucchiere_id)
                .where(Appuntamento.cliente_id.in_(ids))
            )
            eventi = [(e, p) for e, p in righe.all() if e]

    print(f"Clienti finti trovati: {len(ids)}. Eventi Google da togliere: {len(eventi)}.")
    if not args.conferma:
        print("\nNiente è stato tolto. Rilancia con --pulisci --conferma.")
        return

    calendari = mappa_calendari()
    per_id = {}
    async with async_session() as db:
        from models.orm import Parrucchiere

        for parr in (await db.execute(select(Parrucchiere))).scalars().all():
            per_id[parr.id] = parr.gcal_calendar_id or calendari.get(parr.nome)

    tolti = 0
    for evento, parrucchiere_id in eventi:
        try:
            await delete_event(evento, per_id.get(parrucchiere_id))
            tolti += 1
        except Exception as errore:  # noqa: BLE001
            print(f"  ! evento {evento} non tolto: {errore}"[:160])

    async with async_session() as db:
        # `delete()` sulla tabella e non `cliente.appuntamenti`: quella è una
        # relazione pigra e in sessione asincrona solleva MissingGreenlet.
        await db.execute(delete(Appuntamento).where(Appuntamento.cliente_id.in_(ids)))
        await db.execute(delete(Cliente).where(Cliente.id.in_(ids)))
        await db.commit()

    orfani = await _spazza_via_gli_orfani(per_id.values())

    print(f"Fatto: {tolti} eventi tolti da Google, {len(ids)} clienti e i loro "
          "appuntamenti rimossi dal database."
          + (f" Più {orfani} eventi orfani ripuliti dai calendari." if orfani else ""))


async def _spazza_via_gli_orfani(calendari) -> int:
    """Toglie dai calendari gli eventi marcati che il database non conosce più.

    Servono quando qualcosa si è rotto a metà: l'evento è nato su Google e la
    riga in database no. Senza questa passata resterebbero lì a occupare slot
    che il bot vede pieni e il salone vede liberi — cioè il difetto peggiore
    che questi dati finti possano lasciarsi dietro.
    """
    from services.calendar_service import _get_service, delete_event

    servizio = _get_service()
    tolti = 0
    for calendario in {c for c in calendari if c}:
        try:
            pagina = None
            while True:
                risposta = (
                    servizio.events()
                    .list(
                        calendarId=calendario,
                        q=MARCATORE,
                        singleEvents=True,
                        maxResults=250,
                        pageToken=pagina,
                    )
                    .execute()
                )
                for evento in risposta.get("items", []):
                    if MARCATORE in (evento.get("description") or ""):
                        await delete_event(evento["id"], calendario)
                        tolti += 1
                pagina = risposta.get("nextPageToken")
                if not pagina:
                    break
        except Exception as errore:  # noqa: BLE001
            print(f"  ! calendario non ripulito del tutto: {errore}"[:160])
    return tolti


async def main() -> None:
    args = _argomenti()
    if args.pulisci:
        await pulisci(args)
    else:
        await crea(args)


if __name__ == "__main__":
    asyncio.run(main())
