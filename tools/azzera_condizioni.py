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
    if quanti:
        print(f"Dimenticata l'accettazione per {chi}: {quanti} schede.")
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
