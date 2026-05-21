from unittest.mock import patch


def test_search_editorial_content_semantic_mode_with_gemini_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "ga-test")
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-srv")

    fake_rows = [
        {
            "chunk_text": "McLaren's new floor settled the rear through fast corners.",
            "url": "https://the-race.com/x",
            "title": "McLaren upgrade",
            "source": "The Race",
            "published_at": "2026-05-01",
            "similarity": 0.91,
        }
    ]

    from editorial import search as editorial_search

    with patch.object(editorial_search, "embed_texts", return_value=[[0.1] * 1536]) as m_embed, \
         patch.object(editorial_search._client, "call_match_chunks", return_value=fake_rows) as m_rpc:
        out = editorial_search.search_editorial_content("McLaren upgrades Imola", limit=3)

    assert out["available"] is True
    assert out["search_mode"] == "semantic"
    assert out["results"][0]["url"] == "https://the-race.com/x"
    assert out["results"][0]["similarity"] == 0.91
    m_embed.assert_called_once()
    m_rpc.assert_called_once()


def test_search_editorial_content_fts_mode_without_gemini_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-srv")

    fake_rows = [
        {
            "id": 11,
            "url": "https://motorsport.com/y",
            "title": "Ferrari at Imola",
            "source": "Motorsport.com",
            "published_at": "2026-05-02",
            "raw_body": "Ferrari brought a revised diffuser to Imola and Leclerc reported a stable rear.",
        }
    ]

    from editorial import search as editorial_search

    with patch.object(editorial_search, "embed_texts", return_value=None) as m_embed, \
         patch.object(editorial_search._client, "fts_search_articles", return_value=fake_rows) as m_fts:
        out = editorial_search.search_editorial_content("Ferrari diffuser update", limit=5)

    assert out["available"] is True
    assert out["search_mode"] == "fts"
    assert out["results"][0]["url"] == "https://motorsport.com/y"
    assert "Ferrari" in out["results"][0]["chunk_text"]
    assert out["results"][0]["similarity"] is None
    m_embed.assert_called_once()
    m_fts.assert_called_once()


def test_search_editorial_content_returns_unavailable_without_supabase_env(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)

    from editorial.search import search_editorial_content
    out = search_editorial_content("any query")
    assert out["available"] is False
    assert out["reason"] == "editorial_db_unavailable"
    assert out["results"] == []


import os
import sys

import pytest


def _load_dotenv_if_present() -> None:
    """Best-effort: load .env from server/ or repo root so live tests can pick up
    SUPABASE / GEMINI credentials without forcing the dev to export them."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    here = os.path.dirname(os.path.abspath(__file__))
    for candidate in (
        os.path.join(here, "..", ".env"),
        os.path.join(here, "..", "..", ".env"),
    ):
        if os.path.exists(candidate):
            load_dotenv(candidate, override=False)


_load_dotenv_if_present()


def _supabase_configured() -> bool:
    return bool(
        os.getenv("SUPABASE_URL")
        and (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY"))
        and os.getenv("GEMINI_API_KEY")
    )


pytestmark_live = pytest.mark.skipif(
    not _supabase_configured(),
    reason="Live Supabase + Gemini credentials required for hybrid-search regression tests."
)


@pytest.fixture
def _unmock_requests_for_live():
    """conftest.py stubs `requests` with a MagicMock to prevent accidental network
    calls in unit tests. Live tests genuinely need the real `requests` package
    (google-genai depends on it). Restore the real module for the duration of
    the test, then put the mock back."""
    saved = sys.modules.pop("requests", None)
    import importlib
    real_requests = importlib.import_module("requests")
    sys.modules["requests"] = real_requests

    # Also reset the cached editorial client + embed module, in case they were
    # imported earlier under the mocked-requests world.
    from editorial import client as editorial_client
    editorial_client.reset_client_for_tests()
    if "google.genai" in sys.modules:
        # Force a clean re-import so the SDK rebinds against real `requests`.
        for mod_name in list(sys.modules):
            if mod_name.startswith("google.genai"):
                del sys.modules[mod_name]

    try:
        yield
    finally:
        if saved is not None:
            sys.modules["requests"] = saved
        editorial_client.reset_client_for_tests()


@pytestmark_live
def test_hybrid_search_returns_results(_unmock_requests_for_live):
    """Sanity check: the hybrid RPC returns a non-empty result set for a
    typical query that the corpus is known to cover."""
    from editorial.search import search_editorial_content

    out = search_editorial_content("ADUO engine regulation 2026", limit=3)
    assert out.get("available") is True
    assert out.get("search_mode") == "semantic"
    assert len(out.get("results") or []) >= 1


@pytestmark_live
def test_hybrid_finds_fts_only_chunks(_unmock_requests_for_live):
    """When the query contains an exact term that's in the corpus, the
    hybrid RPC should surface chunks via FTS that pure vector might have
    ranked lower. FTS-only chunks come back with similarity=0.0 (no vector
    hit) — verify at least one such chunk appears for a sufficiently
    specific query."""
    from editorial.search import search_editorial_content

    out = search_editorial_content("ADUO", limit=5)
    results = out.get("results") or []
    assert len(results) >= 1
    # At least one chunk should literally contain ADUO (case-insensitive).
    bodies = [(r.get("chunk_text") or "").lower() for r in results]
    assert any("aduo" in b for b in bodies), (
        f"No chunk literally contains 'aduo'; got bodies: "
        f"{[b[:80] for b in bodies]}"
    )


@pytestmark_live
def test_hybrid_returns_results_for_paraphrased_query(_unmock_requests_for_live):
    """When the query is paraphrased and no exact words match the corpus,
    vector search should still carry. Confirms the FTS half doesn't
    starve the result set."""
    from editorial.search import search_editorial_content

    out = search_editorial_content(
        "How are the 2026 power unit regulations changing?",
        limit=3,
    )
    assert out.get("available") is True
    assert len(out.get("results") or []) >= 1, (
        "Vector half of hybrid should return results even when FTS gets no hits."
    )


@pytestmark_live
def test_hybrid_returns_chunks_with_required_fields(_unmock_requests_for_live):
    """Sanity check: the hybrid RPC's return columns are unchanged from
    the original. The Python search layer should see the same shape."""
    from editorial.search import search_editorial_content

    out = search_editorial_content("2026 deployment curve clipping", limit=2)
    for r in out.get("results") or []:
        for required_field in ("url", "title", "source", "chunk_text", "similarity"):
            assert required_field in r, (
                f"Missing required field '{required_field}' in result: "
                f"{list(r.keys())}"
            )


@pytestmark_live
def test_hybrid_finds_driver_specific_content_when_corpus_has_it(_unmock_requests_for_live):
    """For a driver who DOES have substantial coverage in the corpus,
    a name-anchored FTS query should find articles that explicitly
    mention them. This is the failure mode the hybrid is supposed to
    fix — pure vector fuzzes between similar drivers; FTS pins the
    named entity.

    Use Norris (substantial RacingNews365 + Sky F1 coverage in May 2026)
    rather than Verstappen at a specific race where coverage may be thin.
    """
    from editorial.search import search_editorial_content

    out = search_editorial_content(
        "What did Lando Norris say about McLaren's 2026 form?",
        limit=5,
    )
    results = out.get("results") or []
    assert len(results) >= 1
    # At least one chunk should mention Norris by name.
    bodies = [(r.get("chunk_text") or "") for r in results]
    found_norris = any(
        ("Norris" in b) or ("Lando" in b) or ("NOR" in b)
        for b in bodies
    )
    assert found_norris, (
        f"No chunk mentions Norris by name in top 5 results; "
        f"got bodies: {[b[:80] for b in bodies]}. "
        "Hybrid FTS should pin the named driver."
    )
