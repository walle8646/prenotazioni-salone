"""Test sul listino: prezzi, durate e riconoscimento dei nomi.

Il listino è quello fornito dal salone ad agosto 2026. Se cambia, questi test
devono cambiare con lui: servono proprio a impedire che il bot citi prezzi
diversi da quelli concordati.
"""

import pytest

from services import catalogo
from services.operatori import OPERATORI


@pytest.mark.parametrize(
    "nome,prezzo,durata",
    [
        ("Taglio", 13.50, 30),
        ("Taglio + Shampoo", 17.50, 30),
        ("Taglio + Barba", 20.00, 30),
        ("Taglio + Shampoo + Barba", 25.00, 30),
        ("Barba", 8.00, 30),
        ("Taglio + Shampoo + Trattamento barba con oli e panno bagnato", 45.00, 60),
        ("Colore + Taglio + Trattamento capello", 50.00, 120),
    ],
)
def test_listino_ufficiale(nome, prezzo, durata):
    servizio = catalogo.trova(nome)
    assert servizio is not None, f"servizio non trovato: {nome}"
    assert servizio.prezzo == prezzo
    assert servizio.durata_min == durata


def test_il_catalogo_ha_sette_servizi():
    assert len(catalogo.SERVIZI) == 7


@pytest.mark.parametrize(
    "scritto,codice_atteso",
    [
        ("taglio", "taglio"),
        ("TAGLIO", "taglio"),
        ("Taglio+Barba", "taglio_barba"),
        ("taglio e barba", "taglio_barba"),
        ("barba regolata", "barba"),
        ("taglio schampoo", "taglio_shampoo"),
        ("colore", "colore"),
        ("tinta", "colore"),
        ("trattamento barba", "rituale_barba"),
    ],
)
def test_riconoscimento_nomi_e_alias(scritto, codice_atteso):
    """Il cliente e Claude scrivono in modi diversi: devono combaciare lo stesso."""
    servizio = catalogo.trova(scritto)
    assert servizio is not None, f"non riconosciuto: {scritto}"
    assert servizio.codice == codice_atteso


def test_nome_sconosciuto():
    assert catalogo.trova("massaggio thailandese") is None
    assert catalogo.trova("") is None


def test_durata_combinazione_non_si_somma():
    """Taglio + Barba insieme dura 30 minuti, non 60: è una voce di listino."""
    assert catalogo.durata_totale(["Taglio", "Barba"]) == 30
    assert catalogo.prezzo_totale(["Taglio", "Barba"]) == 20.00


def test_durata_servizi_lunghi():
    assert catalogo.durata_totale(["Colore + Taglio + Trattamento capello"]) == 120
    assert catalogo.durata_totale(["trattamento barba"]) == 60


def test_due_servizi_lunghi_si_sommano():
    """Se qualcuno prenota davvero colore e rituale barba, l'operatore è occupato per entrambi."""
    assert catalogo.durata_totale(["colore", "trattamento barba"]) == 180


def test_durata_predefinita_se_non_riconosce():
    assert catalogo.durata_totale(["qualcosa di ignoto"]) == 30
    assert catalogo.durata_totale([]) == 30
    assert catalogo.durata_totale(None) == 30


def test_prezzo_formattato():
    assert catalogo.prezzo_formattato(["Taglio"]) == "13,50 €"
    assert catalogo.prezzo_formattato(["Barba"]) == "8,00 €"
    assert catalogo.prezzo_formattato(["Colore + Taglio + Trattamento capello"]) == "50,00 €"
    assert catalogo.prezzo_formattato(["ignoto"]) == ""


def test_durata_formattata():
    assert catalogo.trova("Taglio").durata_formattata == "30 min"
    assert catalogo.trova("trattamento barba").durata_formattata == "1 ora"
    assert catalogo.trova("colore").durata_formattata == "2 ore"


def test_tutte_le_durate_stanno_nella_griglia_da_30():
    """Ogni servizio deve occupare un numero intero di slot da 30 minuti."""
    for servizio in catalogo.SERVIZI:
        assert servizio.durata_min % 30 == 0, servizio.nome


def test_elenco_per_prompt_contiene_prezzi_e_durate():
    testo = catalogo.elenco_per_prompt()
    assert "13,50 €" in testo
    assert "durata_min=120" in testo
    assert testo.count("\n") == len(catalogo.SERVIZI) - 1


def test_elenco_per_sito():
    voci = catalogo.elenco_per_sito()
    assert len(voci) == 7
    assert voci[0] == {"nome": "Taglio", "prezzo": "13,50 €", "durata": "30 min"}


# ------------------------------------------------------------------- operatori


def test_i_sei_operatori():
    assert OPERATORI == (
        "Simone Big",
        "Simone Jr",
        "Francesco",
        "Andrea",
        "Giava",
        "Bario",
    )


def test_ogni_operatore_ha_una_voce_di_calendario():
    from services.operatori import mappa_calendari

    mappa = mappa_calendari()
    assert set(mappa) == set(OPERATORI)
    assert all(cal_id for cal_id in mappa.values())


def test_calendari_non_configurati_sono_segnalati():
    """Senza GCAL_PARRUCCHIERE_IDS tutti gli operatori risultano da configurare."""
    from services.operatori import senza_calendario

    # In ambiente di test la variabile non è impostata
    assert len(senza_calendario()) == len(OPERATORI)


# ------------------------------------------------------- listino modificabile


def test_listino_puo_essere_sostituito_a_caldo():
    """Il pannello di gestione cambierà i prezzi nel database: il bot li deve recepire."""
    from services.catalogo import Servizio, set_catalogo_cache

    originale = catalogo.tutti()
    try:
        set_catalogo_cache(
            [
                Servizio(
                    codice="taglio",
                    nome="Taglio",
                    prezzo=15.00,
                    durata_min=45,
                    alias=("capelli",),
                )
            ]
        )
        assert len(catalogo.tutti()) == 1
        assert catalogo.prezzo_formattato(["Taglio"]) == "15,00 €"
        assert catalogo.durata_totale(["capelli"]) == 45
        assert "15,00 €" in catalogo.elenco_per_prompt()
        # un servizio non più a listino smette di essere riconosciuto
        assert catalogo.trova("colore") is None
    finally:
        set_catalogo_cache(originale)

    assert catalogo.prezzo_formattato(["Taglio"]) == "13,50 €"


def test_cache_vuota_usa_il_listino_iniziale():
    from services.catalogo import set_catalogo_cache

    originale = catalogo.tutti()
    try:
        set_catalogo_cache([])
        assert catalogo.tutti() == catalogo.SERVIZI_INIZIALI
    finally:
        set_catalogo_cache(originale)
