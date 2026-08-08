"""Test sul pannello di gestione: listino, operatori e primo popolamento.

Qui non si tocca il database: si verificano le decisioni, che sono la parte
in cui si sbaglia. Il giro completo sulle schermate si prova a mano.
"""

import pytest

from routers.admin import _alias_da_testo, _codice_da_nome, _decimale
from services.db_service import sovrascrive_il_calendario
from services.operatori import PREFISSO_NON_CONFIGURATO


# ------------------------------------------------------------------- prezzi


@pytest.mark.parametrize(
    "scritto,atteso",
    [
        ("13,50", 13.50),  # come lo scrive chiunque in Italia
        ("13.50", 13.50),
        (" 20 ", 20.0),
        ("8,00 €", 8.0),
        ("0", 0.0),
    ],
)
def test_prezzi_scritti_come_capita(scritto, atteso):
    assert _decimale(scritto) == atteso


@pytest.mark.parametrize("scritto", ["", "gratis", "13,5,0", None])
def test_un_prezzo_illeggibile_si_fa_riconoscere(scritto):
    """Meglio un errore in faccia che un servizio a zero euro."""
    with pytest.raises(ValueError):
        _decimale(scritto)


# ------------------------------------------------------------------- codici


def test_il_codice_nasce_dal_nome():
    assert _codice_da_nome("Taglio + Barba", set()) == "taglio_barba"


def test_due_servizi_con_lo_stesso_nome_non_si_sovrappongono():
    """`codice` è unico in tabella: senza distinguerli, il secondo non entra."""
    presi = {"taglio", "taglio_2"}

    assert _codice_da_nome("Taglio", presi) == "taglio_3"


def test_un_nome_di_soli_simboli_ha_comunque_un_codice():
    assert _codice_da_nome("+++", set()) == "servizio"


# -------------------------------------------------------------------- alias


def test_gli_alias_si_scrivono_come_viene():
    assert _alias_da_testo("taglio e barba, taglio+barba") == [
        "taglio e barba",
        "taglio+barba",
    ]
    assert _alias_da_testo("uno\ndue , tre") == ["uno", "due", "tre"]
    assert _alias_da_testo("") == []
    assert _alias_da_testo(None) == []


# --------------------------------------------- primo popolamento degli operatori
#
# `seed_parrucchieri` gira a ogni avvio. Prima riattivava chi era nell'elenco
# del codice e disattivava chi non c'era: col pannello vorrebbe dire vedersi
# sparire al deploy l'operatore appena assunto.


def test_un_calendario_vero_non_viene_sovrascritto_dalla_configurazione():
    """È il pannello a cambiarlo: un riavvio non deve disfare quel lavoro."""
    assert (
        sovrascrive_il_calendario(
            "scelto-dal-pannello@group.calendar.google.com",
            "vecchio@group.calendar.google.com",
        )
        is False
    )


def test_un_segnaposto_viene_configurato_dalla_variabile_d_ambiente():
    """Il caso utile: operatore creato senza calendario, poi configurato."""
    assert (
        sovrascrive_il_calendario(
            f"{PREFISSO_NON_CONFIGURATO}andrea",
            "vero@group.calendar.google.com",
        )
        is True
    )


def test_un_segnaposto_non_si_sostituisce_con_un_altro_segnaposto():
    assert (
        sovrascrive_il_calendario(
            f"{PREFISSO_NON_CONFIGURATO}andrea",
            f"{PREFISSO_NON_CONFIGURATO}andrea",
        )
        is False
    )
