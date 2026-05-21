"""Phase C3: execute_tool's registry path writes audit records."""
import pytest

pytestmark = pytest.mark.usefixtures("reset_feature_registry")


def test_execute_tool_writes_audit_record_for_registered_feature():
    from features.registry import discover_features
    from features.base import clear_audit_log, get_audit_log
    discover_features()
    import importlib
    import tools
    importlib.reload(tools)
    import f1_data

    real = f1_data.compare_mini_sectors
    f1_data.compare_mini_sectors = lambda **kw: {"ok": True}
    clear_audit_log()
    try:
        tools.execute_tool("compare_mini_sectors", {
            "driver_a": "NOR", "driver_b": "PIA",
            "lap_number": 21, "round_number": 7,
        })
    finally:
        f1_data.compare_mini_sectors = real

    records = [r for r in get_audit_log() if r["feature_name"] == "compare_mini_sectors"]
    assert len(records) == 1
    r = records[0]
    assert r["executed"] is True
    assert r["error"] is False
    assert r["source"] == "execute_tool"
    assert "ts" in r
    assert isinstance(r["duration_ms"], int)


def test_execute_tool_writes_error_audit_when_feature_raises():
    from features.registry import discover_features
    from features.base import clear_audit_log, get_audit_log
    discover_features()
    import importlib
    import tools
    importlib.reload(tools)
    import f1_data

    real = f1_data.compare_mini_sectors

    def boom(**kw):
        raise RuntimeError("kaboom")

    f1_data.compare_mini_sectors = boom
    clear_audit_log()
    try:
        with pytest.raises(RuntimeError):
            tools.execute_tool("compare_mini_sectors", {
                "driver_a": "NOR", "driver_b": "PIA",
                "lap_number": 21, "round_number": 7,
            })
    finally:
        f1_data.compare_mini_sectors = real

    records = [r for r in get_audit_log() if r["feature_name"] == "compare_mini_sectors"]
    assert len(records) == 1
    assert records[0]["error"] is True
    assert records[0]["executed"] is True


def test_execute_tool_does_not_write_audit_for_legacy_branch():
    """Non-registry path (legacy if/elif) must NOT pollute the audit log."""
    from features.base import clear_audit_log, get_audit_log
    import tools

    clear_audit_log()
    # Pick a legacy-only branch we won't trigger expensively: bogus name → ValueError
    with pytest.raises(Exception):
        tools.execute_tool("__bogus_tool_name__", {})
    assert get_audit_log() == []
