"""RSS feed poller — fetch feeds, ingest unseen URLs.

Default feed list verified live 2026-05-21. Three notes:

- BBC F1 (`feeds.bbci.co.uk/sport/formula1/rss.xml`) is intentionally
  excluded — BBC robots.txt explicitly forbids AI training, RAG,
  summarisation, and agentic AI use of their content.
- RaceFans (`racefans.net/feed/`) is intentionally excluded — their
  Cloudflare AI content-signals are set to `ai-train=no` plus an
  explicit `GPTBot: Disallow /`. The RSS body is title-only anyway.
- Some feeds carry mixed-discipline content (Crash.net covers F1,
  MotoGP, BSB, etc.). Per-feed URL filters live in `_FEED_URL_FILTERS`
  so only F1-relevant entries get ingested.
"""
from __future__ import annotations

import logging
from typing import Any

from editorial.ingest import ingest_url

logger = logging.getLogger(__name__)


DEFAULT_FEEDS: list[str] = [
    # Major news outlets (verified 2026-05-21)
    "https://www.formula1.com/en/latest/all.xml",
    "https://www.motorsport.com/rss/f1/news/",
    "https://www.autosport.com/rss/f1/news/",
    "https://racingnews365.com/feed/news.xml",
    "https://www.planetf1.com/ps-rss",
    "https://www.skysports.com/rss/12433",
    "https://www.crash.net/rss",
    # Technical / long-form
    "https://www.the-race.com/category/formula-1/rss/",
    "https://www.total-motorsport.com/feed/",
    "https://www.f1technical.net/rss/news.xml",
    # Official
    "https://www.fia.com/rss/news",
]


# Per-feed URL substring filters for mixed-discipline feeds.
# Only ingest entries whose URL contains the substring.
_FEED_URL_FILTERS: dict[str, str] = {
    "https://www.crash.net/rss": "/f1/",
}

# FIA RSS covers all motorsport disciplines; only F1 news pages match this pattern.
_FEED_URL_FILTERS["https://www.fia.com/rss/news"] = "/news/f1-"


def _entry_passes_filter(feed_url: str, entry_url: str) -> bool:
    needle = _FEED_URL_FILTERS.get(feed_url)
    if needle is None:
        return True
    return needle in entry_url


def poll_rss_feeds(feed_urls: list[str] | None = None) -> dict[str, Any]:
    feed_urls = feed_urls or DEFAULT_FEEDS
    try:
        import feedparser
    except ImportError:
        logger.warning("feedparser not installed — RSS poll skipped.")
        return {"feeds_polled": 0, "new_articles": 0, "skipped": 0,
                "errors": len(feed_urls), "details": []}

    feeds_polled = 0
    new_articles = 0
    skipped = 0
    errors = 0
    details: list[dict] = []

    for feed_url in feed_urls:
        try:
            parsed = feedparser.parse(feed_url)
        except Exception as e:
            logger.warning("feedparser.parse crashed for %s: %s", feed_url, type(e).__name__)
            errors += 1
            continue

        feeds_polled += 1
        entries = getattr(parsed, "entries", []) or []
        for entry in entries:
            url = entry.get("link") if isinstance(entry, dict) else getattr(entry, "link", None)
            if not url:
                continue
            if not _entry_passes_filter(feed_url, url):
                continue
            try:
                result = ingest_url(url, doc_type="news")
            except Exception as e:
                logger.warning("ingest_url crashed for %s: %s", url, type(e).__name__)
                errors += 1
                continue
            action = result.get("action")
            if action == "inserted":
                new_articles += 1
            elif action == "skipped":
                skipped += 1
            else:
                errors += 1
            details.append(result)

    return {
        "feeds_polled": feeds_polled,
        "new_articles": new_articles,
        "skipped": skipped,
        "errors": errors,
        "details": details,
    }
