"""Test sugli avatar degli operatori e su come arrivano al cliente."""

import pytest

from services.avatar import COLORI, avatar_svg, colore, iniziali
from services.conversation import con_foto, parse_response_with_options
from services.operatori import OPERATORI


# ------------------------------------------------------------------ iniziali


@pytest.mark.parametrize(
    "nome,attese",
    [
        ("Simone Big", "SB"),
        ("Simone Jr", "SJ"),
        ("Francesco", "FR"),
        ("  Andrea  ", "AN"),
        ("Gian-Luca", "GL"),
        ("Maria D'Aria", "MD"),
        ("", "?"),
    ],
)
def test_iniziali(nome, attese):
    assert iniziali(nome) == attese


def test_mai_una_lettera_sola():
    """Con una sola, Simone Big e Simone Jr sarebbero due dischi identici."""
    assert len(iniziali("Francesco")) == 2


def test_gli_operatori_veri_si_distinguono_tutti():
    """Se due si somigliassero, l'avatar sarebbe peggio di niente."""
    assert len({iniziali(n) for n in OPERATORI}) == len(OPERATORI)
    assert len({colore(n) for n in OPERATORI}) == len(OPERATORI)


# -------------------------------------------------------------------- colore


def test_il_colore_non_cambia_fra_un_avvio_e_l_altro():
    """`hash()` di Python è salato a ogni processo: l'operatore cambierebbe
    colore a ogni deploy. Questo valore è calcolato con sha256 ed è fisso."""
    assert colore("Francesco") == "#c0392b"
    assert colore("Francesco") == colore("Francesco")


def test_il_colore_esce_sempre_dalla_tavolozza():
    for nome in ("Francesco", "", "Zzzzz", "Ünico", "12345"):
        assert colore(nome) in COLORI


# ----------------------------------------------------------------------- svg


def test_l_avatar_e_un_svg_con_le_iniziali_dentro():
    svg = avatar_svg("Simone Big")

    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert ">SB<" in svg
    assert colore("Simone Big") in svg


def test_un_nome_con_caratteri_speciali_non_rompe_l_svg():
    """Il nome finisce nell'attributo aria-label: se non è protetto, un
    apice o una parentesi angolare producono un documento illeggibile."""
    svg = avatar_svg('Anna <script>alert("x")</script>')

    assert "<script>" not in svg
    assert "&lt;script&gt;" in svg


# ------------------------------------------- come arrivano nelle scelte


def test_agli_operatori_viene_agganciata_la_foto():
    _, opzioni = parse_response_with_options(
        "Con chi preferisci?\n- Francesco\n- Andrea"
    )

    con_faccia = con_foto(opzioni)

    assert con_faccia[0]["foto"] == "/operatori/Francesco/foto"
    assert con_faccia[1]["foto"] == "/operatori/Andrea/foto"


def test_il_nome_con_lo_spazio_finisce_codificato_nell_indirizzo():
    _, opzioni = parse_response_with_options(
        "Con chi preferisci?\n- Simone Big\n- Andrea"
    )

    assert con_foto(opzioni)[0]["foto"] == "/operatori/Simone%20Big/foto"


def test_indifferente_resta_senza_faccia():
    """Non è una persona."""
    _, opzioni = parse_response_with_options(
        "Con chi preferisci?\n- Francesco\n- Indifferente"
    )

    con_faccia = con_foto(opzioni)

    assert "foto" in con_faccia[0]
    assert "foto" not in con_faccia[1]


def test_gli_orari_non_prendono_facce():
    _, opzioni = parse_response_with_options("Quando?\n- 18:00\n- 18:30\n- 19:00")

    assert con_foto(opzioni) == opzioni


def test_i_servizi_non_prendono_facce():
    _, opzioni = parse_response_with_options("Cosa?\n- Taglio\n- Barba")

    assert con_foto(opzioni) == opzioni


# ------------------------------------------------------- canale per canale


@pytest.mark.asyncio
async def test_il_widget_del_sito_riceve_le_facce(mock_redis, backends):
    from services.channels import WebChannel
    from services.conversation import deliver

    canale = WebChannel()
    await deliver(canale, "web_1", "Con chi preferisci?\n- Francesco\n- Andrea")

    opzioni = canale.payload()["options"]
    assert all("foto" in o for o in opzioni if o["title"] != "Indifferente")


# ------------------------------------------------------------------ WhatsApp
#
# Lì una faccia accanto a ogni riga non esiste: le liste ammettono solo testo
# e i messaggi a bottoni una sola immagine di intestazione. Si manda quella.


@pytest.fixture
def meta(monkeypatch):
    """Registra cosa sarebbe partito verso Meta, senza toccare la rete."""
    from config import settings
    from services import whatsapp_service

    monkeypatch.setattr(settings, "public_base_url", "https://salone.example")

    partiti = []

    async def immagine(to, link, caption=""):
        partiti.append({"tipo": "immagine", "link": link})
        return True

    async def bottoni(to, body_text, buttons, header_image=None):
        partiti.append({"tipo": "bottoni", "header": header_image, "voci": buttons})
        return True

    async def lista(to, body_text, button_text, items):
        partiti.append({"tipo": "lista", "voci": items})
        return True

    monkeypatch.setattr(whatsapp_service, "send_image", immagine)
    monkeypatch.setattr(whatsapp_service, "send_interactive_buttons", bottoni)
    monkeypatch.setattr(whatsapp_service, "send_interactive_list", lista)
    return partiti


@pytest.mark.asyncio
async def test_con_molti_operatori_arriva_un_immagine_sola_e_poi_la_lista(meta):
    from services.channels import MetaWhatsAppChannel
    from services.conversation import deliver

    await deliver(
        MetaWhatsAppChannel(),
        "393331234567",
        "Con chi preferisci?\n- Simone Big\n- Francesco\n- Andrea\n- Giava",
    )

    assert [p["tipo"] for p in meta] == ["immagine", "lista"], (
        "una faccia per operatore sarebbero sei messaggi: se ne manda uno"
    )
    # "Indifferente" non compare: non è una persona e non ha una faccia.
    assert meta[0]["link"] == (
        "https://salone.example/operatori/scelta.png"
        "?nomi=Simone%20Big%2CFrancesco%2CAndrea%2CGiava"
    )
    assert all("image" not in v for v in meta[1]["voci"])


@pytest.mark.asyncio
async def test_con_tre_operatori_l_immagine_sta_dentro_i_bottoni(meta):
    """Nessun messaggio in più: l'intestazione è l'unico posto dove ci sta."""
    from services.channels import MetaWhatsAppChannel
    from services.conversation import deliver

    await deliver(
        MetaWhatsAppChannel(),
        "393331234567",
        "Con chi preferisci?\n- Francesco\n- Andrea",
    )

    assert [p["tipo"] for p in meta] == ["bottoni"]
    assert meta[0]["header"].startswith("https://salone.example/operatori/scelta.png")


@pytest.mark.asyncio
async def test_senza_indirizzo_pubblico_non_si_manda_nessuna_immagine(meta, monkeypatch):
    """Meta l'immagine se la viene a prendere: un indirizzo che non sa
    raggiungere farebbe fallire tutto il messaggio, non solo la faccia."""
    from config import settings
    from services.channels import MetaWhatsAppChannel
    from services.conversation import deliver

    monkeypatch.setattr(settings, "public_base_url", "")

    await deliver(
        MetaWhatsAppChannel(),
        "393331234567",
        "Con chi preferisci?\n- Simone Big\n- Francesco\n- Andrea\n- Giava",
    )

    assert [p["tipo"] for p in meta] == ["lista"]


@pytest.mark.asyncio
async def test_gli_orari_non_si_portano_dietro_nessuna_immagine(meta):
    from services.channels import MetaWhatsAppChannel
    from services.conversation import deliver

    await deliver(
        MetaWhatsAppChannel(),
        "393331234567",
        "Quando?\n- 18:00\n- 18:30\n- 19:00\n- 19:30",
    )

    assert [p["tipo"] for p in meta] == ["lista"]


# ------------------------------------------------- l'immagine con tutte le facce


def test_la_griglia_e_un_png_leggibile():
    import io

    from PIL import Image

    from services.avatar import griglia_operatori_png

    immagine = Image.open(io.BytesIO(griglia_operatori_png(list(OPERATORI))))

    assert immagine.format == "PNG"
    # Sei operatori, tre per riga: due righe da 220×268.
    assert immagine.size == (660, 536)


def test_una_foto_illeggibile_non_lascia_un_buco_nella_griglia():
    """Il file può essere corrotto o non essere affatto un'immagine: si
    ripiega sull'avatar, che non fallisce mai."""
    from services.avatar import griglia_operatori_png

    immagine = griglia_operatori_png(
        ["Francesco", "Andrea"], foto={"Francesco": b"non sono un'immagine"}
    )

    assert immagine.startswith(b"\x89PNG")


def test_senza_nomi_ci_si_ferma_invece_di_disegnare_il_vuoto():
    from services.avatar import griglia_operatori_png

    with pytest.raises(ValueError):
        griglia_operatori_png([])
