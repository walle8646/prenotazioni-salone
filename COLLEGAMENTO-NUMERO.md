# Passare il bot sul numero del salone — passo per passo

Il numero resta sull'app WhatsApp Business del salone e la Cloud API risponde
sullo stesso numero: Meta la chiama **coexistence**. Chi e' in salone continua
a scrivere dall'app come sempre, e il bot si fa da parte quando lo fa.

Due cose che **non** servono, e che fanno risparmiare giorni: il nome
visualizzato **non va riapprovato** da Meta, e il numero **non va registrato**
— lo e' gia', ed e' tutto il senso della coexistence.

L'app Meta da usare e' **Qubi Prenotazioni** (`1777155376858795`), intestata a
Qubi Lab. Non se ne crea una nuova: l'accesso avanzato ai permessi e
l'identificazione come Tech Provider valgono **per quella app**, non per
l'account, e una app nuova nascerebbe con accesso standard — da rifare analisi
e verifica dell'accesso da zero.

Le parti **A** e **B** le fai da solo quando vuoi. La **C** richiede una
persona del salone col telefono in mano, e dura dieci minuti.

---

## A. Nel pannello di Meta

Da `developers.facebook.com/apps`, aperta l'app **Qubi Prenotazioni**.

### A1. Accendi gli interruttori del login

1. Vai su **Facebook Login for Business → Settings → Client OAuth settings**.
2. Metti su **Yes** tutti e sei:
   - Client OAuth login
   - Web OAuth login
   - Enforce HTTPS
   - Embedded Browser OAuth Login
   - Use Strict Mode for redirect URIs
   - **Login with the JavaScript SDK** ← senza questo la nostra pagina non
     apre proprio niente
3. In **Allowed domains for the JavaScript SDK** aggiungi:
   `https://simoneacconciature.it`
4. In **Valid OAuth redirect URIs** aggiungi tutte e due:
   - `https://simoneacconciature.it/`
   - `https://simoneacconciature.it/admin/collega-whatsapp`
5. Salva.

> Se questi campi restano vuoti il flusso arriva fino in fondo e poi **non
> restituisce ne' il codice ne' gli id**: sembra un difetto del nostro server,
> e si perde un tentativo.

### A2. Crea la configurazione del flusso

6. Vai su **Facebook Login for Business → Configurations**.
7. Premi **Create from template** e scegli
   **"WhatsApp Embedded Signup Configuration With 60 Expiration Token"**.
   (In alternativa **Create configuration** → variante di login
   **WhatsApp Embedded Signup**.)
8. Nei prodotti scegli **WhatsApp**. Fra gli asset e i permessi **togli tutto
   quello che non useremo** — cataloghi, pagine, pubblicita': ogni voce in piu'
   e' una schermata in piu' che il cliente deve accettare.
9. Cerca, nella configurazione, l'opzione che riguarda il **collegamento di un
   account WhatsApp Business gia' esistente** (coexistence / WhatsApp Business
   app onboarding) e **accendila**. Il nome esatto non te lo so dire: Meta l'ha
   gia' cambiato una volta. Se non la trovi, vai avanti lo stesso — al punto C5
   c'e' come rimediare dalla URL.
10. Salva e **copia il Configuration ID**.

### A3. Prendi la chiave segreta

11. **Impostazioni → Di base**: copia **ID app** e **Chiave segreta**
    (bottone *Mostra*).

### A4. Configura il webhook

12. Vai su **WhatsApp → Configurazione**, sezione Webhook, **Modifica**.
13. URL di callback:
    `https://salone-nadia-bot.onrender.com/webhook/whatsapp`
14. Token di verifica: **lo stesso valore** che il servizio ha gia' in
    `META_VERIFY_TOKEN` su Render. Devono coincidere carattere per carattere,
    o la verifica non passa.
15. Salva (Meta chiama subito l'indirizzo per verificarlo: deve rispondere
    **Verificato**).
16. Sempre li', **Gestisci** i campi, e iscrivi questi cinque:
    - `messages`
    - `account_update`
    - `smb_message_echoes` ← e' quello che fa tacere il bot quando risponde
      Nadia
    - `history`
    - `smb_app_state_sync`

> Configurare la URL e iscrivere i campi sono **due interruttori diversi**: col
> secondo spento Meta prende in carico i messaggi e non ne inoltra nessuno,
> senza segnalare niente da nessuna parte. E' silenzio totale con tutto che
> sembra a posto.

---

## B. Su Render

17. Controlla che il codice nuovo sia online: apri
    `https://simoneacconciature.it/health` e guarda che `commit` cominci per
    **`273593c`**. Se no, aspetta che il deploy finisca.
18. Nel servizio web, **Environment**, aggiungi tre variabili:

    | Nome | Valore |
    |---|---|
    | `META_APP_ID` | l'ID app del punto 11 |
    | `META_APP_SECRET` | la chiave segreta del punto 11 |
    | `META_ES_CONFIG_ID` | il Configuration ID del punto 10 |

19. Salva: il servizio riparte da se'.
20. Apri `https://simoneacconciature.it/admin/collega-whatsapp` e controlla che
    il bottone **Avvia il collegamento** sia **attivo** (non grigio).
    **Non premerlo adesso**: premilo in salone.

---

## C. In salone, con loro

### Prima di cominciare

21. Sul telefono del salone: **WhatsApp Business aggiornata**, serve almeno la
    versione **2.24.17**. Controllalo prima, non durante.
22. Quel numero non deve essere **gia' collegato** a una Business Platform. Se
    lo e': *Impostazioni → Account → Business Platform → Disconnetti*, poi
    **15 minuti di attesa** prima di andare avanti.
23. Fatti scrivere da Simone un messaggio in cui dice di procedere: nel flusso
    accetti le condizioni di WhatsApp Business **per conto loro**.
24. Decidi **in quale portfolio** finisce l'account:
    - il portfolio del salone, con te invitato come amministratore — la via
      pulita; oppure
    - uno che crei tu durante il flusso, intestato al salone **con la loro
      ragione sociale esatta**.

    Non metterlo in un portfolio intestato a te: la verifica dell'azienda che
    servira' poi per i template — promemoria e avvisi di assenza — si fa su
    quel portfolio con i documenti del salone, e un nome che non combacia viene
    rifiutato.

### Il collegamento

25. Apri `https://simoneacconciature.it/admin/collega-whatsapp` e premi
    **Avvia il collegamento**.
26. Accedi con il tuo account Facebook e scegli il portfolio del punto 24.
27. **Deve comparire la scelta per collegare un account WhatsApp Business che
    esiste gia'.**
    Se invece ti propone **solo** di crearne uno nuovo, **chiudi la finestra**:
    quella strada registra il numero sulla Cloud API e lo **toglie dal
    telefono** del salone. E' l'unico errore di stasera che non si rimedia.
    In quel caso riapri la pagina con una variante:
    - `.../admin/collega-whatsapp?feature=coexistence`
    - `.../admin/collega-whatsapp?feature=` (senza niente)
28. Inserisci il numero del salone.
29. Sul loro telefono arriva un messaggio da Facebook. Devono toccare, in
    quest'ordine:
    **Connect** → **Connect to the Business Platform** → **Confirm**.
    Quel bottone funziona **solo dentro la loro chat**: inoltrato a te e'
    un'immagine e non fa niente.
30. Al **Confirm** scelgono anche se condividere le conversazioni passate.
    **Non ci serve** e non abbiamo dove metterla: possono dire di no.
31. Il codice si scrive nella finestra del browser, da te.
32. **Non chiudete l'app** finche' non ha finito di sincronizzare.

> Un codice sbagliato, o richiesto troppe volte, **blocca tutto per circa 12
> ore**. Una volta con calma, non tre di corsa.

---

## D. Appena finito

33. La pagina mostra `META_PHONE_NUMBER_ID` e `META_WA_TOKEN`: copiali nelle
    variabili d'ambiente su Render (quelle esistenti, da sostituire).
    **Finche' non li cambi, il bot continua a rispondere dal numero di prima.**
34. Nella stessa pagina, controlla che fra le **app iscritte all'account** ci
    sia *Qubi Prenotazioni*, e non solo *WA DevX Webhook Events 1P App*, che e'
    di Meta.
35. Controlla che l'id sia quello **del numero** e non quello dell'account: si
    somigliano e stanno nella stessa schermata. La pagina legge quello giusto
    da Meta, ma vale un'occhiata — con quello sbagliato ogni invio torna
    `code 100, subcode 33`, e siccome fallisce anche la conferma di lettura le
    spunte restano grigie: identico al sintomo di un messaggio mai arrivato.

---

## E. Le due prove che decidono

36. **Scrivi al numero del salone dal tuo telefono.** Deve rispondere il bot,
    dal numero del salone.
37. **Fai rispondere Nadia dall'app, nella stessa conversazione.** Da quel
    momento il bot deve **tacere** su quel numero, e in **Conversazioni** deve
    comparire la riga con dentro quello che ha scritto lei.

Il punto 37 e' quello che decide se si puo' restare online: senza, il cliente
riceve due risposte diverse alla stessa domanda — una del bot e una di Nadia —
ed e' peggio di una risposta lenta.

---

## Se qualcosa va storto

| Cosa vedi | Cos'e' | Cosa fare |
|---|---|---|
| Il flusso finisce ma la pagina dice che non e' arrivato nessun codice | Dominio non autorizzato | Rivedi i punti 3 e 4 |
| Meta parla di troppi tentativi sul codice | Blocco anti-abuso | **Circa 12 ore** di attesa, non c'e' scorciatoia |
| Errore `3441049` | Il numero e' gia' collegato altrove | Punto 22, poi 15 minuti |
| Non compare la scelta "account esistente" | Variante non attiva | Punto 27, prova le due URL |
| Il bot non risponde a niente | Campi non iscritti, o token di verifica diverso | Punti 14 e 16 |
| Il bot risponde due volte insieme a Nadia | `smb_message_echoes` non iscritto | Punto 16 |

---

## Rimasto da decidere, ma non stasera

- **Il numero vecchio** (+39 351 639 5494) resta acceso sull'app
  `salone-nadia`. Dopo il punto 33 i messaggi che arrivano li' vengono
  **ignorati** di proposito: rispondere da un numero diverso da quello a cui
  uno ha scritto e' peggio che non rispondere. Va deciso se spegnerlo
  togliendo l'iscrizione di quell'app, o se tenerlo acceso — e in quel caso
  serve far rispondere il bot da due numeri, che e' lavoro in piu'.
- **La verifica dell'azienda del salone**, che sblocca i template: senza, niente
  promemoria, niente avvisi di assenza, e niente modo di riscrivere a un
  cliente dopo 24 ore dal suo ultimo messaggio.
