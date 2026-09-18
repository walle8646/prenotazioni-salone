#!/usr/bin/env python3
"""Genera la coppia di chiavi per le notifiche push. Una volta sola.

    python tools/chiavi_push.py

Stampa due valori da mettere fra le variabili d'ambiente su Render:
`VAPID_PUBLIC_KEY` e `VAPID_PRIVATE_KEY`. La privata firma le notifiche e non
va scritta da nessun'altra parte; la pubblica la conosce il browser.

Cambiare le chiavi invalida tutte le iscrizioni esistenti: i telefoni già
iscritti smettono di ricevere e devono riattivare le notifiche dal pannello.
"""

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def _senza_riempimento(dati: bytes) -> str:
    """Base64 per URL e senza '=': è la forma che vogliono i servizi push."""
    return base64.urlsafe_b64encode(dati).decode("ascii").rstrip("=")


def main() -> None:
    chiave = ec.generate_private_key(ec.SECP256R1())

    privata = _senza_riempimento(
        chiave.private_numbers().private_value.to_bytes(32, "big")
    )
    pubblica = _senza_riempimento(
        chiave.public_key().public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.UncompressedPoint,
        )
    )

    print("\nDa mettere su Render, in Environment:\n")
    print(f"VAPID_PUBLIC_KEY={pubblica}")
    print(f"VAPID_PRIVATE_KEY={privata}")
    print("VAPID_SUBJECT=mailto:<la casella del salone>")
    print("\nLa privata non va scritta altrove. Cambiarle disiscrive tutti.\n")


if __name__ == "__main__":
    main()
