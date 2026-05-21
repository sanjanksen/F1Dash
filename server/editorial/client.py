"""PostgREST client + low-level table operations for editorial RAG.

Uses the `postgrest` package directly instead of the umbrella `supabase` package
because the latter pulls `pyiceberg` (Cython-built, doesn't compile cleanly on
Windows + Python 3.14). We only need PostgREST for table queries and RPC — the
storage / realtime / functions layers of supabase-py aren't used here.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from editorial import EditorialUnavailable

logger = logging.getLogger(__name__)

_client = None


def _get_supabase_client():
    """Return a cached PostgREST client. Raises EditorialUnavailable if env vars missing."""
    global _client
    if _client is not None:
        return _client

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    if not url or not key:
        raise EditorialUnavailable("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set")

    try:
        from postgrest import SyncPostgrestClient
    except ImportError as e:
        raise EditorialUnavailable(f"postgrest not installed: {e}") from e

    # Supabase exposes PostgREST at /rest/v1; auth via apikey + Bearer headers.
    base_url = url.rstrip("/") + "/rest/v1"
    _client = SyncPostgrestClient(
        base_url,
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
        },
    )
    return _client


def reset_client_for_tests() -> None:
    global _client
    _client = None


def find_article_by_url(url: str) -> dict | None:
    client = _get_supabase_client()
    try:
        res = client.from_("articles").select("id, url").eq("url", url).limit(1).execute()
    except Exception as e:
        logger.warning("find_article_by_url failed: %s", type(e).__name__)
        return None
    rows = getattr(res, "data", None) or []
    return rows[0] if rows else None


def upsert_article(article: dict[str, Any]) -> dict | None:
    """Insert an article row, returning the inserted row (with id). Idempotent on url."""
    client = _get_supabase_client()
    try:
        res = (
            client.from_("articles")
            .upsert(article, on_conflict="url", returning="representation")
            .execute()
        )
    except Exception as e:
        logger.warning("upsert_article failed for url=%s: %s", article.get("url"), type(e).__name__)
        return None
    rows = getattr(res, "data", None) or []
    return rows[0] if rows else None


def insert_chunks(chunks: list[dict[str, Any]]) -> int:
    if not chunks:
        return 0
    client = _get_supabase_client()
    try:
        res = client.from_("article_chunks").insert(chunks, returning="representation").execute()
    except Exception as e:
        logger.warning("insert_chunks failed: %s", type(e).__name__)
        return 0
    rows = getattr(res, "data", None) or []
    return len(rows)


def insert_subjects(subjects: list[dict[str, Any]]) -> int:
    if not subjects:
        return 0
    client = _get_supabase_client()
    try:
        res = (
            client.from_("article_subjects")
            .upsert(subjects, on_conflict="article_id,kind,ref", returning="representation")
            .execute()
        )
    except Exception as e:
        logger.warning("insert_subjects failed: %s", type(e).__name__)
        return 0
    rows = getattr(res, "data", None) or []
    return len(rows)


def call_match_chunks(
    query_embedding: list[float],
    query_text: str | None = None,
    match_count: int = 5,
    min_published: str | None = None,
) -> list[dict]:
    client = _get_supabase_client()
    payload = {
        "query_embedding": query_embedding,
        "query_text": query_text,
        "match_count": match_count,
        "min_published": min_published,
    }
    try:
        res = client.rpc("match_article_chunks", payload).execute()
    except Exception as e:
        logger.warning("match_article_chunks RPC failed: %s", type(e).__name__)
        return []
    return getattr(res, "data", None) or []


def fts_search_articles(query: str, limit: int = 5, min_date: str | None = None) -> list[dict]:
    """Fallback when no embeddings: rank articles by Postgres FTS on body_tsv."""
    client = _get_supabase_client()
    try:
        q = (
            client.from_("articles")
            .select("id, url, title, source, published_at, raw_body")
            .text_search("body_tsv", query, options={"type": "websearch"})
            .limit(limit)
        )
        if min_date:
            q = q.gte("published_at", min_date)
        res = q.execute()
    except Exception as e:
        logger.warning("fts_search_articles failed: %s", type(e).__name__)
        return []
    return getattr(res, "data", None) or []
