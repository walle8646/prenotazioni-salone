"""Test sulle pagine pubbliche del sito.

L'informativa sulla privacy ha un test suo per un motivo che non si vede
guardando la pagina: Meta pretende quell'indirizzo per pubblicare l'app, e
un'app non pubblicata **non riceve nessun webhook di produzione**. Se un domani
la rotta sparisse o rispondesse 404, il sintomo non sarebbe una pagina rotta —
sarebbe WhatsApp che smette di consegnare i messaggi dei clienti, senza un
errore da nessuna parte.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import website


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(website.router)
    return TestClient(app)


def test_informativa_privacy_raggiungibile(client):
    risposta = client.get("/privacy")
    assert risposta.status_code == 200


def test_informativa_dice_chi_tratta_i_dati(client):
    """Senza titolare e senza un recapito non è un'informativa, è un testo."""
    pagina = client.get("/privacy").text
    assert website.TITOLARE_PRIVACY in pagina
    assert "Titolare del trattamento" in pagina


def test_informativa_nomina_i_fornitori(client):
    """I terzi che vedono i dati vanno nominati, non riassunti in 'partner'."""
    pagina = client.get("/privacy").text
    for fornitore in ("Meta", "Anthropic", "Google", "Render"):
        assert fornitore in pagina, fornitore


def test_la_data_non_segue_l_orologio(client):
    """Dice quando l'informativa è cambiata, non quando la si legge.

    Calcolarla con `date.today()` la farebbe sembrare revisionata ogni giorno.
    """
    assert website.PRIVACY_AGGIORNATA in client.get("/privacy").text


def test_il_sito_linka_l_informativa(client):
    """Deve essere raggiungibile navigando, non solo conoscendo l'indirizzo."""
    assert '/privacy' in client.get("/").text


def test_pagina_cancellazione_dati_raggiungibile(client):
    """Meta la vuole a un indirizzo diverso da quello dell'informativa.

    Rifiuta lo stesso URL per i due campi, quindi non è un doppione: senza
    questa pagina l'app non si pubblica, e il resto segue.
    """
    risposta = client.get("/cancellazione-dati")
    assert risposta.status_code == 200
    assert "cancellazione" in risposta.text.lower()


def test_le_due_pagine_si_rimandano(client):
    """Chi arriva su una deve poter raggiungere l'altra."""
    assert "/privacy" in client.get("/cancellazione-dati").text


def test_le_immagini_del_sito_esistono(client):
    """Un nome di file sbagliato non rompe niente di visibile nei test: sul
    sito diventa un riquadro vuoto proprio in cima alla homepage.

    Si controlla ogni immagine citata dalle pagine pubbliche contro i file che
    ci sono davvero in `static/`.
    """
    import re
    from pathlib import Path

    radice = Path(__file__).resolve().parent.parent
    pagine = ["/", "/chi-siamo", "/privacy", "/cancellazione-dati"]

    citate = set()
    for pagina in pagine:
        citate.update(re.findall(r"/static/(img/[^\"?\s]+)", client.get(pagina).text))

    assert citate, "nessuna immagine trovata: il test non starebbe controllando niente"
    mancanti = sorted(c for c in citate if not (radice / "static" / c).is_file())
    assert mancanti == [], f"immagini citate ma assenti: {mancanti}"


def test_la_homepage_mostra_logo_e_foto(client):
    pagina = client.get("/").text
    assert "/static/img/logo.png" in pagina
    for foto in ("salone", "al-lavoro", "poltrona", "ingresso"):
        assert f"/static/img/{foto}-" in pagina, foto
