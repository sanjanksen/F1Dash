"""OpenAI text-embedding-3-small caller. Returns None when OPENAI_API_KEY is absent."""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_BATCH_SIZE = 100


def embed_texts(
    texts: list[str],
    model: str = "text-embedding-3-small",
) -> Optional[list[list[float]]]:
    if not texts:
        return []
    if not os.getenv("OPENAI_API_KEY"):
        logger.warning("OPENAI_API_KEY not set — skipping embeddings.")
        return None

    try:
        from openai import OpenAI
    except ImportError:
        logger.warning("openai package not installed — skipping embeddings.")
        return None

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    vectors: list[list[float]] = []
    for i in range(0, len(texts), _BATCH_SIZE):
        batch = texts[i : i + _BATCH_SIZE]
        try:
            resp = client.embeddings.create(model=model, input=batch)
        except Exception as e:
            logger.warning("OpenAI embedding call failed: %s", type(e).__name__)
            return None
        vectors.extend([d.embedding for d in resp.data])
    return vectors
