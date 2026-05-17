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

    // WebSocket connection
    function connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/chat`;

        ws = new WebSocket(wsUrl);

        ws.onopen = () => {
            console.log('Chat WebSocket connected');
        };

        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            if (data.type === 'message') {
                appendMessage(data.text, 'bot');
                // Se ci sono opzioni, mostra i bottoni
                if (data.options && data.options.length > 0) {
                    appendButtons(data.options);
                }
            }
        };

        ws.onclose = () => {
            console.log('Chat WebSocket disconnected');
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
    }

    sendBtn.addEventListener('click', () => sendMessage());
    input.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') sendMessage();
    });

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
