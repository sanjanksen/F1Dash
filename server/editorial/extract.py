"""URL + FIA PDF extraction.

extract_url: trafilatura HTML -> {title, source, author, published_at, body}
extract_fia_pdf: pdfplumber -> {title, source, published_at, body, doc_type}
"""
from __future__ import annotations

import io
import logging
import os
import re
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


SOURCE_FROM_HOST: dict[str, str] = {
    "the-race.com": "The Race",
    "www.the-race.com": "The Race",
    "motorsport.com": "Motorsport.com",
    "www.motorsport.com": "Motorsport.com",
    "autosport.com": "Autosport",
    "www.autosport.com": "Autosport",
    "racingnews365.com": "RacingNews365",
    "www.racingnews365.com": "RacingNews365",
    "planetf1.com": "PlanetF1",
    "www.planetf1.com": "PlanetF1",
    "racefans.net": "RaceFans",
    "www.racefans.net": "RaceFans",
    "skysports.com": "Sky Sports F1",
    "www.skysports.com": "Sky Sports F1",
    "bbc.co.uk": "BBC Sport",
    "feeds.bbci.co.uk": "BBC Sport",
    "www.bbc.co.uk": "BBC Sport",
    "bbc.com": "BBC Sport",
    "fia.com": "FIA",
    "www.fia.com": "FIA",
    "formula1.com": "Formula1.com",
    "www.formula1.com": "Formula1.com",
}


def _source_from_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return SOURCE_FROM_HOST.get(host, host or "unknown")


def extract_url(url: str) -> dict | None:
    """Fetch a URL and return article metadata + cleaned plaintext body, or None."""
    try:
        import trafilatura
    except ImportError:
        logger.warning("trafilatura not installed.")
        return None

    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            logger.warning("trafilatura.fetch_url returned empty for %s", url)
            return None

        body = trafilatura.extract(
            downloaded,
            output_format="txt",
            include_comments=False,
            include_tables=False,
        )
        if not body or not body.strip():
            logger.warning("trafilatura.extract empty body for %s", url)
            return None

        title = None
        author = None
        published_at = None
        try:
            meta = trafilatura.extract_metadata(downloaded)
            if meta is not None:
                title = getattr(meta, "title", None)
                author = getattr(meta, "author", None)
                published_at = getattr(meta, "date", None)
        except Exception as e:
            logger.warning("metadata extract failed for %s: %s", url, type(e).__name__)

        return {
            "title": title,
            "source": _source_from_url(url),
            "author": author,
            "published_at": published_at,
            "body": body.strip(),
        }
    except Exception as e:
        logger.warning("extract_url crashed for %s: %s", url, type(e).__name__)
        return None


_FIA_FILENAME_DATE = re.compile(r"(20\d{2})[._-]?(\d{2})[._-]?(\d{2})")


def _guess_pdf_date(path_or_url: str) -> str | None:
    m = _FIA_FILENAME_DATE.search(path_or_url)
    if not m:
        return None
    y, mo, d = m.groups()
    try:
        return f"{y}-{mo}-{d}"
    except Exception:
        return None


def _pdf_title_from_filename(path_or_url: str) -> str:
    name = os.path.basename(urlparse(path_or_url).path or path_or_url)
    name = re.sub(r"\.pdf$", "", name, flags=re.IGNORECASE)
    return name.replace("_", " ").replace("-", " ").strip() or "FIA Document"


def extract_fia_pdf(pdf_path_or_url: str) -> dict | None:
    try:
        import pdfplumber
    except ImportError:
        logger.warning("pdfplumber not installed.")
        return None

    pdf_bytes: bytes | None = None
    if pdf_path_or_url.startswith("http://") or pdf_path_or_url.startswith("https://"):
        try:
            import requests
            resp = requests.get(pdf_path_or_url, timeout=30)
            if resp.status_code >= 400:
                logger.warning("FIA PDF fetch %s returned %s", pdf_path_or_url, resp.status_code)
                return None
            pdf_bytes = resp.content
        except Exception as e:
            logger.warning("FIA PDF fetch crashed for %s: %s", pdf_path_or_url, type(e).__name__)
            return None
    else:
        try:
            with open(pdf_path_or_url, "rb") as f:
                pdf_bytes = f.read()
        except Exception as e:
            logger.warning("FIA PDF read crashed for %s: %s", pdf_path_or_url, type(e).__name__)
            return None

    if not pdf_bytes:
        return None

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages_text = [p.extract_text() or "" for p in pdf.pages]
        body = "\n\n".join(t.strip() for t in pages_text if t.strip())
    except Exception as e:
        logger.warning("pdfplumber failed for %s: %s", pdf_path_or_url, type(e).__name__)
        return None

    if not body.strip():
        return None

    return {
        "title": _pdf_title_from_filename(pdf_path_or_url),
        "source": "FIA",
        "author": None,
        "published_at": _guess_pdf_date(pdf_path_or_url),
        "body": body.strip(),
        "doc_type": "fia_scrutineering",
    }
