import pytest

pytestmark = pytest.mark.usefixtures("reset_feature_registry")


def test_pit_stop_analysis_registered():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    assert "get_pit_stop_analysis" in FEATURE_REGISTRY


def test_pit_stop_analysis_applies_to_race_session():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    feat = FEATURE_REGISTRY["get_pit_stop_analysis"]
    assert "race_session" in feat.applies_to


def test_pit_stop_analysis_make_widget_delegates():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    feat = FEATURE_REGISTRY["get_pit_stop_analysis"]
    sample = {"round_number": 7, "drivers": []}
    w = feat.make_widget(sample)
    assert w.get("type") == "pit_stop_strategy"


def test_pit_stop_analysis_should_show_widget_suppresses_empty():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    feat = FEATURE_REGISTRY["get_pit_stop_analysis"]
    full = {
        "available": True,
        "total_laps": 56,
        "drivers": [
            {"compound": "M", "stop_count": 1},
            {"compound": "H", "stop_count": 2},
            {"compound": "M", "stop_count": 1},
        ],
    }
    assert feat.should_show_widget({"available": False}) is False
    assert feat.should_show_widget({}) is False
    assert feat.should_show_widget(full) is True


def test_pit_stop_analysis_should_show_widget_meaningful_signal():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    feat = FEATURE_REGISTRY["get_pit_stop_analysis"]
    sample = {
        "available": True,
        "total_laps": 53,
        "drivers": [
            {"compound": "S", "stop_count": 1},
            {"compound": "M", "stop_count": 2},
            {"compound": "M", "stop_count": 2},
            {"compound": "H", "stop_count": 1},
        ],
    }
    assert feat.should_show_widget(sample) is True


def test_pit_stop_analysis_should_show_widget_suppresses_negligible():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    feat = FEATURE_REGISTRY["get_pit_stop_analysis"]
    # All drivers identical: only 1 compound, only 1 stop_count
    sample = {
        "available": True,
        "total_laps": 53,
        "drivers": [
            {"compound": "M", "stop_count": 1},
            {"compound": "M", "stop_count": 1},
            {"compound": "M", "stop_count": 1},
        ],
    }
    assert feat.should_show_widget(sample) is False
