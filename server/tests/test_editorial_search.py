from unittest.mock import patch


def test_search_editorial_content_semantic_mode_with_openai_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
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


def test_search_editorial_content_fts_mode_without_openai_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
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
