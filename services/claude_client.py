import anthropic
from config import settings

client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)


async def call_claude(system_prompt: str, history: list[dict]) -> str:
    """Chiama Claude API con system prompt e history."""

    # Converti history nel formato messages API
    messages = []
    for msg in history:
        messages.append({
            "role": msg["role"],
            "content": msg["content"],
        })

    response = await client.messages.create(
        model=settings.claude_model,
        max_tokens=1024,
        system=system_prompt,
        messages=messages,
    )

    return response.content[0].text
