"""Poll the FIA F1 documents season index for new weekend PDFs.

Matches a broad set of useful doc types — scrutineering, Pirelli previews,
stewards decisions, PU info, post-race checks, competition visa — not just
scrutineering. doc_type classification lives in editorial.extract.classify_fia_doc.
"""
from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urljoin

from editorial.extract import classify_fia_doc
from editorial.ingest import ingest_fia_pdf

logger = logging.getLogger(__name__)


DEFAULT_FIA_SEASON_URL = (
    "https://www.fia.com/documents/championships/"
    "fia-formula-one-world-championship-14/season/season-2026-2072"
)


_USEFUL_DOC_KEYWORDS: tuple[str, ...] = (
    "scrutineering",
    "pirelli_preview", "pirelli-preview", "pirelli",
    "competition_visa", "competition-visa",
    "power_unit_information", "power-unit-information",
    "new_pu_elements", "new-pu-elements",
    "post_race_checks", "post-race-checks", "post_race_check", "post-race_check",
    "post-race_checks",
    "stewards", "decision", "penalty",
)


_PDF_HREF_RE = re.compile(
    r"""href=["']([^"']+\.pdf)["']""",
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


def poll_fia_documents(season_url: str | None = None) -> dict[str, Any]:
    season_url = season_url or DEFAULT_FIA_SEASON_URL

    try:
        import requests
    except ImportError:
        logger.warning("requests not installed — FIA poll skipped.")
        return {"feeds_polled": 0, "new_articles": 0, "skipped": 0,
                "errors": 1, "details": []}

    try:
        resp = requests.get(season_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
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
        # Annotate the result with the classified doc_type for observability.
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
        "feeds_polled": 1,
        "new_articles": new_articles,
        "skipped": skipped,
        "errors": errors,
        "details": details,
    }
