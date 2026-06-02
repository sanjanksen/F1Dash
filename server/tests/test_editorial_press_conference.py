from editorial import press_conference_poller as pcp


def test_press_conference_urls_match_fia_pattern():
    """URLs must match the FIA's real, deterministic transcript pattern."""
    urls = pcp.press_conference_urls(2026, "Miami Grand Prix")
    assert (
        "https://www.fia.com/news/f1-2026-miami-grand-prix-thursday-press-conference-transcript"
        in urls
    )
    # one candidate per known session variant
    assert len(urls) == len(pcp.CANDIDATE_SESSIONS)


def test_slugify_handles_spaces_and_punctuation():
    assert pcp._slugify("Miami Grand Prix") == "miami-grand-prix"
    assert pcp._slugify("São Paulo Grand Prix").endswith("paulo-grand-prix")


def test_poll_ingests_only_real_transcripts_tagged_press_conference():
    """Soft-404 candidates (is_transcript False) must NOT be ingested; real ones
    are ingested with doc_type='press_conference'."""
    ingested = []

    def fake_ingest(url, doc_type):
        ingested.append((url, doc_type))
        return {"action": "inserted", "url": url}

    out = pcp.poll_press_conferences(
        2026,
        ["Miami Grand Prix"],
        already_ingested=lambda u: False,
        is_transcript=lambda u: "thursday" in u,   # only the Thursday page is real
        ingest=fake_ingest,
    )

    assert out["new_articles"] == 1
    assert len(ingested) == 1
    assert ingested[0][1] == "press_conference"
    assert "thursday" in ingested[0][0]


def test_poll_skips_already_ingested_without_probing_or_fetching():
    """Already-ingested URLs are skipped via the DB check, with no network probe."""
    probed = []

    out = pcp.poll_press_conferences(
        2026,
        ["Miami Grand Prix"],
        already_ingested=lambda u: True,
        is_transcript=lambda u: probed.append(u) or True,
        ingest=lambda url, doc_type: {"action": "inserted"},
    )

    assert probed == []  # never fetched — DB short-circuit
    assert out["skipped"] == len(pcp.CANDIDATE_SESSIONS)
    assert out["new_articles"] == 0
