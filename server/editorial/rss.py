"""RSS feed poller — fetch feeds, ingest unseen URLs."""
from __future__ import annotations

import logging
from typing import Any

from editorial.ingest import ingest_url

logger = logging.getLogger(__name__)


DEFAULT_FEEDS: list[str] = [
    "https://www.formula1.com/en/latest/all.xml",
    "https://www.motorsport.com/rss/f1/news/",
    "https://www.autosport.com/rss/f1/news/",
    "https://racingnews365.com/feed/news.xml",
    "https://www.planetf1.com/feed",
    "https://www.racefans.net/feed/",
    "https://www.skysports.com/rss/12040",
    "https://feeds.bbci.co.uk/sport/formula1/rss.xml",
    "https://www.fia.com/media-center/rss-feed",
]


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
