import pytest

pytestmark = pytest.mark.usefixtures("reset_feature_registry")


def test_mini_sectors_feature_registered_after_discover():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    assert "compare_mini_sectors" in FEATURE_REGISTRY


def test_mini_sectors_applies_to_pair_and_lap():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    feat = FEATURE_REGISTRY["compare_mini_sectors"]
    assert "pair_of_drivers" in feat.applies_to
    assert "lap" in feat.applies_to


def test_mini_sectors_relevance_high_for_where_questions():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    feat = FEATURE_REGISTRY["compare_mini_sectors"]
    score_where = feat.is_relevant_for("Where did Norris gain time?", {})
    score_random = feat.is_relevant_for("What is F1?", {})
    assert score_where > score_random
    assert score_where >= 0.5


def test_mini_sectors_relevance_high_for_qualifying_battle_mode():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    feat = FEATURE_REGISTRY["compare_mini_sectors"]
    score = feat.is_relevant_for(
        "Why was Norris faster?",
        {"analysis_mode": "qualifying_battle"},
    )
    assert score >= 0.5


def test_mini_sectors_mode_only_does_not_fire():
    """Mode match without keyword intent must score below the 0.5 fire
    threshold. Otherwise every qualifying_battle conversation would fire
    mini-sectors regardless of what the user actually asked."""
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    feat = FEATURE_REGISTRY["compare_mini_sectors"]
    score = feat.is_relevant_for(
        "What is the weather forecast?",
        {"analysis_mode": "qualifying_battle"},
    )
    assert score < 0.5


def test_mini_sectors_keyword_alone_fires_without_mode():
    """Keyword intent alone (no mode context) should still fire — the user
    is explicitly asking about sector / lap-time differences."""
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    feat = FEATURE_REGISTRY["compare_mini_sectors"]
    score = feat.is_relevant_for("Where did Norris gain time?", {})
    assert score >= 0.5
    assert score < 0.85  # ranked below the keyword+mode case


def test_mini_sectors_should_show_widget_suppresses_tiny_delta():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    feat = FEATURE_REGISTRY["compare_mini_sectors"]
    assert feat.should_show_widget({"total_delta_s": 0.4}) is True
    assert feat.should_show_widget({"total_delta_s": 0.01}) is False
    assert feat.should_show_widget({}) is False


def test_mini_sectors_make_widget_passes_through_to_existing_builder():
    """The Feature's make_widget should produce the same widget shape
    as the existing _make_mini_sector_heatmap_widget in chat.py."""
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    import chat
    FEATURE_REGISTRY.clear()
    discover_features()
    feat = FEATURE_REGISTRY["compare_mini_sectors"]
    sample_result = {
        "available": True,
        "driver_a": "NOR", "driver_b": "PIA",
        "lap_number": 21, "round_number": 7, "session_type": "Q",
        "n_segments": 25, "weather_state": "dry",
        "segments": [],
        "cumulative_delta": [(0, 0)],
        "total_delta_s": 0.187,
        "segments_won_a": 14, "segments_won_b": 8, "segments_tied": 3,
        "drs_mix_warning": False,
    }
    via_feature = feat.make_widget(sample_result)
    via_chat = chat._make_mini_sector_heatmap_widget(sample_result)
    assert via_feature["type"] == "mini_sector_heatmap"
    assert via_feature["type"] == via_chat["type"]
    assert via_feature["driver_a"] == via_chat["driver_a"]
    assert via_feature["total_delta_s"] == via_chat["total_delta_s"]
