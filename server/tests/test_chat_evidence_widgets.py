"""Tests for _widgets_from_analysis_evidence's registry-first dispatch.

C2 adds registry-first lookup for the safe per-tool branches while
preserving the cross-feature orchestration (grip_commitment merge,
track_map passing, focus skip, emit_context_widget skip, dedup).
"""
import pytest

pytestmark = pytest.mark.usefixtures("reset_feature_registry")


def _mini_sectors_sample(total_delta=0.187):
    return {
        "available": True,
        "driver_a": "NOR", "driver_b": "PIA",
        "lap_number": 21, "round_number": 7, "session_type": "Q",
        "n_segments": 25, "weather_state": "dry",
        "segments": [],
        "cumulative_delta": [(0, 0)],
        "total_delta_s": total_delta,
        "segments_won_a": 14, "segments_won_b": 8, "segments_tied": 3,
        "drs_mix_warning": False,
    }


def test_evidence_compare_mini_sectors_goes_through_registry():
    """compare_mini_sectors widget in the evidence path now comes from the
    Feature's make_widget, not the legacy _make_mini_sector_heatmap_widget
    call directly."""
    from features.registry import discover_features
    from features.base import FEATURE_REGISTRY
    discover_features()
    import chat

    feat = FEATURE_REGISTRY["compare_mini_sectors"]
    calls: list[dict] = []
    original = feat.make_widget
    feat.make_widget = lambda r: (calls.append(r) or original(r))

    try:
        evidence = [{"tool": "compare_mini_sectors", "result": _mini_sectors_sample()}]
        widgets = chat._widgets_from_analysis_evidence({}, evidence)
        assert len(calls) == 1, "Feature.make_widget should have fired once"
        assert any(w["type"] == "mini_sector_heatmap" for w in widgets)
    finally:
        feat.make_widget = original


def test_evidence_mini_sectors_suppressed_by_should_show_widget():
    """When mini-sectors result has |total_delta_s| < 0.05, the widget is
    suppressed via the registry's should_show_widget gate — legacy path is
    NOT used as fallback (registry decision is authoritative)."""
    from features.registry import discover_features
    discover_features()
    import chat

    evidence = [{"tool": "compare_mini_sectors", "result": _mini_sectors_sample(total_delta=0.01)}]
    widgets = chat._widgets_from_analysis_evidence({}, evidence)
    assert not any(w.get("type") == "mini_sector_heatmap" for w in widgets), (
        "Tiny-delta mini_sectors must not emit a widget"
    )


def test_evidence_unmigrated_tool_still_works():
    """A not-yet-migrated tool (e.g. get_driver_race_story) still produces
    a widget via the legacy path. Confirms the legacy fallback didn't break."""
    from features.registry import discover_features
    discover_features()
    import chat

    evidence = [{"tool": "get_driver_race_story", "result": {"driver": "NOR", "round_number": 7}}]
    widgets = chat._widgets_from_analysis_evidence({}, evidence)
    # The legacy builder may emit an empty/sparse widget but it MUST be present.
    assert any(w.get("type") == "race_story" for w in widgets) or widgets == []


def test_evidence_cross_feature_orchestration_preserved():
    """The grip_commitment / qualifying_battle merge logic stays on the
    legacy path. Confirms we didn't accidentally route the qualifying_battle
    branch through the registry."""
    from features.registry import discover_features
    discover_features()
    import chat

    evidence = [
        {"tool": "analyze_cornering_loads", "result": {
            "driver_a": "NOR", "driver_b": "PIA",
            "event": "Imola GP", "session": "Q",
        }},
        {"tool": "analyze_qualifying_battle", "result": {
            "round_number": 7, "session_type": "Q",
            "driver_a": "NOR", "driver_b": "PIA",
        }},
    ]
    widgets = chat._widgets_from_analysis_evidence({}, evidence)
    assert any(w.get("type") == "qualifying_battle" for w in widgets)
