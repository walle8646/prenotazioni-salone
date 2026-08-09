"""Test sulla divisione del prompt per la cache di Anthropic.

La cache è un confronto di prefisso: si ferma al primo byte diverso. Con lo
stato della conversazione in mezzo al prompt restavano cacheabili solo i primi
novecento token — sotto la soglia minima — e non si attivava affatto, senza
nessun errore. Questi test difendono l'ordine.
"""

import pytest

from prompts.system_prompt import (
    blocchi_system,
    build_system_prompt,
    parte_stabile,
    parte_variabile,
)


def _sessione(**extra) -> dict:
    base = {"stato_flusso": "scelta_slot", "dati_temp": {}}
    base.update(extra)
    return base


# ------------------------------------------------- la parte stabile è stabile


def test_la_parte_stabile_non_cambia_al_cambiare_della_conversazione():
    """È tutto il punto: se cambiasse, la cache si invaliderebbe ogni volta."""
    vuota = _sessione()
    piena = _sessione(
        stato_flusso="confermato",
        dati_temp={
            "servizio": "Taglio + Barba",
            "giorno": "2026-08-11",
            "parrucchiere": "Andrea",
            "slot": "2026-08-11T16:00",
            "nome": "Mario",
            "cognome": "Rossi",
            "email": "mario@example.it",
            "telefono": "393331234567",
        },
        cliente_conosciuto=True,
        ultimo_operatore="Francesco",
    )

    assert blocchi_system(vuota)[0] == blocchi_system(piena)[0]


def test_nessun_dato_del_cliente_finisce_nella_parte_stabile():
    """Anche dal sito, dove il telefono si raccoglie a metà conversazione."""
    # Un nome che nel prompt non compare in nessun esempio: "Mario" c'è già,
    # dentro la regola sui trattini, e cercarlo darebbe un falso allarme.
    sessione = _sessione(
        dati_temp={"nome": "Ludovica", "telefono": "393331234567"},
        cliente_conosciuto=True,
    )

    stabile = blocchi_system(sessione, canale="web")[0]["text"]

    assert "Ludovica" not in stabile
    assert "393331234567" not in stabile
    assert "CONOSCIAMO" not in stabile


def test_il_telefono_raccolto_compare_solo_dal_sito():
    """Su WhatsApp è il mittente: scriverlo inviterebbe a chiederlo."""
    sessione = _sessione(dati_temp={"telefono": "393331234567"})

    assert "Telefono:" in parte_variabile(sessione, "web")
    assert "Telefono:" not in parte_variabile(sessione, "whatsapp")


# --------------------------------------------------------------- l'ordine


def test_lo_stato_della_conversazione_sta_in_fondo():
    prompt = build_system_prompt(_sessione())

    assert prompt.rindex("DATI GIÀ RACCOLTI") > prompt.rindex("AZIONI SPECIALI")
    assert prompt.rindex("FASE CORRENTE") > prompt.rindex("COME PARLI")


def test_le_due_parti_ricompongono_il_prompt_intero():
    """Nessun pezzo perso e nessuno duplicato nel passaggio a blocchi."""
    sessione = _sessione(cliente_conosciuto=True, ultimo_operatore="Andrea")
    blocchi = blocchi_system(sessione)

    assert blocchi[0]["text"] + blocchi[1]["text"] == build_system_prompt(sessione)


def test_il_prompt_non_rimanda_piu_a_dati_scritti_qui_sopra():
    """Erano sopra; adesso sono in fondo, e il rimando sarebbe falso."""
    prompt = build_system_prompt(_sessione())

    assert "qui sopra in DATI GIÀ RACCOLTI" not in prompt


# ---------------------------------------------------------- il segnaposto


def test_il_segnaposto_sta_sulla_parte_stabile_e_solo_lì():
    blocchi = blocchi_system(_sessione())

    assert len(blocchi) == 2
    assert blocchi[0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in blocchi[1]


def test_la_parte_stabile_supera_la_soglia_minima_della_cache():
    """Sotto i 1024 token Sonnet non cachea, in silenzio e senza errori.

    Qui si contano i caratteri, non i token: quattro caratteri per token è una
    stima prudente, e serve solo ad accorgersi se il prompt si accorciasse
    tanto da avvicinarsi alla soglia.
    """
    caratteri = len(parte_stabile())

    assert caratteri > 1024 * 4 * 1.5, (
        f"la parte stabile è scesa a {caratteri} caratteri: verifica con "
        "count_tokens che superi ancora i 1024 token"
    )


@pytest.mark.parametrize("canale", ["whatsapp", "web"])
def test_la_parte_variabile_resta_piccola(canale):
    """È l'unica che si ripaga per intero a ogni messaggio."""
    assert len(parte_variabile(_sessione(), canale)) < 1200
