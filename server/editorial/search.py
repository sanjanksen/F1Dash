"""search_editorial_content — semantic-first chunk retrieval with FTS fallback."""
from __future__ import annotations

import logging
import os
from typing import Any

from editorial import EditorialUnavailable
from editorial import client as _client
from editorial.embed import embed_texts

logger = logging.getLogger(__name__)


def _fts_snippet(body: str, limit: int = 600) -> str:
    if not body:
        return ""
    body = body.strip()
    if len(body) <= limit:
        return body
    return body[:limit].rstrip() + "…"


def search_editorial_content(
    query: str,
    limit: int = 5,
    min_date: str | None = None,
) -> dict[str, Any]:
    if not query or not query.strip():
        return {"available": True, "search_mode": "unavailable",
                "results": [], "reason": "empty_query"}

    # Probe env so we surface unavailability cleanly instead of crashing later.
    if not os.getenv("SUPABASE_URL") or not (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    ):
        return {"available": False, "reason": "editorial_db_unavailable", "results": []}

    try:
        vectors = embed_texts([query])
    except Exception as e:
        logger.warning("embed_texts for query crashed: %s", type(e).__name__)
        vectors = None

    # Semantic path
    if vectors:
        try:
            rows = _client.call_match_chunks(
                query_embedding=vectors[0],
                query_text=query,
                match_count=limit,
                min_published=min_date,
            )
        except EditorialUnavailable:
            return {"available": False, "reason": "editorial_db_unavailable", "results": []}
        except Exception as e:
            logger.warning("call_match_chunks crashed: %s", type(e).__name__)
            return {"available": False, "reason": "rpc_failed", "results": []}

        results = [
            {
                "chunk_text": r.get("chunk_text", ""),
                "url": r.get("url"),
                "title": r.get("title"),
                "source": r.get("source"),
                "published_at": r.get("published_at"),
                "similarity": r.get("similarity"),
            }
            for r in rows or []
        ]
        return {"available": True, "search_mode": "semantic", "results": results}

    # FTS fallback
    try:
        rows = _client.fts_search_articles(query, limit=limit, min_date=min_date)
    except EditorialUnavailable:
        return {"available": False, "reason": "editorial_db_unavailable", "results": []}
    except Exception as e:
        logger.warning("fts_search_articles crashed: %s", type(e).__name__)
        return {"available": False, "reason": "fts_failed", "results": []}

    results = [
        {
            "chunk_text": _fts_snippet(r.get("raw_body", "")),
            "url": r.get("url"),
            "title": r.get("title"),
            "source": r.get("source"),
            "published_at": r.get("published_at"),
            "similarity": None,
        }
        for r in rows or []
    ]
    return {"available": True, "search_mode": "fts", "results": results}
