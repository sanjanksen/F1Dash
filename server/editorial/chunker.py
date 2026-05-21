"""Sentence-aware chunker for editorial body text.

Splits prose into ~target_tokens-sized chunks with a configurable overlap so
embeddings keep neighbouring context. Uses tiktoken if importable; otherwise
falls back to a word-count proxy (len(words) * 1.3 ≈ tokens for English).
"""
from __future__ import annotations

import re

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")

try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")

    def _count_tokens(text: str) -> int:
        return len(_ENC.encode(text))
except Exception:
    _ENC = None

    def _count_tokens(text: str) -> int:
        words = text.split()
        return int(len(words) * 1.3) if words else 0


def _split_sentences(text: str) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    parts = _SENTENCE_SPLIT.split(text)
    return [p.strip() for p in parts if p.strip()]


def chunk_text(text: str, target_tokens: int = 600, overlap: int = 80) -> list[str]:
    """Greedy sentence-aware splitter.

    Accumulates sentences until token-count reaches target_tokens, then starts
    a new chunk that begins with the tail of the previous chunk (sentences
    summing to ~overlap tokens).
    """
    sentences = _split_sentences(text)
    if not sentences:
        return []

    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0

    for sent in sentences:
        sent_tokens = _count_tokens(sent)
        if current and current_tokens + sent_tokens > target_tokens:
            chunks.append(" ".join(current))
            # Build overlap tail from the chunk we just emitted
            tail: list[str] = []
            tail_tokens = 0
            for s in reversed(current):
                t = _count_tokens(s)
                if tail_tokens + t > overlap and tail:
                    break
                tail.insert(0, s)
                tail_tokens += t
            current = list(tail)
            current_tokens = tail_tokens
        current.append(sent)
        current_tokens += sent_tokens

    if current:
        chunks.append(" ".join(current))
    return chunks
