import math
from datetime import datetime, timedelta, timezone

from editorial.relevance import (
    EDITORIAL_RELEVANT_MODES,
    should_retrieve_editorial,
)
from editorial.relevance import build_resolver_subject_set, chunk_passes_subject_filter
from editorial.relevance import (
    HALF_LIFE_DAYS,
    apply_recency_multiplier,
)


def test_interpretive_modes_retrieve():
    """Interpretive modes ('why' questions) should retrieve editorial."""
    for mode in ("qualifying_battle", "race_pace_comparison",
                 "driver_comparison", "team_performance",
                 "team_circuit_fit"):
        assert should_retrieve_editorial(mode), f"{mode} should retrieve"


def test_descriptive_modes_skip():
    """Descriptive modes (telemetric / structural) should skip retrieval."""
    for mode in ("circuit_profile", "grip_comparison",
                 "sector_comparison", "corner_comparison"):
        assert not should_retrieve_editorial(mode), f"{mode} should skip"


def test_unknown_mode_skips():
    """Unknown modes default to skip — fail safe."""
    assert not should_retrieve_editorial("unknown_mode")
    assert not should_retrieve_editorial(None)
    assert not should_retrieve_editorial("")


def test_build_resolver_subject_set_includes_drivers_team_circuit():
    resolved = {
        "drivers": [{"code": "NOR"}, {"code": "PIA"}],
        "team": "McLaren",
        "circuit_slug": "imola",
    }
    subjects = build_resolver_subject_set(resolved)
    assert ("driver", "NOR") in subjects
    assert ("driver", "PIA") in subjects
    assert ("team", "mclaren") in subjects
    assert ("circuit", "imola") in subjects


def test_build_resolver_subject_set_handles_missing_fields():
    """Resolver output is sometimes partial — must not crash on missing keys."""
    assert build_resolver_subject_set({}) == frozenset()
    assert build_resolver_subject_set({"drivers": []}) == frozenset()
    assert build_resolver_subject_set(None) == frozenset()


def test_chunk_passes_subject_filter_when_overlap():
    """Chunk passes when its article shares at least one subject with the resolver."""
    chunk = {"article_subjects": [{"kind": "driver", "ref": "NOR"}]}
    resolver_subjects = frozenset({("driver", "NOR"), ("circuit", "imola")})
    assert chunk_passes_subject_filter(chunk, resolver_subjects)


def test_chunk_fails_subject_filter_when_no_overlap():
    """Chunk fails when its article has no matching subject."""
    chunk = {"article_subjects": [{"kind": "driver", "ref": "VER"}]}
    resolver_subjects = frozenset({("driver", "NOR"), ("circuit", "imola")})
    assert not chunk_passes_subject_filter(chunk, resolver_subjects)


def test_chunk_passes_when_resolver_subjects_empty():
    """If the resolver produced no entities, don't gate on subjects — fall
    back to similarity-only filtering. Returning False here would silently
    drop every chunk on under-specified questions."""
    chunk = {"article_subjects": [{"kind": "driver", "ref": "NOR"}]}
    assert chunk_passes_subject_filter(chunk, frozenset())


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def test_recency_multiplier_fresh_article_score_unchanged():
    """An article published today gets multiplier ≈ 1.0."""
    today = datetime.now(timezone.utc)
    adjusted = apply_recency_multiplier(0.80, _iso(today), now=today)
    assert abs(adjusted - 0.80) < 0.001


def test_recency_multiplier_one_half_life_halves_score():
    """At 21 days old, score should be ~exp(-1) of original."""
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=HALF_LIFE_DAYS)
    adjusted = apply_recency_multiplier(0.80, _iso(old), now=now)
    expected = 0.80 * math.exp(-1)
    assert abs(adjusted - expected) < 0.001


def test_recency_multiplier_handles_missing_date():
    """Articles without published_at get a neutral 1.0 multiplier — no
    information, no penalty."""
    assert apply_recency_multiplier(0.80, None) == 0.80
    assert apply_recency_multiplier(0.80, "") == 0.80


def test_recency_multiplier_handles_unparseable_date():
    """Garbage in shouldn't crash — fall back to neutral."""
    assert apply_recency_multiplier(0.80, "not-a-date") == 0.80


def test_recency_multiplier_never_below_floor():
    """Very old articles still get a small positive multiplier so they can
    surface if similarity is very high. Floor at 0.05 to avoid total zero."""
    now = datetime.now(timezone.utc)
    very_old = now - timedelta(days=400)
    adjusted = apply_recency_multiplier(0.80, _iso(very_old), now=now)
    assert adjusted >= 0.80 * 0.05 - 0.001
