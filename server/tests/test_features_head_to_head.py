import pytest

pytestmark = pytest.mark.usefixtures("reset_feature_registry")


def _load_feat():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    return FEATURE_REGISTRY["get_head_to_head"]


def test_head_to_head_registered_after_discover():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    assert "get_head_to_head" in FEATURE_REGISTRY


def test_head_to_head_no_widget():
    feat = _load_feat()
    assert feat.make_widget({"any": "thing"}) == {}
    assert feat.should_show_widget({"any": "thing"}) is False


def test_head_to_head_should_show_widget_meaningful_signal():
    feat = _load_feat()
    # No widget component is wired up yet; even a rich result must stay gated.
    rich = {
        "available": True,
        "driver_a": "NOR", "driver_b": "PIA",
        "wins_a": 5, "wins_b": 3,
    }
    assert feat.should_show_widget(rich) is False


def test_head_to_head_should_show_widget_suppresses_negligible():
    feat = _load_feat()
    assert feat.should_show_widget({"available": False}) is False
    assert feat.should_show_widget({}) is False
