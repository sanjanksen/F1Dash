"""High-level editorial ingestion: URL/PDF -> article + chunks + subjects."""
from __future__ import annotations

import logging
from typing import Any

from editorial import EditorialUnavailable
from editorial import client as _client
from editorial.chunker import chunk_text
from editorial.embed import embed_texts
from editorial.extract import extract_fia_pdf, extract_url
from editorial.subjects import tag_subjects

logger = logging.getLogger(__name__)


def _persist_article_with_chunks(
    article_record: dict[str, Any],
    body: str,
    doc_type: str,
) -> dict[str, Any]:
    """Shared persist path used by URL and PDF ingestion. Returns summary dict."""
    url = article_record["url"]

    chunks = chunk_text(body)
    if not chunks:
        return {"action": "failed", "reason": "empty_chunks", "url": url}

    try:
        vectors = embed_texts(chunks)
    except Exception as e:
        logger.warning("embed_texts threw for %s: %s", url, type(e).__name__)
        vectors = None

    article_row = {
        "url": url,
        "title": article_record.get("title"),
        "source": article_record.get("source") or "unknown",
        "author": article_record.get("author"),
        "published_at": article_record.get("published_at"),
        "doc_type": doc_type,
        "raw_body": body,
    }

    try:
        inserted = _client.upsert_article(article_row)
    except EditorialUnavailable:
        raise
    except Exception as e:
        logger.warning("upsert_article failed for %s: %s", url, type(e).__name__)
        return {"action": "failed", "reason": "upsert_failed", "url": url}

    if not inserted or "id" not in inserted:
        return {"action": "failed", "reason": "no_article_id", "url": url}

    article_id = inserted["id"]

    chunk_rows: list[dict[str, Any]] = []
    for idx, text in enumerate(chunks):
        row: dict[str, Any] = {
            "article_id": article_id,
            "chunk_index": idx,
            "chunk_text": text,
        }
        if vectors is not None and idx < len(vectors):
            row["embedding"] = vectors[idx]
            row["embedding_model"] = "text-embedding-3-small"
        chunk_rows.append(row)

    try:
        chunks_inserted = _client.insert_chunks(chunk_rows)
    except Exception as e:
        logger.warning("insert_chunks failed for %s: %s", url, type(e).__name__)
        chunks_inserted = 0

    try:
        subjects = tag_subjects(article_id, body, article_record.get("title") or "")
        subjects_inserted = _client.insert_subjects(subjects) if subjects else 0
    except Exception as e:
        logger.warning("insert_subjects failed for %s: %s", url, type(e).__name__)
        subjects_inserted = 0

    return {
        "action": "inserted",
        "article_id": article_id,
        "url": url,
        "chunks": chunks_inserted,
        "subjects": subjects_inserted,
        "embedded": vectors is not None,
    }


def ingest_url(url: str, doc_type: str = "news") -> dict[str, Any]:
    """Idempotent URL ingestion. Returns {action, url, ...}."""
    if not url:
        return {"action": "failed", "reason": "empty_url", "url": url}

    try:
        existing = _client.find_article_by_url(url)
    except EditorialUnavailable as e:
        logger.warning("Editorial DB unavailable: %s", e)
        return {"action": "failed", "reason": "editorial_db_unavailable", "url": url}
    except Exception as e:
        logger.warning("find_article_by_url crashed for %s: %s", url, type(e).__name__)
        existing = None

    if existing:
        return {"action": "skipped", "reason": "duplicate_url", "url": url,
                "article_id": existing.get("id")}

    try:
        record = extract_url(url)
    except Exception as e:
        logger.warning("extract_url crashed for %s: %s", url, type(e).__name__)
        return {"action": "failed", "reason": "extraction_crashed", "url": url}

    if not record or not record.get("body"):
        return {"action": "failed", "reason": "extraction_failed", "url": url}

    record["url"] = url
    try:
        return _persist_article_with_chunks(record, record["body"], doc_type)
    except EditorialUnavailable:
        return {"action": "failed", "reason": "editorial_db_unavailable", "url": url}


def ingest_fia_pdf(pdf_url: str) -> dict[str, Any]:
    if not pdf_url:
        return {"action": "failed", "reason": "empty_url", "url": pdf_url}

    try:
        existing = _client.find_article_by_url(pdf_url)
    except EditorialUnavailable:
        return {"action": "failed", "reason": "editorial_db_unavailable", "url": pdf_url}
    except Exception as e:
        logger.warning("find_article_by_url crashed for %s: %s", pdf_url, type(e).__name__)
        existing = None

    if existing:
        return {"action": "skipped", "reason": "duplicate_url", "url": pdf_url,
                "article_id": existing.get("id")}

    try:
        record = extract_fia_pdf(pdf_url)
    except Exception as e:
        logger.warning("extract_fia_pdf crashed for %s: %s", pdf_url, type(e).__name__)
        return {"action": "failed", "reason": "extraction_crashed", "url": pdf_url}

    if not record or not record.get("body"):
        return {"action": "failed", "reason": "empty_pdf", "url": pdf_url}

    record["url"] = pdf_url
    doc_type = record.get("doc_type", "fia_scrutineering")
    try:
        return _persist_article_with_chunks(record, record["body"], doc_type)
    except EditorialUnavailable:
        return {"action": "failed", "reason": "editorial_db_unavailable", "url": pdf_url}
