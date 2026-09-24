"""Prova la posta in uscita e dice cosa non va, in italiano.

Esiste per un guasto già pagato: sul piano gratuito di Render le porte SMTP
sono bloccate, e `smtplib` non fallisce il login — non riesce proprio ad
aprire la connessione. Nei log restava una riga sola, e per settimane nessuna
email è partita senza che se ne accorgesse nessuno.

Da usare a ogni cambio di casella o di dominio, **dalla shell di Render** e
non solo dal proprio computer: la differenza fra i due non è una
configurazione, è la rete della piattaforma.

    python tools/prova_email.py                  # scrive alla casella stessa
    python tools/prova_email.py a@esempio.it     # scrive a un altro indirizzo
"""

import smtplib
import socket
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402


def _riga(etichetta: str, valore: str) -> None:
    print(f"  {etichetta:<22} {valore}")


def main() -> int:
    destinatario = sys.argv[1] if len(sys.argv) > 1 else settings.smtp_user

    print("\n1. CONFIGURAZIONE")
    _riga("server", settings.smtp_host or "(non impostato)")
    _riga("porta", str(settings.smtp_port))
    _riga("utente", settings.smtp_user or "(non impostato)")
    _riga("mittente", settings.email_from or settings.smtp_user or "(non impostato)")
    _riga("password", "impostata" if settings.smtp_password else "MANCANTE")
    _riga(
        "cifratura",
        "SSL dall'inizio (465)" if settings.smtp_port == 465 else "STARTTLS",
    )

    if not settings.smtp_user or not settings.smtp_password:
        print("\n   Senza SMTP_USER e SMTP_PASSWORD il codice esce subito e non")
        print("   spedisce niente, senza errori. Impostale e riprova.")
        return 1

    if settings.smtp_port == 25:
        print("\n   Attenzione: la porta 25 è bloccata su Render anche a pagamento.")
        print("   Con Aruba usa la 465, con Gmail la 587.")

    messaggio = EmailMessage()
    messaggio["From"] = f"Acconciature Simone <{settings.email_from or settings.smtp_user}>"
    messaggio["To"] = destinatario
    messaggio["Subject"] = "Prova di invio — Acconciature Simone"
    messaggio.set_content(
        "Se stai leggendo questo messaggio, la posta in uscita funziona.\n\n"
        f"Server: {settings.smtp_host}:{settings.smtp_port}\n"
        f"Mittente: {settings.email_from or settings.smtp_user}\n"
    )

    print(f"\n2. INVIO a {destinatario}")
    try:
        if settings.smtp_port == 465:
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=30) as server:
                server.login(settings.smtp_user, settings.smtp_password)
                server.send_message(messaggio)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
                server.starttls()
                server.login(settings.smtp_user, settings.smtp_password)
                server.send_message(messaggio)
    except socket.gaierror as e:
        print(f"   FALLITO: il nome del server non si risolve ({e}).")
        print("   Server sbagliato, o questa macchina non ha DNS.")
        return 1
    except (TimeoutError, ConnectionRefusedError, OSError) as e:
        print(f"   FALLITO: la connessione non si apre ({e}).")
        print("   È il sintomo delle porte SMTP bloccate: sul piano gratuito di")
        print("   Render è normale e nei log si legge 'Network is unreachable'.")
        print("   Se sei a pagamento, controlla la porta: 465 con Aruba, 587 con Gmail.")
        return 1
    except smtplib.SMTPAuthenticationError as e:
        print(f"   FALLITO: credenziali rifiutate ({e.smtp_code}).")
        print("   L'utente è l'indirizzo email per intero, non il nome prima della @.")
        print("   Con Gmail serve una password per le app, non quella dell'account.")
        return 1
    except smtplib.SMTPSenderRefused as e:
        print(f"   FALLITO: mittente rifiutato ({e.smtp_error}).")
        print("   EMAIL_FROM deve essere una casella che quel server può usare.")
        return 1
    except smtplib.SMTPNotSupportedError as e:
        print(f"   FALLITO: {e}")
        print("   Con la porta 465 non si fa STARTTLS, e viceversa: controlla la porta.")
        return 1
    except ssl.SSLError as e:
        print(f"   FALLITO: errore TLS ({e}).")
        print("   Di solito è la 465 usata come STARTTLS, o il contrario.")
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"   FALLITO: {type(e).__name__}: {e}")
        return 1

    print("   Partita.")
    print("\n3. ORA GUARDA LA POSTA IN ARRIVO")
    print("   Partita non vuol dire consegnata. Controlla che non sia finita")
    print("   nella posta indesiderata: se ci finisce, mancano i record SPF,")
    print("   DKIM e DMARC nelle DNS del dominio — il messaggio parte, arriva")
    print("   e nessuno lo legge, che è il modo più silenzioso di non funzionare.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
