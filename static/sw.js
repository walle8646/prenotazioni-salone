// Service worker del pannello. Fa due cose sole, e la prima è quella che
// conta: ricevere le notifiche quando l'applicazione è chiusa.
//
// Vive alla radice del sito e non sotto /static/ perché un service worker
// comanda solo sul percorso da cui è stato scaricato: servito da /static/
// non vedrebbe /admin, cioè proprio le pagine per cui esiste.

const VERSIONE = 'salone-1';

self.addEventListener('install', () => {
    // Subito al lavoro, senza aspettare che si chiudano le schede aperte:
    // chi ha appena installato l'applicazione si aspetta che funzioni adesso.
    self.skipWaiting();
});

self.addEventListener('activate', (evento) => {
    evento.waitUntil(self.clients.claim());
});

// Senza un gestore di fetch il browser non considera il sito installabile.
// Non si mette niente in cache: il pannello mostra appuntamenti e messaggi,
// e una pagina servita dalla memoria direbbe cose vecchie proprio dove
// contano quelle nuove.
self.addEventListener('fetch', () => {});

self.addEventListener('push', (evento) => {
    let dati = { titolo: 'Acconciature Simone', testo: 'Qualcuno ti sta aspettando.', url: '/admin/conversazioni' };
    try {
        if (evento.data) {
            dati = Object.assign(dati, evento.data.json());
        }
    } catch (e) {
        // Notifica senza contenuto leggibile: meglio quella predefinita che niente
    }

    evento.waitUntil(
        self.registration.showNotification(dati.titolo, {
            body: dati.testo,
            icon: '/static/img/app-192.png',
            badge: '/static/img/app-192.png',
            // Stesso tag: se ne arrivano tre di fila non si impilano tre
            // avvisi, si aggiorna quello che c'è.
            tag: 'conversazioni',
            renotify: true,
            data: { url: dati.url },
        })
    );
});

self.addEventListener('notificationclick', (evento) => {
    evento.notification.close();
    const destinazione = (evento.notification.data && evento.notification.data.url) || '/admin/conversazioni';

    evento.waitUntil(
        self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((finestre) => {
            // Se l'applicazione è già aperta si porta in primo piano e la si
            // sposta: aprirne una seconda lascerebbe due copie della stessa
            // conversazione, ognuna convinta di essere quella buona.
            for (const finestra of finestre) {
                if (finestra.url.includes('/admin') && 'focus' in finestra) {
                    finestra.navigate(destinazione);
                    return finestra.focus();
                }
            }
            return self.clients.openWindow(destinazione);
        })
    );
});
