"""Test end-to-end del flusso di prenotazione, con Claude, calendario e DB finti.

Sono i test che rispondono alla domanda "il bot prenota davvero?" senza toccare
WhatsApp, Google o PostgreSQL.
"""

import pytest

from services.conversation import handle_incoming_message, handle_incoming_message_web
from services.fakes import ScriptedClaude

MARTEDI = "2026-05-19"  # giorno di apertura, usato in tutti i test


@pytest.mark.asyncio
async def test_prenotazione_completa(mock_redis, canale, backends, cal_id_operatore):
    """Dal messaggio iniziale all'appuntamento salvato: verifica l'intera catena."""
    claude = ScriptedClaude(
        [
            ScriptedClaude.azione(
                action="CHECK_DISPONIBILITA",
                data=MARTEDI,
                parrucchiere=cal_id_operatore,
                durata_min=30,
            ),
            "Francesco è libero alle 09:00, ti va bene?",
            ScriptedClaude.azione(
                action="CREA_APPUNTAMENTO",
                slot=f"{MARTEDI}T09:00",
                parrucchiere="Francesco",
                parrucchiere_cal_id=cal_id_operatore,
                servizi=["Taglio"],
                durata_min=30,
                nome="Valerio",
                cognome="Rossi",
                email="valerio@example.it",
                richieste_spec="Corto ai lati",
            ),
            "Perfetto Valerio, ci vediamo martedì alle 09:00!",
        ]
    )

    await handle_incoming_message(
        redis=mock_redis,
        phone="393331234567",
        text="vorrei un taglio da Francesco martedì",
        msg_type="text",
        channel=canale,
        backends=backends,
        claude=claude,
    )
    await handle_incoming_message(
        redis=mock_redis,
        phone="393331234567",
        text="sì va benissimo",
        msg_type="text",
        channel=canale,
        backends=backends,
        claude=claude,
    )

    # L'appuntamento è finito nel database
    assert len(backends.appuntamenti) == 1
    appuntamento = backends.appuntamenti[0]
    assert appuntamento["data_ora"] == f"{MARTEDI}T09:00"
    assert appuntamento["servizi"] == ["Taglio"]
    assert appuntamento["parrucchiere"] == "Francesco"
    assert appuntamento["richieste_spec"] == "Corto ai lati"
    assert appuntamento["prezzo"] == 13.50  # prezzo di listino salvato
    assert appuntamento["durata_min"] == 30

    # L'evento è finito sul calendario
    assert len(backends.eventi) == 1
    evento = next(iter(backends.eventi.values()))
    assert evento["cliente"] == "Valerio Rossi"
    assert "Corto ai lati" in evento["descrizione"]
    assert "13,50 €" in evento["descrizione"]

    # Il cliente è stato creato e l'email di conferma inviata
    assert backends.clienti[0]["telefono"] == "393331234567"
    assert backends.email_inviate[0]["to"] == "valerio@example.it"

    # E il cliente ha ricevuto la conferma in chat
    assert "ci vediamo martedì" in canale.ultimo()["text"]


@pytest.mark.asyncio
async def test_slot_occupato_non_viene_proposto(mock_redis, canale, backends, cal_id_operatore):
    """Dopo una prenotazione, lo stesso orario non risulta più libero per quel parrucchiere."""
    backends.occupa(cal_id_operatore, f"{MARTEDI}T09:00", 30)

    slots = await backends.check_availability(MARTEDI, cal_id_operatore, 30)
    orari = [s["slot"] for s in slots]

    assert f"{MARTEDI}T09:00" not in orari
    assert f"{MARTEDI}T09:30" in orari


@pytest.mark.asyncio
async def test_servizio_da_60_minuti_richiede_due_slot(backends, cal_id_operatore):
    """Con 60 minuti servono due slot consecutivi liberi."""
    # Occupo le 09:30: le 09:00 non possono più ospitare un servizio da un'ora
    backends.occupa(cal_id_operatore, f"{MARTEDI}T09:30", 30)

    slots_30 = [s["slot"] for s in await backends.check_availability(MARTEDI, cal_id_operatore, 30)]
    slots_60 = [s["slot"] for s in await backends.check_availability(MARTEDI, cal_id_operatore, 60)]

    assert f"{MARTEDI}T09:00" in slots_30
    assert f"{MARTEDI}T09:00" not in slots_60
    assert f"{MARTEDI}T10:00" in slots_60


@pytest.mark.asyncio
async def test_giorno_chiuso_non_ha_slot(backends):
    """Domenica e lunedì il salone è chiuso."""
    assert await backends.check_availability("2026-05-24", None, 30) == []  # domenica
    assert await backends.check_availability("2026-05-18", None, 30) == []  # lunedì


@pytest.mark.asyncio
async def test_chiusura_straordinaria(backends):
    """Una chiusura straordinaria svuota la disponibilità di quel giorno."""
    assert await backends.check_availability(MARTEDI, None, 30)
    backends.chiudi_giorno(MARTEDI)
    assert await backends.check_availability(MARTEDI, None, 30) == []


@pytest.mark.asyncio
async def test_senza_preferenza_cerca_tutti_i_parrucchieri(backends):
    """Se il cliente non ha preferenze, la ricerca copre tutti i calendari."""
    slots = await backends.check_availability(MARTEDI, None, 30)
    nomi = {s["parrucchiere"] for s in slots}
    assert len(nomi) == len(backends.parrucchieri)


@pytest.mark.asyncio
async def test_cancellazione_libera_lo_slot(mock_redis, canale, backends, cal_id_operatore):
    """Cancellare un appuntamento rimette in circolo l'orario."""
    event_id = await backends.create_event(
        slot=f"{MARTEDI}T09:00",
        parrucchiere_cal_id=cal_id_operatore,
        servizi=["Taglio"],
        durata=30,
        cliente_nome="Valerio",
    )
    await backends.create_appointment(
        client_id=1,
        data_ora=f"{MARTEDI}T09:00",
        servizi=["Taglio"],
        parrucchiere="Francesco",
        gcal_event_id=event_id,
    )
    orari = [s["slot"] for s in await backends.check_availability(MARTEDI, cal_id_operatore, 30)]
    assert f"{MARTEDI}T09:00" not in orari

    claude = ScriptedClaude(
        [
            ScriptedClaude.azione(
                action="CANCELLA_APPUNTAMENTO",
                app_id=1,
                gcal_event_id=event_id,
                parrucchiere_cal_id=cal_id_operatore,
            ),
            "Fatto, ho cancellato il tuo appuntamento.",
        ]
    )
    await handle_incoming_message(
        redis=mock_redis,
        phone="393331234567",
        text="devo disdire",
        msg_type="text",
        channel=canale,
        backends=backends,
        claude=claude,
    )

    assert backends.appuntamenti[0]["stato"] == "Cancellato"
    orari = [s["slot"] for s in await backends.check_availability(MARTEDI, cal_id_operatore, 30)]
    assert f"{MARTEDI}T09:00" in orari


@pytest.mark.asyncio
async def test_chat_web_restituisce_testo_e_opzioni(mock_redis, backends):
    """Il widget del sito riceve un dict pronto da mandare al browser."""
    claude = ScriptedClaude(["Che servizio desideri?\n- Taglio\n- Barba"])

    risposta = await handle_incoming_message_web(
        redis=mock_redis,
        session_id="web_test123",
        text="ciao",
        backends=backends,
        claude=claude,
    )

    assert risposta["text"] == "Che servizio desideri?"
    assert [o["title"] for o in risposta["options"]] == ["Taglio", "Barba"]


@pytest.mark.asyncio
async def test_chat_web_mostra_anche_il_testo_prima_dell_azione(mock_redis, backends):
    """Il testo che Claude scrive prima di un'azione non deve andare perso."""
    claude = ScriptedClaude(
        [
            "Controllo subito!\n"
            + ScriptedClaude.azione(action="CHECK_DISPONIBILITA", data=MARTEDI, durata_min=30),
            "Ci sono posti liberi martedì mattina.",
        ]
    )

    risposta = await handle_incoming_message_web(
        redis=mock_redis,
        session_id="web_test123",
        text="martedì avete posto?",
        backends=backends,
        claude=claude,
    )

    assert "Controllo subito!" in risposta["text"]
    assert "posti liberi" in risposta["text"]


@pytest.mark.asyncio
async def test_foto_allegata_alla_prenotazione(mock_redis, canale, backends, cal_id_operatore):
    """Una foto inviata dal cliente finisce sull'appuntamento."""
    claude = ScriptedClaude(
        [
            ScriptedClaude.azione(
                action="CREA_APPUNTAMENTO",
                slot=f"{MARTEDI}T10:00",
                parrucchiere="Francesco",
                parrucchiere_cal_id=cal_id_operatore,
                servizi=["Taglio"],
                durata_min=30,
                nome="Valerio",
            ),
            "Ricevuta la foto, appuntamento confermato!",
        ]
    )

    await handle_incoming_message(
        redis=mock_redis,
        phone="393331234567",
        text="vorrei questo taglio martedì alle 10",
        msg_type="image",
        media_id="media-123",
        channel=canale,
        backends=backends,
        claude=claude,
    )

    # Nel database finisce l'indirizzo del file, non i byte dell'immagine
    foto = backends.appuntamenti[0]["foto_url"]
    assert isinstance(foto, str)
    assert foto.startswith("/static/foto/")
    assert backends.foto_salvate == ["cliente1"]


@pytest.mark.asyncio
async def test_prezzo_e_durata_del_colore(mock_redis, canale, backends, cal_id_operatore):
    """Un servizio lungo blocca due ore e salva 50 €, anche se Claude sbaglia i conti."""
    claude = ScriptedClaude(
        [
            ScriptedClaude.azione(
                action="CREA_APPUNTAMENTO",
                slot=f"{MARTEDI}T09:00",
                parrucchiere="Francesco",
                parrucchiere_cal_id=cal_id_operatore,
                servizi=["Colore + Taglio + Trattamento capello"],
                durata_min=30,  # sbagliato di proposito: deve vincere il catalogo
                nome="Valerio",
            ),
            "Ci vediamo martedì!",
        ]
    )

    await handle_incoming_message(
        redis=mock_redis,
        phone="393331234567",
        text="vorrei fare il colore martedì alle 9",
        msg_type="text",
        channel=canale,
        backends=backends,
        claude=claude,
    )

    appuntamento = backends.appuntamenti[0]
    assert appuntamento["durata_min"] == 120
    assert appuntamento["prezzo"] == 50.00
    # e le due ore risultano davvero occupate sul calendario
    liberi = [s["slot"] for s in await backends.check_availability(MARTEDI, cal_id_operatore, 30)]
    assert f"{MARTEDI}T09:00" not in liberi
    assert f"{MARTEDI}T10:30" not in liberi
    assert f"{MARTEDI}T11:00" in liberi


@pytest.mark.asyncio
async def test_cliente_dal_sito_e_marcato_come_web(mock_redis, backends, cal_id_operatore):
    """Chi prenota dal sito non deve finire in anagrafica come contatto WhatsApp."""
    claude = ScriptedClaude(
        [
            ScriptedClaude.azione(
                action="CREA_APPUNTAMENTO",
                slot=f"{MARTEDI}T09:00",
                parrucchiere="Francesco",
                parrucchiere_cal_id=cal_id_operatore,
                servizi=["Taglio"],
                nome="Valerio",
                email="valerio@example.it",
            ),
            "Confermato!",
        ]
    )

    await handle_incoming_message_web(
        redis=mock_redis,
        session_id="web_abc123",
        text="prenoto martedì alle 9",
        backends=backends,
        claude=claude,
    )

    assert backends.clienti[0]["canale"] == "web"


@pytest.mark.asyncio
async def test_cliente_web_riconosciuto_dalla_email(backends):
    """Sessione diversa ma stessa email: è la stessa persona, non un doppione."""
    primo = await backends.find_or_create_client(
        phone="web_sessione1", email="valerio@example.it", nome="Valerio", canale="web"
    )
    secondo = await backends.find_or_create_client(
        phone="web_sessione2", email="valerio@example.it", canale="web"
    )

    assert primo["is_new"] is True
    assert secondo["is_new"] is False
    assert secondo["id"] == primo["id"]
    assert len(backends.clienti) == 1
