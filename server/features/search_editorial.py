"""Editorial content search feature. Migrated from tools.py / editorial.search."""
from __future__ import annotations

import logging

from features.base import Feature, register_feature

logger = logging.getLogger(__name__)


_RELEVANT_KEYWORDS = (
    "news", "article", "recent", "latest", "press conference",
    "interview", "reported", "say about", "said about",
    "fia bulletin", "technical directive", "editorial",
)

_RELEVANT_MODES: frozenset[str] = frozenset()

_REQUIRED_ARGS = ("query",)


def _search_safe(query: str, limit: int = 5, min_date: str | None = None):
    try:
        from editorial.search import search_editorial_content
    except Exception as e:  # pragma: no cover — defensive only
        logger.warning("editorial.search import failed: %s", type(e).__name__)
        return {"available": False, "reason": "editorial_db_unavailable", "results": []}
    return search_editorial_content(query, limit=limit, min_date=min_date)


@register_feature
class SearchEditorialFeature(Feature):
    name = "search_editorial_content"
    applies_to = ()  # always candidate
    description = (
        "PRIMITIVE TOOL. Retrieve relevant excerpts from F1Dash's editorial knowledge base "
        "(articles from The Race, Motorsport.com, FIA technical docs, press-conference "
        "transcripts, etc.) for a question. Use when the user asks about: "
        "context behind a result, what teams said in interviews, technical upgrades "
        "brought to a weekend, FIA technical bulletins, or any 'why' question that "
        "benefits from published reporting. Returns up to 5 article chunks with URL, "
        "source, date, and the chunk text. Always quote sparingly and cite the URL. "
        "If the tool returns available=False, the editorial knowledge base is not "
        "connected — answer from telemetry/results alone."
    )
    required_args = _REQUIRED_ARGS
    tool_schema = {
        "type": "object",
        "properties": {
            "query":    {"type": "string", "description": "Natural-language query for editorial retrieval."},
            "limit":    {"type": "integer", "description": "Max chunks to return. Defaults to 5."},
            "min_date": {"type": "string",  "description": "Optional ISO date (YYYY-MM-DD); only articles published on or after this date are returned."},
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
        return _search_safe(
            args["query"],
            limit=int(args.get("limit", 5)),
            min_date=args.get("min_date"),
        )

    def make_widget(self, result: dict) -> dict:
        return {}

    def should_show_widget(self, result: dict) -> bool:
        return False
