"""Mini-sectors heatmap feature. Migrated from chat.py / tools.py / f1_data.py.

This is the pilot feature for the registry refactor. The underlying
analysis function stays in f1_data.py; this module wraps it with the
applies_to + is_relevant_for + make_widget + should_show_widget surface
the registry expects.
"""
from __future__ import annotations

import f1_data
from features.base import Feature, register_feature


_RELEVANT_KEYWORDS = (
    "where", "sector", "segment", "faster", "slower", "lose time",
    "gain time", "lost", "gained", "split", "lap-by-lap",
)

# Compatible modes act as an eligibility gate only — they cap the score below
# the fire threshold (0.5) when no keyword intent is present. Mode classifier
# already narrowed scope upstream; this predicate confirms specific intent.
_RELEVANT_MODES = frozenset({"qualifying_battle", "driver_comparison"})

_REQUIRED_ARGS = ("driver_a", "driver_b", "lap_number", "round_number")


@register_feature
class MiniSectorsFeature(Feature):
    name = "compare_mini_sectors"
    applies_to = ("pair_of_drivers", "lap")
    description = (
        "Compare two drivers across 25 equal-distance mini-sectors of a "
        "single lap. Returns per-segment delta + cumulative delta along "
        "distance, segments-won counts, DRS-mix warning."
    )
    required_args = _REQUIRED_ARGS
    tool_schema = {
        "type": "object",
        "properties": {
            "driver_a": {"type": "string"},
            "driver_b": {"type": "string"},
            "lap_number": {"type": "integer"},
            "round_number": {"type": "integer"},
            "session_type": {"type": "string", "default": "Q"},
            "n": {"type": "integer", "default": 25},
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
            return 0.45  # eligibility candidate but no explicit intent — below fire threshold
        return 0.0

    def execute(self, **args) -> dict:
        return f1_data.compare_mini_sectors(
            driver_a=args["driver_a"],
            driver_b=args["driver_b"],
            lap_number=args["lap_number"],
            round_number=args["round_number"],
            session_type=args.get("session_type", "Q"),
            n=args.get("n", 25),
        )

    def make_widget(self, result: dict) -> dict:
        # Delegate to the existing chat.py builder to keep widget shape
        # identical. Once all features are migrated, the builder will move
        # here and the chat.py function will be removed.
        import chat
        return chat._make_mini_sector_heatmap_widget(result)

    def should_show_widget(self, result: dict) -> bool:
        if not result.get("available", True):
            return False
        total = result.get("total_delta_s")
        if total is None:
            return False
        return abs(total) >= 0.05
