#!/usr/bin/env python3
"""Stampa un link che apre la chat del sito già riconoscendo un numero.

Serve per provare, e alla receptionist che vuole mandarlo a mano a un cliente
al telefono. Il bot lo manda da sé con l'azione CONTINUA_SUL_SITO.

    python tools/link_chat.py 393491021925

Va lanciato dove Redis è raggiungibile — sulla Shell di Render, non dal
proprio computer: il gettone vive lì, e uno creato altrove non lo troverebbe
nessuno.

Il link vale **un quarto d'ora e una volta sola**. Chi lo apre entra come
titolare di quel numero: mandalo solo a quel numero, come fa il bot.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2

    cifre = "".join(c for c in sys.argv[1] if c.isdigit())
    if len(cifre) < 8:
        print(f"'{sys.argv[1]}' non sembra un numero di telefono.")
        return 2

    import redis.asyncio as aioredis

    from config import settings
    from services.link_chat import DURATA_SECONDI, crea_gettone, indirizzo

    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        gettone = await crea_gettone(redis, cifre)
    finally:
        await redis.close()

    if not gettone:
        print("Gettone non creato: Redis non risponde.")
        return 1

    link = indirizzo(gettone)
    if not link:
        print(
            "Gettone creato ma manca PUBLIC_BASE_URL, quindi non so comporre "
            "l'indirizzo. Il link sarebbe: <indirizzo del sito>/chat/" + gettone
        )
        return 1

    print(f"\nPer il numero {cifre}, valido {DURATA_SECONDI // 60} minuti e una volta sola:\n")
    print(link)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
