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


@pytest.mark.asyncio
async def test_whatsapp_non_le_riceve_nemmeno(canale):
    """Nelle liste di Meta non c'è posto per un'immagine: allegarla sarebbe
    peso inutile a ogni messaggio."""
    from services.conversation import deliver

    await deliver(canale, "393331234567", "Con chi preferisci?\n- Francesco\n- Andrea")

    assert all("foto" not in o for o in canale.ultimo()["options"])
