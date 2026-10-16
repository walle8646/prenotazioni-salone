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
16. Sempre li', nella tabella **Campi del webhook**, servono quattro
    iscrizioni attive. Meta ne accende gia' parecchie da se', fra cui due
    delle nostre:
    - `messages` — di solito gia' attivo
    - `account_update` — di solito gia' attivo
    - `smb_message_echoes` — **va acceso a mano**, ed e' quello che fa tacere
      il bot quando risponde Nadia
    - `smb_app_state_sync` — **va acceso a mano**, ed e' quello che porta la
      rubrica del telefono del salone

    Attenzione: nell'elenco c'e' anche **`message_echoes`** senza `smb_`.
    Quello e' di Messenger e non serve: lascialo spento.

    `history` **si lascia spento**: sono le conversazioni passate, e non
    abbiamo dove metterle ne' motivo di tenerle — e' la stessa regola per cui
    in database finiscono solo le conversazioni passate a una persona e non
    tutte. Il codice la ignora comunque, se un giorno si accendesse.

    La rubrica invece la vogliamo, ed e' una decisione presa sapendo il
    prezzo: in quella rubrica non ci sono solo clienti, ci sono il fornitore
    e il commercialista. Per questo i contatti finiscono in una tabella loro
    e **non** fra i clienti: servono a mettere un nome su un numero che
    scrive, non ad aprire schede di gente che non ha mai prenotato.

    Le altre che Meta accende da se' (`calls`, `security`,
    `phone_number_quality_update`, quelle sui template) si lasciano stare: il
    webhook le ignora, e `message_template_status_update` tornera' utile
    quando sbloccheremo i template.

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
24. Decidi **in quale portfolio** finisce l'account del salone.

    Tre cose diverse che si confondono facilmente, e la distinzione cambia
    cosa chiedere.

    - L'**account sviluppatore** (`developers.facebook.com`) serve solo a chi
      **crea** le app. E' nostro: il salone non ci mette piede e non crea
      nessuna app, usa la nostra.
    - Il **portfolio aziendale** (`business.facebook.com`, prima Business
      Manager) e' il contenitore che possiede pagina, account WhatsApp ed
      eventuali account pubblicitari. Si crea da un normale account Facebook,
      e' gratis e non richiede niente di tecnico. **E' questo che serve qui**,
      perche' e' dentro al portfolio che nascera' il WABA.
    - L'**account Facebook personale** e' il login di Simone: se hanno una
      pagina del salone, ce l'hanno per forza.

    Quindi la domanda da fargli non e' "avete un account sviluppatore", ma:
    **andate su business.facebook.com, vi si apre un account aziendale del
    salone?**

    - **Se ce l'hanno:** fatti aggiungere come amministratore. Loro vanno su
      *Impostazioni aziendali -> Persone -> Aggiungi*, mettono la tua email e
      danno accesso completo; a te arriva un invito da accettare. Cosi'
      stasera **loro non devono fare login da nessuna parte**: accedi tu col
      tuo Facebook e nel flusso scegli il loro portfolio.
    - **Se non ce l'hanno:** lo crei tu durante il flusso, intestato al salone
      **con la ragione sociale esatta**. Fattela mandare scritta, insieme alla
      partita IVA.

    Non metterlo in un portfolio intestato a te: la verifica dell'azienda che
    servira' poi per i template — promemoria e avvisi di assenza — si fa su
    quel portfolio con i documenti del salone, e un nome che non combacia viene
    rifiutato.

    Se il portfolio ce l'hanno gia', chiedi anche se e' **verificato**
    (*Impostazioni aziendali -> Centro sicurezza*): se il salone ha gia' fatto
    la verifica dell'azienda per altro, i template si sbloccano senza rifare
    niente.

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
29. Dal telefono del salone si arriva al collegamento in **due modi**, e il
    secondo e' piu' semplice.

    **Col QR (consigliato).** Sul telefono: *Impostazioni → Collegati alla
    piattaforma Business*. Dice "Inquadra il codice QR": tu mostri lo schermo
    del portatile, loro lo inquadrano. Nessun codice da dettare.

    **Col messaggio.** Nella loro chat arriva un messaggio da Facebook e
    toccano, in quest'ordine: **Connect** → **Connect to the Business
    Platform** → **Confirm**. Quel bottone funziona solo dentro la loro chat:
    inoltrato a te e' un'immagine e non fa niente.

    Che la voce *Collegati alla piattaforma Business* esista gia' nelle
    impostazioni vuol dire che l'app e' abbastanza aggiornata: il punto 21 si
    verifica da li' in due secondi.
30. Alla conferma scelgono cosa condividere, e qui **serve un si'**.
    - **Contatti: si'.** E' la rubrica, e per noi passa da qui. Si puo'
      chiedere una volta sola, entro 24 ore: se dicono di no, per riaverla
      bisogna scollegare il numero e rifare tutto.
    - **Cronologia chat: non ci serve.** L'app offre fino a 6 mesi di chat
      passate (quelle di gruppo non si condividono comunque). Noi non la
      chiediamo e non abbiamo dove metterla.
31. Se siete andati col messaggio, il codice si scrive nella finestra del
    browser, da te. Col QR questo passaggio non c'e'.
32. **Non chiudete l'app** finche' non ha finito di sincronizzare.

> Un codice sbagliato, o richiesto troppe volte, **blocca tutto per circa 12
> ore**. Una volta con calma, non tre di corsa.

---

## D. Appena finito

33. La pagina mostra `META_PHONE_NUMBER_ID` e `META_WA_TOKEN`: copiali nelle
    variabili d'ambiente su Render (quelle esistenti, da sostituire).
    **Finche' non li cambi, il bot continua a rispondere dal numero di prima.**

    **Poi torna sulla pagina e premi *Importa la rubrica*.** In fondo alla
    schermata c'e' il bottone. Va premuto **dopo** aver salvato le variabili:
    con quelle vecchie chiederesti la rubrica del numero sbagliato, e il
    tentativo si brucia lo stesso — si puo' chiedere una volta sola, entro 24
    ore dal collegamento.

    La pagina dice "richiesta accettata" ma non vuol dire che siano arrivati:
    i contatti li porta il webhook nei minuti dopo. Ricarica la pagina e
    guarda che il conto dei contatti in rubrica sia salito. Se resta a zero
    dopo dieci minuti, qualcosa non va — con ogni probabilita'
    `smb_app_state_sync` non e' iscritto (punto 16) o alla conferma hanno
    detto di no ai contatti (punto 30).
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

    Mentre lo fai, **tieni d'occhio il telefono del salone**: in coexistence
    il messaggio arriva anche li', e il bot lo segna come letto via API. Se il
    pallino della notifica si spegne da solo quando il bot risponde, siamo a
    posto. Se resta, Nadia si ritrova notifiche di messaggi gia' gestiti — e
    il rischio non e' il fastidio, e' che risponda a qualcosa a cui il bot ha
    gia' risposto. Il codice se ne accorge e si fa da parte, ma a quel punto
    due risposte sono partite. Rimedio: silenziare quelle chat dall'app.
37. **Fai rispondere Nadia dall'app, nella stessa conversazione.** Da quel
    momento il bot deve **tacere** su quel numero, e in **Conversazioni** deve
    comparire la riga con dentro quello che ha scritto lei.

Il punto 37 e' quello che decide se si puo' restare online: senza, il cliente
riceve due risposte diverse alla stessa domanda — una del bot e una di Nadia —
ed e' peggio di una risposta lenta.

---

## F. I calendari degli operatori

Non c'entra con WhatsApp e si puo' fare in un altro giorno, ma la procedura e'
questa e non si ricorda mai. Ogni operatore ha un calendario Google suo: e' li'
che il bot scrive gli appuntamenti ed e' da li' che legge se un'ora e' libera.
Finche' un operatore non ce l'ha, prenotare con lui **fallisce**.

38. Decidi **da quale account Google** nascono i sei calendari, e usane uno solo
    per tutti. Oggi sono sull'account di prova `parrucchiere.bot.test@gmail.com`;
    se il salone ne vuole uno suo, si rifanno li' con questa stessa procedura. Al
    bot non importa di chi sia l'account, gli importa solo di essere invitato.

39. Su `calendar.google.com`, colonna di sinistra, accanto a **Altri calendari**
    premi **+** -> **Crea nuovo calendario**. Nome: quello dell'operatore, come
    e' scritto nel pannello. Fuso orario **Europe/Rome**.

40. Passa il mouse sul calendario appena creato -> **tre puntini** ->
    **Impostazioni e condivisione**. Scendi a **Condividi con persone e gruppi
    specifici** -> **Aggiungi persone e gruppi**, e incolla l'indirizzo del
    service account:

    ```
    salone-nadia-bot@wired-framework-496615-r0.iam.gserviceaccount.com
    ```

    Autorizzazioni: **Apportare modifiche agli eventi**. Invia.

    Non aspettare nessuna conferma: un service account non ha una casella di
    posta e non accetta nessun invito. Appena premi *Invia*, funziona.

41. Stessa pagina, scendi a **Integra calendario** e copia l'**ID calendario**:
    una stringa lunga che finisce per `@group.calendar.google.com`. Non e' il
    nome del calendario e non e' l'indirizzo dell'account.

42. Pannello -> **Operatori** -> riga di quell'operatore -> campo **Calendario
    Google** -> incolla -> **Salva**. Finche' manca, il campo e' evidenziato e
    contiene `da-configurare-...`. Vale **subito**: la schermata ricarica da se'
    la copia in memoria che legge il bot, senza deploy e senza riavvio.

    In alternativa c'e' `GCAL_PARRUCCHIERE_IDS` su Render (oggetto JSON, nome ->
    id), ma serve solo a riempire quello che manca: quando in tabella c'e' un
    calendario vero, a comandare e' il pannello (`sovrascrive_il_calendario()`).

43. Ripeti 39-42 per tutti e sei: Simone Big, Simone Jr, Francesco, Andrea,
    Giava, Bario.

44. Dallo stesso punto del 40, condividi ogni calendario anche con l'account
    Google personale di chi lavora in salone, **in sola lettura**: cosi' ognuno
    vede l'agenda nella sua app senza che nessuno giri una password, e a chi se
    ne va si toglie la condivisione.

45. **Solo se stai sostituendo calendari gia' in uso**: prima di cambiare l'ID
    nel pannello, sposta sul calendario nuovo gli **appuntamenti futuri** che
    stanno sul vecchio. Su Google: apri l'evento -> tre puntini -> **Sposta in**
    -> calendario nuovo. Spostare non cambia l'identificativo dell'evento,
    quindi *Disdici* e *Sposta* dal pannello continuano a funzionare.

46. **La prova.** Pannello -> **Prenota**, scegli un giorno: devono comparire
    caselle verdi per quell'operatore. Prenota una prova, guarda che l'evento
    compaia sul calendario entro qualche secondo, poi disdiscila da
    **Appuntamenti** e controlla che sparisca anche li'.

47. Se un operatore **non ha nessuna casella verde** mentre gli altri si', la
    condivisione e' sbagliata: torna al punto 40 e controlla indirizzo e
    permesso.

**Il permesso e' la meta' che si sbaglia.** *Apportare modifiche agli eventi*,
non *Visualizzare tutti i dettagli*: con la sola lettura il bot vede le ore
libere e le propone, poi fallisce nell'ultimo passaggio, quello in cui scrive —
il cliente ha gia' scelto servizio, giorno e ora, e si sente dire che c'e' stato
un problema tecnico.

**Un calendario nuovo e' un calendario vuoto.** Cambiando l'ID di un operatore
che ha gia' appuntamenti presi, per il bot quelle ore tornano libere: il
calendario nuovo non sa niente dei vecchi e le rioffre al primo che scrive. Due
clienti sulla stessa poltrona, e il secondo se ne accorge arrivando in salone.
E' il motivo per cui il punto 45 viene prima.

---

## Se qualcosa va storto

| Cosa vedi | Cos'e' | Cosa fare |
|---|---|---|
| Il flusso finisce ma la pagina dice che non e' arrivato nessun codice | Dominio non autorizzato | Rivedi i punti 3 e 4 |
| Meta parla di troppi tentativi sul codice | Blocco anti-abuso | **Circa 12 ore** di attesa, non c'e' scorciatoia |
| Errore `3441049` | Il numero e' gia' collegato altrove | Punto 22, poi 15 minuti |
| Non compare la scelta "account esistente" | Variante non attiva | Punto 27, prova le due URL |
| Il bot non risponde a niente | Campi non iscritti, o token di verifica diverso | Punti 14 e 16 |
| Il bot risponde due volte insieme a Nadia | `smb_message_echoes` spento, o acceso `message_echoes` al suo posto | Punto 16 |
| "Problema tecnico" proprio quando conferma | Calendario condiviso in sola lettura | Punto 40, permesso *Apportare modifiche* |
| Con un operatore non c'e' mai posto | Calendario non condiviso, o ID sbagliato | Punti 40 e 41 |
| Il bot dice ai clienti qualcosa di sbagliato | Succede | **Spegni il bot** dal menù del pannello: smette subito, e i messaggi continuano ad arrivare in Conversazioni |

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
