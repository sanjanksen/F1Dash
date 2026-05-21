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


from unittest.mock import patch

from editorial.relevance import log_gate_decision


def test_log_gate_decision_calls_supabase_insert():
    """log_gate_decision should write one row to editorial_gate_audit via
    the existing postgrest client wrapper."""
    candidates = [
        {"chunk_id": 1, "similarity": 0.72, "published_at": "2026-05-01"},
        {"chunk_id": 2, "similarity": 0.55, "published_at": "2026-05-15"},
    ]
    survivors = [
        {"chunk_id": 1, "similarity": 0.72, "published_at": "2026-05-01"},
    ]

    with patch("editorial.relevance._client") as mock_client:
        log_gate_decision(
            question="why was norris faster",
            analysis_mode="qualifying_battle",
            resolver_subjects=frozenset([("driver", "NOR")]),
            candidates=candidates,
            survivors=survivors,
            threshold_used=0.62,
        )
        mock_client.insert_gate_audit.assert_called_once()
        row = mock_client.insert_gate_audit.call_args.args[0]
        assert row["question"] == "why was norris faster"
        assert row["analysis_mode"] == "qualifying_battle"
        assert row["candidate_count"] == 2
        assert row["kept_count"] == 1


def test_log_gate_decision_does_not_crash_on_db_unavailable():
    """If the audit insert fails, the main path must continue. Audit is
    best-effort, never blocking."""
    with patch("editorial.relevance._client") as mock_client:
        mock_client.insert_gate_audit.side_effect = Exception("supabase down")
        log_gate_decision(
            question="q",
            analysis_mode="qualifying_battle",
            resolver_subjects=frozenset(),
            candidates=[],
            survivors=[],
            threshold_used=0.62,
        )


from editorial.relevance import gated_editorial_lookup


def test_gated_lookup_skips_irrelevant_mode():
    """circuit_profile mode shouldn't even attempt retrieval."""
    with patch("editorial.relevance._search") as mock_search, \
         patch("editorial.relevance.log_gate_decision") as mock_log:
        result = gated_editorial_lookup(
            question="what's the circuit profile for Monaco",
            resolved={"drivers": [], "circuit_slug": "monaco"},
            analysis_mode="circuit_profile",
        )
        assert result is None
        mock_search.assert_not_called()
        mock_log.assert_not_called()  # not even logged — early exit


def test_gated_lookup_returns_none_when_no_candidates():
    """If pgvector returns nothing, return None — caller knows to skip."""
    with patch("editorial.relevance._search", return_value={"results": []}), \
         patch("editorial.relevance.log_gate_decision") as mock_log:
        result = gated_editorial_lookup(
            question="why was norris faster",
            resolved={"drivers": [{"code": "NOR"}, {"code": "PIA"}]},
            analysis_mode="qualifying_battle",
        )
        assert result is None
        mock_log.assert_called_once()  # logged the empty candidate set


def test_gated_lookup_keeps_chunks_passing_all_gates():
    """High-similarity, subject-matching, recent chunk survives."""
    from datetime import datetime, timezone
    recent = datetime.now(timezone.utc).isoformat()
    fake_results = {
        "search_mode": "semantic",
        "results": [
            {
                "chunk_id": 101,
                "similarity": 0.82,
                "chunk_text": "Norris said McLaren brought a new floor...",
                "title": "McLaren Imola upgrade",
                "url": "https://the-race.com/x",
                "source": "The Race",
                "published_at": recent,
                "article_subjects": [
                    {"kind": "driver", "ref": "NOR"},
                    {"kind": "team", "ref": "mclaren"},
                ],
            },
        ],
    }
    with patch("editorial.relevance._search", return_value=fake_results), \
         patch("editorial.relevance.log_gate_decision"):
        result = gated_editorial_lookup(
            question="why was norris faster at Imola",
            resolved={
                "drivers": [{"code": "NOR"}, {"code": "PIA"}],
                "team": "McLaren",
                "circuit_slug": "imola",
            },
            analysis_mode="qualifying_battle",
        )
        assert result is not None
        assert result["kind"] == "editorial"
        assert len(result["chunks"]) == 1
        assert result["chunks"][0]["chunk_id"] == 101


def test_gated_lookup_drops_chunk_failing_subject_intersection():
    """High similarity but wrong driver/team → dropped."""
    from datetime import datetime, timezone
    recent = datetime.now(timezone.utc).isoformat()
    fake_results = {
        "search_mode": "semantic",
        "results": [
            {
                "chunk_id": 202,
                "similarity": 0.85,
                "chunk_text": "Verstappen took pole in Bahrain...",
                "url": "https://...",
                "source": "...",
                "published_at": recent,
                "article_subjects": [{"kind": "driver", "ref": "VER"}],
            },
        ],
    }
    with patch("editorial.relevance._search", return_value=fake_results), \
         patch("editorial.relevance.log_gate_decision"):
        result = gated_editorial_lookup(
            question="why was norris faster",
            resolved={"drivers": [{"code": "NOR"}, {"code": "PIA"}]},
            analysis_mode="qualifying_battle",
        )
        assert result is None  # everything dropped → return None


def test_gated_lookup_drops_chunk_below_similarity_threshold():
    """Subject-matching but low similarity → dropped."""
    from datetime import datetime, timezone
    recent = datetime.now(timezone.utc).isoformat()
    fake_results = {
        "search_mode": "semantic",
        "results": [
            {
                "chunk_id": 303,
                "similarity": 0.40,  # below 0.62 threshold
                "chunk_text": "some borderline content...",
                "url": "https://...",
                "source": "...",
                "published_at": recent,
                "article_subjects": [{"kind": "driver", "ref": "NOR"}],
            },
        ],
    }
    with patch("editorial.relevance._search", return_value=fake_results), \
         patch("editorial.relevance.log_gate_decision"):
        result = gated_editorial_lookup(
            question="why was norris faster",
            resolved={"drivers": [{"code": "NOR"}]},
            analysis_mode="qualifying_battle",
        )
        assert result is None
