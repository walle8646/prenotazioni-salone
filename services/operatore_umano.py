"""Quando la conversazione passa dal bot a una persona.

Tre decisioni vivono qui, tutte prese senza toccare il database così restano
verificabili con un istante fissato: se il cliente sta chiedendo una persona,
se la finestra di WhatsApp è ancora aperta, e se un passaggio è stato
dimenticato.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

# WhatsApp lascia scrivere testo libero solo entro 24 ore dall'ultimo messaggio
# del cliente. Fuori da quella finestra servirebbe un template approvato da
# Meta, che non abbiamo: la schermata deve dirlo prima di far scrivere, non
# dopo aver fatto scrivere.
ORE_FINESTRA = 24

# Dopo quanto un passaggio a cui nessuno ha risposto viene considerato
# dimenticato e il bot riprende in mano la conversazione. Senza questo, un
# cliente a cui la receptionist non risponde resterebbe a parlare con un muro
# per sempre: il bot muto è una scelta, il bot muto e nessun altro no.
ORE_PRIMA_DI_RIPRENDERE = 24

# Quello che il bot dice al cliente quando si fa da parte. Dichiara anche
# l'attesa: "ti rispondiamo appena possibile" senza dire quando è il modo
# migliore per farsi riscrivere tre volte.
MESSAGGIO_PASSAGGIO = (
    "Ci penso io a farti parlare con una persona del salone: ho segnalato la "
    "tua richiesta e ti risponderanno da questo stesso numero, "
    "negli orari di apertura. Da adesso non ti rispondo più io."
)

# Sul sito non c'è nessuno a cui passare: la receptionist risponde da WhatsApp,
# e una pagina chiusa non si può richiamare. Meglio dirlo che far aspettare.
MESSAGGIO_PASSAGGIO_WEB = (
    "Da qui non riesco a passarti una persona: scrivi su WhatsApp al {telefono} "
    "e ti risponde qualcuno del salone."
)
MESSAGGIO_PASSAGGIO_WEB_SENZA_NUMERO = (
    "Da qui non riesco a passarti una persona: prova a telefonare al salone "
    "negli orari di apertura, oppure scrivici su WhatsApp."
)


# Parole che indicano una persona in carne e ossa. "Operatore" da solo non c'è
# ed è voluto: in questo salone gli operatori sono i parrucchieri, e "vorrei un
# operatore qualsiasi" vuol dire il contrario di quello che sembra.
_PERSONA = re.compile(
    r"(una persona|un[' ]?essere umano|un umano|qualcuno|"
    r"il titolare|la titolare|il proprietario|la proprietaria|"
    r"un responsabile|la reception|un addetto|un impiegato)",
    re.IGNORECASE,
)

_PARLARE = re.compile(
    r"(parlar|parlo|parlare|sentir|senti|contattar|mi pass|mi mett|"
    r"passami|passatemi|posso avere|c'è|ci sarebbe|vorrei)",
    re.IGNORECASE,
)

# Il rifiuto esplicito del bot vale da solo, senza bisogno del verbo: chi
# scrive "non voglio parlare con un robot" ha già detto tutto.
#
# La negazione e la parola "bot" possono avere in mezzo qualsiasi cosa ("non
# voglio parlare con un bot"), quindi si accetta una distanza invece di
# elencare i verbi: elencarli vuol dire scoprire quello che manca dal cliente
# arrabbiato che non riceve risposta.
_NIENTE_BOT = re.compile(
    r"("
    r"\b(non|niente|basta|smettila)\b[^.!?]{0,40}"
    r"\b(bot|robot|risponditore|automatic|intelligenza artificiale)"
    r"|sei un (bot|robot)"
    r"|parlando con un (bot|robot)"
    r"|non sei una persona"
    r")",
    re.IGNORECASE,
)


def vuole_una_persona(text: str | None, operatori: list[str] | None = None) -> bool:
    """True se il cliente sta chiedendo di parlare con qualcuno del salone.

    Il controllo sta nel codice e non solo nel prompt per lo stesso motivo per
    cui ci sta `vuole_ricominciare()`: è l'ultima via d'uscita di chi non sta
    ottenendo quello che vuole, e non può dipendere da quanto bene il modello
    se lo ricorda in fondo a una conversazione lunga.

    Se nella frase compare il nome di un operatore non è un passaggio: "vorrei
    parlare con Simone" sta scegliendo il parrucchiere, non chiedendo aiuto.
    """
    if not text:
        return False
    frase = text.strip()

    if _NIENTE_BOT.search(frase):
        return True

    if not (_PERSONA.search(frase) and _PARLARE.search(frase)):
        return False

    # Un nome di operatore nella frase la riporta al suo significato normale.
    for nome in operatori or ():
        primo = (nome or "").split()[0] if nome else ""
        if primo and re.search(rf"\b{re.escape(primo)}\b", frase, re.IGNORECASE):
            return False

    return True


def finestra_aperta(ultimo_messaggio_cliente: datetime | None, adesso: datetime) -> bool:
    """Se si può ancora scrivere testo libero a questo cliente.

    L'istante corrente arriva come parametro e non si legge dall'orologio, come
    per gli slot: una finestra che scade è esattamente il genere di cosa che va
    provata con un momento fissato.
    """
    if ultimo_messaggio_cliente is None:
        return False
    return adesso - ultimo_messaggio_cliente < timedelta(hours=ORE_FINESTRA)


def minuti_rimasti(ultimo_messaggio_cliente: datetime | None, adesso: datetime) -> int:
    """Quanto manca alla chiusura della finestra, in minuti. 0 se è già chiusa."""
    if ultimo_messaggio_cliente is None:
        return 0
    scadenza = ultimo_messaggio_cliente + timedelta(hours=ORE_FINESTRA)
    return max(0, int((scadenza - adesso).total_seconds() // 60))


def passaggio_dimenticato(conversazione: dict, adesso: datetime) -> bool:
    """Se nessuno ha risposto per troppo tempo e il bot deve riprendere.

    Conta l'ultima attività dell'operatore, non l'apertura: una conversazione
    seguita davvero non scade mentre è in corso.
    """
    if not conversazione:
        return False
    riferimento = conversazione.get("presa_il") or conversazione.get("aperta_il")
    if riferimento is None:
        return False
    return adesso - riferimento >= timedelta(hours=ORE_PRIMA_DI_RIPRENDERE)


def storico_da_salvare(history: list[dict], quanti: int = 10) -> list[tuple[str, str]]:
    """Gli ultimi scambi col bot, da mostrare a chi prende in mano il discorso.

    Senza, la receptionist legge "va bene allora" e non sa a cosa. Si scartano
    i risultati delle azioni, che sono conversazione fra il codice e il
    modello: chi risponde al cliente non deve leggere JSON.
    """
    utili: list[tuple[str, str]] = []
    for messaggio in history or ():
        testo = (messaggio.get("content") or "").strip()
        if not testo or testo.startswith("[SISTEMA]"):
            continue
        autore = "cliente" if messaggio.get("role") == "user" else "bot"
        utili.append((autore, testo))
    return utili[-quanti:]
