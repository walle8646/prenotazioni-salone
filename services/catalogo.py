"""Catalogo dei servizi del salone: nomi, prezzi e durate.

Da qui leggono il system prompt di Claude (così il bot cita prezzi e tempi
giusti), il sito pubblico, il calcolo della durata da bloccare sul calendario e
il totale mostrato alla receptionist.

Dove vive il listino: la fonte di verità a runtime è la tabella `servizi` del
database, così il pannello di gestione potrà modificare prezzi e durate senza
toccare il codice. La lista qui sotto è il listino iniziale con cui la tabella
viene riempita al primo avvio, e resta come rete di sicurezza per simulatore e
test, che girano senza database.

Listino fornito dal salone (agosto 2026):
    Taglio                                              13,50 €   30 min
    Taglio + Shampoo                                    17,50 €   30 min
    Taglio + Barba                                      20,00 €   30 min
    Taglio + Shampoo + Barba                            25,00 €   30 min
    Barba                                                8,00 €   30 min
    Taglio + Shampoo + trattamento barba (oli e panno)  45,00 €    1 ora
    Colore + Taglio + trattamento capello               50,00 €    2 ore
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Servizio:
    codice: str
    nome: str
    prezzo: float
    durata_min: int
    alias: tuple[str, ...] = field(default=())

    @property
    def prezzo_formattato(self) -> str:
        return f"{self.prezzo:.2f}".replace(".", ",") + " €"

    @property
    def durata_formattata(self) -> str:
        if self.durata_min < 60:
            return f"{self.durata_min} min"
        ore, minuti = divmod(self.durata_min, 60)
        testo = "1 ora" if ore == 1 else f"{ore} ore"
        return testo if not minuti else f"{testo} e {minuti} min"


SERVIZI_INIZIALI: tuple[Servizio, ...] = (
    Servizio(
        codice="taglio",
        nome="Taglio",
        prezzo=13.50,
        durata_min=30,
        alias=("solo taglio", "capelli"),
    ),
    Servizio(
        codice="taglio_shampoo",
        nome="Taglio + Shampoo",
        prezzo=17.50,
        durata_min=30,
        alias=("taglio e shampoo", "taglio con shampoo", "taglio+shampoo", "taglio schampoo"),
    ),
    Servizio(
        codice="taglio_barba",
        nome="Taglio + Barba",
        prezzo=20.00,
        durata_min=30,
        alias=("taglio e barba", "taglio+barba"),
    ),
    Servizio(
        codice="taglio_shampoo_barba",
        nome="Taglio + Shampoo + Barba",
        prezzo=25.00,
        durata_min=30,
        alias=(
            "taglio shampoo e barba",
            "taglio + barba + shampoo",
            "taglio barba shampoo",
            "taglio schampoo barba",
        ),
    ),
    Servizio(
        codice="barba",
        nome="Barba",
        prezzo=8.00,
        durata_min=30,
        alias=("barba regolata", "solo barba", "rasatura"),
    ),
    Servizio(
        codice="rituale_barba",
        nome="Taglio + Shampoo + Trattamento barba con oli e panno bagnato",
        prezzo=45.00,
        durata_min=60,
        alias=(
            "trattamento barba",
            "trattamento barba con oli",
            "barba con oli e panno bagnato",
            "rituale barba",
            "taglio shampoo trattamento barba",
        ),
    ),
    Servizio(
        codice="colore",
        nome="Colore + Taglio + Trattamento capello",
        prezzo=50.00,
        durata_min=120,
        alias=(
            "colore",
            "tinta",
            "colore e taglio",
            "colore + taglio",
            "trattamento capello",
            "colore taglio e trattamento capello",
        ),
    ),
)

DURATA_PREDEFINITA_MIN = 30

# Catalogo attivo in memoria. Viene riempito all'avvio leggendo la tabella
# `servizi` del database; finché non succede si usa il listino iniziale qui
# sopra, così simulatore e test funzionano senza database.
_cache: tuple[Servizio, ...] = ()


def set_catalogo_cache(servizi) -> None:
    """Sostituisce il listino in memoria (chiamata all'avvio e dopo le modifiche)."""
    global _cache, _INDICE
    _cache = tuple(servizi)
    _INDICE = _costruisci_indice(_cache or SERVIZI_INIZIALI)


def tutti() -> tuple[Servizio, ...]:
    """Listino attualmente in vigore."""
    return _cache or SERVIZI_INIZIALI


def _normalizza(testo: str) -> str:
    """Minuscolo, senza accenti, senza punteggiatura, spazi compattati.

    Serve a far combaciare 'Taglio+Barba', 'taglio e barba' e 'TAGLIO  BARBA'.
    """
    testo = unicodedata.normalize("NFKD", testo or "")
    testo = "".join(c for c in testo if not unicodedata.combining(c))
    testo = testo.lower()
    testo = re.sub(r"[+&/,]", " ", testo)
    testo = re.sub(r"\b(e|con|il|la|lo|un|una|di)\b", " ", testo)
    testo = re.sub(r"[^a-z0-9 ]", " ", testo)
    return re.sub(r"\s+", " ", testo).strip()


def _costruisci_indice(servizi) -> dict[str, Servizio]:
    indice: dict[str, Servizio] = {}
    for servizio in servizi:
        indice[_normalizza(servizio.nome)] = servizio
        indice[_normalizza(servizio.codice)] = servizio
        for alias in servizio.alias:
            indice.setdefault(_normalizza(alias), servizio)
    return indice


_INDICE: dict[str, Servizio] = _costruisci_indice(SERVIZI_INIZIALI)


def trova(nome: str) -> Servizio | None:
    """Riconosce un servizio dal nome, dal codice o da un alias."""
    if not nome:
        return None
    chiave = _normalizza(nome)
    if chiave in _INDICE:
        return _INDICE[chiave]

    # Ripiego: la stringa contiene esattamente le stesse parole di un servizio
    parole = set(chiave.split())
    for servizio in tutti():
        if parole and parole == set(_normalizza(servizio.nome).split()):
            return servizio
    return None


def risolvi(nomi: list[str] | str | None) -> list[Servizio]:
    """Trasforma quello che ha scritto Claude nell'elenco dei servizi reali.

    Prova prima a leggere l'elenco come una combinazione unica (['Taglio',
    'Barba'] è il servizio 'Taglio + Barba', non due servizi separati), poi
    ripiega sul riconoscimento voce per voce.
    """
    if not nomi:
        return []
    if isinstance(nomi, str):
        nomi = [nomi]

    combinato = trova(" ".join(nomi))
    if combinato is not None:
        return [combinato]

    risolti = []
    for nome in nomi:
        servizio = trova(nome)
        if servizio is not None and servizio not in risolti:
            risolti.append(servizio)
    return risolti


def durata_totale(nomi: list[str] | str | None) -> int:
    """Minuti da bloccare sul calendario.

    Le combinazioni standard durano 30 minuti anche se sommano più prestazioni
    (il salone lo ha detto esplicitamente: "il resto durata 30 minuti"), quindi
    non si sommano i tempi. Solo se vengono richiesti due servizi lunghi diversi
    — per esempio colore e rituale barba — i tempi si sommano, perché in quel
    caso l'operatore è davvero occupato per entrambi.
    """
    servizi = risolvi(nomi)
    if not servizi:
        return DURATA_PREDEFINITA_MIN

    lunghi = [s for s in servizi if s.durata_min > DURATA_PREDEFINITA_MIN]
    if len(lunghi) > 1:
        return sum(s.durata_min for s in lunghi)
    return max(s.durata_min for s in servizi)


def prezzo_totale(nomi: list[str] | str | None) -> float:
    """Totale in euro dei servizi richiesti. 0 se non ne riconosce nessuno."""
    return round(sum(s.prezzo for s in risolvi(nomi)), 2)


def prezzo_formattato(nomi: list[str] | str | None) -> str:
    """Totale già pronto da mostrare, es. '25,00 €'. Stringa vuota se sconosciuto."""
    totale = prezzo_totale(nomi)
    if not totale:
        return ""
    return f"{totale:.2f}".replace(".", ",") + " €"


# Alias storico: alcuni moduli e i test si riferiscono ancora a SERVIZI
SERVIZI = SERVIZI_INIZIALI


def elenco_per_prompt() -> str:
    """Listino da inserire nel system prompt di Claude."""
    return "\n".join(
        f"- {s.nome} — {s.prezzo_formattato} — {s.durata_formattata} "
        f"(durata_min={s.durata_min})"
        for s in tutti()
    )


def elenco_per_sito() -> list[dict]:
    """Listino per la pagina pubblica del sito."""
    return [
        {
            "nome": s.nome,
            "prezzo": s.prezzo_formattato,
            "durata": s.durata_formattata,
        }
        for s in tutti()
    ]
