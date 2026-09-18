// Attiva le notifiche sul telefono di chi lavora in salone.
//
// Il bottone dice sempre lo stato vero, perché il permesso lo dà il telefono
// e non questa pagina: chi l'ha negato una volta non lo può riattivare da qui,
// e un bottone che promette di farlo mentirebbe.
(function () {
    const bottone = document.getElementById('attiva-notifiche');
    const stato = document.getElementById('stato-notifiche');
    if (!bottone) return;

    function dillo(testo, mostraBottone) {
        if (stato) stato.textContent = testo;
        bottone.hidden = !mostraBottone;
    }

    // iOS manda le notifiche solo a un'applicazione aggiunta alla schermata
    // Home: dal browser il permesso non si può nemmeno chiedere. Dirlo prima
    // evita il bottone che non fa niente.
    const iOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
    const installata = window.matchMedia('(display-mode: standalone)').matches
        || window.navigator.standalone === true;

    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
        if (iOS && !installata) {
            dillo('Su iPhone: tocca Condividi e poi "Aggiungi a Home". Da lì potrai attivare le notifiche.', false);
        } else {
            dillo('Questo browser non supporta le notifiche.', false);
        }
        return;
    }

    if (Notification.permission === 'denied') {
        dillo('Notifiche bloccate: si riattivano dalle impostazioni del telefono, non da qui.', false);
        return;
    }

    function daBase64(base64) {
        const riempito = (base64 + '='.repeat((4 - (base64.length % 4)) % 4))
            .replace(/-/g, '+').replace(/_/g, '/');
        const grezzo = atob(riempito);
        return Uint8Array.from(grezzo, (c) => c.charCodeAt(0));
    }

    async function registra() {
        const registrazione = await navigator.serviceWorker.register('/sw.js');
        await navigator.serviceWorker.ready;
        return registrazione;
    }

    async function giaIscritto() {
        try {
            const registrazione = await navigator.serviceWorker.getRegistration('/');
            if (!registrazione) return false;
            return Boolean(await registrazione.pushManager.getSubscription());
        } catch (e) {
            return false;
        }
    }

    async function attiva() {
        bottone.disabled = true;
        dillo('Attivazione in corso…', true);
        try {
            const permesso = await Notification.requestPermission();
            if (permesso !== 'granted') {
                dillo('Permesso non concesso: le notifiche restano spente.', permesso === 'default');
                bottone.disabled = false;
                return;
            }

            const risposta = await fetch('/admin/push/chiave');
            const { chiave } = await risposta.json();
            if (!chiave) {
                dillo('Le notifiche non sono ancora configurate sul server.', false);
                return;
            }

            const registrazione = await registra();
            const iscrizione = await registrazione.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: daBase64(chiave),
            });

            const salvata = await fetch('/admin/push/iscrizione', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(iscrizione),
            });
            if (!salvata.ok) throw new Error('il server non ha accettato l\'iscrizione');

            dillo('Notifiche attive su questo dispositivo.', false);
        } catch (errore) {
            dillo('Non è stato possibile attivarle. Riprova.', true);
            bottone.disabled = false;
        }
    }

    bottone.addEventListener('click', attiva);

    // Chi le ha già attivate non deve vedersi proporre di attivarle di nuovo.
    giaIscritto().then((si) => {
        if (si) {
            dillo('Notifiche attive su questo dispositivo.', false);
            registra();
        } else {
            dillo('', true);
        }
    });
})();
