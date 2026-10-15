"""I numeri a cui risponde solo una persona, e come si scrive un numero.

Serve quando su un contatto il bot non deve proprio entrare: un cliente con
una situazione delicata, un fornitore, qualcuno che ha chiesto di parlare solo
con il salone. Non e' l'interruttore generale — quello spegne tutto — ma lo
stesso trattamento su un numero solo, e **senza scadenza**: a differenza di un
passaggio a una persona, che dopo 24 ore senza risposta torna al bot, qui il
bot resta fuori finche' il numero non viene tolto dall'elenco.

La parte delicata e' il formato. Il numero deve essere scritto **come lo manda
WhatsApp**: solo cifre, con il prefisso internazionale e senza il piu'. Un
numero scritto in un altro modo finirebbe in tabella sotto una chiave che
nessun messaggio usera' mai, l'elenco sembrerebbe a posto e il bot
continuerebbe a rispondere — lo stesso guasto silenzioso gia' visto con le
eco. Per questo la normalizzazione sta qui, in una funzione pura con i suoi
test, e non nel modulo che disegna la pagina.
"""

from __future__ import annotations

import re

# Tutto quello che la gente infila dentro un numero scrivendolo a mano.
_DA_BUTTARE = re.compile(r"[\s./\-()]")

# Lunghezza di un numero con prefisso internazionale. Sotto le otto cifre e'
# un numero breve o un errore di battitura; sopra le quindici non esiste
# (E.164 si ferma li').
MINIMO = 8
MASSIMO = 15

PREFISSO_ITALIA = "39"


def normalizza(valore: str | None) -> str | None:
    """Il numero nella forma in cui arriva da WhatsApp, o None se non lo e'.

    Accetta come lo scrive una persona — `+39 349 102 19 25`, `0039 349...`,
    `349-102-1925` — e restituisce `393491021925`.

    **Il prefisso lo aggiunge qui**, e non e' un vezzo: chi lavora in salone
    scrive il numero come ce l'ha in rubrica, cioe' senza 39 davanti. Senza
    questo passaggio l'elenco si riempirebbe di numeri che non corrispondono a
    nessun mittente, e il bot continuerebbe a rispondere a chi era stato messo
    nell'elenco apposta.
    """
    if not valore:
        return None

    cifre = _DA_BUTTARE.sub("", valore.strip())
    if cifre.startswith("+"):
        cifre = cifre[1:]
    elif cifre.startswith("00"):
        # 0039... e' lo stesso di +39...
        cifre = cifre[2:]

    if not cifre.isdigit():
        return None

    # Italiano scritto senza prefisso: un cellulare comincia per 3 ed e' lungo
    # nove o dieci cifre, un fisso comincia per 0. In tutti e due i casi il 39
    # va davanti, e nel fisso lo zero resta.
    if (cifre.startswith("3") and len(cifre) in (9, 10)) or (
        cifre.startswith("0") and len(cifre) in range(9, 12)
    ):
        cifre = PREFISSO_ITALIA + cifre

    if not (MINIMO <= len(cifre) <= MASSIMO):
        return None
    return cifre


def come_si_scrive() -> str:
    """La spiegazione da mostrare accanto al campo."""
    return (
        "Scrivilo come preferisci: 349 102 1925, +39 349 102 1925 o "
        "393491021925. Viene salvato nella forma che usa WhatsApp, con il "
        "prefisso internazionale e senza il piu'."
    )


# ----------------------------------------------------------------- la copia

# Come listino, operatori e orari: il controllo si fa a ogni messaggio in
# arrivo, e una query per messaggio si paga per sempre. Chi scrive ricarica la
# copia nello stesso giro, quindi un numero aggiunto vale dal messaggio dopo.
# La copia e' per processo; oggi il processo e' uno solo.
_elenco: frozenset[str] = frozenset()


def set_cache(numeri) -> None:
    global _elenco
    _elenco = frozenset(n for n in (numeri or ()) if n)


def risponde_solo_una_persona(telefono: str | None) -> bool:
    """Se su questo numero il bot deve stare zitto."""
    if not telefono:
        return False
    return telefono.strip().lstrip("+") in _elenco


def quanti() -> int:
    return len(_elenco)
