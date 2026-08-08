// Ritaglio della foto di un operatore, nel browser.
//
// Il taglio centrale che fa il server è un ripiego: se la persona sta di lato
// nella fotografia, la faccia esce dal tondo. Qui si sceglie l'inquadratura
// vedendo esattamente il cerchio che poi vedrà il cliente, e si carica
// un'immagine già quadrata.
//
// Scritto a mano e senza librerie: la pagina del pannello non ne carica
// nessuna, e per trascinare e ingrandire un'immagine non vale la pena
// cominciare adesso.
(function () {
    const LATO = 512;          // quanto esce, in pixel
    const ANTEPRIMA = 320;     // quanto è grande il riquadro a schermo

    const finestra = document.getElementById('ritaglio');
    if (!finestra) return;

    const tela = document.getElementById('ritaglio-tela');
    const contesto = tela.getContext('2d');
    const zoom = document.getElementById('ritaglio-zoom');
    const conferma = document.getElementById('ritaglio-conferma');
    const annulla = document.getElementById('ritaglio-annulla');

    let immagine = null;
    let campoInCorso = null;
    let scalaMinima = 1;
    let scala = 1;
    let spostamentoX = 0;
    let spostamentoY = 0;
    let trascina = null;

    function disegna() {
        contesto.clearRect(0, 0, ANTEPRIMA, ANTEPRIMA);
        contesto.save();
        // Tutto quello che si disegna resta dentro il cerchio: così il riquadro
        // mostra il ritaglio vero, non una promessa.
        contesto.beginPath();
        contesto.arc(ANTEPRIMA / 2, ANTEPRIMA / 2, ANTEPRIMA / 2, 0, Math.PI * 2);
        contesto.clip();
        contesto.fillStyle = '#ecf0f1';
        contesto.fillRect(0, 0, ANTEPRIMA, ANTEPRIMA);
        if (immagine) {
            contesto.drawImage(
                immagine,
                spostamentoX, spostamentoY,
                immagine.width * scala, immagine.height * scala
            );
        }
        contesto.restore();
    }

    function limita() {
        // L'immagine non può scoprire il cerchio: si ferma ai bordi.
        const larghezza = immagine.width * scala;
        const altezza = immagine.height * scala;
        spostamentoX = Math.min(0, Math.max(ANTEPRIMA - larghezza, spostamentoX));
        spostamentoY = Math.min(0, Math.max(ANTEPRIMA - altezza, spostamentoY));
    }

    function apri(campo, file) {
        const lettore = new FileReader();
        lettore.onload = () => {
            const img = new Image();
            img.onload = () => {
                immagine = img;
                campoInCorso = campo;
                // Si parte dall'inquadratura più larga che riempie il cerchio.
                scalaMinima = Math.max(ANTEPRIMA / img.width, ANTEPRIMA / img.height);
                scala = scalaMinima;
                spostamentoX = (ANTEPRIMA - img.width * scala) / 2;
                spostamentoY = (ANTEPRIMA - img.height * scala) / 2;
                zoom.min = '1';
                zoom.max = '3';
                zoom.step = '0.01';
                zoom.value = '1';
                finestra.classList.remove('nascosto');
                disegna();
            };
            img.onerror = () => alert('Non riesco ad aprire questa immagine.');
            img.src = lettore.result;
        };
        lettore.readAsDataURL(file);
    }

    function chiudi() {
        finestra.classList.add('nascosto');
        immagine = null;
        campoInCorso = null;
    }

    zoom.addEventListener('input', () => {
        if (!immagine) return;
        const centroPrimaX = (ANTEPRIMA / 2 - spostamentoX) / scala;
        const centroPrimaY = (ANTEPRIMA / 2 - spostamentoY) / scala;
        scala = scalaMinima * parseFloat(zoom.value);
        // Si ingrandisce attorno al centro del cerchio, non all'angolo:
        // altrimenti la faccia scappa via mentre si usa il cursore.
        spostamentoX = ANTEPRIMA / 2 - centroPrimaX * scala;
        spostamentoY = ANTEPRIMA / 2 - centroPrimaY * scala;
        limita();
        disegna();
    });

    tela.addEventListener('pointerdown', (e) => {
        if (!immagine) return;
        trascina = { x: e.clientX - spostamentoX, y: e.clientY - spostamentoY };
        tela.setPointerCapture(e.pointerId);
    });

    tela.addEventListener('pointermove', (e) => {
        if (!trascina) return;
        spostamentoX = e.clientX - trascina.x;
        spostamentoY = e.clientY - trascina.y;
        limita();
        disegna();
    });

    tela.addEventListener('pointerup', () => { trascina = null; });
    tela.addEventListener('pointercancel', () => { trascina = null; });

    annulla.addEventListener('click', () => {
        if (campoInCorso) campoInCorso.value = '';
        chiudi();
    });

    conferma.addEventListener('click', () => {
        if (!immagine || !campoInCorso) return chiudi();

        const finale = document.createElement('canvas');
        finale.width = finale.height = LATO;
        const c = finale.getContext('2d');
        const fattore = LATO / ANTEPRIMA;
        c.drawImage(
            immagine,
            spostamentoX * fattore, spostamentoY * fattore,
            immagine.width * scala * fattore, immagine.height * scala * fattore
        );

        const campo = campoInCorso;
        finale.toBlob((blob) => {
            try {
                const trasferimento = new DataTransfer();
                trasferimento.items.add(
                    new File([blob], 'foto.jpg', { type: 'image/jpeg' })
                );
                campo.files = trasferimento.files;
            } catch (e) {
                // Se il browser non lascia sostituire il file scelto, parte
                // l'originale e il ritaglio lo fa il server, al centro.
                console.warn('Ritaglio non applicato, va il file originale', e);
            }
            chiudi();
        }, 'image/jpeg', 0.85);
    });

    // Ogni campo "foto" del pannello apre il riquadro invece di caricare subito.
    document.querySelectorAll('input[type="file"][name="foto"]').forEach((campo) => {
        campo.addEventListener('change', () => {
            const file = campo.files && campo.files[0];
            // Un file già passato da qui non va ritagliato una seconda volta.
            if (file && file.name !== 'foto.jpg') apri(campo, file);
        });
    });
})();
