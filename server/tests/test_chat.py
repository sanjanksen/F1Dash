# server/tests/test_chat.py
import json
import os
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


def _load_chat_with_client(mock_client):
    import chat
    importlib.reload(chat)
    chat.os.environ["LLM_PROVIDER"] = "anthropic"
    chat._anthropic_client = mock_client
    chat._openai_client = None
    return chat


# ─── Tests ──────────────────────────────────────────────────

def test_answer_f1_question_direct_answer():
    """Claude answers without calling any tools."""
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _end_turn_response("F1 started in 1950.")

    chat = _load_chat_with_client(mock_client)
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

    chat = _load_chat_with_client(mock_client)
    with patch.object(chat, 'execute_tool', return_value=[{"standing": 1, "full_name": "Max Verstappen"}]):
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

    chat = _load_chat_with_client(mock_client)
    with patch.object(chat, 'execute_tool', side_effect=lambda n, a: execute_tool_results[n]):
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

    chat = _load_chat_with_client(mock_client)
    with patch.object(chat, 'execute_tool', side_effect=ValueError("Driver not found: 'nobody'")):
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

    chat = _load_chat_with_client(mock_client)
    with patch.object(chat, 'execute_tool', return_value=[]):
        with pytest.raises(ValueError, match="Exceeded"):
            chat.answer_f1_question("A question Claude never stops trying to answer")

    assert mock_client.messages.create.call_count == chat.MAX_TOOL_ROUNDS


def test_answer_f1_question_passes_system_prompt():
    """The system prompt is passed on every API call."""
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _end_turn_response("Answer.")

    chat = _load_chat_with_client(mock_client)
    chat.answer_f1_question("Any question")

    call_kwargs = mock_client.messages.create.call_args[1]
    assert "system" in call_kwargs
    assert len(call_kwargs["system"]) > 50  # not empty


def test_answer_f1_question_passes_tool_definitions():
    """TOOL_DEFINITIONS are passed to every API call."""
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _end_turn_response("Answer.")

    chat = _load_chat_with_client(mock_client)
    chat.answer_f1_question("Any question")

    call_kwargs = mock_client.messages.create.call_args[1]
    assert "tools" in call_kwargs
    assert len(call_kwargs["tools"]) == len(chat.TOOL_DEFINITIONS)


def test_build_request_system_prompt_uses_previous_context():
    import chat
    resolved = {
        "has_explicit_context": False,
        "used_previous_context": True,
        "entity_type": "driver",
        "entity_name": "George Russell",
        "entity_code": "RUS",
        "event_name": "Japanese Grand Prix",
        "round_number": 3,
        "session_type": None,
        "scope": "overview",
        "suggested_tool": "get_driver_race_story",
        "resolution_confidence": "medium",
        "routing_confidence": "medium",
    }
    prompt = chat._build_request_system_prompt(resolved, None)

    assert "George Russell" in prompt
    assert "Japanese Grand Prix" in prompt
    assert "used_previous_context: True" in prompt
    assert "Routing directive: start with get_driver_race_story" in prompt


def test_suggested_tool_args_driver_story():
    import chat
    resolved = {
        "suggested_tool": "get_driver_race_story",
        "round_number": 3,
        "entity_name": "George Russell",
    }
    assert chat._suggested_tool_args(resolved) == {"round_number": 3, "driver_name": "George Russell"}


def test_prepare_resolved_context_preloads_high_confidence():
    import chat
    resolved = {
        "suggested_tool": "get_driver_race_story",
        "round_number": 3,
        "entity_name": "George Russell",
        "routing_confidence": "high",
        "has_explicit_context": True,
        "used_previous_context": False,
    }
    with patch('chat.resolve_context_from_history', return_value=None), \
         patch('chat.resolve_query_context', return_value=resolved), \
         patch.object(chat, 'execute_tool', return_value={"driver": "George Russell"}) as exec_mock:
        merged, preloaded = chat._prepare_resolved_context("How did Russell do at Suzuka?", [])

    assert merged is resolved
    assert preloaded["tool"] == "get_driver_race_story"
    assert preloaded["result"]["driver"] == "George Russell"
    exec_mock.assert_called_once_with("get_driver_race_story", {"round_number": 3, "driver_name": "George Russell"})


def test_try_deterministic_analysis_uses_analysis_and_writer_stages():
    import chat

    resolved = {
        "analysis_mode": "driver_comparison",
        "analysis_focus": "qualifying",
        "round_number": 3,
        "entity_names": ["Charles Leclerc", "Lando Norris"],
        "entity_codes": ["LEC", "NOR"],
        "session_type": "Q",
    }
    plan = {
        "analysis_mode": "driver_comparison",
        "focus": "qualifying",
        "tool_calls": [],
    }
    evidence = [{"tool": "get_sector_comparison", "result": {"overall_gap_s": -0.106}}]
    analysis = {
        "direct_answer": "Leclerc beat Norris mainly in sector 1.",
        "primary_reason": "Sector 1 pace",
        "secondary_reasons": [],
        "strongest_evidence": ["Sector 1 gap: -0.271s"],
        "caveats": [],
        "confidence": "high",
    }

    with patch.object(chat, '_prepare_resolved_context', return_value=(resolved, None)), \
         patch.object(chat, '_build_analysis_plan', return_value=plan), \
         patch.object(chat, '_retrieve_analysis_evidence', return_value=evidence), \
         patch.object(chat, '_run_anthropic_analysis', return_value=analysis) as analysis_mock, \
         patch.object(chat, '_run_anthropic_answer_writer', return_value="Leclerc beat Norris mainly through sector 1.") as writer_mock:
        result = chat._try_deterministic_analysis("How did Leclerc beat Lando in qualifying at Suzuka?", [], provider="anthropic")

    assert "sector 1" in result.lower()
    analysis_mock.assert_called_once()
    writer_mock.assert_called_once()


def test_build_analysis_plan_uses_qualifying_battle_tool_for_qualifying_comparison():
    import chat

    resolved = {
        "analysis_mode": "driver_comparison",
        "analysis_focus": "qualifying",
        "round_number": 3,
        "entity_names": ["Charles Leclerc", "Lando Norris"],
        "entity_codes": ["LEC", "NOR"],
        "session_type": "Q",
    }

    plan = chat._build_analysis_plan("How did Leclerc beat Lando in qualifying at Suzuka?", resolved)

    tool_names = [tool for tool, _ in plan["tool_calls"]]
    assert "analyze_qualifying_battle" in tool_names
    assert "get_qualifying_results" in tool_names
    assert tool_names.count("get_team_radio") == 2


def test_try_deterministic_analysis_falls_back_on_analysis_failure():
    import chat

    resolved = {
        "analysis_mode": "driver_comparison",
        "analysis_focus": "qualifying",
        "round_number": 3,
        "entity_names": ["Charles Leclerc", "Lando Norris"],
        "entity_codes": ["LEC", "NOR"],
        "session_type": "Q",
    }
    plan = {"analysis_mode": "driver_comparison", "focus": "qualifying", "tool_calls": []}
    evidence = [{"tool": "get_sector_comparison", "result": {"overall_gap_s": -0.106}}]

    with patch('chat.resolve_context_from_history', return_value=None), \
         patch('chat.resolve_query_context', return_value=resolved), \
         patch.object(chat, '_build_analysis_plan', return_value=plan), \
         patch.object(chat, '_retrieve_analysis_evidence', return_value=evidence), \
         patch.object(chat, '_run_anthropic_analysis', side_effect=ValueError("bad json")):
        result = chat._try_deterministic_analysis("How did Leclerc beat Lando in qualifying at Suzuka?", [], provider="anthropic")

    assert result is None
