"""Gemini gemini-embedding-2 caller. Returns None when GEMINI_API_KEY is absent.

gemini-embedding-2 (GA April 2026) auto-normalizes truncated dimensions, so no
manual L2 normalization is required for 1536-dim output. Unlike v1, task_type
is not a parameter — the recommended way to hint task is a short prompt prefix
on the input text itself.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

_MODEL = "gemini-embedding-2"
_DEFAULT_DIM = 1536  # matches the Supabase vector(1536) column
_BATCH_SIZE = 100
_MAX_RETRIES = 4  # per chunk; transient 429s clear after a short backoff
_TRANSIENT_MARKERS = (
    "429", "resource_exhausted", "rate", "503", "unavailable", "deadline", "timeout",
)


def _is_transient(exc: Exception) -> bool:
    """Gemini returns 429 RESOURCE_EXHAUSTED under burst load — retryable."""
    s = str(exc).lower()
    return any(m in s for m in _TRANSIENT_MARKERS)


def embed_texts(
    texts: list[str],
    *,
    task: str = "document",
    output_dim: int = _DEFAULT_DIM,
) -> Optional[list[list[float]]]:
    """Embed texts via gemini-embedding-2.

    Returns None when GEMINI_API_KEY is absent, the SDK is missing, or the call
    fails — callers must handle gracefully (skip embedding, fall back to FTS,
    etc.).

    task: "document" for corpus inserts, "query" for search-time embedding.
    Translated to a short prompt prefix because gemini-embedding-2 doesn't
    accept task_type natively (unlike v1).

    output_dim: 768, 1536, or 3072. Defaults to 1536 to match the Supabase
    schema. v2 auto-normalizes truncated dimensions.
    """
    if not texts:
        return []
    if not os.getenv("GEMINI_API_KEY"):
        logger.warning("GEMINI_API_KEY not set — skipping embeddings.")
        return None

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        logger.warning("google-genai package not installed — skipping embeddings.")
        return None

    if task == "query":
        prepared = [f"Search query: {t}" for t in texts]
    else:
        prepared = [f"Document for retrieval: {t}" for t in texts]

    try:
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    except Exception as e:
        logger.warning("Gemini client init failed: %s", type(e).__name__)
        return None

    # Gemini's embed_content treats contents=[...] as ONE content (concatenated),
    # not a batch. Loop one text per call to get one embedding per input.
    #
    # Each call is retried with exponential backoff on transient 429s (burst load
    # hits the rate limit). A chunk that still fails yields None for that slot —
    # we do NOT abort the whole article, so one bad chunk can't wipe every
    # embedding (the persist layer stores null for None slots, FTS still covers).
    vectors: list[Optional[list[float]]] = []
    for text in prepared:
        vec: Optional[list[float]] = None
        for attempt in range(_MAX_RETRIES):
            try:
                resp = client.models.embed_content(
                    model=_MODEL,
                    contents=text,
                    config=types.EmbedContentConfig(output_dimensionality=output_dim),
                )
                if resp.embeddings:
                    vec = list(resp.embeddings[0].values)
                else:
                    logger.warning("Gemini returned no embeddings for input.")
                break
            except Exception as e:
                if attempt < _MAX_RETRIES - 1 and _is_transient(e):
                    time.sleep(2 ** attempt)  # 1s, 2s, 4s
                    continue
                logger.warning(
                    "Gemini embedding failed (attempt %d/%d): %s",
                    attempt + 1, _MAX_RETRIES, type(e).__name__,
                )
                break
        vectors.append(vec)
    return vectors
