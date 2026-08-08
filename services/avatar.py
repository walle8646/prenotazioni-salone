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
import logging
import re
from xml.sax.saxutils import escape

logger = logging.getLogger(__name__)

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


def _tonda(immagine, lato: int):
    """Ritaglia un'immagine in un tondo del lato richiesto."""
    from PIL import Image, ImageDraw

    quadrata = immagine.convert("RGB")
    larghezza, altezza = quadrata.size
    corto = min(larghezza, altezza)
    # Ritaglio centrale: le foto non arriveranno quadrate, e deformare la
    # faccia di qualcuno è peggio che tagliarne un pezzo.
    sinistra = (larghezza - corto) // 2
    alto = (altezza - corto) // 2
    quadrata = quadrata.crop((sinistra, alto, sinistra + corto, alto + corto))
    quadrata = quadrata.resize((lato, lato), Image.LANCZOS)

    maschera = Image.new("L", (lato, lato), 0)
    ImageDraw.Draw(maschera).ellipse((0, 0, lato - 1, lato - 1), fill=255)
    quadrata.putalpha(maschera)
    return quadrata


def normalizza_foto(contenuto: bytes, lato: int = 512) -> tuple[bytes, str]:
    """Riduce una foto a un quadrato piccolo, pronto da mostrare in tondo.

    Fatto qui e non chiesto a chi carica: le foto arrivano dal telefono, tre
    o quattro megabyte a testa, e finirebbero tali e quali nel database e in
    ogni immagine di riepilogo. Così restano cinquanta chilobyte.

    Il ritaglio è centrale, ed è un ripiego: chi carica dal pannello sceglie
    l'inquadratura nel browser e qui arriva già quadrata, quindi questo taglio
    non toglie niente. Serve per le foto che arrivano per altre strade.

    L'orientamento EXIF va applicato, altrimenti le fotografie fatte col
    telefono in verticale si vedono coricate.
    """
    import io

    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(contenuto)) as originale:
        immagine = ImageOps.exif_transpose(originale)
        immagine = immagine.convert("RGB")

        corto = min(immagine.size)
        sinistra = (immagine.width - corto) // 2
        alto = (immagine.height - corto) // 2
        immagine = immagine.crop((sinistra, alto, sinistra + corto, alto + corto))
        if corto > lato:
            immagine = immagine.resize((lato, lato), Image.LANCZOS)

        memoria = io.BytesIO()
        immagine.save(memoria, format="JPEG", quality=85, optimize=True)
        return memoria.getvalue(), "image/jpeg"


def griglia_operatori_png(
    nomi: list[str], foto: dict[str, bytes] | None = None, per_riga: int = 3
) -> bytes:
    """Un'unica immagine con le facce di tutti, per WhatsApp.

    Lì una faccia accanto a ogni riga non è possibile: le liste ammettono solo
    testo e i messaggi a bottoni una sola immagine di intestazione. Allora si
    manda quella, e le scelte restano i nomi.

    Chi ha una foto vera la mostra, gli altri l'avatar con le iniziali: la
    griglia non deve avere buchi mentre il salone raccoglie le fotografie.
    """
    from PIL import Image, ImageDraw, ImageFont

    foto = foto or {}
    nomi = [n for n in nomi if n]
    if not nomi:
        raise ValueError("nessun operatore da disegnare")

    LATO_CELLA, ALTEZZA_CELLA, DIAMETRO = 220, 268, 168
    colonne = min(per_riga, len(nomi))
    righe = -(-len(nomi) // colonne)  # divisione intera per eccesso

    tela = Image.new(
        "RGB", (colonne * LATO_CELLA, righe * ALTEZZA_CELLA), "#ffffff"
    )
    disegno = ImageDraw.Draw(tela)
    font_iniziali = ImageFont.load_default(size=int(DIAMETRO * 0.4))
    font_nome = ImageFont.load_default(size=26)

    for indice, nome in enumerate(nomi):
        colonna, riga = indice % colonne, indice // colonne
        centro_x = colonna * LATO_CELLA + LATO_CELLA // 2
        alto = riga * ALTEZZA_CELLA + 18
        centro_y = alto + DIAMETRO // 2

        contenuto = foto.get(nome)
        disegnata = False
        if contenuto:
            try:
                import io

                tonda = _tonda(Image.open(io.BytesIO(contenuto)), DIAMETRO)
                tela.paste(tonda, (centro_x - DIAMETRO // 2, alto), tonda)
                disegnata = True
            except Exception:  # noqa: BLE001
                # Un file illeggibile non deve lasciare un buco nella griglia:
                # si ripiega sull'avatar, che non fallisce mai.
                logger.warning("Foto di %s illeggibile, uso l'avatar", nome)

        if not disegnata:
            raggio = DIAMETRO // 2
            disegno.ellipse(
                (centro_x - raggio, centro_y - raggio, centro_x + raggio, centro_y + raggio),
                fill=colore(nome),
            )
            disegno.text(
                (centro_x, centro_y),
                iniziali(nome),
                font=font_iniziali,
                fill="#ffffff",
                anchor="mm",
            )

        disegno.text(
            (centro_x, alto + DIAMETRO + 30),
            nome,
            font=font_nome,
            fill="#2c3e50",
            anchor="mm",
        )

    import io

    memoria = io.BytesIO()
    tela.save(memoria, format="PNG", optimize=True)
    return memoria.getvalue()


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
