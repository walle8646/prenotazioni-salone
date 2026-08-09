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

Le migrazioni non si lanciano a mano. All'avvio (`models/database.py`): se il
database è vuoto le tabelle nascono dai modelli e viene annotato come allineato;
se esiste già, riceve le migrazioni che gli mancano. Dimenticare un `alembic
upgrade head` prima di un deploy non rompeva la funzione appena aggiunta, ma
tutto: SQLAlchemy chiede al database tutte le colonne del modello, e quella
nuova non c'era ancora.

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

**Chi ha già prenotato viene riconosciuto prima che il modello parli**
(`_riconosci_cliente()`, all'inizio di ogni conversazione nuova). Il
riconoscimento esisteva già dentro `STORICO_APPUNTAMENTI`, ma ci si arrivava
solo se il modello sceglieva di chiamarlo: quando non lo faceva, ricominciava a
chiedere nome e cognome a chi viene da tre anni. Una lettura per conversazione,
non per messaggio. **Dal sito non riconosce nessuno**, ed è la stessa regola di
sempre: `_appuntamenti_del_richiedente` risponde solo dopo il codice via email,
e un numero di sessione del browser non è una prova di identità — altrimenti
basterebbe aprire la chat per vedersi salutare col nome e l'email di un altro.

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

**Il seed degli operatori riempie solo quello che manca.** `seed_parrucchieri`
gira a ogni avvio: prima riattivava chi era nell'elenco del codice e
disattivava chi non c'era, e col pannello vorrebbe dire vedersi sparire al
deploy successivo l'operatore appena assunto e tornare al lavoro quello appena
messo a riposo. Il calendario della configurazione sovrascrive solo un
segnaposto (`sovrascrive_il_calendario()`): quando in tabella c'è un
calendario vero, a cambiarlo è il pannello.

**"Indifferente" lo aggiunge il codice, non il modello** (`con_indifferente()`).
Il prompt lo chiede da sempre e quasi sempre viene rispettato, ma "quasi" non
basta per l'unica via d'uscita di chi non ha preferenze: senza quella voce
restano sei scelte tutte impegnative, e va scritto a mano. Si interviene solo
quando le voci sono tutte e sole nomi di operatori, così un elenco di orari o di
servizi non viene toccato.

**Su WhatsApp il cliente vede subito che il messaggio è arrivato.** Appena il
webhook ha risposto a Meta, `segna_letto_e_sta_scrivendo()` mette le spunte blu
e l'indicatore "sta scrivendo" — una chiamata sola per entrambe le cose. Dura
venticinque secondi o fino alla risposta, e serve l'id del messaggio in arrivo.
Senza, fra Claude e i calendari passano secondi di silenzio, e su Render appena
risvegliato una trentina: il cliente crede di aver scritto nel vuoto. Se il
segnale non parte non cambia niente, è cortesia e non funzionamento.

**Su WhatsApp le facce stanno in un'immagine sola, non una per riga.** Non è
una scorciatoia: le liste di Meta ammettono solo intestazioni di testo e nelle
righe non entra nessuna immagine, mentre i messaggi a bottoni accettano
un'immagine di intestazione, una per messaggio. Quindi fino a tre scelte
l'immagine è l'intestazione dei bottoni, e da quattro in su arriva prima, in un
messaggio suo, seguita dalla lista (`MetaWhatsAppChannel._immagine_delle_facce`).
La compone `griglia_operatori_png()` in PNG, perché l'SVG Meta non lo accetta, e
la serve `/operatori/scelta.png?nomi=...`. Senza `PUBLIC_BASE_URL` non se ne fa
niente e le scelte restano testo: Meta l'immagine se la viene a prendere da sé,
e un indirizzo che non sa raggiungere farebbe fallire tutto il messaggio, non
solo la faccia.

**L'inquadratura la sceglie chi carica, nel browser** (`static/ritaglio.js`):
si trascina e si ingrandisce dentro il tondo che vedrà il cliente, e al server
arriva un quadrato da 512 pixel. Il ritaglio centrale di `normalizza_foto()`
resta come ripiego per le foto che arrivano per altre strade — e per chi ha un
browser che non lascia sostituire il file scelto. Lì si applica anche
l'orientamento EXIF: senza, le fotografie fatte col telefono in verticale si
vedono coricate.

**Le facce degli operatori stanno nel database, non su disco** (colonne `foto`
e `foto_mime` su `parrucchieri`): su Render il disco è effimero, e una foto
caricata dal pannello sparirebbe al primo deploy. Finché la colonna è vuota,
`services/avatar.py` disegna un avatar con le iniziali, quindi non c'è mai un
buco al posto della faccia. Il colore si ricava con `hashlib` e non con
`hash()`, che è salato a ogni avvio: con quello l'operatore cambiava colore a
ogni deploy. Le iniziali sono sempre due, altrimenti Simone Big e Simone Jr
diventano due dischi identici con una S. La foto si chiede **per nome**
(`/operatori/{nome}/foto`) perché il nome è l'unica cosa che il motore
conversazionale ha in mano, e l'indirizzo non risponde mai 404: senza foto, e
anche senza database, restituisce l'avatar.

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

**La disponibilità torna un orario per riga, non uno per operatore**
(`raggruppa_per_orario()`). Cercando con `parrucchiere: null` Google risponde
per ogni calendario, quindi diciotto orari diventavano centootto righe, ognuna
con l'identificativo del calendario appresso — novanta caratteri che il modello
non usa mai e che il codice gli tiene nascosti apposta. Il costo non è il
messaggio: quel risultato resta nello storico e viene **rimandato a prezzo
pieno a ogni messaggio successivo**. Misurato su una prenotazione intera:
18.851 caratteri per ricerca, 59.668 token a prezzo pieno, 19,7 centesimi.
Raggruppando: 2.003 caratteri, 10.769 token, **6,6 centesimi**. Da qui la
regola: prima di aggiungere un campo al risultato di un'azione, ricordarsi che
lo si paga per tutti i messaggi che verranno dopo.

**Il prompt è diviso in due e l'ordine non è estetico** (`parte_stabile()` e
`parte_variabile()`): la cache di Anthropic è un confronto di prefisso e si
ferma al primo byte diverso. Prima lo stato della conversazione stava in mezzo,
e restavano cacheabili solo i primi 938 token — sotto la soglia minima di 1024
di Sonnet, quindi la cache non si sarebbe attivata affatto, in silenzio.
Spostato lo stato in fondo, il prefisso stabile fa 3.775 token e le letture
costano un decimo: misurato, una chiamata a caldo passa da 3.876 token a prezzo
pieno a un centinaio. Da qui la regola: **nella parte stabile non entra nessun
dato del cliente**, nemmeno "Telefono raccolto", che infatti è stato spostato.
`services/claude_client.py` scrive nei log quanti token vengono letti dalla
cache: se non si attivasse non si romperebbe niente, si pagherebbe e basta, e
nessuno se ne accorgerebbe.

**La sessione annota servizio, giorno e operatore al primo
`CHECK_DISPONIBILITA`.** Lo storico viene troncato agli ultimi
`max_history_messages` messaggi e ogni turno ne aggiunge quattro: dal sesto
turno la richiesta iniziale del cliente non c'è più, e senza quei dati il bot
ricomincia a chiedere cosa voleva.

**Prima il giorno, poi la persona** (regole 4 e 5 del prompt, e l'ordine di
`_FASI`). Chiedere l'operatore per primo faceva scegliere qualcuno che quel
giorno poteva non esserci, e il cliente scopriva il buco dopo essersi
affezionato al nome. Ora si cerca con `parrucchiere: null` e si offre di
scegliere solo fra chi è libero a quell'ora. Conseguenza da tenere a mente:
gli slot tornano ripetuti, uno per operatore libero — il prompt dice
esplicitamente di elencare ogni orario una volta sola, altrimenti alle sedici
compaiono sei bottoni identici.

## Pannello di gestione

Sotto `/admin`, protetto da `ADMIN_PASSWORD`: **Appuntamenti** (la giornata,
con la striscia dei sette giorni da cui si salta a un'altra data: un conteggio
solo per tutta la settimana, non sette query),
**Clienti** (elenco con ricerca e scheda singola), **Listino** e **Operatori**
(modifica in linea, una riga per form), **Presenze**, **Assenze**.

**Presenze** (`services/presenze.py`) dice quando ciascuno è in salone, con
fasce settimanali: la disponibilità toglie prima chi quel giorno non c'è, poi
quello che Google segna occupato — il calendario dice se è impegnato, non se
lavora. **Chi non ha orari suoi segue quelli del salone**, ed è ciò che rende
innocuo l'aggiornamento: finché nessuno tocca la schermata, il bot fa esattamente
quello che faceva prima. Distinguere i due casi richiede il flag
`orari_propri` sull'operatore, perché "non ho ancora configurato niente" e "non
lavora mai" sarebbero altrimenti la stessa tabella vuota — e attivare la
funzione li avrebbe fatti sparire tutti insieme. Un giorno di assenza singolo
non si mette qui: per quello c'è **Assenze**, che avvisa anche i clienti.

**Assenze** (`services/assenze.py`) annulla in blocco la giornata di un
operatore che non viene: toglie gli eventi da Google, annulla nel database e
manda ai clienti un'email diversa da quella della disdetta normale — qui la
colpa non è loro, e il salone si scusa. Si vede sempre prima l'elenco di chi
si sta per annullare: il bottone compare solo sotto quell'elenco.

Ogni appuntamento va per conto suo. Un'email che non parte non impedisce
l'annullamento degli altri; un evento che Google non trova non lascia in
agenda i rimanenti; se invece è il database a non rispondere il cliente
**non** viene avvisato, perché annunciare un annullamento che non è avvenuto
è il danno peggiore. Chi resta senza avviso finisce nel resoconto col numero
di telefono, da chiamare.

Due regole valgono per tutte e due le schermate di modifica.

**Dopo ogni scrittura si ricarica la cache** (`_ricarica_listino()`,
`_ricarica_operatori()` in `routers/admin.py`). Bot, prompt e sito leggono il
listino e gli operatori da una copia in memoria, non dal database: senza
quella riga il prezzo corretto resterebbe quello vecchio in bocca al bot fino
al riavvio. La copia è per processo, quindi con più worker uvicorn andrebbe
ripensata; oggi il processo è uno solo.

**Non si cancella niente, si sospende.** Un servizio tolto dal listino e un
operatore a riposo spariscono dalle scelte del bot ma restano negli
appuntamenti già fatti, che altrimenti diventerebbero illeggibili.

Le righe di modifica non sono in una tabella: ogni riga è un form a sé, e un
`<form>` dentro un `<tr>` non è HTML valido — il browser lo sposta fuori dalla
tabella e i campi smettono di essere inviati. Le colonne le fa una griglia CSS.

## Listino e operatori

A runtime il listino vive nella tabella `servizi` del database, così il
pannello di gestione può cambiarlo senza toccare il codice.
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
con i finti. Il rovescio della medaglia va tenuto presente: **quello che
succede solo contro il database vero, la suite non lo vede.** Il caso tipico
sono le relazioni SQLAlchemy: leggerne una caricata pigramente dentro una
sessione asincrona solleva `MissingGreenlet`, e succede in produzione con la
suite tutta verde. O si carica esplicitamente con `selectinload`, o non la si
tocca — per cancellare le righe collegate basta una `delete()` sulla tabella.
Le schermate del pannello vanno provate almeno una volta con
`docker compose up`. Due regole imparate a spese nostre: **niente date fisse** — usare
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
- I clienti senza email vanno avvisati a voce anche quando un operatore manca:
  su WhatsApp si potrebbe, ma fuori dalle 24 ore serve un template approvato
  da Meta, che non abbiamo.
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
