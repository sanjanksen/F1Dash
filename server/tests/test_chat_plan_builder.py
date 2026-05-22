"""Regression tests for chat._build_analysis_plan.

These tests pin the CURRENT mode -> tools mapping so Task 2.1's refactor
(replacing the hardcoded if/elif with features_for_mode) cannot silently
change which tools fire per mode.

Inventory of _build_analysis_plan branches (as of pre-refactor, server/chat.py:1165):

- circuit_profile:
    requires: country
    tools (always): [get_circuit_profile]
    tools (if round_number): adds [get_circuit_track_map, get_historical_circuit_performance]
    flags: focus="circuit", emit_context_widget=bool(...)

- team_performance:
    requires: round_number AND entity_name (team)
    tools: [analyze_team_performance]
    flags: focus="team"

- team_circuit_fit:
    requires: entity_name (team)
    tools (always): [analyze_team_circuit_fit, get_team_car_profile]
    tools (if round_number): adds [analyze_team_telemetry_traits]
    flags: focus="team_fit", session_type derived from message ("race" -> R else Q)

- grip_comparison:
    requires: round_number AND >=2 entity_codes AND >=2 entity_names
    tools: [analyze_cornering_loads]
    flags: focus="grip"

- race_pace_comparison:
    requires: round_number AND >=2 entity_codes AND >=2 entity_names
    tools: [analyze_race_pace_battle, get_safety_car_periods, get_driver_strategy]
    flags: focus="race"

- driver_comparison (qualifying focus, focus = "qualifying"):
    requires: round_number AND >=2 entity_codes AND >=2 entity_names
    triggered when analysis_focus=="qualifying" OR session_type in (Q, SQ)
    tools: [get_qualifying_results OR get_sprint_qualifying_results (if SQ),
            analyze_qualifying_battle, compare_corner_profiles,
            analyze_cornering_loads, get_team_radio (driver_a), get_team_radio (driver_b)]
    flags: focus="qualifying"

- driver_comparison (race focus, focus in {"race", "session"}):
    requires: round_number AND >=2 entity_codes AND >=2 entity_names
    tools: [get_driver_race_story (driver_a), get_driver_race_story (driver_b),
            analyze_race_pace_battle, get_safety_car_periods]
    flags: focus="race" (or "session")

- No mode / unknown mode / missing required fields: returns None

NOTE: plan["tool_calls"] is a list of (tool_name, args) tuples, NOT dicts.
"""

import pytest


def _resolved(**kwargs):
    """Build a resolved dict for _build_analysis_plan tests.

    Defaults are intentionally minimal — each test passes the fields its branch
    requires. _build_analysis_plan reads keys directly via .get(), so only the
    listed keys matter.
    """
    base = {
        "analysis_mode": kwargs.get("analysis_mode"),
        "round_number": kwargs.get("round_number"),
        "session_type": kwargs.get("session_type"),
        "entity_name": kwargs.get("entity_name"),
        "entity_names": kwargs.get("entity_names"),
        "entity_codes": kwargs.get("entity_codes"),
        "event_name": kwargs.get("event_name"),
        "country": kwargs.get("country"),
        "analysis_focus": kwargs.get("analysis_focus"),
        "has_explicit_context": kwargs.get("has_explicit_context", True),
    }
    return {k: v for k, v in base.items() if v is not None}


def _tool_names(plan):
    return [name for name, _args in plan["tool_calls"]]


# ── circuit_profile ─────────────────────────────────────────────────────────


def test_build_analysis_plan_circuit_profile_with_round():
    from chat import _build_analysis_plan
    plan = _build_analysis_plan(
        "What kind of track is Imola?",
        _resolved(
            analysis_mode="circuit_profile",
            country="Italy",
            event_name="Emilia Romagna Grand Prix",
            round_number=7,
        ),
    )
    assert plan is not None
    assert plan["analysis_mode"] == "circuit_profile"
    assert plan["focus"] == "circuit"
    assert plan["country"] == "Italy"
    assert plan["event_name"] == "Emilia Romagna Grand Prix"
    assert plan["round_number"] == 7
    names = _tool_names(plan)
    assert names == [
        "get_circuit_profile",
        "get_circuit_track_map",
        "get_historical_circuit_performance",
    ]
    assert plan["emit_context_widget"] is True


def test_build_analysis_plan_circuit_profile_without_round():
    from chat import _build_analysis_plan
    plan = _build_analysis_plan(
        "tell me about the track",
        _resolved(
            analysis_mode="circuit_profile",
            country="Italy",
            event_name="Italian Grand Prix",
        ),
    )
    assert plan is not None
    names = _tool_names(plan)
    assert names == ["get_circuit_profile"]


def test_build_analysis_plan_circuit_profile_requires_country():
    from chat import _build_analysis_plan
    plan = _build_analysis_plan(
        "track profile",
        _resolved(analysis_mode="circuit_profile", round_number=7),
    )
    assert plan is None


# ── team_performance ────────────────────────────────────────────────────────


def test_build_analysis_plan_team_performance():
    from chat import _build_analysis_plan
    plan = _build_analysis_plan(
        "How did Ferrari do?",
        _resolved(
            analysis_mode="team_performance",
            round_number=7,
            entity_name="Ferrari",
            session_type="Q",
        ),
    )
    assert plan is not None
    assert plan["analysis_mode"] == "team_performance"
    assert plan["focus"] == "team"
    assert plan["team"] == "Ferrari"
    names = _tool_names(plan)
    assert names == ["analyze_team_performance"]
    _, args = plan["tool_calls"][0]
    assert args == {"round_number": 7, "team_name": "Ferrari", "session_type": "Q"}


def test_build_analysis_plan_team_performance_defaults_session_to_q():
    from chat import _build_analysis_plan
    plan = _build_analysis_plan(
        "How did Ferrari do?",
        _resolved(
            analysis_mode="team_performance",
            round_number=7,
            entity_name="Ferrari",
        ),
    )
    assert plan is not None
    _, args = plan["tool_calls"][0]
    assert args["session_type"] == "Q"


def test_build_analysis_plan_team_performance_missing_team_returns_none():
    from chat import _build_analysis_plan
    plan = _build_analysis_plan(
        "team perf",
        _resolved(analysis_mode="team_performance", round_number=7),
    )
    assert plan is None


def test_build_analysis_plan_team_performance_missing_round_returns_none():
    from chat import _build_analysis_plan
    plan = _build_analysis_plan(
        "team perf",
        _resolved(analysis_mode="team_performance", entity_name="Ferrari"),
    )
    assert plan is None


# ── team_circuit_fit ────────────────────────────────────────────────────────


def test_build_analysis_plan_team_circuit_fit_with_round():
    from chat import _build_analysis_plan
    plan = _build_analysis_plan(
        "Will Ferrari be fast here?",
        _resolved(
            analysis_mode="team_circuit_fit",
            entity_name="Ferrari",
            round_number=7,
        ),
    )
    assert plan is not None
    assert plan["analysis_mode"] == "team_circuit_fit"
    assert plan["focus"] == "team_fit"
    assert plan["team"] == "Ferrari"
    names = _tool_names(plan)
    assert names == [
        "analyze_team_circuit_fit",
        "get_team_car_profile",
        "analyze_team_telemetry_traits",
    ]


def test_build_analysis_plan_team_circuit_fit_without_round():
    from chat import _build_analysis_plan
    plan = _build_analysis_plan(
        "Will Ferrari be fast at this circuit?",
        _resolved(
            analysis_mode="team_circuit_fit",
            entity_name="Ferrari",
        ),
    )
    assert plan is not None
    names = _tool_names(plan)
    assert names == ["analyze_team_circuit_fit", "get_team_car_profile"]


def test_build_analysis_plan_team_circuit_fit_session_q_default():
    from chat import _build_analysis_plan
    plan = _build_analysis_plan(
        "How will Ferrari fit this track?",
        _resolved(analysis_mode="team_circuit_fit", entity_name="Ferrari"),
    )
    assert plan is not None
    _, args = plan["tool_calls"][0]
    assert args["session_type"] == "Q"


def test_build_analysis_plan_team_circuit_fit_session_r_when_race_in_question():
    from chat import _build_analysis_plan
    plan = _build_analysis_plan(
        "How will Ferrari fit this track in the race?",
        _resolved(analysis_mode="team_circuit_fit", entity_name="Ferrari"),
    )
    assert plan is not None
    _, args = plan["tool_calls"][0]
    assert args["session_type"] == "R"


def test_build_analysis_plan_team_circuit_fit_missing_team_returns_none():
    from chat import _build_analysis_plan
    plan = _build_analysis_plan(
        "track fit",
        _resolved(analysis_mode="team_circuit_fit", round_number=7),
    )
    assert plan is None


# ── grip_comparison ─────────────────────────────────────────────────────────


def test_build_analysis_plan_grip_comparison():
    from chat import _build_analysis_plan
    plan = _build_analysis_plan(
        "Who has more grip, Verstappen or Leclerc?",
        _resolved(
            analysis_mode="grip_comparison",
            round_number=7,
            entity_codes=["VER", "LEC"],
            entity_names=["Max Verstappen", "Charles Leclerc"],
            session_type="Q",
        ),
    )
    assert plan is not None
    assert plan["analysis_mode"] == "grip_comparison"
    assert plan["focus"] == "grip"
    assert plan["drivers"] == [
        {"name": "Max Verstappen", "code": "VER"},
        {"name": "Charles Leclerc", "code": "LEC"},
    ]
    names = _tool_names(plan)
    assert names == ["analyze_cornering_loads"]
    _, args = plan["tool_calls"][0]
    assert args == {
        "round_number": 7,
        "session_type": "Q",
        "driver_a": "VER",
        "driver_b": "LEC",
    }


def test_build_analysis_plan_grip_comparison_defaults_session_to_q():
    from chat import _build_analysis_plan
    plan = _build_analysis_plan(
        "grip diff",
        _resolved(
            analysis_mode="grip_comparison",
            round_number=7,
            entity_codes=["VER", "LEC"],
            entity_names=["Max Verstappen", "Charles Leclerc"],
        ),
    )
    assert plan is not None
    _, args = plan["tool_calls"][0]
    assert args["session_type"] == "Q"


def test_build_analysis_plan_grip_comparison_needs_two_drivers():
    from chat import _build_analysis_plan
    plan = _build_analysis_plan(
        "grip",
        _resolved(
            analysis_mode="grip_comparison",
            round_number=7,
            entity_codes=["VER"],
            entity_names=["Max Verstappen"],
        ),
    )
    assert plan is None


# ── race_pace_comparison ────────────────────────────────────────────────────


def test_build_analysis_plan_race_pace_comparison():
    from chat import _build_analysis_plan
    plan = _build_analysis_plan(
        "Who had better race pace, Verstappen or Leclerc?",
        _resolved(
            analysis_mode="race_pace_comparison",
            round_number=7,
            entity_codes=["VER", "LEC"],
            entity_names=["Max Verstappen", "Charles Leclerc"],
            session_type="R",
        ),
    )
    assert plan is not None
    assert plan["analysis_mode"] == "race_pace_comparison"
    assert plan["focus"] == "race"
    assert plan["drivers"] == [
        {"name": "Max Verstappen", "code": "VER"},
        {"name": "Charles Leclerc", "code": "LEC"},
    ]
    names = _tool_names(plan)
    assert names == [
        "analyze_race_pace_battle",
        "get_safety_car_periods",
        "get_driver_strategy",
    ]


def test_build_analysis_plan_race_pace_comparison_defaults_session_to_r():
    from chat import _build_analysis_plan
    plan = _build_analysis_plan(
        "race pace",
        _resolved(
            analysis_mode="race_pace_comparison",
            round_number=7,
            entity_codes=["VER", "LEC"],
            entity_names=["Max Verstappen", "Charles Leclerc"],
        ),
    )
    assert plan is not None
    _, args = plan["tool_calls"][0]
    assert args["session_type"] == "R"


def test_build_analysis_plan_race_pace_comparison_needs_round():
    from chat import _build_analysis_plan
    plan = _build_analysis_plan(
        "race pace",
        _resolved(
            analysis_mode="race_pace_comparison",
            entity_codes=["VER", "LEC"],
            entity_names=["Max Verstappen", "Charles Leclerc"],
        ),
    )
    assert plan is None


# ── driver_comparison: qualifying focus ─────────────────────────────────────


def test_build_analysis_plan_driver_comparison_qualifying():
    from chat import _build_analysis_plan
    plan = _build_analysis_plan(
        "Verstappen vs Leclerc in qualifying",
        _resolved(
            analysis_mode="driver_comparison",
            round_number=7,
            entity_codes=["VER", "LEC"],
            entity_names=["Max Verstappen", "Charles Leclerc"],
            session_type="Q",
            analysis_focus="qualifying",
        ),
    )
    assert plan is not None
    assert plan["analysis_mode"] == "driver_comparison"
    assert plan["focus"] == "qualifying"
    names = _tool_names(plan)
    assert names == [
        "get_qualifying_results",
        "analyze_qualifying_battle",
        "compare_corner_profiles",
        "analyze_cornering_loads",
        "get_team_radio",
        "get_team_radio",
    ]
    # team_radio called once per driver
    radio_calls = [args for name, args in plan["tool_calls"] if name == "get_team_radio"]
    assert radio_calls[0]["driver_ref"] == "VER"
    assert radio_calls[1]["driver_ref"] == "LEC"
    assert radio_calls[0]["limit"] == 6
    assert radio_calls[1]["limit"] == 6


def test_build_analysis_plan_driver_comparison_sprint_qualifying_uses_sprint_results_tool():
    from chat import _build_analysis_plan
    plan = _build_analysis_plan(
        "VER vs LEC in sprint qualifying",
        _resolved(
            analysis_mode="driver_comparison",
            round_number=7,
            entity_codes=["VER", "LEC"],
            entity_names=["Max Verstappen", "Charles Leclerc"],
            session_type="SQ",
            analysis_focus="qualifying",
        ),
    )
    assert plan is not None
    names = _tool_names(plan)
    assert names[0] == "get_sprint_qualifying_results"
    # all qualifying tools use SQ session type
    _, qbattle_args = plan["tool_calls"][1]
    assert qbattle_args["session_type"] == "SQ"


def test_build_analysis_plan_driver_comparison_qualifying_inferred_from_session():
    """No analysis_focus passed; session_type=Q should pick qualifying focus."""
    from chat import _build_analysis_plan
    plan = _build_analysis_plan(
        "VER vs LEC",
        _resolved(
            analysis_mode="driver_comparison",
            round_number=7,
            entity_codes=["VER", "LEC"],
            entity_names=["Max Verstappen", "Charles Leclerc"],
            session_type="Q",
        ),
    )
    assert plan is not None
    assert plan["focus"] == "qualifying"
    names = _tool_names(plan)
    assert "analyze_qualifying_battle" in names


# ── driver_comparison: race focus ───────────────────────────────────────────


def test_build_analysis_plan_driver_comparison_race():
    from chat import _build_analysis_plan
    plan = _build_analysis_plan(
        "Verstappen vs Leclerc in the race",
        _resolved(
            analysis_mode="driver_comparison",
            round_number=7,
            entity_codes=["VER", "LEC"],
            entity_names=["Max Verstappen", "Charles Leclerc"],
            session_type="R",
            analysis_focus="race",
        ),
    )
    assert plan is not None
    assert plan["focus"] == "race"
    names = _tool_names(plan)
    assert names == [
        "get_driver_race_story",
        "get_driver_race_story",
        "analyze_race_pace_battle",
        "get_safety_car_periods",
    ]
    race_story_args = [args for name, args in plan["tool_calls"] if name == "get_driver_race_story"]
    assert race_story_args[0]["driver_name"] == "Max Verstappen"
    assert race_story_args[1]["driver_name"] == "Charles Leclerc"
    assert race_story_args[0]["session_type"] == "R"


def test_build_analysis_plan_driver_comparison_sprint_uses_s_session():
    from chat import _build_analysis_plan
    plan = _build_analysis_plan(
        "VER vs LEC in the sprint",
        _resolved(
            analysis_mode="driver_comparison",
            round_number=7,
            entity_codes=["VER", "LEC"],
            entity_names=["Max Verstappen", "Charles Leclerc"],
            session_type="S",
            analysis_focus="race",
        ),
    )
    assert plan is not None
    race_story_args = [args for name, args in plan["tool_calls"] if name == "get_driver_race_story"]
    assert race_story_args[0]["session_type"] == "S"


def test_build_analysis_plan_driver_comparison_race_inferred_from_session():
    """No analysis_focus passed; session_type=R should pick race focus."""
    from chat import _build_analysis_plan
    plan = _build_analysis_plan(
        "VER vs LEC",
        _resolved(
            analysis_mode="driver_comparison",
            round_number=7,
            entity_codes=["VER", "LEC"],
            entity_names=["Max Verstappen", "Charles Leclerc"],
            session_type="R",
        ),
    )
    assert plan is not None
    assert plan["focus"] == "race"
    names = _tool_names(plan)
    assert "analyze_race_pace_battle" in names


def test_build_analysis_plan_driver_comparison_needs_two_drivers():
    from chat import _build_analysis_plan
    plan = _build_analysis_plan(
        "VER alone",
        _resolved(
            analysis_mode="driver_comparison",
            round_number=7,
            entity_codes=["VER"],
            entity_names=["Max Verstappen"],
            session_type="Q",
        ),
    )
    assert plan is None


def test_build_analysis_plan_driver_comparison_needs_round():
    from chat import _build_analysis_plan
    plan = _build_analysis_plan(
        "VER vs LEC",
        _resolved(
            analysis_mode="driver_comparison",
            entity_codes=["VER", "LEC"],
            entity_names=["Max Verstappen", "Charles Leclerc"],
            session_type="Q",
        ),
    )
    assert plan is None


# ── None / unknown mode ─────────────────────────────────────────────────────


def test_build_analysis_plan_returns_none_for_no_mode():
    from chat import _build_analysis_plan
    assert _build_analysis_plan("hi", _resolved(analysis_mode=None)) is None


def test_build_analysis_plan_returns_none_for_unknown_mode():
    from chat import _build_analysis_plan
    assert _build_analysis_plan("hi", _resolved(analysis_mode="not_a_real_mode")) is None
