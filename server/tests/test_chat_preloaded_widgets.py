"""Tests for _widgets_from_preloaded's registry-first dispatch.

After Phase C1, _widgets_from_preloaded checks FEATURE_REGISTRY first.
If a feature is registered for the preloaded tool, that path runs;
otherwise the legacy if/elif chain handles it.
"""
import pytest

pytestmark = pytest.mark.usefixtures("reset_feature_registry")


def test_preloaded_registered_feature_uses_registry():
    """compare_mini_sectors is in FEATURE_REGISTRY; its widget should come
    via feature.make_widget, NOT via the legacy _make_mini_sector_heatmap_widget
    branch."""
    from features.registry import discover_features
    from features.base import FEATURE_REGISTRY
    discover_features()
    import chat

    # Spy on the feature's make_widget to confirm the registry path fired
    feat = FEATURE_REGISTRY["compare_mini_sectors"]
    calls: list[dict] = []
    original_make = feat.make_widget
    def spy(result):
        calls.append(result)
        return original_make(result)
    feat.make_widget = spy

    try:
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
        widgets = chat._widgets_from_preloaded({"tool": "compare_mini_sectors", "result": sample_result})
        assert len(calls) == 1
        assert calls[0] == sample_result
        assert len(widgets) == 1
        assert widgets[0]["type"] == "mini_sector_heatmap"
    finally:
        feat.make_widget = original_make


def test_preloaded_unregistered_tool_uses_legacy_branch():
    """analyze_qualifying_battle isn't migrated yet — it should still produce
    a widget via the legacy _make_qualifying_battle_widget branch."""
    from features.registry import discover_features
    discover_features()
    import chat
    sample_result = {
        "round_number": 7, "session_type": "Q",
        "driver_a": "NOR", "driver_b": "PIA",
        # minimal — _make_qualifying_battle_widget should still emit type=qualifying_battle
    }
    widgets = chat._widgets_from_preloaded({"tool": "analyze_qualifying_battle", "result": sample_result})
    assert len(widgets) == 1
    assert widgets[0]["type"] == "qualifying_battle"


def test_preloaded_unknown_tool_returns_empty():
    """Unrecognized tool name → empty widget list (unchanged)."""
    import chat
    widgets = chat._widgets_from_preloaded({"tool": "_nonexistent_tool", "result": {}})
    assert widgets == []


def test_preloaded_empty_input_returns_empty():
    """No tool/result → empty (unchanged)."""
    import chat
    assert chat._widgets_from_preloaded(None) == []
    assert chat._widgets_from_preloaded({}) == []
    assert chat._widgets_from_preloaded({"tool": "compare_mini_sectors"}) == []  # no result key


def test_preloaded_registered_feature_respects_should_show_widget():
    """If the feature's should_show_widget returns False, no widget should
    be emitted — even though the tool name matches a registered feature."""
    from features.registry import discover_features
    from features.base import FEATURE_REGISTRY
    discover_features()
    import chat

    # mini_sectors's should_show_widget returns False when |total_delta_s| < 0.05
    sample_result = {
        "available": True,
        "driver_a": "NOR", "driver_b": "PIA",
        "lap_number": 21, "round_number": 7, "session_type": "Q",
        "total_delta_s": 0.01,  # below the 0.05 gate
        "segments": [], "cumulative_delta": [(0, 0)],
        "segments_won_a": 0, "segments_won_b": 0, "segments_tied": 0,
        "drs_mix_warning": False, "n_segments": 25, "weather_state": "dry",
    }
    widgets = chat._widgets_from_preloaded({"tool": "compare_mini_sectors", "result": sample_result})
    assert widgets == []
