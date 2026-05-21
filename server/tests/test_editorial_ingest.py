from unittest.mock import patch, MagicMock


def test_ingest_url_new_url_inserts_article_and_chunks():
    from editorial import ingest as ingest_mod

    fake_extract = {
        "title": "Norris on Imola pace",
        "source": "The Race",
        "author": "Edd Straw",
        "published_at": "2026-05-12",
        "body": (
            "Lando Norris said McLaren's floor upgrade lifted the rear stability through Imola's "
            "high-speed direction changes. Lando added that the medium compound was the surprise of the day. "
            "Ferrari's pace was strong too. Leclerc said the same balance window. "
        ) * 6,
    }

    with patch.object(ingest_mod._client, "find_article_by_url", return_value=None) as m_find, \
         patch.object(ingest_mod, "extract_url", return_value=fake_extract) as m_extract, \
         patch.object(ingest_mod, "embed_texts", return_value=[[0.0] * 1536]) as m_embed, \
         patch.object(ingest_mod._client, "upsert_article", return_value={"id": 99, "url": "https://x"}) as m_upsert, \
         patch.object(ingest_mod._client, "insert_chunks", return_value=1) as m_chunks, \
         patch.object(ingest_mod._client, "insert_subjects", return_value=1) as m_subjects:
        result = ingest_mod.ingest_url("https://x")

    assert result["action"] == "inserted"
    assert result["article_id"] == 99
    m_find.assert_called_once_with("https://x")
    m_extract.assert_called_once()
    m_upsert.assert_called_once()
    m_chunks.assert_called_once()
    # embeddings attempted at least once
    assert m_embed.call_count >= 1


def test_ingest_url_duplicate_skips_without_extracting():
    from editorial import ingest as ingest_mod

    with patch.object(ingest_mod._client, "find_article_by_url",
                      return_value={"id": 7, "url": "https://dup"}) as m_find, \
         patch.object(ingest_mod, "extract_url") as m_extract, \
         patch.object(ingest_mod._client, "upsert_article") as m_upsert:
        result = ingest_mod.ingest_url("https://dup")

    assert result["action"] == "skipped"
    assert result["article_id"] == 7
    m_find.assert_called_once()
    m_extract.assert_not_called()
    m_upsert.assert_not_called()
