"""Wrapper attorno all'SDK Anthropic.

Il client viene creato alla prima chiamata e non all'import del modulo: così il
resto del codice (motore conversazionale, test, simulatore) resta importabile
anche senza ANTHROPIC_API_KEY configurata.
"""

import logging

from config import settings

logger = logging.getLogger(__name__)

_client = None


def get_client():
    """Restituisce il client Anthropic, creandolo alla prima chiamata."""
    global _client
    if _client is None:
        import anthropic

        if not settings.anthropic_api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY non configurata: impostala nel file .env "
                "oppure usa il simulatore con --fake-claude."
            )
        _client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


async def call_claude(system_prompt, history: list[dict]) -> str:
    """Chiama Claude con il system prompt e lo storico della conversazione.

    `system_prompt` è la lista di blocchi che costruisce `blocchi_system()`:
    il primo porta il segnaposto della cache. Accetta anche una stringa, per
    il simulatore e per chiunque chiami questa funzione a mano.
    """
    messages = [
        {"role": msg["role"], "content": msg["content"]} for msg in history
    ]

    response = await get_client().messages.create(
        model=settings.claude_model,
        max_tokens=1024,
        system=system_prompt,
        messages=messages,
    )

    # Se la cache non si attiva non si rompe niente, si paga e basta — quindi
    # nessuno se ne accorgerebbe. Nei log resta il conto, per poterlo vedere.
    uso = response.usage
    logger.info(
        "Claude: %s token letti dalla cache, %s scritti, %s a prezzo pieno",
        getattr(uso, "cache_read_input_tokens", 0) or 0,
        getattr(uso, "cache_creation_input_tokens", 0) or 0,
        uso.input_tokens,
    )
    return response.content[0].text
