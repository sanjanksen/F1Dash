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


def test_head_to_head_relevance_high_for_h2h_keyword():
    feat = _load_feat()
    assert feat.is_relevant_for("Norris vs Piastri this season", {}) >= 0.5
    assert feat.is_relevant_for("Tell me about the weather", {}) < 0.5


def test_head_to_head_no_widget():
    feat = _load_feat()
    assert feat.make_widget({"any": "thing"}) == {}
    assert feat.should_show_widget({"any": "thing"}) is False
