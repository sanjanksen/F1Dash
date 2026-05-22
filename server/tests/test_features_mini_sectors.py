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


def test_mini_sectors_should_show_widget_suppresses_tiny_delta():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    feat = FEATURE_REGISTRY["compare_mini_sectors"]
    full = {
        "available": True,
        "total_delta_s": 0.4,
        "segments": [{} for _ in range(10)],
        "segments_won_a": 2, "segments_won_b": 2,
    }
    assert feat.should_show_widget(full) is True
    assert feat.should_show_widget({**full, "total_delta_s": 0.01}) is False
    assert feat.should_show_widget({}) is False


def test_mini_sectors_should_show_widget_meaningful_signal():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    feat = FEATURE_REGISTRY["compare_mini_sectors"]
    sample = {
        "available": True,
        "segments": [{} for _ in range(12)],
        "segments_won_a": 5,
        "segments_won_b": 4,
        "total_delta_s": 0.187,
    }
    assert feat.should_show_widget(sample) is True


def test_mini_sectors_should_show_widget_suppresses_negligible():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    feat = FEATURE_REGISTRY["compare_mini_sectors"]
    # Flip only segments_won to fail the won-segment gate
    sample = {
        "available": True,
        "segments": [{} for _ in range(12)],
        "segments_won_a": 1,
        "segments_won_b": 1,
        "total_delta_s": 0.187,
    }
    assert feat.should_show_widget(sample) is False


def test_mini_sectors_make_widget_produces_typed_widget():
    """The Feature's make_widget should produce a typed mini_sector_heatmap widget."""
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
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
    widget = feat.make_widget(sample_result)
    assert widget["type"] == "mini_sector_heatmap"
    assert widget["driver_a"] == "NOR"
    assert widget["total_delta_s"] == 0.187
    assert widget["lap_number"] == 21
