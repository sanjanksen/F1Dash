from editorial.relevance import (
    EDITORIAL_RELEVANT_MODES,
    should_retrieve_editorial,
)
from editorial.relevance import build_resolver_subject_set, chunk_passes_subject_filter


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
