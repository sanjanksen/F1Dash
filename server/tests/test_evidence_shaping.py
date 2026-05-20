from evidence_shaping import (
    CORNERING_TOOL_NAMES,
    is_cornering_evidence,
    reject_data_table_for_cornering,
    strip_heavy_payload_fields,
)


def test_strip_heavy_payload_fields_drops_per_corner_for_cornering_tools():
    for tool in CORNERING_TOOL_NAMES:
        result = {"summary": {"driver_a": "NOR"}, "per_corner": [{"corner": 1}]}
        shaped = strip_heavy_payload_fields(tool, result)
        assert "per_corner" not in shaped
        assert shaped["summary"] == {"driver_a": "NOR"}


def test_strip_heavy_payload_fields_passthrough_for_other_tools():
    result = {"per_corner": [{"corner": 1}], "x": 1}
    shaped = strip_heavy_payload_fields("get_driver_race_story", result)
    assert shaped is result
    assert shaped["per_corner"] == [{"corner": 1}]

    list_result = [{"x": 1}]
    assert strip_heavy_payload_fields("analyze_cornering_loads", list_result) is list_result


def test_is_cornering_evidence_recognises_all_four_tools():
    assert is_cornering_evidence("analyze_cornering_loads")
    assert is_cornering_evidence("analyze_race_cornering_profile")
    assert is_cornering_evidence("compare_corner_profiles")
    assert is_cornering_evidence("extract_corner_profiles")
    assert not is_cornering_evidence("get_driver_race_story")
    assert not is_cornering_evidence(None)


def test_reject_data_table_for_cornering_blocks_cornering_data_table():
    assert reject_data_table_for_cornering("data_table", "analyze_cornering_loads") is True
    assert reject_data_table_for_cornering("data_table", "extract_corner_profiles") is True


def test_reject_data_table_for_cornering_allows_non_cornering_data_table():
    assert reject_data_table_for_cornering("data_table", "get_driver_race_story") is False
    assert reject_data_table_for_cornering("data_table", None) is False
    assert reject_data_table_for_cornering("qualifying_battle", "analyze_cornering_loads") is False
