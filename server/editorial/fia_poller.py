"""Poll the FIA F1 documents season index for new scrutineering PDFs."""
from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urljoin

from editorial.ingest import ingest_fia_pdf

logger = logging.getLogger(__name__)


DEFAULT_FIA_SEASON_URL = (
    "https://www.fia.com/documents/championships/"
    "fia-formula-one-world-championship-14/season/season-2026-2072"
)


_SCRUTINEERING_HREF_RE = re.compile(
    r"""href=["']([^"']*?scrutineering[^"']*?\.pdf)["']""",
    re.IGNORECASE,
)


def _extract_pdf_links(html: str, base_url: str) -> list[str]:
    if not html:
        return []
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        hrefs = [a.get("href") for a in soup.find_all("a") if a.get("href")]
    except Exception:
        hrefs = _SCRUTINEERING_HREF_RE.findall(html)

    urls: list[str] = []
    for h in hrefs:
        if not h:
            continue
        if "scrutineering" in h.lower() and h.lower().endswith(".pdf"):
            urls.append(urljoin(base_url, h))
    seen: set[str] = set()
    deduped: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            deduped.append(u)
    return deduped


def poll_fia_documents(season_url: str | None = None) -> dict[str, Any]:
    season_url = season_url or DEFAULT_FIA_SEASON_URL

    try:
        import requests
    except ImportError:
        logger.warning("requests not installed — FIA poll skipped.")
        return {"feeds_polled": 0, "new_articles": 0, "skipped": 0,
                "errors": 1, "details": []}

    try:
        resp = requests.get(season_url, timeout=30)
        if resp.status_code >= 400:
            logger.warning("FIA season page %s returned %s", season_url, resp.status_code)
            return {"feeds_polled": 1, "new_articles": 0, "skipped": 0,
                    "errors": 1, "details": []}
        html = resp.text
    except Exception as e:
        logger.warning("FIA season page fetch failed: %s", type(e).__name__)
        return {"feeds_polled": 1, "new_articles": 0, "skipped": 0,
                "errors": 1, "details": []}

    pdf_urls = _extract_pdf_links(html, season_url)
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
        action = result.get("action")
        if action == "inserted":
            new_articles += 1
        elif action == "skipped":
            skipped += 1
        else:
            errors += 1
        details.append(result)

    return {
        "feeds_polled": 1,
        "new_articles": new_articles,
        "skipped": skipped,
        "errors": errors,
        "details": details,
    }
