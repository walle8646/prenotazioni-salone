"""La pagina da cui si collega il numero del salone alla Cloud API.

Si usa una volta sola, col telefono del salone in mano e una persona che
aspetta: quello che va storto qui va detto subito e per intero, perche' non
c'e' tempo per andare a leggere i log — e un codice richiesto troppe volte
blocca la procedura per mezza giornata.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import admin, collegamento


@pytest.fixture
def client(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "meta_app_id", "111")
    monkeypatch.setattr(settings, "meta_app_secret", "segreto")
    monkeypatch.setattr(settings, "meta_es_config_id", "222")

    app = FastAPI()
    app.include_router(collegamento.router)
    app.dependency_overrides[admin.utente_del_pannello] = lambda: "nadia"
    return TestClient(app)


# ------------------------------------------------------------- la pagina


def test_la_pagina_dice_di_fermarsi_se_non_vede_la_scelta_giusta(client):
    """La strada sbagliata registra il numero e lo toglie dal telefono del
    salone: e' l'unico errore di stasera che non si rimedia."""
    pagina = client.get("/admin/collega-whatsapp").text

    assert "collegare un account WhatsApp Business che esiste gia'" in pagina
    assert "toglie dal telefono" in pagina


def test_la_pagina_porta_la_configurazione_dell_app(client):
    pagina = client.get("/admin/collega-whatsapp").text

    assert 'var APP_ID = "111";' in pagina
    assert 'var CONFIG_ID = "222";' in pagina
    assert 'var FEATURE_TYPE = "whatsapp_business_app_onboarding";' in pagina


def test_il_nome_della_variante_si_cambia_dalla_url(client):
    """Meta lo ha gia' rinominato una volta: scoprirlo davanti al cliente non
    deve voler dire aspettare un deploy."""
    pagina = client.get("/admin/collega-whatsapp?feature=coexistence").text
    assert 'var FEATURE_TYPE = "coexistence";' in pagina

    # Vuoto vuol dire non mandarlo affatto, che e' una delle varianti da provare.
    pagina = client.get("/admin/collega-whatsapp?feature=").text
    assert 'var FEATURE_TYPE = "";' in pagina


def test_senza_credenziali_la_pagina_lo_dice_e_non_si_parte(monkeypatch):
    """Un bottone che apre un flusso che non puo' funzionare fa perdere il
    turno: il codice si puo' chiedere poche volte."""
    from config import settings

    monkeypatch.setattr(settings, "meta_app_id", "")
    monkeypatch.setattr(settings, "meta_app_secret", "")
    monkeypatch.setattr(settings, "meta_es_config_id", "")

    app = FastAPI()
    app.include_router(collegamento.router)
    app.dependency_overrides[admin.utente_del_pannello] = lambda: "nadia"

    pagina = TestClient(app).get("/admin/collega-whatsapp").text

    assert "META_APP_SECRET" in pagina
    assert "disabled" in pagina


# --------------------------------------------------- lo scambio del codice


def _finte_risposte(monkeypatch, esiti: dict):
    """Sostituisce le chiamate a Graph con risposte decise qui.

    La chiave e' un pezzo della URL, cosi' un test puo' far fallire solo uno
    dei passaggi.
    """
    chiamate = []

    async def finta(metodo, url, **argomenti):
        chiamate.append((metodo, url))
        for pezzo, esito in esiti.items():
            if pezzo in url:
                return esito
        return False, f"nessuna risposta prevista per {url}"

    monkeypatch.setattr(collegamento, "_chiedi", finta)
    return chiamate


def test_lo_scambio_restituisce_token_e_id_del_numero(client, monkeypatch):
    chiamate = _finte_risposte(
        monkeypatch,
        {
            "oauth/access_token": (True, {"access_token": "EAAG-token"}),
            "subscribed_apps": (
                True,
                {"data": [{"whatsapp_business_api_data": {"name": "Qubi Prenotazioni"}}]},
            ),
            "phone_numbers": (
                True,
                {
                    "data": [
                        {
                            "id": "555000111",
                            "display_phone_number": "+39 351 234 5678",
                            "platform_type": "SMB_APP",
                        }
                    ]
                },
            ),
        },
    )

    risposta = client.post(
        "/admin/collega-whatsapp/scambia",
        json={"code": "AQB-codice", "waba_id": "999", "phone_number_id": "dal-browser"},
    )

    dati = risposta.json()
    assert dati["ok"] is True
    assert dati["token"] == "EAAG-token"
    # L'id del numero si legge da Meta: l'id del numero e quello dell'account
    # si somigliano, e con quello sbagliato ogni invio viene rifiutato mentre
    # tutto sembra configurato.
    assert dati["numeri"][0]["id"] == "555000111"
    assert dati["app_iscritte"] == ["Qubi Prenotazioni"]
    assert "avvisi" not in dati

    # L'iscrizione si scrive e poi si rilegge: l'unico modo di sapere che e'
    # andata e' vedersi nell'elenco.
    assert ("POST", "https://graph.facebook.com/v23.0/999/subscribed_apps") in chiamate
    assert ("GET", "https://graph.facebook.com/v23.0/999/subscribed_apps") in chiamate
    # Il numero non si registra: e' gia' registrato e deve restare sull'app.
    assert not any("register" in url for _, url in chiamate)


def test_il_motivo_del_rifiuto_di_meta_arriva_a_chi_sta_guardando(client, monkeypatch):
    _finte_risposte(
        monkeypatch,
        {"oauth/access_token": (False, "Invalid verification code format — codice 100")},
    )

    risposta = client.post(
        "/admin/collega-whatsapp/scambia", json={"code": "scaduto", "waba_id": "999"}
    )

    assert risposta.status_code == 400
    assert "Invalid verification code format" in risposta.json()["errore"]


def test_un_iscrizione_mancata_non_fa_perdere_il_token(client, monkeypatch):
    """Il token e' la cosa che non si riottiene senza rifare tutto il flusso:
    l'iscrizione invece si riprova quando si vuole."""
    _finte_risposte(
        monkeypatch,
        {
            "oauth/access_token": (True, {"access_token": "EAAG-token"}),
            "subscribed_apps": (False, "Application does not have permission"),
            "phone_numbers": (True, {"data": []}),
        },
    )

    dati = client.post(
        "/admin/collega-whatsapp/scambia", json={"code": "AQB", "waba_id": "999"}
    ).json()

    assert dati["ok"] is True
    assert dati["token"] == "EAAG-token"
    assert any("Application does not have permission" in a for a in dati["avvisi"])


def test_senza_codice_non_si_chiama_meta(client, monkeypatch):
    chiamate = _finte_risposte(monkeypatch, {})

    risposta = client.post("/admin/collega-whatsapp/scambia", json={"waba_id": "999"})

    assert risposta.status_code == 400
    assert chiamate == []


def test_senza_credenziali_lo_scambio_si_rifiuta(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "meta_app_secret", "")

    app = FastAPI()
    app.include_router(collegamento.router)
    app.dependency_overrides[admin.utente_del_pannello] = lambda: "nadia"

    risposta = TestClient(app).post(
        "/admin/collega-whatsapp/scambia", json={"code": "AQB"}
    )

    assert risposta.status_code == 400
    assert "META_APP_SECRET" in risposta.json()["errore"]


def test_la_pagina_e_lo_scambio_stanno_dietro_la_password(monkeypatch):
    """La pagina mostra il token, cioe' la chiave per scrivere a nome del
    salone: senza sessione si torna al login."""
    from config import settings

    monkeypatch.setattr(settings, "secret_key", "una-chiave-vera")
    monkeypatch.setattr(settings, "meta_app_id", "111")
    monkeypatch.setattr(settings, "meta_app_secret", "segreto")
    monkeypatch.setattr(settings, "meta_es_config_id", "222")

    app = FastAPI()
    app.include_router(collegamento.router)
    client = TestClient(app, follow_redirects=False)

    assert client.get("/admin/collega-whatsapp").status_code == 303
    assert (
        client.post("/admin/collega-whatsapp/scambia", json={"code": "AQB"}).status_code
        == 303
    )
