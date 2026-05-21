"""Relevance gating for editorial RAG in the deterministic analysis path.

Two layers of gating:
1. Per-mode: only fire retrieval for interpretive analysis_modes (why was X
   faster?). Descriptive modes (sector deltas, circuit profile) skip
   retrieval entirely — no embedding call, no Supabase round-trip.
2. Per-chunk: after pgvector returns top-N candidates, filter by similarity
   threshold + resolver-subject intersection + recency multiplier. Anything
   that doesn't clear the bar is dropped.

Failure mode is silence: if nothing passes the gates, the analyzer gets no
editorial evidence and its prompt rule says to omit the editorial_observation
field. That's safer than confidently citing an irrelevant article.
"""
from __future__ import annotations


# Analysis modes where editorial context is consistently useful.
# Modes NOT in this set will skip editorial retrieval entirely — saves an
# embedding call + pgvector round-trip on every descriptive question.
EDITORIAL_RELEVANT_MODES: frozenset[str] = frozenset({
    "qualifying_battle",
    "race_pace_comparison",
    "driver_comparison",
    "team_performance",
    "team_circuit_fit",
})


def should_retrieve_editorial(analysis_mode: str | None) -> bool:
    """Return True if this analysis_mode should attempt editorial retrieval."""
    if not analysis_mode:
        return False
    return analysis_mode in EDITORIAL_RELEVANT_MODES
