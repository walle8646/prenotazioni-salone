"""Test sul passaggio della conversazione a una persona.

Il rischio vero di questa funzione non è che non parta: è che parta quando non
deve. In un salone "operatore" vuol dire parrucchiere, e scambiare "vorrei
parlare con Simone" per una richiesta di aiuto significa zittire il bot in
mezzo a una prenotazione che stava andando bene.
"""

from datetime import datetime, timedelta

import pytest

from services.conversation import handle_incoming_message
from services.fakes import ScriptedClaude
from services.operatore_umano import (
    MESSAGGIO_PASSAGGIO,
    finestra_aperta,
    minuti_rimasti,
    passaggio_dimenticato,
    storico_da_salvare,
    vuole_una_persona,
)

NUMERO = "393331234567"
OPERATORI = ["Simone Big", "Simone Jr", "Francesco", "Andrea", "Giava", "Bario"]


# ------------------------------------------------------- riconoscere la richiesta


@pytest.mark.parametrize(
    "frase",
    [
        "vorrei parlare con una persona",
        "posso parlare con qualcuno?",
        "mi passi un umano per favore",
        "voglio parlare con il titolare",
        "non voglio parlare con un bot",
        "sei un bot?",
        "basta con i messaggi automatici",
    ],
)
def test_chiede_una_persona(frase):
    assert vuole_una_persona(frase, OPERATORI) is True


@pytest.mark.parametrize(
    "frase",
    [
        # Qui "operatore" sono i parrucchieri: sta scegliendo, non chiedendo aiuto.
        "vorrei parlare con Simone",
        "posso prenotare con Francesco?",
        "mi va bene qualsiasi operatore",
        "vorrei un taglio",
        "va bene giovedì alle 10",
        "",
        None,
    ],
)
def test_non_chiede_una_persona(frase):
    assert vuole_una_persona(frase, OPERATORI) is False


def test_il_nome_di_un_operatore_riporta_la_frase_al_suo_senso():
    """Con un nome di parrucchiere dentro, "qualcuno" torna a essere una scelta.

    Senza l'elenco degli operatori la stessa frase resta una richiesta di
    aiuto: è il motivo per cui l'elenco va passato e non tenuto qui dentro.
    """
    frase = "vorrei parlare con qualcuno, magari Andrea"
    assert vuole_una_persona(frase, OPERATORI) is False
    assert vuole_una_persona(frase, []) is True


# ------------------------------------------------------------- finestra 24 ore


def test_finestra_aperta_entro_le_24_ore():
    adesso = datetime(2026, 9, 5, 12, 0)
    assert finestra_aperta(adesso - timedelta(hours=23, minutes=59), adesso) is True


def test_finestra_chiusa_dopo_le_24_ore():
    adesso = datetime(2026, 9, 5, 12, 0)
    assert finestra_aperta(adesso - timedelta(hours=24, minutes=1), adesso) is False


def test_finestra_chiusa_se_non_ha_mai_scritto():
    assert finestra_aperta(None, datetime(2026, 9, 5, 12, 0)) is False


def test_quanto_manca_alla_chiusura():
    adesso = datetime(2026, 9, 5, 12, 0)
    assert minuti_rimasti(adesso - timedelta(hours=23), adesso) == 60
    assert minuti_rimasti(adesso - timedelta(hours=30), adesso) == 0


# ------------------------------------------------------- passaggi dimenticati


def test_passaggio_dimenticato_dopo_un_giorno_senza_risposta():
    adesso = datetime(2026, 9, 5, 12, 0)
    conversazione = {"aperta_il": adesso - timedelta(hours=25), "presa_il": None}
    assert passaggio_dimenticato(conversazione, adesso) is True


def test_passaggio_seguito_non_scade():
    """Conta l'ultima attività di chi risponde, non l'apertura."""
    adesso = datetime(2026, 9, 5, 12, 0)
    conversazione = {
        "aperta_il": adesso - timedelta(hours=40),
        "presa_il": adesso - timedelta(hours=1),
    }
    assert passaggio_dimenticato(conversazione, adesso) is False


# --------------------------------------------------------- storico da mostrare


def test_lo_storico_scarta_i_risultati_delle_azioni():
    """Chi risponde al cliente non deve leggere JSON di sistema."""
    history = [
        {"role": "user", "content": "vorrei un taglio"},
        {"role": "assistant", "content": '{"action": "CHECK_DISPONIBILITA"}'},
        {"role": "user", "content": '[SISTEMA] Risultato azione: {"slot": []}'},
        {"role": "assistant", "content": "Che giorno preferisci?"},
    ]
    assert storico_da_salvare(history) == [
        ("cliente", "vorrei un taglio"),
        ("bot", '{"action": "CHECK_DISPONIBILITA"}'),
        ("bot", "Che giorno preferisci?"),
    ]


# ------------------------------------------------------------- il motore intero


@pytest.mark.asyncio
async def test_chi_chiede_una_persona_apre_una_conversazione(
    mock_redis, backends, canale
):
    await handle_incoming_message(
        redis=mock_redis,
        phone=NUMERO,
        text="vorrei parlare con una persona",
        msg_type="text",
        channel=canale,
        backends=backends,
        claude=ScriptedClaude(["non dovrei essere chiamato"]),
    )

    assert len(backends.conversazioni_operatore) == 1
    conversazione = backends.conversazioni_operatore[0]
    assert conversazione["telefono"] == NUMERO
    assert conversazione["stato"] == "attesa"
    assert MESSAGGIO_PASSAGGIO in canale.testi


@pytest.mark.asyncio
async def test_il_salone_viene_avvisato(mock_redis, backends, canale):
    """Senza l'email la funzione esiste solo per chi apre il pannello."""
    await handle_incoming_message(
        redis=mock_redis,
        phone=NUMERO,
        text="posso parlare con qualcuno?",
        msg_type="text",
        channel=canale,
        backends=backends,
        claude=ScriptedClaude([]),
    )

    assert len(backends.email_handoff) == 1
    assert backends.email_handoff[0]["telefono"] == NUMERO


@pytest.mark.asyncio
async def test_dopo_il_passaggio_il_bot_tace(mock_redis, backends, canale):
    """Due risposte diverse alla stessa domanda sono peggio di una lenta."""
    claude = ScriptedClaude(["Ciao! Come posso aiutarti?"])
    await handle_incoming_message(
        redis=mock_redis, phone=NUMERO, text="voglio parlare con una persona",
        msg_type="text", channel=canale, backends=backends, claude=claude,
    )
    quanti_prima = len(canale.testi)

    await handle_incoming_message(
        redis=mock_redis, phone=NUMERO, text="allora? c'è nessuno?",
        msg_type="text", channel=canale, backends=backends, claude=claude,
    )

    assert len(canale.testi) == quanti_prima, "il bot ha risposto invece di tacere"
    assert claude.chiamate == [], "ha comunque chiamato il modello, e si paga"


@pytest.mark.asyncio
async def test_il_messaggio_successivo_finisce_nello_scambio(
    mock_redis, backends, canale
):
    """La receptionist deve leggere anche quello che è arrivato dopo."""
    await handle_incoming_message(
        redis=mock_redis, phone=NUMERO, text="mi passi una persona",
        msg_type="text", channel=canale, backends=backends,
        claude=ScriptedClaude([]),
    )
    await handle_incoming_message(
        redis=mock_redis, phone=NUMERO, text="è per il taglio di ieri",
        msg_type="text", channel=canale, backends=backends,
        claude=ScriptedClaude([]),
    )

    testi = [m["testo"] for m in backends.conversazioni_operatore[0]["messaggi"]]
    assert "è per il taglio di ieri" in testi


@pytest.mark.asyncio
async def test_insistere_non_apre_una_seconda_conversazione(
    mock_redis, backends, canale
):
    for _ in range(3):
        await handle_incoming_message(
            redis=mock_redis, phone=NUMERO, text="voglio parlare con una persona",
            msg_type="text", channel=canale, backends=backends,
            claude=ScriptedClaude([]),
        )
    assert len(backends.conversazioni_operatore) == 1


@pytest.mark.asyncio
async def test_ricominciare_restituisce_la_conversazione_al_bot(
    mock_redis, backends, canale
):
    """Se il cliente cambia idea non deve restare in coda ad aspettare."""
    await handle_incoming_message(
        redis=mock_redis, phone=NUMERO, text="voglio parlare con una persona",
        msg_type="text", channel=canale, backends=backends,
        claude=ScriptedClaude([]),
    )
    await handle_incoming_message(
        redis=mock_redis, phone=NUMERO, text="ricominciamo da capo",
        msg_type="text", channel=canale, backends=backends,
        claude=ScriptedClaude([]),
    )

    assert backends.conversazioni_operatore[0]["stato"] == "chiusa"

    claude = ScriptedClaude(["Eccomi, dimmi pure."])
    await handle_incoming_message(
        redis=mock_redis, phone=NUMERO, text="vorrei un taglio",
        msg_type="text", channel=canale, backends=backends, claude=claude,
    )
    assert "Eccomi, dimmi pure." in canale.testi


@pytest.mark.asyncio
async def test_un_passaggio_dimenticato_torna_al_bot(mock_redis, backends, canale):
    """Il bot muto è una scelta; il bot muto e nessun altro è un cliente perso."""
    await handle_incoming_message(
        redis=mock_redis, phone=NUMERO, text="voglio parlare con una persona",
        msg_type="text", channel=canale, backends=backends,
        claude=ScriptedClaude([]),
    )
    conversazione = backends.conversazioni_operatore[0]
    conversazione["aperta_il"] = datetime.now() - timedelta(hours=25)

    claude = ScriptedClaude(["Eccomi, come posso aiutarti?"])
    await handle_incoming_message(
        redis=mock_redis, phone=NUMERO, text="c'è nessuno?",
        msg_type="text", channel=canale, backends=backends, claude=claude,
    )

    assert conversazione["stato"] == "chiusa"
    assert "Eccomi, come posso aiutarti?" in canale.testi


@pytest.mark.asyncio
async def test_il_modello_puo_chiedere_il_passaggio(mock_redis, backends, canale):
    """L'azione esiste per i casi che nessuna espressione fissa può prevedere."""
    claude = ScriptedClaude(
        [ScriptedClaude.azione(action="PASSA_A_OPERATORE", motivo="reclamo sul colore")]
    )
    await handle_incoming_message(
        redis=mock_redis, phone=NUMERO, text="il colore mi ha rovinato i capelli",
        msg_type="text", channel=canale, backends=backends, claude=claude,
    )

    assert len(backends.conversazioni_operatore) == 1
    assert backends.conversazioni_operatore[0]["motivo"] == "reclamo sul colore"
    assert MESSAGGIO_PASSAGGIO in canale.testi


@pytest.mark.asyncio
async def test_dal_sito_non_si_passa_ma_si_risponde(mock_redis, backends):
    """Una pagina chiusa non si può richiamare: meglio dare il numero."""
    from services.conversation import handle_incoming_message_web

    risposta = await handle_incoming_message_web(
        redis=mock_redis,
        session_id="web_abc",
        text="voglio parlare con una persona",
        backends=backends,
        claude=ScriptedClaude([]),
    )

    assert backends.conversazioni_operatore == []
    assert "WhatsApp" in risposta["text"] or "telefonare" in risposta["text"]


@pytest.mark.asyncio
async def test_chi_risponde_lo_si_puo_sapere_senza_toccare_niente(
    mock_redis, backends, canale
):
    """Il webhook lo chiede prima di elaborare, e non deve avere effetti.

    Serve a decidere se mostrare "sta scrivendo": quei puntini promettono una
    risposta fra pochi secondi, e con la conversazione in mano al salone la
    promessa non la manteniamo.
    """
    from services.conversation import risponde_una_persona

    assert await risponde_una_persona(NUMERO, backends) is False

    await handle_incoming_message(
        redis=mock_redis, phone=NUMERO, text="voglio parlare con una persona",
        msg_type="text", channel=canale, backends=backends,
        claude=ScriptedClaude([]),
    )

    prima = len(backends.conversazioni_operatore[0]["messaggi"])
    assert await risponde_una_persona(NUMERO, backends) is True
    # Sola lettura: chiederlo non registra niente e non chiude niente.
    assert len(backends.conversazioni_operatore[0]["messaggi"]) == prima
    assert backends.conversazioni_operatore[0]["stato"] == "attesa"


@pytest.mark.asyncio
async def test_su_un_passaggio_dimenticato_i_puntini_tornano_veri(
    mock_redis, backends, canale
):
    """Lì a rispondere sarà di nuovo il bot, quindi l'indicatore dice il vero."""
    from services.conversation import risponde_una_persona

    await handle_incoming_message(
        redis=mock_redis, phone=NUMERO, text="voglio parlare con una persona",
        msg_type="text", channel=canale, backends=backends,
        claude=ScriptedClaude([]),
    )
    backends.conversazioni_operatore[0]["aperta_il"] = datetime.now() - timedelta(
        hours=25
    )

    assert await risponde_una_persona(NUMERO, backends) is False
