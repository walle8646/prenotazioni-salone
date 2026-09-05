# Come testare il bot senza WhatsApp

Il numero WhatsApp non serve per provare il bot. Il motore conversazionale è
separato dal canale su cui parla, quindi lo stesso identico flusso di
prenotazione si può guidare da terminale, dal widget del sito o da un test
automatico. Questo documento spiega i quattro modi, dal più veloce al più simile
alla produzione.

## 1. Simulatore da terminale (il modo più rapido)

Chatti col bot direttamente nel terminale. Serve solo `ANTHROPIC_API_KEY` nel
file `.env`: Redis, Google Calendar, PostgreSQL ed email sono finti e vivono in
memoria.

```bash
python simulate.py --offline
```

Durante la chat sono disponibili tre comandi: `/stato` mostra lo stato della
sessione, i dati raccolti finora e gli appuntamenti creati; `/reset` ricomincia
da zero; `/esci` chiude.

Se vuoi verificare che l'impianto giri senza consumare token, aggiungi
`--fake-claude`: le risposte diventano prestabilite e l'API non viene chiamata.

Questa è la modalità giusta per affinare il system prompt, perché vedi subito
l'effetto di ogni modifica a `prompts/system_prompt.py`.

## 2. Test automatici

```bash
pytest
```

La suite copre il riconoscimento delle azioni JSON, la conversione delle
risposte in bottoni, il flusso completo di prenotazione (calendario, database,
email di conferma), gli slot da 60 minuti che richiedono due posti consecutivi,
le chiusure straordinarie, la cancellazione e la chat del sito. Non tocca
Internet: Claude, Google e PostgreSQL sono sostituiti da finti deterministici,
quindi i test sono ripetibili e gratuiti.

Per aggiungere uno scenario, guarda `tests/test_booking_flow.py`: si scrive la
sequenza di risposte che Claude dovrebbe dare con `ScriptedClaude` e si verifica
cosa è finito in `backends.appuntamenti`, `backends.eventi` o
`backends.email_inviate`.

## 3. Widget di chat del sito

```bash
docker compose up
```

Poi apri `http://localhost:8000`: il widget in basso a destra usa lo stesso
motore conversazionale di WhatsApp, con i bottoni cliccabili. È il modo migliore
per far provare il bot a Nadia senza installare niente sul suo telefono, e
funziona già oggi in produzione una volta pubblicato il sito.

## 4. Simulatore di webhook WhatsApp

Riproduce i payload esatti che manda Meta, per testare `routers/webhook.py` sul
serio (parsing dei messaggi, gestione dei tipi, handshake di verifica) senza
avere un account sviluppatore.

```bash
docker compose up                                     # in un terminale

python tools/fake_webhook.py verify                   # handshake di verifica
python tools/fake_webhook.py text "vorrei un taglio"  # messaggio di testo
python tools/fake_webhook.py button "Taglio"          # risposta a un bottone
python tools/fake_webhook.py image "un taglio così"   # foto con didascalia
python tools/fake_webhook.py status                   # notifica di consegna
python tools/fake_webhook.py audio                    # tipo non supportato
```

Le risposte del bot partono verso le API di Meta, quindi non le vedi a schermo:
si guardano nei log del server. Aggiungi `--dry-run` per stampare il payload
senza inviarlo.

## 5. Riempire l'agenda di appuntamenti finti

Un'agenda vuota non mette alla prova niente: il bot propone il primo orario
libero e ha sempre ragione. I difetti si vedono quando le giornate sono piene a
macchie, un operatore è più richiesto degli altri e certi orari mancano solo
per alcuni.

```bash
python tools/dati_di_prova.py                        # mostra il piano, non scrive
python tools/dati_di_prova.py --conferma             # crea davvero
python tools/dati_di_prova.py --pulisci --conferma   # toglie tutto
```

**Va lanciato dalla Shell di Render, non dal proprio computer**: gli
appuntamenti servono dove il bot li leggerà, e da fuori il database di
produzione non è raggiungibile.

Scrive **sia nel database sia sui calendari Google**. Solo da una parte non
servirebbe: la disponibilità il bot la chiede a Google, e righe senza eventi
lascerebbero l'agenda libera come prima.

I dati finti si riconoscono da due cose, ed è così che `--pulisci` li ritrova
tutti: il telefono comincia per `39000000`, che non è un numero assegnabile, e
la descrizione degli eventi contiene `[DATI DI PROVA]`. Le email finiscono in
`@example.invalid`, dominio che per definizione non esiste: **nemmeno
sbagliando si scrive a una persona vera**.

Rispetta orari del salone, chiusure, presenze dei singoli e durate del listino,
e dà a ogni cliente **un solo appuntamento futuro** — come impone il bot:
averne due farebbe sembrare un difetto il rifiuto che si riceve provando a
prenotare. Nel passato invece si accumulano, ed è quello che rende
riconoscibile un cliente abituale.

Con i valori predefiniti (1 settembre - 31 ottobre, densità 0.45) fa circa
**2.100 appuntamenti su 1.900 clienti**, poco meno della metà dell'agenda.
`--densita`, `--da` e `--a` cambiano la misura; `--seme` ripete la stessa
agenda, utile per riprovare una prova andata storta.

## Listino e operatori

A runtime il listino vive nella tabella `servizi` del database, così il futuro
pannello di gestione potrà cambiare prezzi e durate senza toccare il codice.
Il listino iniziale sta in `services/catalogo.py` e serve a due cose: riempire
la tabella al primo avvio e fare da rete di sicurezza per simulatore e test,
che girano senza database. Da lì leggono il system prompt di Claude, la pagina
servizi del sito, il calcolo della durata da bloccare sul calendario e il
totale in dashboard.

Quando il listino cambia nel database, il bot lo recepisce al riavvio (o
richiamando `catalogo.set_catalogo_cache()` dopo la modifica). I test in
`tests/test_catalogo.py` verificano sia che il listino iniziale resti quello
concordato col salone, sia che una modifica a caldo venga applicata davvero.

Gli operatori sono in `services/operatori.py`. Ognuno ha bisogno di un
calendario Google condiviso con il service account; l'associazione si configura
nella variabile d'ambiente `GCAL_PARRUCCHIERE_IDS`, scritta come oggetto JSON su
una riga:

```
GCAL_PARRUCCHIERE_IDS={"Simone Big":"...@group.calendar.google.com","Simone Jr":"..."}
```

Finché mancano, l'avvio scrive nei log quali operatori non hanno ancora un
calendario e le prenotazioni con loro falliscono in modo esplicito, invece di
finire silenziosamente sul calendario sbagliato.

## Migrazioni del database

Lo schema è gestito con Alembic. Su un database nuovo:

```bash
alembic upgrade head
```

Se il database esiste già con le tre tabelle originali (create da
`create_all()` ai primi avvii), va prima allineato e poi aggiornato:

```bash
alembic stamp 0001
alembic upgrade head
```

La migrazione `0002` aggiunge la tabella `servizi` e la colonna `prezzo` sugli
appuntamenti.

## Come è organizzato il codice

Il motore (`services/conversation.py`) riceve tre cose sostituibili:

- un **canale** (`services/channels.py`) su cui scrivere le risposte —
  WhatsApp, widget web, terminale o raccoglitore per i test;
- dei **backend** (`services/backends.py`) da cui leggere e su cui scrivere —
  quelli veri oppure quelli finti in `services/fakes.py`;
- una funzione **claude** da chiamare — l'API vera oppure risposte prestabilite.

In produzione non cambia nulla: se non passi niente, vengono usati i servizi
veri. Il vantaggio pratico è che il giorno in cui si sceglie un provider
WhatsApp diverso da Meta (Twilio, Green API, o un BSP) basta aggiungere una
classe in `services/channels.py` e un adattatore del webhook: la logica di
prenotazione non si tocca.
