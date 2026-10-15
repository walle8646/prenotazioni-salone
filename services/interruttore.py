"""L'interruttore che zittisce il bot, e dove vive mentre il server gira.

Esiste perche' il numero e' quello vero del salone: se il bot dicesse qualcosa
di sbagliato ai clienti, l'unica leva sarebbe cambiare le variabili d'ambiente
su Render e aspettare il riavvio. Un interruttore d'emergenza che richiede un
deploy non e' un interruttore d'emergenza.

Il valore sta in database — deve sopravvivere a un riavvio, o si riaccende da
solo proprio quando qualcuno l'aveva spento apposta — ma si legge da una copia
in memoria, come il listino e gli operatori: la decisione va presa prima di
ogni messaggio, e una query in piu' per messaggio si paga per sempre.

La copia e' per processo, quindi con piu' worker uvicorn andrebbe ripensata;
oggi il processo e' uno solo. Per lo stesso motivo chi scrive il valore
ricarica subito la cache, come fanno `_ricarica_listino()` e
`_ricarica_operatori()` nel pannello.
"""

from __future__ import annotations

CHIAVE = "bot_attivo"

# Acceso finche' qualcuno non dice il contrario. Il valore predefinito non e'
# neutro: un errore di lettura o una tabella vuota devono lasciare il bot che
# funziona, non un salone che tace senza che nessuno sappia perche'.
_attivo = True


def bot_attivo() -> bool:
    """Se il bot puo' rispondere ai clienti."""
    return _attivo


def set_bot_attivo_cache(valore: bool) -> None:
    """Rimette in memoria il valore appena letto o scritto."""
    global _attivo
    _attivo = bool(valore)


def da_testo(valore: str | None) -> bool:
    """Come si legge in database: manca o non si capisce vuol dire acceso."""
    if valore is None:
        return True
    return valore.strip().lower() not in ("0", "false", "no", "spento")


def a_testo(valore: bool) -> str:
    return "1" if valore else "0"
