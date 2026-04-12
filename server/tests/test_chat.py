# server/tests/test_chat.py
from unittest.mock import patch, MagicMock


def _make_anthropic_response(text="Great question about F1!"):
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text=text)]
    return mock_resp


def test_answer_f1_question_calls_claude():
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_anthropic_response("Verstappen leads by 25 points.")

    with patch('chat.anthropic.Anthropic', return_value=mock_client):
        import importlib, chat
        importlib.reload(chat)
        result = chat.answer_f1_question(
            message="Who leads the championship?",
            f1_context="=== Standings ===\n  1. Max Verstappen — 120 pts",
        )

    mock_client.messages.create.assert_called_once()
    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["model"] == "claude-sonnet-4-20250514"
    assert call_kwargs["max_tokens"] >= 512
    messages = call_kwargs["messages"]
    assert messages[0]["role"] == "user"
    assert "Who leads the championship?" in messages[0]["content"]
    assert "Verstappen" in messages[0]["content"]

    assert result == "Verstappen leads by 25 points."


def test_answer_f1_question_embeds_context_in_prompt():
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_anthropic_response("Norris is close.")

    with patch('chat.anthropic.Anthropic', return_value=mock_client):
        import importlib, chat
        importlib.reload(chat)
        chat.answer_f1_question("How is Norris doing?", "Context: Norris P2")

    content = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Context: Norris P2" in content
    assert "How is Norris doing?" in content
