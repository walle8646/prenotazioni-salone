"""Avatar disegnati dal codice, per gli operatori che non hanno ancora una foto.

Un SVG con le iniziali su un colore ricavato dal nome. Serve a non aspettare
le foto vere per mostrare qualcosa, e sparisce da sé nel momento in cui una
foto viene caricata dal pannello.

Due scelte che sembrano dettagli e non lo sono.

**Il colore si ricava con `hashlib`, non con `hash()`.** Quello incorporato in
Python è salato a ogni avvio del processo: lo stesso operatore cambierebbe
colore a ogni deploy, e chi lo riconosceva a colpo d'occhio non lo
riconoscerebbe più.

**Le iniziali sono due anche per i nomi di una parola sola.** Con una sola
lettera Simone Big e Simone Jr sarebbero due dischi identici con una S: la
distinzione fra i due è esattamente quello che serve al cliente.
"""

from __future__ import annotations

import hashlib
import re
from xml.sax.saxutils import escape

# Colori scuri quanto basta perché il bianco sopra si legga. Tenuti distanti
# fra loro in tinta: due operatori vicini nell'elenco non devono sembrare lo
# stesso disco.
COLORI = (
    "#c0392b",  # rosso
    "#2980b9",  # blu
    "#27ae60",  # verde
    "#8e44ad",  # viola
    "#d35400",  # arancio
    "#16a085",  # verde acqua
    "#2c3e50",  # blu notte
    "#b7950b",  # ocra
    "#a93226",  # granata
    "#6c3483",  # prugna
    "#1f618d",  # petrolio
    "#117864",  # smeraldo
)


def iniziali(nome: str) -> str:
    """Fino a due lettere maiuscole che identificano l'operatore.

    "Simone Big" → SB, "Francesco" → FR. Mai una lettera sola: con quella,
    due operatori che si chiamano uguale diventano indistinguibili.
    """
    parole = [p for p in re.split(r"[\s'-]+", (nome or "").strip()) if p]
    if not parole:
        return "?"
    if len(parole) == 1:
        return parole[0][:2].upper()
    return (parole[0][:1] + parole[1][:1]).upper()


def colore(nome: str) -> str:
    """Colore stabile per un nome: lo stesso oggi, fra un mese e dopo un deploy."""
    impronta = hashlib.sha256((nome or "").encode("utf-8")).digest()
    return COLORI[impronta[0] % len(COLORI)]


def avatar_svg(nome: str, lato: int = 96) -> str:
    """Disco colorato con le iniziali, pronto da servire come immagine."""
    testo = escape(iniziali(nome))
    raggio = lato / 2
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{lato}" height="{lato}" '
        f'viewBox="0 0 {lato} {lato}" role="img" '
        f'aria-label="{escape(nome or "Operatore")}">'
        f'<circle cx="{raggio}" cy="{raggio}" r="{raggio}" fill="{colore(nome)}"/>'
        f'<text x="50%" y="50%" dy="0.35em" text-anchor="middle" fill="#ffffff" '
        f'font-family="-apple-system, Segoe UI, Roboto, sans-serif" '
        f'font-size="{lato * 0.4:.0f}" font-weight="600">{testo}</text>'
        f"</svg>"
    )
