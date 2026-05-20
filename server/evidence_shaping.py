"""Shared evidence shaping for deterministic + agentic analysis paths.

Both paths must apply identical post-tool transformations so behavior does not
diverge. The system prompt's 'no data_table for cornering' rule is enforced
here, not by the LLM.
"""

CORNERING_TOOL_NAMES = frozenset({
    "analyze_cornering_loads",
    "analyze_race_cornering_profile",
    "compare_corner_profiles",
    "extract_corner_profiles",
})


def strip_heavy_payload_fields(tool_name: str, result):
    """Drop per_corner from cornering payloads. Apply uniformly to both paths."""
    if tool_name in CORNERING_TOOL_NAMES and isinstance(result, dict):
        return {k: v for k, v in result.items() if k != "per_corner"}
    return result


def is_cornering_evidence(tool_name: str) -> bool:
    return tool_name in CORNERING_TOOL_NAMES


def reject_data_table_for_cornering(widget_type: str, source_tool: str | None) -> bool:
    """Returns True if this widget should be suppressed. Use at widget-builder boundary."""
    return widget_type == "data_table" and source_tool in CORNERING_TOOL_NAMES
