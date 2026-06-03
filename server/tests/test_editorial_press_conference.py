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


def test_event_names_for_year_current_uses_live_schedule(monkeypatch):
    """Current year → the live app schedule (date-filtered), unchanged for cron."""
    monkeypatch.setattr(pcp, "_scheduled_past_events", lambda y: ["Live GP"])
    assert pcp._event_names_for_year(pcp.CURRENT_YEAR) == ["Live GP"]


def test_event_names_for_year_historical_uses_fastf1(monkeypatch):
    """Prior years → FastF1's full historical schedule (calendars differ by year)."""
    import fastf1

    class _Col:
        def __init__(self, v):
            self._v = v

        def tolist(self):
            return self._v

    class _Sched:
        def __init__(self, names):
            self._names = names

        def __getitem__(self, key):
            return _Col(self._names)

    monkeypatch.setattr(
        fastf1, "get_event_schedule",
        lambda year, **kw: _Sched(["Bahrain Grand Prix", "Saudi Arabian Grand Prix"]),
        raising=False,
    )
    assert pcp._event_names_for_year(2024) == ["Bahrain Grand Prix", "Saudi Arabian Grand Prix"]


def test_backfill_seasons_runs_per_year_and_aggregates(monkeypatch):
    """backfill_seasons polls each year once and sums the counts."""
    seen = []

    def fake_poll(year=None, **kw):
        seen.append(year)
        return {"new_articles": 5, "skipped": 2, "errors": 0, "details": []}

    monkeypatch.setattr(pcp, "poll_press_conferences", fake_poll)
    out = pcp.backfill_seasons([2024, 2025])

    assert seen == [2024, 2025]
    assert out["new_articles"] == 10 and out["skipped"] == 4
    assert out["by_year"][2024]["new_articles"] == 5
