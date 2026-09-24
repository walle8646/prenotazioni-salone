# Acconciature Simone — bot prenotazioni

Il salone si chiama **Acconciature Simone**. Il nome compare in una trentina
di punti — saluto del bot, prompt, email, sito, informativa, pannello — e
sbagliarlo in metà di quelli è peggio che sbagliarlo in tutti: chi legge due
nomi diversi non sa più a chi sta scrivendo. **Nadia lavora in salone**: il
suo nome non va dato all'assistente, che infatti non ne ha nessuno. Un bot che
si presenta col nome di una persona vera fa credere a chi scrive di stare
parlando con lei.

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

python tools/prova_email.py            # prova la posta in uscita e spiega cosa non va
```

Le migrazioni non si lanciano a mano. All'avvio (`models/database.py`): se il
database è vuoto le tabelle nascono dai modelli e viene annotato come allineato;
se esiste già, riceve le migrazioni che gli mancano. Dimenticare un `alembic
upgrade head` prima di un deploy non rompeva la funzione appena aggiunta, ma
tutto: SQLAlchemy chiede al database tutte le colonne del modello, e quella
nuova non c'era ancora.

Due trappole di alembic, entrambe pagate.

**`alembic/env.py` ignora l'URL che gli passi** e usa `DATABASE_URL`. Un
`alembic upgrade` lanciato dal proprio computer credendo di puntare a un
database di prova va a toccare quello vero. Per questo i test eseguono le
migrazioni a mano, con `MigrationContext`, invece di chiamare `command.upgrade`.

**`fileConfig()` non aggiunge una configurazione di logging: la sostituisce.**
Disattiva tutti i logger già esistenti e riporta la radice a `WARN`. Da riga di
comando è innocuo, ma le migrazioni girano anche a ogni avvio dell'applicazione,
e lì "già esistenti" vuol dire ogni logger del progetto: da quel momento in
produzione non usciva più una riga, **nemmeno gli errori**, e nei log restavano
solo le righe dell'avvio. Ci abbiamo perso una serata a cercare guasti che i
log non raccontavano perché non uscivano. Ora `env.py` salta `fileConfig`
quando la connessione arriva da fuori, cioè quando è l'applicazione a ospitare
il processo ed è lei a configurare il logging.

`TESTING.md` spiega in dettaglio i modi di provare il bot senza WhatsApp.

## Come è organizzato

Il cuore è `services/conversation.py`. Riceve un messaggio, ricostruisce la
sessione da Redis, chiede a Claude cosa rispondere ed esegue le azioni JSON che
Claude richiede, con un massimo di 5 iterazioni per messaggio (tre erano poche:
chiedendo "il primo posto libero" il modello interroga più giorni di fila).

Le azioni sono `CHECK_DISPONIBILITA`, `CREA_APPUNTAMENTO`, `SPOSTA_APPUNTAMENTO`,
`CANCELLA_APPUNTAMENTO`, `STORICO_APPUNTAMENTI`, `INVIA_CODICE_VERIFICA`,
`VERIFICA_CODICE`, `PASSA_A_OPERATORE` e `CONTINUA_SUL_SITO`.

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

**Una persona per volta ha un appuntamento solo**
(`_appuntamento_futuro_di_chi_prenota()`, dentro `CREA_APPUNTAMENTO`). Senza
questo controllo la stessa persona è finita due volte sulla stessa mezz'ora con
due operatori diversi: due poltrone occupate per un cliente solo. **Per
persona e non per contatto**, da quando lo stesso numero può coprire una
famiglia: il padre che ha già il suo può comunque prenotare per il figlio, e
quello che resta impossibile è lo stesso nome due volte. Il rifiuto
sta nel codice perché "mai" non può dipendere da quanto bene il modello se lo
ricorda, ma la sessione annota anche l'appuntamento già preso
(`prossimo_appuntamento`) e il prompt lo mostra dal primo messaggio: avvisare
dopo avergli fatto scegliere servizio, giorno, ora e operatore sarebbe il modo
peggiore di dirglielo. Quanto si racconta dipende da chi scrive: su WhatsApp
data e operatore, dal sito non verificato solo che un appuntamento esiste —
altrimenti basterebbe scrivere l'email di un conoscente per sapere quando va
dal barbiere.

**Il link che porta dalla chat WhatsApp a quella del sito contiene un
gettone, non il numero** (`services/link_chat.py`, azione
`CONTINUA_SUL_SITO`). Col numero nell'indirizzo chiunque avesse quel link
*sarebbe* quel cliente: ne vedrebbe gli appuntamenti e potrebbe disdirli. E i
link si inoltrano, restano nella cronologia e nelle anteprime. Il gettone è
casuale (`secrets`), **usa e getta** — bruciato prima di restituire il numero,
così l'anteprima del messaggio non ruba il turno al cliente — e scade in un
quarto d'ora. Lo consegna WhatsApp al numero del mittente, già verificato dal
gestore: è la stessa prova d'identità del codice via email, con un passaggio in
meno. Il gettone **non arriva mai da un parametro del modello**: vale sempre e
solo il numero della conversazione, quindi un link per il numero di un altro
non è nemmeno esprimibile. Da lì la sessione del sito ha
`telefono_verificato`, che `_identita_provata()` tratta come l'email
confermata. Esiste per il costo: dal 1° ottobre 2026 ogni risposta del bot su
WhatsApp si paga a messaggio, la chat del sito no.

**Alla conferma si ricontrolla che l'orario sia libero**
(`_slot_ancora_libero()`, dentro `CREA_APPUNTAMENTO`). Visto in produzione: il
modello ha elencato fra i "liberi" un operatore che a quell'ora era occupato,
e senza questo controllo sarebbero finiti due clienti sulla stessa poltrona —
**Google accetta le sovrapposizioni in silenzio**, e il secondo se ne accorge
arrivando in salone. Vale comunque la pena anche senza errori del modello: fra
la proposta e la conferma passano minuti, e in quei minuti può prenotare
qualcun altro. Se il controllo non si può fare — Google irraggiungibile — si
prenota lo stesso: rifiutare tutto perché una verifica in più non riesce
sarebbe peggio del rischio che copre.

**Un contatto copre fino a quattro persone: chi scrive e tre familiari**
(`services/persone.py`, colonna `titolare_id` su `clienti`). Chi prenota per i
figli non ha un telefono per ciascuno, e prima quelle prenotazioni finivano
tutte sulla stessa scheda — tre tagli sullo stesso nome — mentre la regola
dell'appuntamento unico le rendeva addirittura impossibili: prenotato il
figlio, il padre non poteva più.

Un familiare è un cliente vero: ha il suo storico, il suo appuntamento, il suo
nome sul calendario dell'operatore. Quello che non ha è un contatto proprio,
e la colonna del telefono — obbligatoria e unica — prende un segnaposto
`fam:<titolare>:<n>`. **Nessuna schermata deve mostrarlo**: passa tutto da
`telefono_da_mostrare()`, perché un segnaposto scambiato per un numero manda
la receptionist a comporre cifre che non chiamano nessuno.

**Il nome della persona arriva dal modello, ma non è mai un contatto**
(`_per_chi_si_prenota()`): vale solo dentro la famiglia di chi sta scrivendo,
e chi non c'è viene creato lì dentro. Se fosse un'email o un numero,
basterebbe scrivere quello di un conoscente per prenotare a suo nome. Dal sito
prima della verifica si può **aggiungere** una persona nuova ma non
sceglierne una che c'è già: aggiungere non rivela niente, mentre riconoscere
"Luca" direbbe a chiunque abbia indovinato un indirizzo email chi c'è dentro
quella famiglia.

**Tre e non di più**, e il tetto sta nel codice (`aggiungi_familiare`): un
contatto che ne dichiara quindici non è una famiglia, è un modo per prendersi
mezza giornata di poltrone con un telefono solo — e "un appuntamento per
volta" smetterebbe di valere per chiunque abbia voglia di aggirarlo. I nomi si
confrontano in modo tollerante (`stessa_persona`): "luca" e "Luca " sono lo
stesso figlio, e trattarli come due persone brucerebbe un posto per niente.
Il familiare **nasce al momento di prenotare**, non prima: un contatto che
abbandona a metà non deve lasciarsi dietro delle persone mai esistite.

Due conseguenze da tenere a mente. Sul calendario va il nome di **chi si
siede**, con "Prenotato da ..." nella descrizione: è l'unica cosa che
l'operatore ha davanti quando il cliente entra. E l'email di conferma va
sempre al titolare — un figlio non ne ha una — ma dice **per chi è**, o chi la
riceve la legge come propria e si presenta il martedì mattina.

**Le persone si correggono dalla scheda del cliente** (`/admin/cliente/{id}`,
rotte `persone*` in `routers/admin.py`). Il nome l'ha dettato qualcuno a
voce: "Lucca" al posto di "Luca" è un posto bruciato su tre, e senza una
schermata non tornava più indietro. Da lì si rinomina, si aggiunge — il
cliente al telefono dice "e anche per mio figlio" — e si toglie. **Togliere
non è cancellare**, e la scelta la fa `cosa_fare_del_familiare()`, logica pura
coi suoi test perché sbagliarla costa: chi ha un appuntamento **in programma**
non si tocca (la scheda sparirebbe e il cliente si presenterebbe lo stesso,
con nessuno in salone che sa chi è); chi ha solo **storico** esce dal contatto
e libera il posto ma la scheda resta (buttare via gli appuntamenti già fatti
per correggere un nome sarebbe il rimedio peggiore del male); chi non ha
**niente** si cancella, perché è un nome scritto male e terrebbe occupato uno
dei tre posti per sempre. La persona si tocca solo passando dal suo titolare
(`_familiare_di()`): senza quel controllo basterebbe cambiare un numero
nell'indirizzo per rinominare il familiare di un altro cliente.

**Disdette e spostamenti valgono solo sui propri appuntamenti, e su quelli
della propria famiglia.** Gli id sono progressivi: senza il controllo
basterebbe dire "cancella il numero 3". Chi prenota per il figlio è però
l'unico che può disdirglielo, visto che il figlio un telefono non ce l'ha:
`_appuntamenti_del_richiedente` risponde per tutta la famiglia, e ogni riga
porta `per` — senza, un padre che chiede lo storico si vede tre tagli nello
stesso pomeriggio senza capire di chi.

**Chi chiede una persona la ottiene, e il bot tace**
(`services/operatore_umano.py`, schermata **Conversazioni**). Il
riconoscimento sta nel codice come `vuole_ricominciare()`, non solo nel
prompt: è l'ultima via d'uscita di chi non sta ottenendo quello che vuole, e
non può dipendere da quanto bene il modello se la ricorda in fondo a una
conversazione lunga. C'è anche l'azione `PASSA_A_OPERATORE` per i casi che
nessuna espressione fissa prevede — un reclamo, una richiesta fuori listino.

Tre cose non sono semplificabili. **"Operatore" qui vuol dire parrucchiere**:
la parola non compare fra quelle riconosciute, e se nella frase c'è il nome di
un operatore il passaggio non scatta — "vorrei parlare con Andrea" sta
scegliendo, non chiedendo aiuto. **Finché la conversazione è aperta il bot non
chiama nemmeno il modello**: due risposte diverse alla stessa domanda, una del
bot e una della receptionist, sono peggio di una risposta lenta, e il
controllo sta prima di tutto anche per non pagarle. **Un passaggio a cui
nessuno risponde entro 24 ore torna al bot**: il bot muto è una scelta, il bot
muto e nessun altro è un cliente perso. Anche "ricominciamo da capo" chiude il
passaggio, per chi cambia idea.

Lo scambio si salva in database **solo per queste conversazioni**
(`conversazioni_operatore` e `messaggi_conversazione`). Le altre restano nella
sessione Redis che scade da sé: registrarle tutte vorrebbe dire conservare
ogni parola di ogni cliente, che non è quello che l'informativa promette.

Il salone riceve un'**email** a ogni passaggio: senza, la funzione esisterebbe
solo per chi si ricorda di aprire il pannello. E la risposta dal pannello si
registra **solo se Meta l'ha accettata**: una riga che dice "risposto" quando
il messaggio non è partito è peggio di nessuna riga, perché nessuno
richiamerà quel cliente.

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

**Ma i puntini si mostrano solo se a scrivere sarà il bot.** Quando la
conversazione è in mano a una persona resta `segna_letto()`, spunte blu e
basta: "letto" è vero, "sta scrivendo" prometterebbe una risposta fra pochi
secondi che arriverà quando il salone potrà. I puntini fermi mentre non scrive
nessuno sono peggio di nessun segnale — il cliente aspetta guardando lo
schermo. La domanda la fa il webhook con `risponde_una_persona()`, che è di
sola lettura e costa una SELECT in più: deve decidere **prima** di far partire
l'elaborazione, perché un indicatore che compare tardi non serve a niente.

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
solo per tutta la settimana, non sette query), **Prenota**,
**Conversazioni**, **Clienti** (elenco con ricerca e scheda singola),
**Listino** e **Operatori** (modifica in linea, una riga per form),
**Presenze**, **Assenze**.

**Appuntamenti** mostra la giornata come la vista giornaliera di Google
Calendar: ore in verticale, una colonna per operatore, un blocco alto quanto
dura l'appuntamento e colorato per servizio, a righe le ore in cui un
operatore non è in salone. Con settanta appuntamenti un elenco non dice le due
cose che si cercano — chi è libero adesso e dove c'è un buco — e la griglia sì.
La geometria sta in `services/agenda.py`, logica pura con i suoi test: un
blocco disegnato mezz'ora fuori posto non fa fallire niente, ma fa dare il
posto a un altro. Due scelte: la giornata si **allarga** per mostrare un
appuntamento fuori orario invece di nasconderlo, perché anomalo è proprio il
motivo per cui va visto; e due appuntamenti sovrapposti nella stessa colonna
si **affiancano**, perché uno sopra l'altro il secondo sparirebbe. L'elenco
di prima resta come seconda vista (`?vista=elenco`).

**Prenota è una schermata a sé**, non un pezzo di Appuntamenti, perché
risponde a un'altra domanda: lì si guarda la giornata che c'è, qui si cerca
dove infilare chi ha telefonato. Sono anche due momenti diversi — la giornata
si apre la mattina e resta aperta, la prenotazione si fa col cliente in linea.
Le mezz'ore libere sono celle verdi: toccarne una apre il modulo già compilato
con **quando e con chi**, i due dati appena detti al telefono e i più facili
da ricopiare male. Gli appuntamenti già presi si vedono, ma spenti e non
cliccabili: dicono dove **non** c'è posto, e a pieno colore coprirebbero il
verde che si sta cercando. La griglia la costruisce una funzione sola
(`_giornata()`), perché due schermate che la disegnano per conto loro prima o
poi dicono due cose diverse sullo stesso orario — e quella su cui si prenota è
sempre l'altra.

**In cima ci sono quattro mesi interi, non un campo "vai a un'altra data".**
Quello sapeva portare da qualche parte, ma non dove conveniva andare: per
trovare il primo giorno scarico si tiravano a indovinare date una per volta.
Ogni casella porta sotto il numero una barretta lunga quanto il suo carico,
**relativo al giorno più pieno della finestra** e non a una capienza teorica —
le poltrone cambiano con le presenze, e una percentuale calcolata su una
capienza sbagliata direbbe "pieno" dove c'è posto. La domanda vera è "dove c'è
meno gente". I giorni di chiusura non sono cliccabili: mandare a cercare posto
di domenica fa perdere tempo a chi ha il cliente in linea. Il conteggio dei
sessanta giorni è **una query sola** (`_carico()`), per lo stesso motivo per
cui la striscia dei sette giorni ne fa una.

**I quattro mesi sono fissi e partono sempre da oggi**, non dal giorno che si
sta guardando. Servono a farsi confrontare a colpo d'occhio, e un calendario
che scorre di un mese ogni volta che si tocca una data costringe a ritrovarsi
prima di poterlo leggere: si perde proprio la cosa per cui esiste. Il giorno
scelto si accende dov'è, se cade dentro la finestra; oltre, la griglia sotto
funziona lo stesso. Quattro perché è quanto avanti si prenota davvero un
parrucchiere, e perché in riga ci stanno su uno schermo normale — a coppie
quando non ci stanno. Sul telefono impilati sarebbero novecento pixel prima di
arrivare alla griglia, quindi lì partono **chiusi** dietro una riga da toccare:
sotto i 760 pixel un `<details>` che una riga di JS chiude all'avvio, perché
aprirlo e richiuderlo dopo farebbe saltare la pagina. Con un operatore scelto il carico
è **il suo**, non quello del salone: altrimenti i calendari direbbero che
giovedì è pieno mentre lui è libero tutto il giorno.

**Le chips in cima cambiano il significato delle colonne.** Con "Tutti" si
guarda una giornata, una colonna per operatore. Scegliendo una persona si
guarda la sua **settimana**: sette giorni, una colonna per giorno, e le frecce
spostano di sette in sette. Risponde alla domanda che la giornata non sa
reggere — "quando me lo dai con Andrea?" — che altrimenti vuol dire aprire
sette schermate per scoprire che il primo posto è giovedì. **Toccando un
giorno sui calendari si scende su quel giorno solo** (`vista=giorno`), con
quell'operatore in una colonna sola o con tutti se non ne è scelto nessuno: le
due viste si dichiarano con un interruttore, invece di dipendere da come ci si
è arrivati. L'operatore scelto
**resta** cambiando settimana (`filtro` in `_striscia()`): perderlo a ogni
freccia renderebbe le chips inservibili proprio mentre si cerca un posto per
quella persona.

La geometria è `costruisci_settimana()`, e restituisce **la stessa forma** di
`costruisci_agenda()` perché il template disegni la griglia una volta sola:
due markup per la stessa cosa divergono, e uno dei due finisce per mostrare i
blocchi mezz'ora fuori posto. Tre scelte che hanno i loro test. Niente linea
dell'ora corrente: attraverserebbe sette giorni e in sei non vorrebbe dire
niente, quindi oggi si riconosce dalla sua colonna. Un giorno di chiusura è
tutto a righe anche se l'operatore avrebbe le sue fasce — il salone chiuso
viene prima di chi ci lavora. E la casella verde porta l'operatore scelto,
non l'intestazione della colonna, che lì è una data: senza, si prenoterebbe
con "Mer 23". Le sette domande a Google partono **insieme** (`asyncio.gather`)
e su un calendario solo: sette chiamate, non quarantadue.

I posti liberi arrivano da **Google e non dal database**, e non perché i due
siano disallineati: per tutto quello che passa dal bot o dal pannello si
scrive sempre su entrambi. È il contrario a non valere. Quello che il salone
segna a mano sul calendario dal telefono — una pausa, una commissione, un
cliente arrivato senza appuntamento — occupa la poltrona, e il database non ne
sa niente. Google è anche la fonte che il bot consulta e che `_slot_ancora_libero()`
ricontrolla al momento di confermare: leggendo il database si offrirebbero
orari che il controllo finale rifiuta, dopo aver fatto compilare tutto il
modulo. Il filtro delle presenze si applica anche qui (`solo_chi_e_in_salone`),
o il verde comparirebbe sopra le righe di chi quel giorno non c'è: **il
calendario dice se è occupato, non se lavora.** Separare le due schermate ha
anche fatto sparire sei chiamate a Google da Appuntamenti, che si tiene aperta
per ore.

**Quando di verde non ce n'è, la pagina dice perché.** Giornata finita,
calendari illeggibili e giornata piena si somigliano solo a guardarli, e chi
guarda conclude sempre il terzo: `_dove_c_e_posto()` restituisce anche la
frase da mostrare. Quello grave è il secondo — un guasto letto come "siamo
pieni" fa mandare via un cliente che il posto ce l'aveva. Per lo stesso motivo
l'ora dentro la cella verde **si legge sempre**: nascosta fino al passaggio
del mouse, una giornata piena di posti liberi sembrava una giornata vuota.

La creazione passa dalle **stesse funzioni del bot** (`find_or_create_client`,
`create_event`, `create_appointment`, la conferma per email): due strade per
creare la stessa cosa divergono al primo cambiamento, e una delle due smette
di mandare le email senza che nessuno se ne accorga. Restano validi il
ricontrollo dello slot e la durata decisa dal listino. **Cade invece la regola
dell'unico appuntamento per cliente**: esiste perché il modello sbagliava da
solo, mentre chi prenota a mano ha la persona al telefono.

**Il modulo comincia dalla ricerca, non da campi vuoti**, perché chi telefona
quasi sempre è già stato qui: due schede per la stessa persona vogliono dire
uno storico spezzato e il bot che non la riconosce più quando scrive su
WhatsApp. Il cliente nuovo sta dietro un bottone — è il caso meno frequente,
non quello che conta meno. Le due strade non sono mai aperte insieme: i campi
di quella chiusa restano `disabled`, così non vengono nemmeno inviati e il
server non deve indovinare quale delle due valeva.

**Chi si sceglie dall'elenco viaggia come id, non come numero**
(`cliente_per_id()`). Ritrovarlo per telefono lo perderebbe proprio nei casi
che contano: chi è arrivato dal sito ha per telefono un identificativo di
sessione, e chi non l'ha mai lasciato non ne ha nessuno — in tutti e due i
casi `find_or_create_client` aprirebbe una seconda scheda proprio mentre lo si
stava riconoscendo. Nome ed email per l'evento e per la conferma si
riprendono dall'anagrafica, non da quello che è rimasto scritto nei campi. Un
id che nel frattempo non esiste più **ferma** la prenotazione: una riga in
agenda senza nome è peggio di un rifiuto.

Due trappole del popup, tutte e due pagate guardandolo storto in produzione.
**Una finestra modale la centra il browser con `margin: auto`**, e il reset in
cima al foglio di stile (`* { margin: 0 }`) glielo toglie: restava incollata
in alto a sinistra e alta quanto lo schermo. E **la larghezza naturale di un
`<select>` è quella della sua voce più lunga** — "Taglio + Shampoo +
Trattamento barba con oli e panno bagnato": dentro una griglia bastava quella
a spingere tutto il modulo fuori dalla finestra, con i campi tagliati a metà.
Da qui `min-width: 0` sugli elementi del modulo.

**Conversazioni** mostra chi sta aspettando una risposta da una persona, con
lo scambio già avuto col bot e una casella per rispondere via WhatsApp.

**Le due schermate hanno la forma di una chat**, perché chi risponde usa
WhatsApp tutto il giorno e ritrovare le stesse forme vuol dire non dover
imparare niente: l'elenco ha faccia, ultima frase e ora; la conversazione ha
le bolle, il cliente a sinistra e noi a destra, la casella in fondo. Le tinte
restano quelle del pannello: far finta di essere WhatsApp confonde chi passa
dall'una all'altro. Il **bot sta dalla nostra parte ma in una bolla più
pallida e col nome sopra** — confonderlo con la receptionist vorrebbe dire non
sapere più chi ha detto cosa al cliente. Il numero sulla riga è **quanti
messaggi del cliente aspettano risposta**, non quanti ce ne sono in tutto: è
l'unico che dice se qualcuno sta aspettando. Le anteprime costano **una query
per tutte** le conversazioni e non una per riga (`_aggiungi_anteprime`).

**La conversazione si aggiorna da sola ma non si ricarica.** Un refresh della
pagina intera cancellerebbe la risposta che la receptionist sta scrivendo,
proprio nell'unico momento in cui è al lavoro: la pagina chiede ogni otto
secondi solo i **messaggi arrivati dopo l'ultimo che ha già**
(`/admin/conversazioni/{id}/messaggi?dopo=`), e li aggiunge in fondo. Si
inseriscono con `textContent` e non con `innerHTML`, perché quel testo l'ha
scritto un cliente. L'elenco invece si ricarica per intero ogni trenta
secondi: lì non c'è niente da perdere. Entrambi si fermano quando la scheda è
in secondo piano. La
schermata dichiara **quanto manca alla chiusura della finestra di 24 ore** e
toglie la casella quando è passata: fuori da quella finestra Meta accetta solo
template approvati, che non abbiamo, e far scrivere una risposta per poi
rifiutarla dopo l'invio è il modo peggiore di dirlo. Chiudere la conversazione
la restituisce al bot e non manda niente al cliente — un "da adesso ti risponde
il bot" scritto tre ore dopo è un messaggio senza contesto.

**Il pannello si installa sul telefono e suona.** Manifest e service worker
stanno alla **radice** (`/manifest.webmanifest`, `/sw.js`) e non sotto
`/static/`: un service worker comanda solo sul percorso da cui è stato
scaricato, e da `/static/` non vedrebbe `/admin` — cioè proprio le pagine per
cui esiste. `start_url` è **Conversazioni**, perché chi installa questa
applicazione lo fa per rispondere a chi aspetta.

Le notifiche (`services/push.py`, tabella `iscrizioni_push`) partono quando un
cliente chiede una persona e a ogni suo messaggio successivo: l'email c'era
già, ma la posta si guarda la sera. Servono `VAPID_PUBLIC_KEY` e
`VAPID_PRIVATE_KEY`, generate una volta con `python tools/chiavi_push.py`;
**cambiarle disiscrive tutti i telefoni**. Tre cose non sono semplificabili.
Un invio fallito **non esce mai** da `avvisa()`: chi la chiama sta passando una
conversazione a una persona, e quella deve riuscire comunque — c'è un test che
fa esplodere la notifica apposta. Un'iscrizione rifiutata con 404 o 410 si
**cancella**: è un telefono che non c'è più, e tenerla vorrebbe dire ritentare
per sempre. E su **iOS le notifiche arrivano solo all'applicazione aggiunta
alla schermata Home**: dal browser il permesso non si può nemmeno chiedere,
quindi il bottone lo dice invece di non fare niente.

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

Sulla stessa schermata si cambiano gli **orari del salone** e si segnano i
**giorni di chiusura**. Gli orari stavano in una costante e cambiarli voleva
dire un deploy; ora vivono nella tabella `orari_salone` e a runtime si leggono
da una copia in memoria, come listino e operatori. Tre conseguenze da tenere a
mente.

**Un giorno chiuso è una riga con gli orari a NULL, non l'assenza di righe.**
Serve a distinguere "chiuso il lunedì" da "nessuno ha ancora configurato
niente": senza, chiudere tutta la settimana dal pannello la farebbe riempire di
nuovo al riavvio con gli orari del codice — lo stesso difetto già pagato con
`seed_parrucchieri`.

**Gli orari li dichiara una fonte sola.** Il prompt (`orari_in_parole()`) e il
sito (`orari_a_coppie()`) leggono gli stessi dati che generano la
disponibilità. Scritti a mano in tre posti, cambiarli dal pannello faceva dire
al bot un orario e proporne un altro — e il cliente crede a quello che legge.

**Le chiusure straordinarie le applica `generate_slots()`**, non i chiamanti:
tutto passa da lì, `is_open()` compreso, e un controllo in più altrove sarebbe
uno da dimenticare. Chiudere un giorno **non avvisa** chi aveva già prenotato:
per quello serve **Assenze**, operatore per operatore. Annullare in silenzio
sarebbe il danno peggiore.

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

**Il menù sta a sinistra e si riduce a icone** (`templates/base.html`,
`.barra` nel foglio di stile). In cima rubava una fascia a tutta larghezza per
dieci parole, e la cosa che su questo pannello serve di più è lo spazio in
verticale: la griglia della giornata ci sta dentro per intero. Ridotto resta
largo quattro dita e le voci restano raggiungibili — nascosto del tutto
costringerebbe ad aprirlo a ogni passaggio. La scelta si ricorda in
`localStorage` e **si applica prima che la pagina si disegni**, con lo script
in cima al `<body>`: messa dopo, la barra si stringerebbe sotto gli occhi di
chi sta già leggendo. Sul telefono la barra esce dallo schermo e si richiama
col bottone: una colonna fissa larga quattro dita su 375 pixel lascerebbe al
contenuto meno della metà. Le icone sono un foglio di `<symbol>` solo,
richiamate per nome: disegnate dentro ogni voce sarebbero dieci copie da
ritrovare una per una.

**I colori vengono dalle fotografie del salone, non dal gusto di nessuno.**
Il verde è quello della pelle delle poltrone — tinta 190°, misurata su
`poltrona-1600.jpg` — e l'arancio è la luce calda dietro, tinta 32°. Nelle
foto l'arancio è chiaro perché è luce: nella tavolozza è portato a metà
luminosità per poterci scrivere sopra, ma la tinta è quella. Stanno tutti in
`:root` come variabili (`--verde-scuro`, `--verde`, `--verde-vivo`,
`--arancio`): chi cambia una tinta la cambia lì, non nelle duemila righe
sotto. Due regole che tengono: **il rosso resta solo per gli errori**, perché
è l'unico colore che qui vuol dire "attenzione" e usarlo per il marchio lo
renderebbe muto; e **il verde è la struttura, l'arancio è quello che si
tocca** — barra, intestazioni e stato in verde; bottoni, voce di menù dove si
è, linea dell'ora corrente e barrette del carico in arancio. Divisi così si
riconoscono senza leggere.

La prima versione teneva l'arancio per tre filetti sottili e il resto tutto
verde scuro: sullo schermo somigliava al blu di prima e il cambio **non si
vedeva**. Da lì una regola che vale oltre questo pannello: un colore usato
solo nei dettagli non cambia niente, perché quello che decide di che colore
sembra una schermata sono le due o tre superfici più grandi — qui il fondo
della pagina e la barra. L'arancio dei bottoni è più scuro di quello delle
foto per un motivo misurabile: sul chiaro il bianco sopra stava a 2,9 contro
1, sotto la soglia di leggibilità; così sta a 4,9, e la tinta è la stessa. Il
`theme_color` del
manifest è lo stesso verde: installata sul telefono, la cornice la disegna il
sistema, e un blu rimasto indietro si vedrebbe attaccato al menù.

Le righe di modifica non sono in una tabella: ogni riga è un form a sé, e un
`<form>` dentro un `<tr>` non è HTML valido — il browser lo sposta fuori dalla
tabella e i campi smettono di essere inviati. Le colonne le fa una griglia CSS.

**Sotto i 760 pixel le tabelle diventano schede, una per riga.** L'intestazione
non sta più in cima ma dentro ogni cella, nel `data-label` che il CSS mostra con
`::before`: sette colonne su un telefono non si leggono, e lo scorrimento
orizzontale nasconde sempre proprio quella che serve. Chi aggiunge una colonna
deve aggiungere anche il suo `data-label`, altrimenti su telefono quel valore
compare senza sapere cos'è. Nella stessa fascia il menù va a capo invece di
uscire dallo schermo, le righe di modifica si impilano, e i campi passano a 16
pixel: sotto quella misura iOS ingrandisce la pagina appena si tocca un campo e
poi la lascia ingrandita. Verificato a 375 e a 320 pixel su tutte e nove le
schermate, misurando che niente sbordi — a occhio non si vede, e uno screenshot
può mentire.

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
Giava, Bario. **Nadia non è fra loro e non è una dimenticanza**: sta alla cassa
e gestisce gli appuntamenti, non riceve clienti. Aggiungerla vorrebbe dire
farla comparire fra le scelte del bot e nelle colonne dell'agenda, cioè offrire
ai clienti un appuntamento con chi non taglia i capelli. Il pannello è suo, il
calendario no. Ognuno ha un calendario Google dedicato, creato l'8 agosto 2026 e
di proprietà dell'account `parrucchiere.bot.test@gmail.com`, con il service
account come `writer`. L'associazione nome → id sta in `GCAL_PARRUCCHIERE_IDS`,
**oggetto JSON, non lista**: con la lista i nomi non sono noti, la mappa resta
vuota e ogni operatore risulta non configurato.

Orari: **martedì-sabato 9:00-19:00 continuato**, chiuso domenica e lunedì. Slot
da 30 minuti. Fino a settembre 2026 il codice diceva 8:00-12:00 e 14:30-19:30,
che il salone non ha mai fatto: adesso quelli scritti in `ORARI_APERTURA` sono
solo i valori iniziali, e a comandare è la tabella che si modifica da
**Presenze**.

## Email

Si spedisce via SMTP dalla casella del salone (`SMTP_*`), non da un servizio
esterno: il mittente è l'indirizzo che i clienti conoscono e le risposte
arrivano dove qualcuno le legge. Con Gmail serve una **password per le app**, non
quella dell'account. Senza configurazione le funzioni escono subito senza
errori, e un invio fallito non fa mai fallire una prenotazione.

Partono cinque messaggi: conferma, spostamento, annullamento, codice di
verifica e l'avviso al salone quando un cliente chiede di parlare con una
persona. Le date vanno scritte con `_quando()`, che le rende in italiano: i nomi
di giorni e mesi sono nel codice perché nel container non c'è il locale.

**Il piano gratuito di Render blocca il traffico SMTP in uscita** — porte 25,
465 e 587, per politica loro contro lo spam. Lì `smtplib` non fallisce il
login: non riesce proprio ad aprire la connessione, e nei log si legge
`[Errno 101] Network is unreachable`. Sul gratuito quindi **nessuna email è mai
partita in produzione**: né le conferme, né gli annullamenti, né i codici di
verifica — e senza codice, dal sito lo storico non si sblocca. Serve un piano a
pagamento (porta 25 resta chiusa comunque, 465 e 587 no), oppure un servizio
che spedisca via HTTPS. Si è scelto il piano a pagamento per non perdere il
mittente: le risposte dei clienti devono arrivare nella casella del salone.

Da qui una regola imparata a caro prezzo: **"funziona in locale" non è "funziona
in produzione"**, e per l'email la differenza non era una configurazione ma la
rete della piattaforma. `python tools/prova_email.py` manda un messaggio di
prova e traduce il guasto in italiano: va lanciato **dalla shell di Render** a
ogni cambio di casella, non solo dal proprio computer.

**465 e 587 non sono due porte per la stessa cosa** (`_connessione()`). Sulla
465 il canale è cifrato dal primo byte — SSL implicito, `smtplib.SMTP_SSL` —
mentre sulla 587 si parte in chiaro e si sale a TLS con `starttls()`.
Scambiarle non dà un errore di protocollo che si legge nei log: la connessione
resta appesa fino al timeout, l'eccezione viene inghiottita perché un'email non
deve far fallire una prenotazione, e il risultato è identico alle porte
bloccate — silenzio. Decide la porta, così cambiare fornitore non vuol dire
cambiare codice: **Gmail 587 con STARTTLS, Aruba 465 con SSL**.

Con una casella Aruba sul dominio del salone i parametri sono
`smtps.aruba.it:465`, e l'utente è **l'indirizzo per intero**, non la parte
prima della chiocciola. La porta 25 resta inutile comunque: Render la blocca
anche a pagamento.

**Partita non vuol dire consegnata.** Con un mittente sul proprio dominio
servono tre record nelle DNS, o le conferme finiscono nella posta
indesiderata: **SPF** (`v=spf1 include:_spf.aruba.it ~all`), **DKIM** — la
chiave la dà il pannello di chi ospita la casella — e **DMARC**
(`v=DMARC1; p=none; rua=mailto:...`, che si irrigidisce dopo aver guardato i
rapporti per qualche settimana). È lo stesso tipo di guasto delle porte
bloccate: nessun errore da nessuna parte, e il cliente che non ha ricevuto
niente non lo dice, semplicemente non si presenta.

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

## Stato al 5 settembre 2026

Il bot è **pubblicato su Render e funzionante su un numero italiano vero**
(+39 351 639 5494): chiunque può scrivergli, non più solo cinque destinatari
autorizzati a mano. Prenota, sposta, disdice, mostra lo storico, riconosce i
clienti abituali e passa la conversazione a una persona quando gliela
chiedono, scrivendo davvero sui calendari Google e mandando email che
arrivano. 314 test.

Provato sul campo: Google Calendar (sei calendari veri, eventi creati, spostati
e cancellati), il widget del sito, il database e **WhatsApp**, che risponde da
un telefono vero con testo e bottoni.

**L'invio email era provato solo in locale.** In produzione non è mai partito
niente, perché il piano gratuito di Render blocca le porte SMTP: vedi la
sezione Email. Si passa a un piano a pagamento.

Non ancora provata contro il database vero: la schermata **Conversazioni**. La
suite gira sui finti e lì non si vede quello che succede solo con Postgres —
`docker compose up` e un giro a mano prima di fidarsene.

Cosa cambia col piano a pagamento, oltre all'email: il servizio non si sospende
più per inattività — niente attesa di una trentina di secondi al primo messaggio
dopo una pausa — e i promemoria a 12 ore diventano possibili, perché serviva un
processo sempre acceso. Resta invece il disco effimero: le foto salvate da
`services/storage.py` spariscono a ogni deploy, ed è il motivo per cui quelle
degli operatori stanno nel database.

## Cose note ancora da fare

- **La verifica dell'azienda non è ancora fatta.** Senza, il limite è di 250
  conversazioni al giorno avviate dal salone (le risposte a chi scrive per
  primo non contano, e ne sono incluse 1.000 al mese), e soprattutto non si
  possono usare i **template**. Servono per i promemoria, per gli avvisi di
  assenza e per riscrivere a un cliente dopo che sono passate 24 ore dal suo
  ultimo messaggio — cioè le tre cose che oggi mancano.
- **Chi è in salone viene avvisato solo per email** quando un cliente chiede di
  parlare con una persona. Le alternative sono state valutate e scartate per
  ora: su WhatsApp servirebbero un metodo di pagamento e un template approvato
  (è una conversazione avviata dall'azienda, e col template il messaggio del
  cliente non ci sta dentro per intero); Telegram sarebbe gratuito e immediato
  ma richiede che il personale ce l'abbia; gli SMS costano di più e dicono meno.
- **Il titolare nell'informativa privacy è solo "Acconciature Simone"**
  (`TITOLARE_PRIVACY` in `routers/website.py`): va completato con ragione
  sociale, sede e partita IVA.
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
(id `1493423639206303`) e il numero **+39 351 639 5494** (eSIM iliad, id
`1321638091031766` in `META_PHONE_NUMBER_ID`), sull'account WhatsApp Business
`Salone Simone Nadia`, id `1743717593345386`. Il token è di un utente di
sistema e non scade.

**Il nome visualizzato su WhatsApp è l'unico che non si cambia da qui.** Il
salone si chiama **Acconciature Simone** e così si presenta in ogni messaggio,
email e pagina; l'account su Meta è ancora registrato come "Salone Simone
Nadia". Il nome visualizzato si cambia dal Business Manager e **lo riapprova
Meta**, quindi resta indietro qualche giorno — ed è quello che il cliente
legge in cima alla conversazione, prima ancora di aprirla.

Il numero di prova americano `+1 555-201-1459` e il vecchio account
`1687123500082794` non si usano più: quello era un **Test WhatsApp Business
Account**, e su quelli un numero vero non si può aggiungere — il bottone
"Aggiungi numero" resta spento senza spiegare perché.

Quattro cose costate una serata, perché danno tutte lo stesso sintomo —
silenzio totale, spunte grigie — e sembrano già fatte quando non lo sono.

**L'app dev'essere pubblicata.** Finché è "Non pubblicata", Meta non consegna
al webhook **nessun** messaggio di produzione, nemmeno quelli
dell'amministratore. L'invio dall'API continua a funzionare, quindi sembra un
problema del server. Per pubblicare serve l'URL di un'informativa privacy e un
indirizzo **diverso** per le istruzioni di cancellazione dati: sono `/privacy` e
`/cancellazione-dati`, serviti dal bot stesso.

**Configurare l'endpoint del webhook e sottoscrivere il campo `messages` sono
due interruttori diversi.** Col secondo spento Meta prende in carico i messaggi
e non ne inoltra nessuno, senza segnalare niente da nessuna parte.

**`META_PHONE_NUMBER_ID` è l'id del numero, non quello dell'account.** Si
somigliano e stanno nella stessa schermata. Con quello sbagliato ogni invio
torna `code 100, subcode 33`, e dato che fallisce anche la conferma di lettura
le spunte restano grigie — cioè il sintomo di un messaggio mai arrivato, non di
una risposta mai partita. Il valore giusto si legge con
`GET /{WABA_ID}/phone_numbers`.

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

**Le credenziali Google si provano all'avvio** (`credenziali_utilizzabili()`,
chiamata da `main.py`). Esiste per un guasto già successo, e la catena vale la
pena di essere ricordata. La chiave del service account era **malformata** —
valori derivati (dp, dq, qinv) sbagliati — ma `google-auth` senza
`cryptography` installata usa il lettore in puro Python, che li **ricalcola da
sé** e stampa solo un avviso: per settimane ha funzionato tutto. Poi
`pywebpush`, aggiunto per le notifiche, si è portato dietro `cryptography`, che
è severa e la rifiuta con `Invalid private key`: da quel momento **ogni**
CHECK_DISPONIBILITA è fallito, il cliente leggeva "problema tecnico
momentaneo" e il bot passava a una persona. Due lezioni: una dipendenza nuova
può cambiare il comportamento di una vecchia senza che nessuna riga di codice
nostro cambi, e un guasto che blocca tutto deve **gridare all'avvio** invece di
sussurrare a ogni prenotazione.

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
