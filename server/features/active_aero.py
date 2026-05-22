"""Active-aero deep analysis feature. Migrated from chat.py / tools.py / f1_data.py."""
from __future__ import annotations

import f1_data
from features.base import Feature, register_feature


_RELEVANT_KEYWORDS = (
    "active aero", "x-mode", "z-mode", "x mode", "z mode",
    "aero mode", "wing mode", "drs flap", "low drag", "low-drag",
)

_RELEVANT_MODES: frozenset[str] = frozenset()

_REQUIRED_ARGS = ("driver_code", "round_number", "session_type", "lap_number")


@register_feature
class ActiveAeroFeature(Feature):
    name = "analyze_active_aero_usage"
    applies_to = ("driver", "lap")
    description = (
        "DEEP ANALYSIS PRIMITIVE. Detect 2026 active-aero Z-mode (low-drag) usage on a specific lap. "
        "Returns segments where Z-mode was active inside FIA-permitted aero zones, total Z-mode "
        "seconds, and an estimated speed gain vs full-X-mode. May return inferred=True when FastF1 "
        "doesn't expose the active-aero channel directly — in that case the result is derived from "
        "per-circuit aero-zone definitions and speed-trace heuristics, and the chat layer should "
        "hedge accordingly. Use for specific-lap questions like 'where did Norris run Z-mode on lap 12?'."
    )
    required_args = _REQUIRED_ARGS
    tool_schema = {
        "type": "object",
        "properties": {
            "driver_code": {"type": "string"},
            "round_number": {"type": "integer"},
            "session_type": {"type": "string"},
            "lap_number": {"type": "integer"},
        },
        "required": list(_REQUIRED_ARGS),
    }

    def is_relevant_for(self, question: str, resolved: dict | None) -> float:
        q = (question or "").lower()
        mode = (resolved or {}).get("analysis_mode")
        has_keyword = any(kw in q for kw in _RELEVANT_KEYWORDS)
        has_mode = mode in _RELEVANT_MODES
        if has_keyword and has_mode:
            return 0.85
        if has_keyword:
            return 0.65
        if has_mode:
            return 0.45
        return 0.0

    def execute(self, **args) -> dict:
        return f1_data.analyze_active_aero_usage(
            args["driver_code"],
            args["round_number"],
            args["session_type"],
            args["lap_number"],
        )

    def make_widget(self, result: dict) -> dict:
        import chat
        return chat._make_active_aero_widget(result)

    def should_show_widget(self, result: dict) -> bool:
        # Legacy branch always appended the widget unconditionally.
        if not result.get("available", True):
            return False
        return True
