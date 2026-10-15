# Collegare il numero del salone lasciandolo sul telefono

Procedura da fare una volta sola, con una persona del salone col telefono in
mano. Il numero resta sull'app WhatsApp Business: la Cloud API risponde sullo
stesso numero, e chi e' in salone continua a scrivere dall'app.

Due cose che **non** servono, e che fanno risparmiare giorni: il nome
visualizzato **non va riapprovato** da Meta, e il numero **non va registrato**
— e' gia' registrato, ed e' tutto il punto della coexistence.

L'app Meta da usare e' **Qubi Prenotazioni** (`1777155376858795`). Non se ne
crea una nuova: l'accesso avanzato ai permessi e l'identificazione come Tech
Provider valgono per quella app, non per l'account, e una app nuova nascerebbe
con accesso standard — da rifare analisi e verifica dell'accesso.

---

## 1. Prima di uscire di casa (nel pannello di Meta)

- [ ] **Facebook Login for Business → crea una configurazione.** Ne esce un
      `config_id`: e' quello che apre il flusso.
- [ ] Nelle impostazioni di Facebook Login for Business, fra **Allowed
      domains** e **Valid OAuth redirect URIs**, aggiungi
      `https://simoneacconciature.it`. Senza, il flusso arriva alla fine e non
      restituisce ne' il codice ne' gli id — e sembra un difetto nostro.
- [ ] **WhatsApp → Configurazione**: callback
      `https://salone-nadia-bot.onrender.com/webhook/whatsapp`, con lo stesso
      valore che il servizio ha in `META_VERIFY_TOKEN`. Quell'indirizzo resta
      valido e non va dismesso: cambiarlo e' il modo classico di restare senza
      messaggi in arrivo senza capire perche'.
- [ ] Iscrivi i campi: `messages`, `account_update`, `smb_message_echoes`,
      `history`, `smb_app_state_sync`. Configurare la URL e iscrivere i campi
      sono **due interruttori diversi**: col secondo spento Meta prende in
      carico i messaggi e non ne inoltra nessuno, senza segnalare niente.
- [ ] Segnati la **chiave segreta** dell'app (*Impostazioni → Di base*).

## 2. Prima di uscire di casa (su Render)

- [ ] Fai arrivare online il codice di questa modifica, e controlla con
      `/health` che il commit sia davvero quello.
- [ ] Aggiungi tre variabili d'ambiente:
      `META_APP_ID`, `META_APP_SECRET`, `META_ES_CONFIG_ID`.
      Senza, la pagina lo dice e il bottone resta spento — che e' meglio di un
      flusso avviato per niente, visto che il codice si puo' chiedere poche
      volte.
- [ ] Apri `https://simoneacconciature.it/admin/collega-whatsapp` e controlla
      che il bottone sia attivo. **Non premerlo**: premilo in salone.

## 3. Prima di cominciare, in salone

- [ ] **WhatsApp Business aggiornata**: serve almeno la **2.24.17**. Da fare
      prima, non durante.
- [ ] Il numero non deve essere **gia' collegato** alla Business Platform. Se
      lo e': *Impostazioni → Account → Business Platform → Disconnetti*, e poi
      **15 minuti di attesa** prima di riprovare.
- [ ] Un messaggio di Simone che dice di procedere: nel flusso accetti le
      condizioni di WhatsApp Business **per conto loro**.
- [ ] Decidi **in quale portfolio** finisce l'account. Deve essere quello del
      salone, con te amministratore, oppure uno che crei tu intestato al
      salone con la loro ragione sociale esatta: la verifica dell'azienda —
      quella che sblocca i template, cioe' promemoria e avvisi di assenza — si
      fara' su quel portfolio con i loro documenti, e un nome che non combacia
      viene rifiutato.

## 4. La procedura

Dieci minuti, tu al browser e loro col telefono. Non si puo' spezzare in due
momenti: le due schermate devono stare aperte insieme.

1. Apri `https://simoneacconciature.it/admin/collega-whatsapp` e premi
   **Avvia il collegamento**.
2. Accedi con il tuo account Facebook e scegli il portfolio.
3. **Fermati se non vedi la scelta per collegare un account WhatsApp Business
   che esiste gia'.** Se propone solo di crearne uno nuovo, chiudi la
   finestra: quella strada registra il numero e lo **toglie dal telefono**. In
   quel caso riprova con
   `.../admin/collega-whatsapp?feature=coexistence` oppure
   `.../admin/collega-whatsapp?feature=` (senza niente): il nome di quella
   variante Meta lo ha gia' cambiato una volta.
4. Inserisci il numero del salone.
5. Sul loro telefono arriva un messaggio da Facebook. Devono toccare
   **Connect**, poi **Connect to the Business Platform**, poi **Confirm**.
   Quel bottone funziona solo dentro la loro chat: inoltrato e' solo
   un'immagine.
6. Il codice si scrive nella finestra del browser.
7. Non chiudete l'app finche' non ha finito di sincronizzare.

**Un codice sbagliato o richiesto troppe volte blocca tutto per circa 12 ore.**
Meglio una volta con calma che tre di corsa.

Sulla cronologia: alla voce *Confirm* possono scegliere se condividere le
conversazioni passate. Noi non la chiediamo e non abbiamo dove metterla — e
comunque si potrebbe chiedere **una volta sola ed entro 24 ore**
dall'attivazione, quindi per riaverla servirebbe scollegare e rifare.

## 5. Appena finito

- [ ] La pagina mostra `META_PHONE_NUMBER_ID` e `META_WA_TOKEN`: copiali nelle
      variabili d'ambiente su Render. Finche' non li cambi, il bot continua a
      rispondere dal numero di prima.
- [ ] Controlla nella pagina che fra le **app iscritte all'account** ci sia
      *Qubi Prenotazioni*, e non solo *WA DevX Webhook Events 1P App*, che e'
      di Meta.
- [ ] Controlla che l'id del numero sia quello **del numero** e non quello
      dell'account: si somigliano. La pagina legge quello giusto da Meta, ma
      vale un'occhiata — con quello sbagliato ogni invio torna
      `code 100, subcode 33`, e dato che fallisce anche la conferma di lettura
      le spunte restano grigie, cioe' il sintomo di un messaggio mai arrivato.

## 6. Le due prove che contano

- [ ] **Scrivi al numero del salone dal tuo telefono.** Deve arrivare la
      risposta del bot, dal numero del salone.
- [ ] **Fai rispondere Nadia dall'app, nella stessa conversazione.** Da quel
      momento il bot deve tacere su quel numero, e nel pannello
      **Conversazioni** deve comparire la conversazione con scritto quello che
      ha risposto lei. E' la prova che decide se si puo' stare online sul
      numero del salone: senza, il cliente riceve due risposte diverse alla
      stessa domanda.

## 7. Il numero di prima

Il numero dedicato **+39 351 639 5494** resta acceso sull'app `salone-nadia`.
Il bot risponde sempre e solo dal numero in `META_PHONE_NUMBER_ID`, quindi
dopo il cambio i messaggi arrivati sul numero vecchio vengono **ignorati** —
scelto cosi' di proposito: una risposta che arriva da un numero diverso da
quello a cui hai scritto e' peggio di nessuna risposta.

Da decidere con calma, non stasera: spegnere quel numero (togliendo
l'iscrizione dell'app `salone-nadia` al suo account) oppure tenerlo, che
vorrebbe dire far rispondere il bot da due numeri e quindi un lavoro in piu'.
