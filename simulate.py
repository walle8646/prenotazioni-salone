#!/usr/bin/env python3
"""Simulatore da terminale: parla con il bot senza WhatsApp.

Usa esattamente lo stesso motore conversazionale della produzione, ma consegna
le risposte a schermo invece che a Meta. Serve per provare il flusso di
prenotazione, affinare il system prompt e mostrare il bot al cliente prima di
avere un numero WhatsApp funzionante.

Modalità:

  python simulate.py --offline
      Non tocca niente di esterno tranne Claude: Redis, Google Calendar,
      PostgreSQL ed email sono finti e vivono in memoria. Serve solo
      ANTHROPIC_API_KEY nel file .env.

  python simulate.py --offline --fake-claude
      Non chiama nemmeno Claude: usa risposte prestabilite. Utile per
      verificare che l'impianto giri senza consumare token.

  python simulate.py
      Usa i servizi veri (Redis, Google Calendar, PostgreSQL): stessa
      esperienza della produzione ma senza WhatsApp.

Comandi disponibili durante la chat:
  /reset    ricomincia la conversazione da zero
  /stato    mostra lo stato della sessione e cosa è stato prenotato
  /esci     chiude il simulatore
"""

from __future__ import annotations

import argparse
import asyncio
import sys


def _stampa_intestazione(offline: bool, fake_claude: bool) -> None:
    modalita = "offline (servizi finti)" if offline else "servizi reali"
    if fake_claude:
        modalita += " + Claude finto"
    print("\n" + "=" * 60)
    print("  Simulatore Salone Nadia — modalità:", modalita)
    print("  Comandi: /reset  /stato  /esci")
    print("=" * 60)


async def main() -> int:
    parser = argparse.ArgumentParser(description="Simulatore di chat del bot Salone Nadia")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="usa Redis, calendario, database ed email finti (in memoria)",
    )
    parser.add_argument(
        "--fake-claude",
        action="store_true",
        help="non chiama l'API di Claude: usa risposte prestabilite",
    )
    parser.add_argument(
        "--phone",
        default="393331234567",
        help="numero da simulare come mittente (default: 393331234567)",
    )
    args = parser.parse_args()

    from services.channels import ConsoleChannel
    from services.conversation import handle_incoming_message
    from services.session_manager import delete_session, get_session

    channel = ConsoleChannel()
    backends = None
    claude = None

    if args.offline:
        from prompts.system_prompt import PARRUCCHIERI_MAP, set_parrucchieri_cache
        from services.fakes import FakeBackends, FakeRedis

        set_parrucchieri_cache(PARRUCCHIERI_MAP)
        redis = FakeRedis()
        backends = FakeBackends()
    else:
        import redis.asyncio as aioredis

        from config import settings
        from prompts.system_prompt import set_parrucchieri_cache
        from services.db_service import get_parrucchieri_map

        redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            set_parrucchieri_cache(await get_parrucchieri_map())
        except Exception as e:  # noqa: BLE001
            print(f"[attenzione] parrucchieri non caricati dal database: {e}")

    if args.fake_claude:
        from services.fakes import ScriptedClaude

        claude = ScriptedClaude(
            [
                "Ciao! Che servizio desideri?\n- Taglio (13,50 €)\n- Barba (8,00 €)",
                ScriptedClaude.azione(
                    action="CHECK_DISPONIBILITA",
                    data="2026-08-11",
                    parrucchiere=None,
                    durata_min=30,
                ),
                "Ho questi orari liberi martedì:\n- 09:00 con Francesco\n- 10:30 con Andrea",
            ]
        )

    _stampa_intestazione(args.offline, args.fake_claude)

    while True:
        try:
            testo = input("\033[96mTu\033[0m: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nCiao!")
            break

        if not testo:
            continue
        if testo in ("/esci", "/quit", "/exit"):
            print("Ciao!")
            break
        if testo == "/reset":
            await delete_session(redis, args.phone)
            print("[sessione azzerata]")
            continue
        if testo == "/stato":
            sessione = await get_session(redis, args.phone)
            print(f"\n  stato flusso : {sessione['stato_flusso']}")
            print(f"  dati raccolti: {sessione['dati_temp']}")
            print(f"  messaggi     : {len(sessione['history'])}")
            if backends is not None:
                print(f"  appuntamenti : {backends.appuntamenti}")
                print(f"  email inviate: {backends.email_inviate}")
            print()
            continue

        try:
            await handle_incoming_message(
                redis=redis,
                phone=args.phone,
                text=testo,
                msg_type="text",
                channel=channel,
                backends=backends,
                claude=claude,
            )
        except Exception as e:  # noqa: BLE001
            print(f"\n\033[91m[errore]\033[0m {type(e).__name__}: {e}\n")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
