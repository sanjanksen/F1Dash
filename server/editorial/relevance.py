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

import math
from datetime import datetime, timezone


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


def build_resolver_subject_set(resolved: dict | None) -> frozenset[tuple[str, str]]:
    """Convert resolver entities into a frozenset of (kind, ref) tuples that
    can be intersected with article_subjects rows.

    Drivers come as a list of dicts with a 'code' field (3-letter uppercase).
    Team comes as a string (canonicalised to lowercase for matching).
    Circuit comes as a slug (already lowercase).
    """
    if not resolved:
        return frozenset()

    subjects: set[tuple[str, str]] = set()

    for driver in (resolved.get("drivers") or []):
        code = (driver.get("code") or "").strip().upper()
        if code:
            subjects.add(("driver", code))

    team = (resolved.get("team") or "").strip().lower()
    if team:
        # Normalise team name to slug-ish form to match article_subjects.ref.
        # E.g. "Racing Bulls" -> "racing_bulls". The subject tagger uses the
        # same normalisation.
        subjects.add(("team", team.replace(" ", "_")))

    circuit_slug = (resolved.get("circuit_slug") or "").strip().lower()
    if circuit_slug:
        subjects.add(("circuit", circuit_slug))

    return frozenset(subjects)


def chunk_passes_subject_filter(
    chunk: dict,
    resolver_subjects: frozenset[tuple[str, str]],
) -> bool:
    """A chunk passes when its parent article's subjects intersect the
    resolver's. If the resolver produced no subjects (highly under-specified
    question), the filter is a no-op — fall through to similarity-only.
    """
    if not resolver_subjects:
        return True  # no resolver subjects → no filter, similarity must carry

    raw_subjects = chunk.get("article_subjects") or []
    chunk_subjects = {
        (s.get("kind"), s.get("ref"))
        for s in raw_subjects
        if s.get("kind") and s.get("ref")
    }
    return bool(chunk_subjects & resolver_subjects)


# Half-life for editorial relevance, in days. Tuned for the F1 race-weekend
# cadence — an article is half as relevant 3 weeks after publication, which
# matches the "every other weekend has a race" rhythm of the season.
HALF_LIFE_DAYS: float = 21.0

# Floor below which the recency multiplier is clamped. Prevents very old
# articles from being totally zeroed out — keeps the gate from suppressing
# a 5-year-old article that's still highly relevant by similarity.
RECENCY_FLOOR: float = 0.05


def _parse_published(published_at: str | None) -> datetime | None:
    if not published_at:
        return None
    try:
        if "T" in published_at:
            dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(published_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def apply_recency_multiplier(
    score: float,
    published_at: str | None,
    *,
    now: datetime | None = None,
) -> float:
    """Multiply score by an exponential recency decay.

    score × max(exp(-age_days / HALF_LIFE_DAYS), RECENCY_FLOOR)

    Articles without published_at get a neutral 1.0 multiplier — no
    information means no penalty.
    """
    dt = _parse_published(published_at)
    if dt is None:
        return score

    if now is None:
        now = datetime.now(timezone.utc)

    age_days = max((now - dt).total_seconds() / 86400.0, 0.0)
    multiplier = math.exp(-age_days / HALF_LIFE_DAYS)
    multiplier = max(multiplier, RECENCY_FLOOR)
    return score * multiplier
