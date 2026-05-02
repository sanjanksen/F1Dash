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


def test_extract_inline_data_table_widget():
    import chat
    importlib.reload(chat)

    text = """Piastri was the cleanest tyre manager.

```f1-widget
{"type":"data_table","title":"Tyre management ranking","columns":[{"key":"rank","label":"Rank","align":"right"},{"key":"driver","label":"Driver"},{"key":"note","label":"Note"}],"rows":[{"rank":"1","driver":"PIA","note":"Best consistency"},{"rank":"2","driver":"ANT","note":"Strong hard stint"}]}
```"""

    clean, widgets = chat._extract_inline_widgets(text)

    assert clean == "Piastri was the cleanest tyre manager."
    assert widgets[0]["type"] == "data_table"
    assert widgets[0]["columns"][0]["align"] == "right"
    assert widgets[0]["rows"][1]["driver"] == "ANT"


def test_answer_payload_strips_inline_widget_from_anthropic_response():
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _end_turn_response(
        'Russell won, but Piastri had the cleaner deg profile.\n\n'
        '```f1-widget\n'
        '{"type":"data_table","title":"Consistency ranking","columns":[{"key":"rank","label":"Rank","align":"right"},{"key":"driver","label":"Driver"}],"rows":[{"rank":"1","driver":"PIA"}]}\n'
        '```'
    )

    chat = _load_chat_with_client(mock_client)
    result = chat.answer_f1_payload("Rank tyre management")

    assert "f1-widget" not in result["response"]
    assert result["widgets"][0]["type"] == "data_table"
    assert result["widgets"][0]["title"] == "Consistency ranking"


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
    assert chat._suggested_tool_args(resolved) == {"round_number": 3, "driver_name": "George Russell", "session_type": "R"}


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
    exec_mock.assert_called_once_with("get_driver_race_story", {"round_number": 3, "driver_name": "George Russell", "session_type": "R"})


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

    with patch('chat.resolve_context_from_history', return_value=None), \
         patch('chat.resolve_query_context', return_value=resolved), \
         patch.object(chat, '_build_analysis_plan', return_value=plan), \
         patch.object(chat, '_retrieve_analysis_evidence', return_value=evidence), \
         patch.object(chat, '_run_anthropic_analysis', return_value=analysis) as analysis_mock, \
         patch.object(chat, '_run_anthropic_answer_writer', return_value="Leclerc beat Norris mainly through sector 1.") as writer_mock:
        result = chat._try_deterministic_analysis("How did Leclerc beat Lando in qualifying at Suzuka?", [], provider="anthropic")

    assert "sector 1" in result["response"].lower()
    assert result["widgets"] == []
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
    assert "analyze_cornering_loads" in tool_names
    assert "get_qualifying_results" in tool_names
    assert tool_names.count("get_team_radio") == 2


def test_qualifying_widget_includes_grip_commitment_from_cornering_loads():
    import chat

    evidence = [
        {
            "tool": "analyze_qualifying_battle",
            "result": {
                "driver_a": "ANT",
                "driver_b": "RUS",
                "faster_driver": "ANT",
            },
        },
        {
            "tool": "analyze_cornering_loads",
            "result": {
                "driver_a": "ANT",
                "driver_b": "RUS",
                "summary": {
                    "ANT": {
                        "avg_grip_utilisation_pct": 72.4,
                        "pct_time_above_90pct_grip": 18.0,
                        "avg_corrections_per_corner": 2.1,
                        "avg_load_variance": 0.041,
                    },
                    "RUS": {
                        "avg_grip_utilisation_pct": 68.2,
                        "pct_time_above_90pct_grip": 11.0,
                        "avg_corrections_per_corner": 3.4,
                        "avg_load_variance": 0.062,
                    },
                },
            },
        },
    ]

    widgets = chat._widgets_from_analysis_evidence({"focus": "qualifying"}, evidence)

    assert widgets[0]["type"] == "qualifying_battle"
    assert widgets[0]["grip_commitment"]["commitment_driver"] == "ANT"
    assert widgets[0]["grip_commitment"]["edge_driver"] == "ANT"
    assert widgets[0]["grip_commitment"]["smooth_driver"] == "ANT"


def test_canonicalize_qualifying_analysis_aligns_answer_with_widget_source():
    import chat

    analysis = {
        "direct_answer": "Antonelli won it at 3700m because Russell clipped.",
        "primary_reason": "Energy clipping was decisive.",
        "secondary_reasons": [],
        "strongest_evidence": [],
        "caveats": [],
        "confidence": "medium",
    }
    evidence = [{
        "tool": "analyze_qualifying_battle",
        "result": {
            "driver_a": "ANT",
            "driver_b": "RUS",
            "faster_driver": "ANT",
            "slower_driver": "RUS",
            "overall_gap_s": -0.298,
            "decisive_sector": "Sector 2",
            "decisive_sector_gap_s": -0.168,
            "decisive_distance_m": 600,
            "cause_explanations": [
                {
                    "cause_type": "traction",
                    "rank": 1,
                    "distance_m": 600,
                    "delta_speed_kph": 25.0,
                },
                {
                    "cause_type": "braking",
                    "rank": 2,
                    "distance_m": 2100,
                    "delta_speed_kph": 6.0,
                },
            ],
            "strongest_evidence": ["Primary mechanism — traction: 25.0 kph speed separation around 600m."],
            "telemetry_available": True,
        },
    }]

    canonical = chat._canonicalize_qualifying_analysis(analysis, evidence)

    assert "600m" in canonical["direct_answer"]
    assert "3700m" not in canonical["direct_answer"]
    assert "25.0 kph" in canonical["primary_reason"]
    assert "traction" not in canonical["primary_reason"].lower() or "Cause:" in canonical["primary_reason"]
    assert "2100m" in canonical["secondary_reasons"][0]


def test_build_analysis_plan_uses_requested_session_for_race_pace_comparison():
    import chat

    resolved = {
        "analysis_mode": "race_pace_comparison",
        "analysis_focus": "race",
        "round_number": 3,
        "entity_names": ["Max Verstappen", "Lando Norris"],
        "entity_codes": ["VER", "NOR"],
        "session_type": "S",
    }

    plan = chat._build_analysis_plan("Why did Verstappen pull away from Norris in the sprint?", resolved)

    assert plan["tool_calls"][0][0] == "analyze_race_pace_battle"
    assert plan["tool_calls"][0][1]["session_type"] == "S"
    assert plan["tool_calls"][1][1]["session_type"] == "S"
    assert plan["tool_calls"][2][1]["session_type"] == "S"


def test_widgets_from_preloaded_supports_race_pace_battle():
    import chat

    widgets = chat._widgets_from_preloaded({
        "tool": "analyze_race_pace_battle",
        "result": {
            "driver_a": "VER",
            "driver_b": "NOR",
            "event": "Japanese Grand Prix",
            "session": "R",
        },
    })

    assert widgets[0]["type"] == "race_pace_battle"
    assert widgets[0]["title"] == "VER vs NOR"


def test_widgets_from_preloaded_supports_corner_comparison():
    import chat

    widgets = chat._widgets_from_preloaded({
        "tool": "compare_corner_profiles",
        "result": {
            "driver_a": "LEC",
            "driver_b": "NOR",
            "event": "Japanese Grand Prix",
            "session": "Q",
        },
    })

    assert widgets[0]["type"] == "corner_comparison"
    assert widgets[0]["title"] == "LEC vs NOR"


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


def test_answer_f1_payload_includes_preloaded_race_story_widget():
    import chat

    resolved = {
        "suggested_tool": "get_driver_race_story",
        "round_number": 3,
        "entity_name": "George Russell",
        "routing_confidence": "high",
        "has_explicit_context": True,
        "used_previous_context": False,
    }
    preloaded = {
        "tool": "get_driver_race_story",
        "result": {
            "driver": "George Russell",
            "code": "RUS",
            "team": "Mercedes",
            "event": "Japanese Grand Prix",
            "race": {"grid_position": 5, "finish_position": 4, "points": 12, "status": "Finished"},
            "qualifying": {"position": 5},
            "pit_stops": [],
            "story_points": ["Gained one place from grid to flag."],
            "radio_highlights": [],
            "interval_summary": None,
            "position_timeline_summary": None,
            "rivalry_story": [],
        },
    }
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _end_turn_response("Russell ran a tidy race to P4.")

    chat = _load_chat_with_client(mock_client)
    with patch.object(chat, '_try_deterministic_analysis', return_value=None), \
         patch.object(chat, '_prepare_resolved_context', return_value=(resolved, preloaded)):
        payload = chat.answer_f1_payload("How did Russell do at Suzuka?", [])

    assert payload["response"] == "Russell ran a tidy race to P4."
    assert payload["widgets"][0]["type"] == "race_story"


def _read_chat_source() -> str:
    chat_path = os.path.join(os.path.dirname(__file__), "..", "chat.py")
    with open(chat_path) as f:
        return f.read()


def test_run_anthropic_analysis_uses_current_model():
    """The analysis call must use the current Anthropic model, not a deprecated one."""
    source = _read_chat_source()
    assert "claude-opus-4-5" not in source, (
        "chat.py still references deprecated model claude-opus-4-5"
    )
    assert "claude-opus-4-7" in source, (
        "chat.py must reference the current model claude-opus-4-7"
    )


def test_run_anthropic_answer_writer_uses_current_model():
    """The answer-writer call must use the current Anthropic model, not a deprecated one."""
    source = _read_chat_source()
    assert "claude-opus-4-5" not in source, (
        "chat.py still references deprecated model claude-opus-4-5"
    )
    assert "claude-opus-4-7" in source, (
        "chat.py must reference the current model claude-opus-4-7"
    )


def test_build_analysis_plan_circuit_profile_without_round():
    """Circuit profile plan is built from country alone — round_number is not required."""
    import chat as chat_module
    resolved = {
        "analysis_mode": "circuit_profile",
        "country": "United States",
        "event_name": "Miami Grand Prix",
        "round_number": None,
    }
    plan = chat_module._build_analysis_plan("tell me about the miami circuit", resolved)
    assert plan is not None
    assert plan["analysis_mode"] == "circuit_profile"
    tool_names = [name for name, _ in plan["tool_calls"]]
    assert "get_circuit_profile" in tool_names
    profile_args = next(args for name, args in plan["tool_calls"] if name == "get_circuit_profile")
    assert profile_args["country"] == "United States"
    assert profile_args["event_name"] == "Miami Grand Prix"
    assert plan["emit_context_widget"] is True


def test_build_analysis_plan_suppresses_inherited_circuit_widget():
    import chat as chat_module
    resolved = {
        "analysis_mode": "circuit_profile",
        "country": "United States",
        "event_name": "Miami Grand Prix",
        "round_number": 6,
        "has_explicit_context": False,
        "used_previous_context": True,
    }
    plan = chat_module._build_analysis_plan("what about sector 2?", resolved)

    assert plan is not None
    assert plan["analysis_mode"] == "circuit_profile"
    assert plan["emit_context_widget"] is False


def test_widgets_from_analysis_evidence_suppresses_context_widget_when_requested():
    import chat as chat_module
    evidence = [{
        "tool": "get_circuit_profile",
        "result": {
            "circuit_key": "miami",
            "circuit_name": "Miami International Autodrome",
        },
    }]

    widgets = chat_module._widgets_from_analysis_evidence(
        {"analysis_mode": "circuit_profile", "emit_context_widget": False},
        evidence,
    )

    assert widgets == []


def test_build_analysis_plan_team_circuit_fit_uses_all_evidence_layers_when_round_known():
    import chat as chat_module
    resolved = {
        "analysis_mode": "team_circuit_fit",
        "entity_name": "Mercedes",
        "round_number": 3,
        "session_type": "Q",
    }
    plan = chat_module._build_analysis_plan("what tracks suit Mercedes at Suzuka?", resolved)

    tool_names = [name for name, _ in plan["tool_calls"]]
    assert tool_names == [
        "analyze_team_circuit_fit",
        "get_team_car_profile",
        "analyze_team_telemetry_traits",
    ]


def test_make_circuit_profile_widget_maps_all_fields():
    """_make_circuit_profile_widget passes through all profile fields with type=circuit_profile."""
    import chat as chat_module
    profile = {
        "circuit_key": "miami",
        "circuit_name": "Miami International Autodrome",
        "character": "street_like_mixed",
        "downforce_level": "medium_high",
        "sector_1": {
            "type": "medium_speed_hairpin",
            "description": "T1-T6: hard braking into T1",
            "style_advantage": "late_braker",
            "energy_demand": "medium",
        },
        "sector_2": {
            "type": "high_speed_straight_into_heavy_braking",
            "description": "T7-T11: long back straight",
            "style_advantage": "late_braker",
            "energy_demand": "very_high",
        },
        "sector_3": {
            "type": "stop_and_go",
            "description": "T12-T19: marina hairpins",
            "style_advantage": "v_line",
            "energy_demand": "medium",
        },
        "energy_profile": {
            "deployment_demand": "high",
            "clipping_risk": "medium",
            "harvesting_opportunity": "medium",
            "key_straights": ["back_straight"],
            "notes": "Good harvesting at marina hairpins.",
        },
        "style_verdict": {
            "qualifier": "v_line_late_braker",
            "explanation": "V-line late-brakers have the structural edge.",
        },
        "tyre_challenge": "Heavy rear wear from aggressive traction zones.",
        "narrative": "Miami is a stop-and-go street-like circuit.",
    }
    widget = chat_module._make_circuit_profile_widget(profile)

    assert widget["type"] == "circuit_profile"
    assert widget["circuit_name"] == "Miami International Autodrome"
    assert widget["circuit_key"] == "miami"
    assert widget["character"] == "street_like_mixed"
    assert widget["sector_1"]["style_advantage"] == "late_braker"
    assert widget["sector_3"]["style_advantage"] == "v_line"
    assert widget["energy_profile"]["deployment_demand"] == "high"
    assert widget["style_verdict"]["qualifier"] == "v_line_late_braker"
    assert widget["tyre_challenge"] == "Heavy rear wear from aggressive traction zones."


def test_build_analysis_plan_sprint_qualifying_uses_sq_session():
    import chat

    resolved = {
        "analysis_mode": "driver_comparison",
        "analysis_focus": "qualifying",
        "round_number": 5,
        "entity_names": ["Lando Norris", "Oscar Piastri"],
        "entity_codes": ["NOR", "PIA"],
        "session_type": "SQ",
    }

    plan = chat._build_analysis_plan("Why was Norris faster than Piastri in sprint qualifying?", resolved)

    assert plan is not None
    tool_names = [t[0] for t in plan["tool_calls"]]
    assert "analyze_qualifying_battle" in tool_names
    sq_battle = next(t for t in plan["tool_calls"] if t[0] == "analyze_qualifying_battle")
    assert sq_battle[1]["session_type"] == "SQ"


def test_build_analysis_plan_sprint_race_uses_s_session_for_story():
    import chat

    resolved = {
        "analysis_mode": "driver_comparison",
        "analysis_focus": "race",
        "round_number": 5,
        "entity_names": ["Lando Norris", "Oscar Piastri"],
        "entity_codes": ["NOR", "PIA"],
        "session_type": "S",
    }

    plan = chat._build_analysis_plan("Compare Norris and Piastri in the sprint", resolved)

    assert plan is not None
    story_calls = [t for t in plan["tool_calls"] if t[0] == "get_driver_race_story"]
    assert all(t[1].get("session_type") == "S" for t in story_calls)


def test_suggested_tool_args_sprint_race_story():
    import chat

    resolved = {
        "suggested_tool": "get_driver_race_story",
        "round_number": 5,
        "entity_name": "Lando Norris",
        "session_type": "S",
    }

    args = chat._suggested_tool_args(resolved)

    assert args is not None
    assert args["session_type"] == "S"


def test_suggested_tool_args_sprint_qualifying():
    import chat

    resolved = {
        "suggested_tool": "get_sprint_qualifying_results",
        "round_number": 5,
        "session_type": "SQ",
    }

    args = chat._suggested_tool_args(resolved)

    assert args is not None
    assert args["round_number"] == 5
