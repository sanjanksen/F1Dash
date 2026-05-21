"""Poll the FIA F1 documents season index for new weekend PDFs.

The FIA season landing page only renders the PDFs for the *first* event in HTML;
to get the full season we walk the event selector and crawl each per-event page.

Matches a broad set of useful doc types — scrutineering, Pirelli previews,
stewards decisions, PU info, post-race checks, competition visa, race director
event notes — not just scrutineering. doc_type classification lives in
editorial.extract.classify_fia_doc.
"""
from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urljoin

from editorial.extract import classify_fia_doc
from editorial.ingest import ingest_fia_pdf

logger = logging.getLogger(__name__)


DEFAULT_FIA_SEASON_URLS: list[str] = [
    "https://www.fia.com/documents/championships/"
    "fia-formula-one-world-championship-14/season/season-2024-2043",
    "https://www.fia.com/documents/championships/"
    "fia-formula-one-world-championship-14/season/season-2025-2071",
    "https://www.fia.com/documents/championships/"
    "fia-formula-one-world-championship-14/season/season-2026-2072",
]

# Back-compat alias — old code imported the singular constant.
DEFAULT_FIA_SEASON_URL = DEFAULT_FIA_SEASON_URLS[-1]


_USEFUL_DOC_KEYWORDS: tuple[str, ...] = (
    "scrutineering",
    "pirelli_preview", "pirelli-preview", "pirelli preview", "pirelli",
    "competition_visa", "competition-visa", "competition visa",
    "power_unit_information", "power-unit-information", "power unit information",
    "new_pu_elements", "new-pu-elements", "new pu elements",
    "pu_elements", "pu-elements", "pu elements",
    "post_race_checks", "post-race-checks", "post_race_check", "post-race_check",
    "post-race_checks", "post race check",
    "stewards", "decision", "penalty",
    # Race director event notes — added for 2024-2025 backfill coverage.
    "event_notes", "event-notes", "event notes",
    "sporting_information", "sporting-information", "sporting information",
)


_PDF_HREF_RE = re.compile(
    r"""href=["']([^"']+\.pdf)["']""",
    re.IGNORECASE,
)


# The season landing page's event <select> options are absolute paths like
#   /documents/championships/.../season/season-2024-2043/event/Bahrain%20Grand%20Prix
_EVENT_HREF_RE = re.compile(
    r"""(/documents/championships/[^"'\s>]+?/season/season-\d{4}-\d+/event/[^"'\s>]+)""",
    re.IGNORECASE,
)


def _is_useful_pdf(href: str) -> bool:
    if not href:
        return False
    href_l = href.lower()
    if not href_l.endswith(".pdf"):
        return False
    # Match keywords against the filename (basename), not the directory path —
    # FIA stores everything under .../decision-document/... and that path
    # substring would otherwise let unrelated PDFs match the "decision" keyword.
    basename = href_l.rsplit("/", 1)[-1]
    return any(kw in basename for kw in _USEFUL_DOC_KEYWORDS)


def _extract_pdf_links(html: str, base_url: str) -> list[str]:
    if not html:
        return []
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        hrefs = [a.get("href") for a in soup.find_all("a") if a.get("href")]
    except Exception:
        hrefs = _PDF_HREF_RE.findall(html)

    urls: list[str] = []
    for h in hrefs:
        if _is_useful_pdf(h):
            urls.append(urljoin(base_url, h))
    seen: set[str] = set()
    deduped: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            deduped.append(u)
    return deduped


def _extract_event_urls(html: str, base_url: str) -> list[str]:
    """Pull every per-event documents URL from a season landing page.

    The FIA renders an event <select> whose option values are the per-event
    URLs. We match the path pattern directly so we don't depend on parsing
    the select element.
    """
    if not html:
        return []
    matches = _EVENT_HREF_RE.findall(html)
    seen: set[str] = set()
    out: list[str] = []
    for path in matches:
        url = urljoin(base_url, path)
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


def _fetch_html(url: str) -> str | None:
    try:
        import requests
    except ImportError:
        logger.warning("requests not installed — FIA poll skipped.")
        return None
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    except Exception as e:
        logger.warning("FIA page fetch crashed for %s: %s", url, type(e).__name__)
        return None
    if resp.status_code >= 400:
        logger.warning("FIA page %s returned %s", url, resp.status_code)
        return None
    return resp.text


def _poll_one_page(page_url: str) -> dict[str, Any]:
    """Crawl one URL — season landing or per-event — and ingest every useful PDF.

    Returns the same shape as poll_fia_documents but for a single page.
    """
    html = _fetch_html(page_url)
    if html is None:
        return {"new_articles": 0, "skipped": 0, "errors": 1, "details": []}

    # If this is a season landing page, recurse into each event page; the
    # season page itself only renders the latest event's PDFs.
    event_urls = _extract_event_urls(html, page_url)

    pdf_urls: list[str] = list(_extract_pdf_links(html, page_url))
    seen_pdfs: set[str] = set(pdf_urls)

    for ev in event_urls:
        ev_html = _fetch_html(ev)
        if ev_html is None:
            continue
        for u in _extract_pdf_links(ev_html, ev):
            if u in seen_pdfs:
                continue
            seen_pdfs.add(u)
            pdf_urls.append(u)

    new_articles = 0
    skipped = 0
    errors = 0
    details: list[dict] = []

    for url in pdf_urls:
        try:
            result = ingest_fia_pdf(url)
        except Exception as e:
            logger.warning("ingest_fia_pdf crashed for %s: %s", url, type(e).__name__)
            errors += 1
            continue
        result.setdefault("doc_type", classify_fia_doc(url))
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


def poll_fia_documents(
    season_urls: list[str] | str | None = None,
) -> dict[str, Any]:
    """Poll one or more FIA season pages, recursing into every event.

    Accepts a list of URLs, a single URL string (back-compat), or None
    (uses ``DEFAULT_FIA_SEASON_URLS`` — currently 2024 + 2025 + 2026).
    """
    if season_urls is None:
        urls = list(DEFAULT_FIA_SEASON_URLS)
    elif isinstance(season_urls, str):
        urls = [season_urls]
    else:
        urls = list(season_urls)

    total_new = 0
    total_skipped = 0
    total_errors = 0
    all_details: list[dict] = []

    for u in urls:
        page = _poll_one_page(u)
        total_new += page["new_articles"]
        total_skipped += page["skipped"]
        total_errors += page["errors"]
        all_details.extend(page["details"])

    return {
        "feeds_polled": len(urls),
        "new_articles": total_new,
        "skipped": total_skipped,
        "errors": total_errors,
        "details": all_details,
    }
