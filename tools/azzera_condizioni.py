#!/usr/bin/env python3
"""Dimentica chi ha accettato le condizioni, e dice a quanti e' successo.

    python tools/azzera_condizioni.py            # a tutti
    python tools/azzera_condizioni.py 393491021925   # a un numero solo

Va lanciato sulla Shell di Render: il database e' li'.

Serve in due casi, e tutti e due sono successi davvero.

**Un'accettazione registrata per sbaglio.** Il 15 ottobre 2026 le prime
prenotazioni hanno annotato "accettato" senza che l'avviso fosse mai uscito:
un dato falso, che per giunta zittiva l'avviso per sempre su quei clienti e
nascondeva il difetto. Toglierlo non e' una comodita' per fare le prove, e'
rimettere a posto il dato.

**Provare l'avviso sul proprio numero.** Dopo la prima prenotazione non
ricompare piu', ed e' voluto: per rivederlo bisogna dimenticare.

Quello che **non** serve e' far ricomparire l'avviso quando le condizioni
cambiano: per quello basta aggiornare `VERSIONE` in `services/condizioni.py`,
che e' la stessa data mostrata in cima alla pagina. Chi ha accettato la
versione vecchia se la rivede da se'.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def _dimentica_le_sessioni(numero: str | None) -> int:
    """Butta via le conversazioni in corso, che tengono il valore in memoria.

    Senza Redis non si ferma: la parte che conta e' la tabella, e una sessione
    scade da se' in un paio d'ore.
    """
    from config import settings
    from services.session_manager import SESS_PREFIX

    try:
        import redis.asyncio as aioredis

        redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        chiavi = (
            [f"{SESS_PREFIX}{numero}"]
            if numero
            else [c async for c in redis.scan_iter(f"{SESS_PREFIX}*")]
        )
        quante = await redis.delete(*chiavi) if chiavi else 0
        await redis.aclose()
        return quante
    except Exception as errore:  # noqa: BLE001
        print(f"Sessioni non azzerate ({errore}): scadono da se' entro due ore.")
        return 0


async def main() -> int:
    from sqlalchemy import update

    from models.database import async_session
    from models.orm import Cliente

    numero = sys.argv[1].strip().lstrip("+") if len(sys.argv) > 1 else None

    query = update(Cliente).values(
        condizioni_accettate=None, condizioni_accettate_il=None
    )
    if numero:
        query = query.where(Cliente.telefono_wa == numero)

    async with async_session() as db:
        risultato = await db.execute(query)
        await db.commit()

    quanti = risultato.rowcount or 0
    chi = f"il numero {numero}" if numero else "tutti i clienti"

    # E anche le conversazioni in corso, o non serve a niente. Ogni
    # conversazione si porta in memoria il valore letto quando e' cominciata:
    # ripulire la tabella e lasciare la sessione viva vuol dire vedere il bot
    # continuare a comportarsi come prima, e non capire perche'. Costato
    # un pomeriggio.
    sessioni = await _dimentica_le_sessioni(numero)

    if quanti:
        print(f"Dimenticata l'accettazione per {chi}: {quanti} schede.")
        print(f"Conversazioni in corso azzerate: {sessioni}.")
        print("Alla prossima prenotazione l'avviso ricompare.")
    else:
        print(f"Nessuna scheda da ripulire per {chi}.")
        if numero:
            print(
                "Attenzione al formato: il numero va scritto come lo manda "
                "WhatsApp, in cifre e col prefisso — per esempio 393491021925."
            )
    return 0


if __name__ == "__main__":
    if not os.getenv("DATABASE_URL"):
        print("DATABASE_URL non configurata: lancialo dalla Shell di Render.")
        sys.exit(1)
    sys.exit(asyncio.run(main()))
