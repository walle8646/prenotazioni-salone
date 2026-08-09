"""Una versione per i file statici, da appendere ai loro indirizzi.

Il browser tiene in cache `style.css` e `chat.js` e non li richiede più. Dopo
un deploy la pagina nuova arriva col foglio di stile vecchio: era successo col
bottone del widget, che c'era nell'HTML ma non funzionava, ed è ricapitato con
la striscia dei giorni, che arrivava senza stile e sembrava rotta.

Con `?v=` diverso a ogni deploy l'indirizzo cambia, quindi il browser
riscarica. Il numero si ricava dai file stessi: nessuno deve ricordarsi di
alzarlo a mano, che è l'unico modo perché funzioni davvero.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

CARTELLA = Path(__file__).resolve().parent.parent / "static"


def versione() -> str:
    """Otto caratteri che cambiano quando cambia un file statico.

    Si calcola una volta all'avvio: leggere la cartella a ogni pagina
    costerebbe un accesso al disco per ogni richiesta, per un valore che
    durante l'esecuzione non cambia mai.
    """
    impronta = hashlib.sha256()
    try:
        for file in sorted(CARTELLA.rglob("*")):
            if file.is_file():
                stato = file.stat()
                impronta.update(file.name.encode())
                impronta.update(str(stato.st_mtime_ns).encode())
                impronta.update(str(stato.st_size).encode())
    except OSError:
        # Senza la cartella si serve comunque la pagina: il peggio che può
        # capitare è un foglio di stile vecchio, non un errore.
        return "0"
    return impronta.hexdigest()[:8]


VERSIONE = versione()
