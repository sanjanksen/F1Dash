import pytest

pytestmark = pytest.mark.usefixtures("reset_feature_registry")


def test_anthropic_tool_definitions_includes_registry_features():
    """TOOL_DEFINITIONS should include compare_mini_sectors after discover_features."""
    from features.registry import discover_features
    discover_features()
    import importlib
    import tools
    importlib.reload(tools)  # re-run module-level auto-extension code
    names = {t["name"] for t in tools.TOOL_DEFINITIONS}
    assert "compare_mini_sectors" in names


def test_openai_tool_definitions_includes_registry_features():
    from features.registry import discover_features
    discover_features()
    import importlib
    import tools
    importlib.reload(tools)
    names = {t["function"]["name"] for t in tools.OPENAI_TOOL_DEFINITIONS}
    assert "compare_mini_sectors" in names


def test_execute_tool_dispatches_to_registered_feature():
    """When a tool name is in FEATURE_REGISTRY, execute_tool calls feature.execute()
    instead of the legacy if/elif chain. We monkeypatch the feature instance's
    execute method directly to prove the registry path is what fires.
    """
    from features.registry import discover_features
    discover_features()
    import importlib
    import tools
    importlib.reload(tools)
    from features.base import FEATURE_REGISTRY

    feat = FEATURE_REGISTRY["compare_mini_sectors"]
    calls = []

    def spy_execute(**kw):
        calls.append(kw)
        return {"via_feature_execute": True, "args_seen": kw}

    real_execute = feat.execute
    feat.execute = spy_execute
    try:
        result = tools.execute_tool("compare_mini_sectors", {
            "driver_a": "NOR",
            "driver_b": "PIA",
            "lap_number": 21,
            "round_number": 7,
            "session_type": "Q",
            "n": 25,
        })
    finally:
        feat.execute = real_execute

    assert len(calls) == 1, "feature.execute should have been called exactly once"
    assert result == {
        "via_feature_execute": True,
        "args_seen": {
            "driver_a": "NOR",
            "driver_b": "PIA",
            "lap_number": 21,
            "round_number": 7,
            "session_type": "Q",
            "n": 25,
        },
    }
