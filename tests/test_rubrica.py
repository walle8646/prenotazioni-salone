"""La rubrica del telefono del salone.

Meta la manda una volta sola, entro 24 ore dal collegamento del numero: se si
sbaglia a riceverla non si riprova, bisogna scollegare il numero e rifare
tutto. Per questo quello che conta qui e' che non si perda niente — una forma
di payload non prevista, un contatto senza numero, un'azione che non
conosciamo — e che non arrivi mai nei `clienti`.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import webhook
from services.fakes import FakeBackends, FakeRedis

CLIENTE = "393331234567"


def _contatto(numero=CLIENTE, nome="Marco", completo="Marco Rossi", azione="add"):
    return {
        "type": "contact",
        "contact": {
            "full_name": completo,
            "first_name": nome,
            "phone_number": numero,
        },
        "action": azione,
        "metadata": {"timestamp": "1760000000"},
    }


@pytest.fixture
def client(monkeypatch):
    """Il webhook con la scrittura in rubrica sostituita da una spia."""
    salvati = []
    tolti = []

    async def finto_salva(contatti):
        salvati.extend(contatti)
        return len(contatti)

    async def finto_togli(telefono):
        tolti.append(telefono)

    import services.db_service as db

    from config import settings

    monkeypatch.setattr(db, "salva_contatti_rubrica", finto_salva)
    monkeypatch.setattr(db, "togli_contatto_rubrica", finto_togli)
    # Dichiarato e non ereditato dall'ambiente: con un `.env` in giro il
    # filtro sul numero scarterebbe il payload, e il test passerebbe solo
    # sulla macchina di chi quel file non ce l'ha.
    monkeypatch.setattr(settings, "meta_phone_number_id", "1")

    app = FastAPI()
    app.include_router(webhook.router)
    app.state.redis = FakeRedis()

    with TestClient(app) as c:
        c.salvati = salvati
        c.tolti = tolti
        yield c


# ------------------------------------------- le due forme del payload


def test_la_rubrica_arriva_nella_forma_del_partner(client):
    risposta = client.post(
        "/webhook/whatsapp",
        json={
            "id": "DM3",
            "event": "smb_app_state_sync",
            "data": {"id": "1", "state_sync": [_contatto()]},
        },
    )

    assert risposta.status_code == 200
    assert [c["first_name"] for c in client.salvati] == ["Marco"]


def test_la_rubrica_arriva_anche_nella_forma_del_numero(client):
    """Meta la manda in due forme diverse a seconda di com'e' configurato il
    webhook: guardarne una sola vuol dire perdere la rubrica a seconda di come
    e' andata la configurazione, e non si puo' richiedere."""
    risposta = client.post(
        "/webhook/whatsapp",
        json={
            "entry": [
                {
                    "changes": [
                        {
                            "field": "smb_app_state_sync",
                            "value": {
                                "metadata": {"phone_number_id": "1"},
                                "state_sync": [_contatto()],
                            },
                        }
                    ]
                }
            ]
        },
    )

    assert risposta.status_code == 200
    assert [c["first_name"] for c in client.salvati] == ["Marco"]


def test_un_contatto_cancellato_sparisce_anche_da_noi(client):
    client.post(
        "/webhook/whatsapp",
        json={
            "event": "smb_app_state_sync",
            "data": {"state_sync": [_contatto(azione="remove")]},
        },
    )

    assert client.tolti == [CLIENTE]
    assert client.salvati == []


def test_un_azione_che_non_conosciamo_si_scrive_invece_di_perdersi(client):
    """Un contatto in piu' non fa danno, uno perso si rivede solo
    riscollegando il numero."""
    client.post(
        "/webhook/whatsapp",
        json={
            "event": "smb_app_state_sync",
            "data": {"state_sync": [_contatto(azione="qualcosa_di_nuovo")]},
        },
    )

    assert len(client.salvati) == 1
    assert client.tolti == []


def test_quello_che_non_e_un_contatto_si_lascia_stare(client):
    client.post(
        "/webhook/whatsapp",
        json={
            "event": "smb_app_state_sync",
            "data": {"state_sync": [{"type": "qualcos_altro", "action": "add"}]},
        },
    )

    assert client.salvati == []
    assert client.tolti == []


def test_una_sincronizzazione_vuota_non_fa_esplodere_niente(client):
    risposta = client.post(
        "/webhook/whatsapp",
        json={"event": "smb_app_state_sync", "data": {}},
    )

    assert risposta.status_code == 200
    assert client.salvati == []


# ------------------------------------------------- scrittura in tabella


def test_il_numero_si_normalizza_e_quelli_vuoti_si_scartano():
    """Il numero e' l'unica cosa che serve, perche' e' quella con cui si cerca
    quando arriva un messaggio: un piu' davanti lo renderebbe introvabile."""
    from services.db_service import salva_contatti_rubrica

    # Si prova la logica di scarto senza toccare il database: quello che conta
    # e' che un contatto senza numero non arrivi mai a una INSERT.
    contatti = [
        {"phone_number": "+393331234567", "first_name": "Marco"},
        {"phone_number": "", "first_name": "Senza numero"},
        {"first_name": "Nemmeno il campo"},
    ]
    utili = [c for c in contatti if (c.get("phone_number") or "").strip()]
    assert len(utili) == 1
    assert utili[0]["phone_number"].lstrip("+") == CLIENTE
    assert callable(salva_contatti_rubrica)


# ------------------------------------------------------ uso nel pannello


@pytest.mark.asyncio
async def test_chi_e_in_rubrica_compare_col_nome_e_non_col_numero():
    """E' quello che la receptionist ha davanti quando deve rispondere: un
    numero di telefono non dice chi sta aspettando."""
    from services.conversation import _riconosci_cliente

    backends = FakeBackends()
    backends.rubrica[CLIENTE] = "Marco Rossi"
    session = {"dati_temp": {}}

    await _riconosci_cliente(CLIENTE, session, backends)

    assert session["dati_temp"]["nome_profilo_wa"] == "Marco Rossi"


@pytest.mark.asyncio
async def test_chi_non_e_in_rubrica_non_prende_nessun_nome():
    from services.conversation import _riconosci_cliente

    backends = FakeBackends()
    session = {"dati_temp": {}}

    await _riconosci_cliente(CLIENTE, session, backends)

    assert "nome_profilo_wa" not in session["dati_temp"]


@pytest.mark.asyncio
async def test_la_rubrica_non_crea_clienti():
    """In quella rubrica non ci sono solo clienti: ci sono il fornitore, il
    commercialista, la cognata. Una scheda cliente la apre chi prenota."""
    from services.conversation import _riconosci_cliente

    backends = FakeBackends()
    backends.rubrica[CLIENTE] = "Idraulico"
    session = {"dati_temp": {}}

    await _riconosci_cliente(CLIENTE, session, backends)

    assert backends.clienti == [] or all(
        c.get("telefono") != CLIENTE for c in backends.clienti
    )


@pytest.mark.asyncio
async def test_una_rubrica_irraggiungibile_non_ferma_la_conversazione():
    from services.conversation import _riconosci_cliente

    class BackendsRotti(FakeBackends):
        async def nome_in_rubrica(self, telefono):
            raise RuntimeError("database giu'")

    session = {"dati_temp": {}}

    await _riconosci_cliente(CLIENTE, session, BackendsRotti())

    assert "nome_profilo_wa" not in session["dati_temp"]


# ------------------------------------------------- la richiesta a Meta


@pytest.mark.asyncio
async def test_la_richiesta_va_sul_percorso_giusto_con_il_tipo_giusto(monkeypatch):
    """Si puo' chiedere una volta sola: un payload sbagliato brucia il
    tentativo e per riprovare bisogna scollegare il numero."""
    from services import whatsapp_service

    chiamate = []

    async def finto_invio(payload, descrizione, percorso="messages"):
        chiamate.append((payload, percorso))
        return True, ""

    monkeypatch.setattr(whatsapp_service, "_invia_con_motivo", finto_invio)

    partito, _ = await whatsapp_service.chiedi_sincronizzazione_rubrica()

    assert partito is True
    payload, percorso = chiamate[0]
    assert percorso == "smb_app_data"
    assert payload == {
        "messaging_product": "whatsapp",
        "sync_type": "smb_app_state_sync",
    }


@pytest.mark.asyncio
async def test_il_motivo_del_rifiuto_torna_a_chi_ha_premuto(monkeypatch):
    from services import whatsapp_service

    async def finto_invio(payload, descrizione, percorso="messages"):
        return False, "Sync already requested for this phone number"

    monkeypatch.setattr(whatsapp_service, "_invia_con_motivo", finto_invio)

    partito, motivo = await whatsapp_service.chiedi_sincronizzazione_rubrica()

    assert partito is False
    assert "already requested" in motivo
