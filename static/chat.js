// Chat Widget WebSocket Client
(function() {
    const toggle = document.getElementById('chat-toggle');
    const panel = document.getElementById('chat-panel');
    const closeBtn = document.getElementById('chat-close');
    const input = document.getElementById('chat-input');
    const sendBtn = document.getElementById('chat-send');
    const messages = document.getElementById('chat-messages');

    let ws = null;
    let isOpen = false;

    // Toggle chat panel
    toggle.addEventListener('click', () => {
        isOpen = !isOpen;
        panel.classList.toggle('hidden', !isOpen);
        if (isOpen && !ws) {
            connectWebSocket();
        }
        if (isOpen) {
            input.focus();
        }
    });

    closeBtn.addEventListener('click', () => {
        isOpen = false;
        panel.classList.add('hidden');
    });

    // Identificativo della conversazione. Lo tiene il browser, non il server:
    // altrimenti ogni caduta di connessione — un riavvio, la rete, il computer
    // che si sospende — apriva una sessione nuova, e il bot ricominciava da
    // capo salutando in mezzo al discorso.
    const CHIAVE_SESSIONE = 'salone_nadia_sessione';

    function sessioneSalvata() {
        try {
            return localStorage.getItem(CHIAVE_SESSIONE);
        } catch (e) {
            // Navigazione privata o cookie bloccati: si riparte da zero
            return null;
        }
    }

    function ricordaSessione(id) {
        try {
            localStorage.setItem(CHIAVE_SESSIONE, id);
        } catch (e) {
            /* pazienza: la conversazione vale solo per questa connessione */
        }
    }

    // WebSocket connection
    function connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        let wsUrl = `${protocol}//${window.location.host}/ws/chat`;

        const sessione = sessioneSalvata();
        if (sessione) {
            wsUrl += `?sessione=${encodeURIComponent(sessione)}`;
        }

        ws = new WebSocket(wsUrl);

        ws.onopen = () => {
            console.log('Chat WebSocket connected');
        };

        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            if (data.type === 'sessione') {
                ricordaSessione(data.id);
                return;
            }
            if (data.type === 'storico') {
                // Conversazione ripresa dopo un ricaricamento o una caduta:
                // senza questo il riquadro restava vuoto pur avendo il bot
                // la memoria intatta.
                appendMessage(data.text, data.role === 'user' ? 'user' : 'bot');
                return;
            }
            if (data.type === 'message') {
                nascondiStaScrivendo();
                appendMessage(data.text, 'bot');
                // Se ci sono opzioni, mostra i bottoni
                if (data.options && data.options.length > 0) {
                    appendButtons(data.options);
                }
            }
        };

        ws.onclose = () => {
            console.log('Chat WebSocket disconnected');
            // Se cade la connessione nessuno risponderà più a quel messaggio:
            // lasciare i puntini animati sarebbe una promessa non mantenuta.
            nascondiStaScrivendo();
            ws = null;
            setTimeout(() => {
                if (isOpen) connectWebSocket();
            }, 3000);
        };

        ws.onerror = (err) => {
            console.error('WebSocket error:', err);
        };
    }

    // Send message
    function sendMessage(text) {
        text = text || input.value.trim();
        if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;

        ws.send(JSON.stringify({ text: text }));
        appendMessage(text, 'user');
        input.value = '';
        mostraStaScrivendo();
    }

    sendBtn.addEventListener('click', () => sendMessage());
    input.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') sendMessage();
    });

    // "Nadia sta scrivendo": una risposta può richiedere qualche secondo, fra
    // il modello e la lettura dei calendari. Senza segnale il riquadro sembra
    // fermo, e il cliente riscrive o se ne va.
    let indicatore = null;

    function mostraStaScrivendo() {
        if (indicatore) return;
        indicatore = document.createElement('div');
        indicatore.className = 'message bot sta-scrivendo';
        indicatore.setAttribute('aria-label', 'Nadia sta scrivendo');
        for (let i = 0; i < 3; i++) {
            indicatore.appendChild(document.createElement('span'));
        }
        messages.appendChild(indicatore);
        messages.scrollTop = messages.scrollHeight;
    }

    function nascondiStaScrivendo() {
        if (!indicatore) return;
        indicatore.remove();
        indicatore = null;
    }

    // Append message to chat
    function appendMessage(text, sender) {
        const div = document.createElement('div');
        div.className = `message ${sender}`;
        div.textContent = text;
        messages.appendChild(div);
        messages.scrollTop = messages.scrollHeight;
    }

    // Append clickable buttons
    function appendButtons(options) {
        const container = document.createElement('div');
        container.className = 'buttons-container';

        options.forEach(opt => {
            const btn = document.createElement('button');
            btn.className = 'chat-option-btn';
            btn.textContent = opt.title;
            btn.addEventListener('click', () => {
                // Rimuovi i bottoni dopo il click
                container.remove();
                // Invia la scelta come messaggio
                sendMessage(opt.title);
            });
            container.appendChild(btn);
        });

        messages.appendChild(container);
        messages.scrollTop = messages.scrollHeight;
    }
})();
