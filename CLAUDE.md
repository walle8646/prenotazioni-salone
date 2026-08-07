# Salone Nadia — bot prenotazioni

Bot conversazionale che gestisce le prenotazioni di un salone da barbiere via
WhatsApp e dal sito, con i calendari Google degli operatori e un pannello per
la receptionist.

## Stack

FastAPI · Claude API (Anthropic) · Google Calendar API · PostgreSQL
(SQLAlchemy async + asyncpg) · Redis (sessioni) · WhatsApp Cloud API di Meta ·
Resend (email) · WebSocket per la chat del sito · deploy su Render.

## Comandi

Su Windows `python` è lo stub del Microsoft Store e non esegue nulla: usare
sempre l'interprete del virtualenv, `.venv\Scripts\python.exe`.

```bash
pip install -r requirements.txt

pytest                          # suite completa, non tocca la rete
python simulate.py --offline    # chat da terminale, serve solo ANTHROPIC_API_KEY
python simulate.py --offline --fake-claude   # senza consumare token

docker compose up               # app + PostgreSQL + Redis
alembic upgrade head            # migrazioni (su DB preesistente: alembic stamp 0001 prima)

python tools/fake_webhook.py text "vorrei un taglio"   # payload Meta finti al webhook
```

`TESTING.md` spiega in dettaglio i quattro modi di provare il bot senza WhatsApp.

## Come è organizzato

Il cuore è `services/conversation.py`. Riceve un messaggio, ricostruisce la
sessione da Redis, chiede a Claude cosa rispondere ed esegue le azioni JSON che
Claude richiede (`CHECK_DISPONIBILITA`, `CREA_APPUNTAMENTO`,
`CANCELLA_APPUNTAMENTO`), con un massimo di 3 iterazioni per messaggio.

Non conosce né il canale né i servizi esterni: riceve tre cose sostituibili.

- **Canale** (`services/channels.py`): dove scrivere le risposte. `MetaWhatsAppChannel`
  in produzione, `WebChannel` per il widget del sito, `ConsoleChannel` per il
  simulatore, `CollectorChannel` nei test. Per aggiungere un provider diverso
  (Twilio, Green API, Telegram) si scrive una classe qui e un adattatore del
  webhook: la logica di prenotazione non si tocca.
- **Backend** (`services/backends.py`): Google Calendar, database, email, media.
  `RealBackends` in produzione, `FakeBackends` (`services/fakes.py`) nei test e
  nel simulatore offline.
- **claude**: la funzione che chiama il modello. Nei test è `ScriptedClaude`,
  che restituisce risposte prestabilite.

Gli import delle librerie pesanti (Google, SQLAlchemy, Resend, anthropic) stanno
dentro i metodi, non in cima ai moduli: serve a poter importare il motore
conversazionale senza quelle dipendenze installate. Non spostarli in testa.

### Listino e operatori

A runtime il listino vive nella tabella `servizi` del database, così il futuro
pannello di gestione potrà cambiarlo senza toccare il codice.
`services/catalogo.py` contiene il listino iniziale con cui la tabella viene
riempita al primo avvio, e fa da fallback per test e simulatore. Da lì leggono
il system prompt, il sito, il calcolo della durata e i totali in dashboard.

Listino attuale: Taglio 13,50 € / 30 min · Taglio + Shampoo 17,50 € / 30 min ·
Taglio + Barba 20,00 € / 30 min · Taglio + Shampoo + Barba 25,00 € / 30 min ·
Barba 8,00 € / 30 min · Taglio + Shampoo + Trattamento barba con oli e panno
bagnato 45,00 € / 1 ora · Colore + Taglio + Trattamento capello 50,00 € / 2 ore.

Attenzione: le combinazioni **non** sommano le durate. Taglio + Barba insieme
dura 30 minuti perché è una voce di listino a sé. Si sommano solo due servizi
lunghi diversi. La durata la decide `catalogo.durata_totale()`, mai Claude.

Operatori (`services/operatori.py`): Simone Big, Simone Jr, Francesco, Andrea,
Giava, Bario. Ognuno ha bisogno di un calendario Google condiviso col service
account, configurato in `GCAL_PARRUCCHIERE_IDS` come oggetto JSON nome → id.

Orari: martedì-venerdì 8:00-12:00 e 14:30-19:30, sabato 8:00-18:00 continuato,
chiuso domenica e lunedì. Slot da 30 minuti.

## Convenzioni

Codice, commenti e nomi in italiano, coerentemente con il resto del progetto.
I test non devono mai toccare la rete: Claude, Google e il database si
sostituiscono con i finti. I commenti spiegano il perché di una scelta, non
quello che il codice già dice.

## Stato al 7 agosto 2026

Il lavoro fino a questo punto era stato fatto da una sessione Cowork nel cloud,
dove PyPI era bloccato: test, migrazioni, database e applicazione non erano mai
stati eseguiti davvero. Il 7 agosto 2026 sono stati tutti verificati in locale,
su Windows con Python 3.12 e Docker Desktop:

- i 71 test passano con pytest vero, non con il runner scritto a mano;
- le migrazioni `0001` e `0002` girano su PostgreSQL 16 e portano il database a
  `0002 (head)`;
- il database viene creato e popolato: 6 operatori con i calendar ID segnaposto
  e i 7 servizi del listino, con prezzi e durate corretti;
- l'applicazione si avvia, risponde su `/health` e serve homepage e pannello.

Restano invece **non ancora provati sul campo**: le chiamate vere a Google
Calendar (mancano i calendar ID), l'invio delle email con Resend e il canale
WhatsApp.

Nel repository ci sono ancora parecchi file nuovi e modificati mai committati:
conviene fare un commit di sicurezza.

## Cose note ancora da fare

- I calendar ID Google dei sei operatori non esistono ancora.
- Il bot non riconosce i clienti abituali: il database viene letto solo quando
  si crea l'appuntamento, quindi all'inizio della conversazione non sa chi sta
  scrivendo. Andrebbe caricato il cliente dal numero e passati nome e operatore
  preferito nel system prompt.
- `routers/webhook.py` risponde 200 a Meta solo dopo aver interrogato Claude e
  Google: se supera i pochi secondi di attesa di Meta il messaggio viene
  rinviato e il cliente riceve risposte doppie. Va spostato in background.
- Il fuso orario è fisso a `+02:00` in `services/calendar_service.py`: con
  l'ora solare gli slot slittano di un'ora.
- `min_booking_hours_ahead`, `max_booking_days_ahead` e `cancel_policy_hours`
  sono configurati ma non applicati da nessuna parte.
- `cancel_notify` in `routers/admin.py` è un endpoint vuoto.
- Pannello CRM da costruire: schermate CRUD su `servizi` e `parrucchieri`, più
  anagrafica clienti.

## Account Meta

L'account sviluppatore Meta è stato abbandonato: il codice di verifica arriva ma
viene rifiutato. Non riproporre quella strada senza che l'utente la chieda. Per
provare il bot si usa il simulatore o il widget del sito; se servisse un canale
WhatsApp reale, le alternative valutate sono Twilio Sandbox e Green API.

## Sicurezza

`.env` non va mai committato e non deve finire nei log. Le credenziali del
service account Google stanno in `GOOGLE_CREDENTIALS_JSON`, come percorso o come
stringa JSON.
