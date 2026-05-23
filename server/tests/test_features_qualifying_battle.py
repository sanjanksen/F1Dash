import pytest

pytestmark = pytest.mark.usefixtures("reset_feature_registry")


def _load_feat():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    return FEATURE_REGISTRY["analyze_qualifying_battle"]


def test_qualifying_battle_registered_after_discover():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    assert "analyze_qualifying_battle" in FEATURE_REGISTRY


def test_qualifying_battle_applies_to_pair_of_drivers():
    feat = _load_feat()
    assert "pair_of_drivers" in feat.applies_to


def test_qualifying_battle_make_widget_produces_typed_widget():
    feat = _load_feat()
    sample = {
        "driver_a": "NOR", "driver_b": "PIA",
        "faster_driver": "NOR", "overall_gap_s": 0.12,
        "event": "Imola", "compared_segment": "Q3",
    }
    w = feat.make_widget(sample)
    assert w["type"] == "qualifying_battle"
    assert w["driver_a"] == "NOR"
    assert w["driver_b"] == "PIA"
    assert w["faster_driver"] == "NOR"


def test_qualifying_battle_should_show_widget_respects_availability():
    feat = _load_feat()
    assert feat.should_show_widget({"driver_a": "NOR", "overall_gap_s": 0.15}) is True
    assert feat.should_show_widget({"available": False}) is False


def test_qualifying_battle_should_show_widget_meaningful_signal():
    feat = _load_feat()
    sample = {"available": True, "overall_gap_s": 0.12, "decisive_sector_gap_s": 0.08}
    assert feat.should_show_widget(sample) is True


def test_qualifying_battle_should_show_widget_suppresses_negligible():
    feat = _load_feat()
    # Overall gap below the 0.03 threshold
    sample = {"available": True, "overall_gap_s": 0.01, "decisive_sector_gap_s": 0.08}
    assert feat.should_show_widget(sample) is False


def test_qualifying_battle_declares_triggered_by_modes():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    feat = FEATURE_REGISTRY["analyze_qualifying_battle"]
    assert feat.triggered_by_modes == frozenset({"driver_comparison"})


def test_qualifying_battle_widget_handles_split_sector_lap():
    """When result.split_sector_lap is True and decisive_sector is None,
    the widget must NOT claim a decisive sector. split_sector_lap is passed
    through so the React component can render the appropriate prose."""
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    feat = FEATURE_REGISTRY["analyze_qualifying_battle"]

    result = {
        "available": True,
        "driver_a": "LEC", "driver_b": "NOR",
        "lap_time_a": "1:28.143", "lap_time_b": "1:28.183",
        "overall_gap_s": 0.040,
        "s1_gap_s": 0.05, "s2_gap_s": 0.05, "s3_gap_s": 0.04,
        "decisive_sector": None,
        "decisive_sector_gap_s": None,
        "split_sector_lap": True,
    }
    widget = feat.make_widget(result)
    assert widget["type"] == "qualifying_battle"
    assert widget.get("decisive_sector") is None
    assert widget.get("split_sector_lap") is True


def test_qualifying_battle_widget_passes_through_decisive_sector_when_set():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    feat = FEATURE_REGISTRY["analyze_qualifying_battle"]

    result = {
        "available": True,
        "driver_a": "LEC", "driver_b": "NOR",
        "lap_time_a": "1:28.143", "lap_time_b": "1:28.183",
        "overall_gap_s": 0.040,
        "s1_gap_s": 0.131, "s2_gap_s": -0.081, "s3_gap_s": -0.010,
        "decisive_sector": "Sector 1",
        "decisive_sector_gap_s": 0.131,
        "split_sector_lap": False,
    }
    widget = feat.make_widget(result)
    assert widget.get("decisive_sector") == "Sector 1"
    assert widget.get("split_sector_lap") is False
