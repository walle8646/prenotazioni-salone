"""Test su chi prenota per un'altra persona: i figli, un genitore.

Un contatto solo copre fino a quattro persone. Qui si sbaglia su due cose, e
una delle due è grave. La prima è il conto: se "un appuntamento per volta"
restasse legato al contatto invece che alla persona, chi prenota per il figlio
non potrebbe più prenotare per sé. La seconda è l'identità: il nome della
persona arriva dal modello, e se non fosse confinato alla famiglia di chi
scrive basterebbe scriverne uno per prenotare — o disdire — a nome di un altro.
"""

import pytest

from services.conversation import handle_incoming_message
from services.fakes import ScriptedClaude
from services.persone import (
    MASSIMO_FAMILIARI,
    e_un_telefono,
    posti_liberi,
    segnaposto,
    stessa_persona,
)

from .conftest import prossimo_giorno_aperto

GIORNO = prossimo_giorno_aperto()
TELEFONO = "393331234567"


# --------------------------------------------------------------- le regole


def test_il_segnaposto_non_e_un_numero_da_chiamare():
    """Chi non ha un telefono suo ne ha uno finto in colonna, perché la
    colonna è obbligatoria e unica. Mostrato a qualcuno sembrerebbe un numero,
    e chi lo compone non trova nessuno."""
    assert e_un_telefono("393331234567") is True
    assert e_un_telefono(segnaposto(7, 1)) is False
    assert e_un_telefono("web_4f1c9a") is False
    assert e_un_telefono("salone:2026-09-22T10:00:MarioRossi") is False
    assert e_un_telefono("") is False
    assert e_un_telefono(None) is False


def test_i_posti_sono_tre():
    assert posti_liberi(0) == MASSIMO_FAMILIARI
    assert posti_liberi(MASSIMO_FAMILIARI) == 0
    assert posti_liberi(MASSIMO_FAMILIARI + 1) == 0, "mai un numero negativo"


def test_lo_stesso_nome_scritto_in_due_modi_e_la_stessa_persona():
    """Il nome arriva da come l'ha scritto il cliente in chat: trattare "luca"
    e "Luca " come due figli brucerebbe un posto per niente."""
    assert stessa_persona("Luca", "luca ") is True
    assert stessa_persona(" LUCA", "Luca") is True
    assert stessa_persona("Luca", "Luigi") is False


# ------------------------------------------------------- prenotare per altri


def _prenota(**extra):
    """Le due mosse di una prenotazione: cerca gli orari, poi crea."""
    creazione = dict(
        action="CREA_APPUNTAMENTO",
        slot=f"{GIORNO}T09:00",
        parrucchiere="Francesco",
        servizi=["Taglio"],
        durata_min=30,
        nome="Valerio",
        cognome="Rossi",
        email="valerio@example.it",
    )
    creazione.update(extra)
    return ScriptedClaude(
        [
            ScriptedClaude.azione(action="CHECK_DISPONIBILITA", data=GIORNO, durata_min=30),
            "C'è posto alle 09:00.",
            ScriptedClaude.azione(**creazione),
            "Fatto!",
        ]
    )


async def _conversazione(mock_redis, canale, backends, claude, telefono=TELEFONO):
    for testo in ("vorrei un taglio", "sì"):
        await handle_incoming_message(
            redis=mock_redis,
            phone=telefono,
            text=testo,
            msg_type="text",
            channel=canale,
            backends=backends,
            claude=claude,
        )


@pytest.mark.asyncio
async def test_si_prenota_per_un_figlio_e_l_appuntamento_e_suo(
    mock_redis, canale, backends
):
    await _conversazione(mock_redis, canale, backends, _prenota(per="Luca"))

    assert len(backends.appuntamenti) == 1
    titolare = next(c for c in backends.clienti if c["telefono"] == TELEFONO)
    luca = next(c for c in backends.clienti if c.get("nome") == "Luca")

    assert luca["titolare_id"] == titolare["id"], "Luca fa capo a chi ha scritto"
    assert backends.appuntamenti[0]["client_id"] == luca["id"]
    assert not e_un_telefono(luca["telefono"]), "un figlio non ha un numero suo"
    assert luca["cognome"] == "Rossi", "senza cognome prende quello del titolare"


@pytest.mark.asyncio
async def test_sul_calendario_va_il_nome_di_chi_si_siede(
    mock_redis, canale, backends
):
    """È l'unica cosa che l'operatore ha davanti quando il cliente entra."""
    await _conversazione(mock_redis, canale, backends, _prenota(per="Luca"))

    evento = next(iter(backends.eventi.values()))
    assert "Luca" in evento["cliente"]
    assert "Prenotato da Valerio Rossi" in evento["descrizione"]


@pytest.mark.asyncio
async def test_la_conferma_dice_per_chi_e(mock_redis, canale, backends):
    """L'email arriva al padre, che ne ha una: se non dicesse per chi è,
    si presenterebbe lui il martedì mattina."""
    await _conversazione(mock_redis, canale, backends, _prenota(per="Luca"))

    email = backends.email_inviate[0]
    assert email["to"] == "valerio@example.it"
    assert email["per"] == "Luca"


@pytest.mark.asyncio
async def test_avere_un_appuntamento_non_impedisce_di_prenotare_per_il_figlio(
    mock_redis, canale, backends
):
    """È il punto di tutta la funzione: prima, prenotato il padre, il figlio
    non poteva più."""
    await _conversazione(mock_redis, canale, backends, _prenota())
    assert len(backends.appuntamenti) == 1

    await _conversazione(
        mock_redis, canale, backends, _prenota(per="Luca", slot=f"{GIORNO}T10:00")
    )

    assert len(backends.appuntamenti) == 2, "il secondo è di Luca, non del padre"
    intestatari = {a["client_id"] for a in backends.appuntamenti}
    assert len(intestatari) == 2


@pytest.mark.asyncio
async def test_lo_stesso_figlio_non_ne_ha_due(mock_redis, canale, backends):
    """La regola non sparisce, si sposta: vale per persona."""
    await _conversazione(mock_redis, canale, backends, _prenota(per="Luca"))
    await _conversazione(
        mock_redis, canale, backends, _prenota(per="Luca", slot=f"{GIORNO}T10:00")
    )

    assert len(backends.appuntamenti) == 1


@pytest.mark.asyncio
async def test_lo_stesso_nome_scritto_diverso_non_apre_una_seconda_scheda(
    mock_redis, canale, backends
):
    await _conversazione(mock_redis, canale, backends, _prenota(per="Luca"))
    await _conversazione(
        mock_redis, canale, backends, _prenota(per="luca ", slot=f"{GIORNO}T10:00")
    )

    quanti_luca = [c for c in backends.clienti if stessa_persona(c.get("nome"), "Luca")]
    assert len(quanti_luca) == 1


@pytest.mark.asyncio
async def test_oltre_tre_persone_non_si_va(mock_redis, canale, backends):
    """Il tetto sta nel codice: un contatto che ne dichiara quindici non è una
    famiglia, è un modo per prendersi mezza giornata di poltrone."""
    for indice, nome in enumerate(("Luca", "Sara", "Gino")):
        await _conversazione(
            mock_redis,
            canale,
            backends,
            _prenota(per=nome, slot=f"{GIORNO}T{9 + indice:02d}:00"),
        )
    assert len(backends.appuntamenti) == 3

    await _conversazione(
        mock_redis, canale, backends, _prenota(per="Quarto", slot=f"{GIORNO}T14:00")
    )

    assert len(backends.appuntamenti) == 3, "il quarto non entra"
    assert not [c for c in backends.clienti if c.get("nome") == "Quarto"]


@pytest.mark.asyncio
async def test_si_disdice_anche_l_appuntamento_di_un_figlio(
    mock_redis, canale, backends
):
    """Chi prenota per il figlio è l'unico che può disdirglielo: il figlio un
    telefono non ce l'ha. Senza, resterebbe in agenda per sempre."""
    await _conversazione(mock_redis, canale, backends, _prenota(per="Luca"))
    app_id = backends.appuntamenti[0]["id"]

    claude = ScriptedClaude(
        [
            ScriptedClaude.azione(action="CANCELLA_APPUNTAMENTO", app_id=app_id),
            "Disdetto.",
        ]
    )
    await handle_incoming_message(
        redis=mock_redis,
        phone=TELEFONO,
        text="disdici quello di Luca",
        msg_type="text",
        channel=canale,
        backends=backends,
        claude=claude,
    )

    assert backends.appuntamenti[0]["stato"] == "Cancellato"


@pytest.mark.asyncio
async def test_lo_storico_dice_di_chi_e_ogni_appuntamento(
    mock_redis, canale, backends
):
    """Tre tagli nello stesso pomeriggio senza sapere di chi non servono a niente."""
    await _conversazione(mock_redis, canale, backends, _prenota(per="Luca"))

    trovato = await backends.get_appuntamenti_per_telefono(TELEFONO)

    assert [a["per"] for a in trovato["appuntamenti"]] == ["Luca Rossi"]
    assert [f["nome"] for f in trovato["familiari"]] == ["Luca"]


@pytest.mark.asyncio
async def test_dal_sito_non_verificato_i_familiari_non_si_elencano(backends):
    """Aggiungere una persona non rivela niente; riconoscerla direbbe a
    chiunque abbia indovinato un'email chi c'è dentro quella famiglia."""
    from services.conversation import _per_chi_si_prenota

    sessione = {"dati_temp": {}}
    persona, errore = await _per_chi_si_prenota(
        {"per": "Luca"},
        "web_4f1c9a",
        sessione,
        backends,
        nome="Valerio",
        email="valerio@example.it",
        telefono=None,
    )

    assert errore is None
    assert persona["nuova"] is True, "non si conferma che Luca esiste già"
    assert persona["cliente_id"] is None
