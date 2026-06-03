"""Poll FIA F1 press-conference transcripts and ingest them as text.

The FIA publishes driver/team press-conference transcripts as HTML pages at
deterministic URLs::

    https://www.fia.com/news/f1-{year}-{event-slug}-{session}-press-conference-transcript

The news LISTING page is JS-rendered (no links in static HTML), so it cannot be
crawled. Instead we construct candidate URLs from the season schedule and probe
each one. The FIA serves SOFT 404s — a non-existent transcript returns HTTP 200
with a generic "News" landing page — so status code is not enough: we require the
extracted page title to contain "press conference" before ingesting.

Ingested as doc_type='press_conference' so the editorial RAG can cite pressers
distinctly from generic news.
"""
from __future__ import annotations

import datetime
import logging
import re
from typing import Any, Callable

logger = logging.getLogger(__name__)

CURRENT_YEAR = datetime.date.today().year

# Session variants the FIA publishes per weekend. Non-existent ones (e.g.
# post-sprint on a non-sprint weekend) simply fail the transcript check.
CANDIDATE_SESSIONS: tuple[str, ...] = (
    "thursday",
    "friday",
    "post-qualifying",
    "post-race",
    "post-sprint",
    "post-sprint-qualifying",
)

_NEWS_BASE = "https://www.fia.com/news"


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


def press_conference_urls(year: int, event_name: str) -> list[str]:
    """Candidate transcript URLs for one event, one per session variant."""
    slug = _slugify(event_name)
    if not slug:
        return []
    return [
        f"{_NEWS_BASE}/f1-{year}-{slug}-{session}-press-conference-transcript"
        for session in CANDIDATE_SESSIONS
    ]


def _is_press_conference_page(url: str) -> bool:
    """True only for a real transcript page. The FIA serves soft 404s (HTTP 200
    generic 'News' page) for non-existent transcripts, so we check the extracted
    title contains 'press conference' rather than trusting the status code."""
    try:
        import trafilatura
    except ImportError:
        return False
    try:
        downloaded = trafilatura.fetch_url(url)
        text = trafilatura.extract(downloaded) if downloaded else None
    except Exception as e:
        logger.warning("press-conf probe crashed for %s: %s", url, type(e).__name__)
        return False
    if not text:
        return False
    first_line = text.splitlines()[0].lower() if text.strip() else ""
    return "press conference" in first_line


def _already_ingested(url: str) -> bool:
    """Cheap DB check so already-ingested transcripts are skipped with no fetch."""
    try:
        from editorial import client as _client
        return bool(_client.find_article_by_url(url))
    except Exception:
        return False


def _scheduled_past_events(year: int) -> list[str]:
    """Current-season event names whose weekend has already started — only those
    can have transcripts. Falls back to all events if dates are unavailable."""
    try:
        from f1_data import get_circuits
        circuits = get_circuits()
    except Exception as e:
        logger.warning("press-conf: schedule load failed: %s", type(e).__name__)
        return []
    today = datetime.date.today().isoformat()
    return [
        c["event_name"]
        for c in circuits
        if c.get("event_name") and (c.get("date") or "9999-99-99") <= today
    ]


def _historical_events(year: int) -> list[str]:
    """Full event list for a past season via FastF1 (every event is in the past,
    so no date filter needed). Testing events are excluded."""
    try:
        import fastf1
        sched = fastf1.get_event_schedule(year, include_testing=False)
        return [str(n).strip() for n in sched["EventName"].tolist() if str(n).strip()]
    except Exception as e:
        logger.warning("press-conf: FastF1 schedule for %d failed: %s", year, type(e).__name__)
        return []


def _event_names_for_year(year: int) -> list[str]:
    """Event names to probe for a season. The current year uses the live app
    schedule filtered to events that have started; prior years use FastF1's full
    historical schedule."""
    if year == CURRENT_YEAR:
        return _scheduled_past_events(year)
    return _historical_events(year)


def poll_press_conferences(
    year: int | None = None,
    event_names: list[str] | None = None,
    *,
    already_ingested: Callable[[str], bool] = _already_ingested,
    is_transcript: Callable[[str], bool] = _is_press_conference_page,
    ingest: Callable[..., dict] | None = None,
) -> dict[str, Any]:
    """Probe candidate transcript URLs for each past event and ingest the real
    ones as doc_type='press_conference'. Idempotent — already-ingested URLs are
    skipped without a network fetch."""
    if ingest is None:
        from editorial.ingest import ingest_url
        ingest = ingest_url
    year = year or CURRENT_YEAR
    if event_names is None:
        event_names = _event_names_for_year(year)

    new_articles = skipped = errors = 0
    details: list[dict] = []

    for event_name in event_names:
        for url in press_conference_urls(year, event_name):
            try:
                if already_ingested(url):
                    skipped += 1
                    continue
                if not is_transcript(url):
                    continue
                result = ingest(url, doc_type="press_conference")
            except Exception as e:
                logger.warning("press-conf ingest crashed for %s: %s", url, type(e).__name__)
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
        "new_articles": new_articles,
        "skipped": skipped,
        "errors": errors,
        "details": details,
    }


def backfill_seasons(years: list[int], **kwargs) -> dict[str, Any]:
    """One-off backfill across multiple (typically historical) seasons. Runs the
    poller per year and aggregates counts. NOT used by the cron — the scheduled
    job stays current-year only; this is for a deliberate manual backfill."""
    totals: dict[str, Any] = {"new_articles": 0, "skipped": 0, "errors": 0, "by_year": {}}
    for year in years:
        out = poll_press_conferences(year=year, **kwargs)
        totals["new_articles"] += out["new_articles"]
        totals["skipped"] += out["skipped"]
        totals["errors"] += out["errors"]
        totals["by_year"][year] = {
            k: out[k] for k in ("new_articles", "skipped", "errors")
        }
    return totals
