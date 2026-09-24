"""Test su come ci si connette al server di posta.

Sbagliare qui non dà un errore che si legge: con la porta e la cifratura
scambiate la connessione resta appesa fino al timeout, l'eccezione viene
inghiottita perché un'email non deve far fallire una prenotazione, e nei log
resta una riga. È il guasto che ha tenuto il salone senza conferme per
settimane, quindi la scelta va provata.
"""

import smtplib

import pytest

from config import settings
from services import email_service


class FintoServer:
    """Un server di posta che non parla con nessuno e si ricorda tutto."""

    def __init__(self, tipo):
        self.tipo = tipo
        self.starttls_fatto = False

    def starttls(self):
        self.starttls_fatto = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


@pytest.fixture
def server_finto(monkeypatch):
    """Sostituisce smtplib e restituisce il server che è stato aperto."""
    aperti = []

    def finto_ssl(host, porta, timeout=None):
        server = FintoServer("SSL")
        aperti.append((server, host, porta))
        return server

    def finto_chiaro(host, porta, timeout=None):
        server = FintoServer("chiaro")
        aperti.append((server, host, porta))
        return server

    monkeypatch.setattr(smtplib, "SMTP_SSL", finto_ssl)
    monkeypatch.setattr(smtplib, "SMTP", finto_chiaro)
    monkeypatch.setattr(settings, "smtp_host", "smtps.esempio.it")
    return aperti


def test_la_porta_465_apre_una_connessione_gia_cifrata(server_finto, monkeypatch):
    """Aruba: sulla 465 il canale è cifrato dal primo byte, e chiedere
    STARTTLS su una connessione già cifrata la fa fallire."""
    monkeypatch.setattr(settings, "smtp_port", 465)

    server = email_service._connessione()

    assert server.tipo == "SSL"
    assert server.starttls_fatto is False
    assert server_finto[0][2] == 465


def test_la_porta_587_parte_in_chiaro_e_sale_a_tls(server_finto, monkeypatch):
    """Gmail: sulla 587 senza STARTTLS la password viaggerebbe in chiaro, e
    il server la rifiuterebbe comunque."""
    monkeypatch.setattr(settings, "smtp_port", 587)

    server = email_service._connessione()

    assert server.tipo == "chiaro"
    assert server.starttls_fatto is True


def test_il_server_e_quello_configurato(server_finto, monkeypatch):
    monkeypatch.setattr(settings, "smtp_port", 465)

    email_service._connessione()

    assert server_finto[0][1] == "smtps.esempio.it"
