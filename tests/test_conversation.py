import pytest
import json
from unittest.mock import patch, AsyncMock
from services.conversation import try_parse_action, handle_incoming_message


def test_try_parse_action_valid_json():
    """Testa il parsing di un'azione JSON valida."""
    response = '{"action": "CHECK_DISPONIBILITA", "data": "2026-05-20", "parrucchiere": "Marco"}'
    result = try_parse_action(response)
    assert result is not None
    assert result["action"] == "CHECK_DISPONIBILITA"
    assert result["data"] == "2026-05-20"


def test_try_parse_action_text_response():
    """Risposta testuale non deve essere interpretata come azione."""
    response = "Ciao! Come posso aiutarti oggi?"
    result = try_parse_action(response)
    assert result is None


def test_try_parse_action_json_without_action():
    """JSON senza campo 'action' non è un'azione."""
    response = '{"data": "2026-05-20"}'
    result = try_parse_action(response)
    assert result is None


def test_try_parse_action_invalid_json():
    """JSON malformato restituisce None."""
    response = '{"action": "CHECK_DISPONIBILITA", data: broken}'
    result = try_parse_action(response)
    assert result is None


@pytest.mark.asyncio
async def test_unsupported_message_type(mock_redis):
    """Messaggi non supportati (es. audio) ricevono risposta di errore."""
    with patch("services.conversation.send_text_message", new_callable=AsyncMock) as mock_send:
        await handle_incoming_message(
            redis=mock_redis,
            phone="393331234567",
            text=None,
            msg_type="audio",
            media_id=None,
            contact_name="Test User",
        )
        mock_send.assert_called_once()
        args = mock_send.call_args[0]
        assert "393331234567" in args
        assert "testo e foto" in args[1]
