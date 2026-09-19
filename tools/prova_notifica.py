#!/usr/bin/env python3
"""Dice perché una notifica non è arrivata, e prova a mandarne una.

    python tools/prova_notifica.py

Va lanciato sulla Shell di Render: le chiavi e le iscrizioni stanno lì.

Controlla i tre anelli nell'ordine in cui si rompono, perché il sintomo è
sempre lo stesso — il telefono che non squilla — ma la cosa da fare è diversa:

1. le chiavi VAPID sono configurate? Senza, l'applicazione non offre nemmeno
   il bottone e non prova a mandare niente;
2. c'è almeno un telefono iscritto? Un permesso negato sul telefono non lascia
   traccia qui: si vede solo come "nessun dispositivo";
3. il servizio push accetta la notifica? Se rifiuta, dice il perché.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def main() -> int:
    from config import settings
    from services import push
    from services.db_service import iscrizioni_push

    print()
    if not push.configurato():
        mancano = [
            nome
            for nome, valore in (
                ("VAPID_PUBLIC_KEY", settings.vapid_public_key),
                ("VAPID_PRIVATE_KEY", settings.vapid_private_key),
            )
            if not valore
        ]
        print("1. CHIAVI: mancano " + ", ".join(mancano))
        print("\n   Genera le chiavi con `python tools/chiavi_push.py` e mettile")
        print("   fra le variabili d'ambiente. Finché mancano, l'applicazione non")
        print("   offre nemmeno il bottone per attivare le notifiche.\n")
        return 1
    print("1. CHIAVI: configurate")
    if not settings.vapid_subject:
        print("   (VAPID_SUBJECT è vuota: non blocca niente, ma alcuni servizi")
        print("    push la vogliono per sapere chi contattare se qualcosa va storto)")

    iscritti = await iscrizioni_push()
    print(f"\n2. DISPOSITIVI ISCRITTI: {len(iscritti)}")
    if not iscritti:
        print("\n   Nessun telefono si è iscritto. Le cause possibili, in ordine:")
        print("   - nessuno ha ancora premuto «Avvisami sul telefono» in Conversazioni;")
        print("   - il permesso è stato negato: allora il bottone sparisce e resta")
        print("     scritto che si riattiva dalle impostazioni del telefono, non")
        print("     dall'applicazione — è il sistema operativo a decidere;")
        print("   - su iPhone l'applicazione non è stata aggiunta alla schermata Home:")
        print("     dal browser Safari il permesso non si può proprio chiedere.\n")
        return 1

    for iscrizione in iscritti:
        # L'indirizzo dice quale servizio push è, e basta a distinguere i
        # dispositivi senza stampare le chiavi.
        endpoint = iscrizione["endpoint"]
        print(f"   - {endpoint[:60]}…")

    print("\n3. INVIO DI PROVA…")
    consegnate = await push.avvisa(
        titolo="Prova dal salone",
        testo="Se leggi questo, le notifiche funzionano.",
        url="/admin/conversazioni",
    )
    print(f"   consegnate a {consegnate} dispositivi su {len(iscritti)}")
    if consegnate < len(iscritti):
        print("\n   Le iscrizioni rifiutate come scadute sono state tolte: succede")
        print("   quando l'applicazione è stata disinstallata o il permesso revocato.")
        print("   Riattiva le notifiche dal pannello su quel telefono.")
    print()
    return 0 if consegnate else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
