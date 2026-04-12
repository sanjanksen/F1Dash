# server/tests/test_chat.py
import json
import pytest
from unittest.mock import patch, MagicMock, call
import importlib


# ─── Helpers ────────────────────────────────────────────────

def _tool_use_response(tool_name="get_driver_standings", tool_id="toolu_01", tool_input=None):
    """Simulate Claude responding with a tool call."""
    block = MagicMock()
    block.type = "tool_use"
    block.id = tool_id
    block.name = tool_name
    block.input = tool_input or {}

    resp = MagicMock()
    resp.stop_reason = "tool_use"
    resp.content = [block]
    return resp


def _end_turn_response(text="Verstappen leads the championship."):
    """Simulate Claude responding with a final text answer."""
    block = MagicMock()
    block.type = "text"
    block.text = text

    resp = MagicMock()
    resp.stop_reason = "end_turn"
    resp.content = [block]
    return resp


def _two_tool_use_response():
    """Simulate Claude calling two tools in parallel in a single response."""
    block_a = MagicMock()
    block_a.type = "tool_use"
    block_a.id = "toolu_01"
    block_a.name = "get_driver_standings"
    block_a.input = {}

    block_b = MagicMock()
    block_b.type = "tool_use"
    block_b.id = "toolu_02"
    block_b.name = "get_constructor_standings"
    block_b.input = {}

    resp = MagicMock()
    resp.stop_reason = "tool_use"
    resp.content = [block_a, block_b]
    return resp


# ─── Tests ──────────────────────────────────────────────────

def test_answer_f1_question_direct_answer():
    """Claude answers without calling any tools."""
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _end_turn_response("F1 started in 1950.")

    with patch('chat.anthropic.Anthropic', return_value=mock_client):
        import chat
        importlib.reload(chat)
        result = chat.answer_f1_question("When did F1 start?")

    assert result == "F1 started in 1950."
    assert mock_client.messages.create.call_count == 1


def test_answer_f1_question_single_tool_call():
    """Claude calls one tool then produces the final answer."""
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [
        _tool_use_response("get_driver_standings"),
        _end_turn_response("Verstappen leads with 150 points."),
    ]

    with patch('chat.anthropic.Anthropic', return_value=mock_client), \
         patch('chat.execute_tool', return_value=[{"standing": 1, "full_name": "Max Verstappen"}]):
        import chat
        importlib.reload(chat)
        result = chat.answer_f1_question("Who leads the championship?")

    assert result == "Verstappen leads with 150 points."
    assert mock_client.messages.create.call_count == 2


def test_answer_f1_question_parallel_tool_calls():
    """Claude calls two tools in one round; both results are sent back together."""
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [
        _two_tool_use_response(),
        _end_turn_response("Verstappen leads drivers, Red Bull leads constructors."),
    ]

    execute_tool_results = {
        "get_driver_standings": [{"standing": 1, "full_name": "Max Verstappen"}],
        "get_constructor_standings": [{"position": 1, "team": "Red Bull Racing"}],
    }

    with patch('chat.anthropic.Anthropic', return_value=mock_client), \
         patch('chat.execute_tool', side_effect=lambda n, a: execute_tool_results[n]):
        import chat
        importlib.reload(chat)
        result = chat.answer_f1_question("Who leads drivers and constructors?")

    assert "Verstappen" in result
    # Both tool results must be sent in the SAME user message
    second_call_messages = mock_client.messages.create.call_args_list[1][1]["messages"]
    last_user_content = second_call_messages[-1]["content"]
    assert len(last_user_content) == 2  # two tool_result blocks
    assert last_user_content[0]["tool_use_id"] == "toolu_01"
    assert last_user_content[1]["tool_use_id"] == "toolu_02"


def test_answer_f1_question_tool_error_uses_is_error_flag():
    """When a tool raises, the loop sends is_error=True and continues."""
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [
        _tool_use_response("get_driver_season_stats", tool_input={"driver_name": "nobody"}),
        _end_turn_response("I couldn't find that driver."),
    ]

    with patch('chat.anthropic.Anthropic', return_value=mock_client), \
         patch('chat.execute_tool', side_effect=ValueError("Driver not found: 'nobody'")):
        import chat
        importlib.reload(chat)
        result = chat.answer_f1_question("Tell me about nobody")

    assert mock_client.messages.create.call_count == 2
    # Verify the tool_result sent back to Claude has is_error=True
    second_call_messages = mock_client.messages.create.call_args_list[1][1]["messages"]
    tool_result_block = second_call_messages[-1]["content"][0]
    assert tool_result_block["is_error"] is True


def test_answer_f1_question_exceeds_max_rounds():
    """Raises ValueError after MAX_TOOL_ROUNDS tool calls with no final answer."""
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _tool_use_response()

    with patch('chat.anthropic.Anthropic', return_value=mock_client), \
         patch('chat.execute_tool', return_value=[]):
        import chat
        importlib.reload(chat)
        with pytest.raises(ValueError, match="Exceeded"):
            chat.answer_f1_question("A question Claude never stops trying to answer")

    assert mock_client.messages.create.call_count == chat.MAX_TOOL_ROUNDS


def test_answer_f1_question_passes_system_prompt():
    """The system prompt is passed on every API call."""
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _end_turn_response("Answer.")

    with patch('chat.anthropic.Anthropic', return_value=mock_client):
        import chat
        importlib.reload(chat)
        chat.answer_f1_question("Any question")

    call_kwargs = mock_client.messages.create.call_args[1]
    assert "system" in call_kwargs
    assert len(call_kwargs["system"]) > 50  # not empty


def test_answer_f1_question_passes_tool_definitions():
    """TOOL_DEFINITIONS are passed to every API call."""
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _end_turn_response("Answer.")

    with patch('chat.anthropic.Anthropic', return_value=mock_client):
        import chat
        importlib.reload(chat)
        chat.answer_f1_question("Any question")

    call_kwargs = mock_client.messages.create.call_args[1]
    assert "tools" in call_kwargs
    assert len(call_kwargs["tools"]) == 14
