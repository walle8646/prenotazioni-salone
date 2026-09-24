"""Chi può prenotare: il titolare del contatto e fino a tre persone sue.

Un cliente prenota anche per i figli, per il padre, per chi un telefono suo
non ce l'ha. Prima quelle prenotazioni finivano tutte sulla stessa scheda —
tre tagli sullo stesso nome — e la regola "un appuntamento per volta" le
rendeva addirittura impossibili: prenotato il figlio, il padre non poteva più.

Un familiare è una persona vera in anagrafica: ha il suo storico, il suo
appuntamento, il suo nome sul calendario dell'operatore. Quello che non ha è
un contatto proprio. Si raggiunge attraverso il titolare, ed è il titolare
l'unico che può vederlo e cambiarlo — su WhatsApp lo dice il numero del
mittente, dal sito l'email verificata col codice. Un familiare non è mai un
parametro libero: vale solo dentro la famiglia di chi sta scrivendo.
"""

from __future__ import annotations

# Tre e non di più. Il numero non è tecnico: un contatto che ne dichiara
# quindici non è una famiglia, è un modo per prendersi mezza giornata di
# poltrone con un telefono solo — e il controllo "un appuntamento per volta"
# smetterebbe di valere per chiunque abbia voglia di aggirarlo.
MASSIMO_FAMILIARI = 3

# I "telefoni" che non sono telefoni: l'identificativo di sessione di chi
# arriva dal sito e il segnaposto di chi non ha un numero suo. La colonna è
# unica e obbligatoria, quindi un valore ci deve stare; mostrato a qualcuno
# sembrerebbe però un numero da chiamare, e chi lo compone non trova nessuno.
PREFISSI_SENZA_NUMERO = ("web_", "fam:", "salone:")


def e_un_telefono(valore: str | None) -> bool:
    """True se è un numero vero, da mostrare e da chiamare."""
    testo = (valore or "").strip()
    return bool(testo) and not testo.startswith(PREFISSI_SENZA_NUMERO)


def telefono_da_mostrare(valore: str | None) -> str:
    """Il numero, oppure niente: mai il segnaposto."""
    return valore if e_un_telefono(valore) else ""


def segnaposto(titolare_id: int, progressivo: int) -> str:
    """Il valore che occupa la colonna del telefono per chi non ne ha uno.

    Contiene l'id del titolare perché resti leggibile anche guardando la
    tabella a mano, e il progressivo perché due familiari dello stesso
    titolare non possono avere lo stesso valore in una colonna unica.
    """
    return f"fam:{titolare_id}:{progressivo}"


def posti_liberi(quanti_familiari: int) -> int:
    """Quante persone si possono ancora aggiungere a questo contatto."""
    return max(0, MASSIMO_FAMILIARI - quanti_familiari)


def stessa_persona(uno: str | None, altro: str | None) -> bool:
    """Se due nomi indicano la stessa persona.

    Confronto tollerante — maiuscole, spazi — perché il nome arriva da come
    l'ha scritto il cliente in chat: "luca" e "Luca " sono lo stesso figlio, e
    trattarli come due persone diverse brucerebbe uno dei tre posti.
    """
    return (uno or "").strip().casefold() == (altro or "").strip().casefold()


# Cosa farne di una persona che si vuole togliere da un contatto. Tre casi, e
# uno solo e' una cancellazione: la decisione sta qui, fuori dalla rotta,
# perche' sbagliarla vuol dire o perdere uno storico o lasciare in agenda un
# appuntamento senza piu' nessuno a cui farlo risalire.
TIENI = "tieni"
STACCA = "stacca"
CANCELLA = "cancella"


def cosa_fare_del_familiare(quanti: int, futuri: int) -> str:
    """Se una persona si può togliere dal contatto, e come.

    - **tieni**: ha un appuntamento in programma. Non si tocca: la scheda
      sparirebbe e il cliente si presenterebbe lo stesso, con nessuno in
      salone che sa chi è.
    - **stacca**: ha solo appuntamenti passati. Esce dal contatto e libera il
      posto, ma la scheda resta: buttare via lo storico per correggere un nome
      sarebbe il rimedio peggiore del male.
    - **cancella**: non ha proprio niente. È un nome scritto male, e lasciarlo
      terrebbe occupato uno dei tre posti per sempre.
    """
    if futuri:
        return TIENI
    return STACCA if quanti else CANCELLA
