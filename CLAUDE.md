# Salone Nadia — bot prenotazioni

Bot conversazionale che gestisce le prenotazioni di un salone da barbiere dal
sito e (in futuro) via WhatsApp, con i calendari Google degli operatori e un
pannello per la receptionist.

## Stack

FastAPI · Claude API (Anthropic) · Google Calendar API · PostgreSQL
(SQLAlchemy async + asyncpg) · Redis (sessioni) · WebSocket per la chat del
sito · email SMTP dalla casella del salone · deploy su Render.

## Comandi

Su Windows `python` è lo stub del Microsoft Store e non esegue nulla: usare
sempre l'interprete del virtualenv, `.venv\Scripts\python.exe`.

```bash
pip install -r requirements.txt

pytest                          # suite completa, non tocca la rete
python simulate.py --offline    # chat da terminale, serve solo ANTHROPIC_API_KEY
python simulate.py --offline --fake-claude   # senza consumare token
python simulate.py --phone 390000000001      # servizi veri, si comporta come WhatsApp

docker compose up               # app + PostgreSQL + Redis, poi http://localhost:8000

python tools/fake_webhook.py text "vorrei un taglio"   # payload Meta finti al webhook
```

Un database nuovo non richiede migrazioni: al primo avvio l'applicazione crea le
tabelle e si annota da sé come allineata (`models/database.py`). `alembic upgrade
head` serve solo quando si aggiunge una migrazione a un database esistente.

`TESTING.md` spiega in dettaglio i modi di provare il bot senza WhatsApp.

## Come è organizzato

Il cuore è `services/conversation.py`. Riceve un messaggio, ricostruisce la
sessione da Redis, chiede a Claude cosa rispondere ed esegue le azioni JSON che
Claude richiede, con un massimo di 5 iterazioni per messaggio (tre erano poche:
chiedendo "il primo posto libero" il modello interroga più giorni di fila).

Le azioni sono `CHECK_DISPONIBILITA`, `CREA_APPUNTAMENTO`, `SPOSTA_APPUNTAMENTO`,
`CANCELLA_APPUNTAMENTO`, `STORICO_APPUNTAMENTI`, `INVIA_CODICE_VERIFICA` e
`VERIFICA_CODICE`.

Il motore non conosce né il canale né i servizi esterni: riceve tre cose
sostituibili.

- **Canale** (`services/channels.py`): dove scrivere le risposte.
  `MetaWhatsAppChannel`, `WebChannel` per il widget del sito, `ConsoleChannel`
  per il simulatore, `CollectorChannel` nei test. Per aggiungere un provider
  diverso (Twilio, Green API, Telegram) si scrive una classe qui e un adattatore
  del webhook: la logica di prenotazione non si tocca.
- **Backend** (`services/backends.py`): Google Calendar, database, email, media.
  `RealBackends` in produzione, `FakeBackends` (`services/fakes.py`) nei test e
  nel simulatore offline.
- **claude**: la funzione che chiama il modello. Nei test è `ScriptedClaude`,
  che restituisce risposte prestabilite.

Gli import delle librerie pesanti (Google, SQLAlchemy, anthropic) stanno dentro
i metodi, non in cima ai moduli: serve a poter importare il motore
conversazionale senza quelle dipendenze installate. Non spostarli in testa.

## Cose che sembrano semplificabili e non lo sono

Sono tutte conseguenze di difetti visti accadere. Toccarle senza sapere perché
esistono li fa tornare.

**L'identità del cliente non passa mai dal modello.** Su WhatsApp è il numero
del mittente, verificato dal gestore; sul sito è un'email confermata con un
codice a sei cifre. `STORICO_APPUNTAMENTI` non accetta nessun contatto come
parametro proprio per questo: usa il numero della conversazione, così la
richiesta dello storico di un altro non è nemmeno esprimibile. Se diventasse un
parametro, basterebbe scrivere il numero di un conoscente per leggere i suoi
appuntamenti.

**Il codice di verifica non compare nel risultato dell'azione.** Vive nella
sessione lato server e lo confronta `secrets.compare_digest`. Se finisse nel
risultato, finirebbe nello storico della conversazione — cioè esattamente dove
non deve stare. Ciò che sblocca lo storico è `email_verificata` nella sessione,
non l'opinione del modello: dirgli "ho già inserito il codice" non porta da
nessuna parte.

**Disdette e spostamenti valgono solo sui propri appuntamenti.** Gli id sono
progressivi: senza il controllo basterebbe dire "cancella il numero 3".

**Il fuso si risolve con `ZoneInfo("Europe/Rome")`, mai con un offset scritto a
mano.** Con `+02:00` fisso, in ora solare Google restituisce `+01:00` e il
confronto fra stringhe sballa: misurato, una prenotazione da 30 minuti ne
occupava due.

**Gli slot già passati vengono scartati** in `services/slots.py`, che riceve
l'istante corrente come parametro esplicito e non legge l'orologio da sé (così
resta verificabile con un istante fissato). Senza, alle dieci di sera il bot
proponeva le otto del mattino dello stesso giorno.

**La durata la decide `catalogo.durata_totale()`, anche in fase di ricerca.**
Fidarsi del numero dichiarato dal modello significa proporre slot liberi solo in
apparenza: un colore da due ore prenotato come mezz'ora finisce sopra
l'appuntamento successivo.

**Quanto può essere lungo un titolo cliccabile lo dichiara il canale**
(`Channel.lunghezza_massima_opzione`), non chi analizza il testo: il widget del
sito non ha limiti, WhatsApp sì e diversi a seconda della forma. Un bottone
(fino a tre scelte) ha il solo titolo da venti caratteri: se una voce non ci sta
si rinuncia ai bottoni, perché quel titolo è anche ciò che torna indietro
quando il cliente tocca, e il listino non riconoscerebbe il troncone. Una riga
di lista (da quattro scelte in su) ha invece un titolo da ventiquattro e una
descrizione da settantadue, che Meta ci restituisce insieme alla scelta: lì la
voce sta per intero, il titolo si può accorciare, e `routers/webhook.py` legge
la descrizione. Senza, bastava una voce lunga perché l'intero elenco dei
servizi arrivasse come testo — proprio la prima scelta, e la più importante.

**La sessione annota servizio e operatore al primo `CHECK_DISPONIBILITA`.** Lo
storico viene troncato agli ultimi `max_history_messages` messaggi e ogni turno
ne aggiunge quattro: dal sesto turno la richiesta iniziale del cliente non c'è
più, e senza quei dati il bot ricomincia a chiedere cosa voleva.

## Listino e operatori

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
lunghi diversi.

Operatori (`services/operatori.py`): Simone Big, Simone Jr, Francesco, Andrea,
Giava, Bario. Ognuno ha un calendario Google dedicato, creato l'8 agosto 2026 e
di proprietà dell'account `parrucchiere.bot.test@gmail.com`, con il service
account come `writer`. L'associazione nome → id sta in `GCAL_PARRUCCHIERE_IDS`,
**oggetto JSON, non lista**: con la lista i nomi non sono noti, la mappa resta
vuota e ogni operatore risulta non configurato.

Orari: martedì-venerdì 8:00-12:00 e 14:30-19:30, sabato 8:00-18:00 continuato,
chiuso domenica e lunedì. Slot da 30 minuti.

## Email

Si spedisce via SMTP dalla casella del salone (`SMTP_*`), non da un servizio
esterno: il mittente è l'indirizzo che i clienti conoscono e le risposte
arrivano dove qualcuno le legge. Con Gmail serve una **password per le app**, non
quella dell'account. Senza configurazione le funzioni escono subito senza
errori, e un invio fallito non fa mai fallire una prenotazione.

Partono quattro messaggi: conferma, spostamento, annullamento e codice di
verifica. Le date vanno scritte con `_quando()`, che le rende in italiano: i nomi
di giorni e mesi sono nel codice perché nel container non c'è il locale.

## Convenzioni

Codice, commenti e nomi in italiano, coerentemente con il resto del progetto.
I commenti spiegano il perché di una scelta, non quello che il codice già dice.

I test non toccano mai la rete: Claude, Google e il database si sostituiscono
con i finti. Due regole imparate a spese nostre: **niente date fisse** — usare
`prossimo_giorno_aperto()` in `tests/conftest.py`, perché una data del passato
non ha più slot disponibili e manda in rosso test che non c'entrano — e
**niente premesse ereditate dall'ambiente**: un test che dipende dall'assenza di
un `.env` passa solo sulla macchina di chi non ce l'ha.

## Stato all'8 agosto 2026

Il bot è **pubblicato su Render e funzionante**. Prenota, sposta, disdice,
mostra lo storico e riconosce i clienti abituali, scrivendo davvero sui
calendari Google e mandando email che arrivano. 130 test.

Provato sul campo: Google Calendar (sei calendari veri, eventi creati, spostati
e cancellati), l'invio email, il widget del sito, il database e **WhatsApp**,
che risponde da un telefono vero con testo e bottoni.

Note sul piano gratuito di Render: il servizio si sospende per inattività, e la
prima richiesta dopo una pausa aspetta una trentina di secondi. Per lo stesso
motivo i promemoria a 12 ore non partono in modo affidabile, perché servirebbe un
processo sempre acceso. E il disco è effimero: le foto salvate da
`services/storage.py` spariscono a ogni deploy.

## Cose note ancora da fare

- **WhatsApp** gira su un numero di prova di Meta, che consegna solo ai
  destinatari autorizzati a mano (massimo cinque). Per aprirlo ai clienti serve
  un numero proprio, e a quel punto la verifica dell'azienda.
- Pannello CRM da costruire: schermate CRUD su `servizi` e `parrucchieri`, più
  anagrafica clienti. Oggi il pannello mostra solo gli appuntamenti del giorno.
- `max_booking_days_ahead` è configurato ma non applicato: si può prenotare a
  qualunque distanza.
- `cancel_notify` in `routers/admin.py` è un endpoint vuoto.
- Per ricominciare da capo il cliente deve scrivere "ricominciamo da capo" (o
  "reset", "azzera tutto": le riconosce `vuole_ricominciare()`, e fra queste
  parole non c'è **"annulla"**, che disdice un appuntamento). Sul widget del
  sito servirebbe un bottone: scritta com'è, quella via la trova solo chi legge
  il suggerimento del bot.

## Account Meta

WhatsApp passa dalla Cloud API di Meta, con l'app `salone-nadia`
(id `1493423639206303`) e il numero di prova `+1 555-201-1459`
(`META_PHONE_NUMBER_ID`), sull'account WhatsApp Business `1687123500082794`.
Il token è di un utente di sistema e non scade.

Due cose costate una serata, perché danno lo stesso sintomo — silenzio totale —
e sembrano già fatte quando non lo sono.

**Configurare la URL del webhook e iscrivere l'app all'account sono due
passaggi distinti.** La verifica del webhook riesce comunque, perché è a livello
di app: sembra tutto a posto e non arriva nessun messaggio. L'iscrizione si
controlla con `GET /{WABA_ID}/subscribed_apps`, che deve elencare `salone-nadia`
e non solo `WA DevX Webhook Events 1P App`, che è di Meta. Si aggiunge con la
stessa rotta in `POST`.

**Meta scrive sempre perché rifiuta, in chiaro e in italiano, e va letto.**
`services/whatsapp_service.py` faceva la POST e buttava via la risposta: un
messaggio rifiutato risultava consegnato e nei log restava un 400 senza motivo.
I codici visti: `131030` numero non fra i destinatari consentiti, `131005` token
sbagliato o senza permessi.

## Sicurezza

`.env` non va mai committato e non deve finire nei log. Le credenziali del
service account Google stanno in `GOOGLE_CREDENTIALS_JSON`, come percorso a un
file (in locale) o come stringa JSON per intero (su Render, dove quel file non
esiste).

Il pannello si rifiuta di aprire se `ADMIN_PASSWORD` o `SECRET_KEY` non sono
configurate: senza la prima il confronto riuscirebbe con la password vuota, e la
seconda ha un valore predefinito scritto nel repository, con cui chiunque
potrebbe fabbricarsi il cookie dell'amministratore. Una configurazione mancante
deve chiudere la porta, non spalancarla.

Le altre variabili sconosciute vengono ignorate invece di impedire l'avvio: una
chiave rimasta in giro dopo un cambio di servizio non deve mandare giù
l'applicazione.
