"""Tests for editorial.fia_poller — broadened doc-type matching, link extraction."""
from unittest.mock import MagicMock, patch


def test_extract_pdf_links_matches_multiple_doc_types():
    """The poller should return all useful weekend doc types — not just scrutineering."""
    from editorial.fia_poller import _extract_pdf_links

    html = """
    <html><body>
      <a href="/system/files/decision-document/2026_canadian_grand_prix_-_race_scrutineering.pdf">a</a>
      <a href="/system/files/decision-document/2026_canadian_grand_prix_-_competition_notes_-_pirelli_preview.pdf">b</a>
      <a href="/system/files/decision-document/2026_canadian_grand_prix_-_stewards_decision_car_55.pdf">c</a>
      <a href="/system/files/decision-document/2026_canadian_grand_prix_-_post-race_checks_on_car_55.pdf">d</a>
      <a href="/system/files/decision-document/2026_canadian_grand_prix_-_competition_visa.pdf">e</a>
      <a href="/system/files/decision-document/2026_canadian_grand_prix_-_power_unit_information.pdf">f</a>
      <a href="/system/files/decision-document/some_random_unrelated.pdf">g</a>
      <a href="/some/non-pdf-link">h</a>
    </body></html>
    """
    urls = _extract_pdf_links(html, "https://www.fia.com/season-page")

    joined = "\n".join(urls)
    assert len(urls) == 6, f"expected 6 matched PDFs, got {len(urls)}: {urls}"
    assert "race_scrutineering" in joined
    assert "pirelli_preview" in joined
    assert "stewards_decision_car_55" in joined
    assert "post-race_checks" in joined
    assert "competition_visa" in joined
    assert "power_unit_information" in joined
    assert "some_random_unrelated.pdf" not in joined


def test_extract_pdf_links_resolves_relative_to_base():
    from editorial.fia_poller import _extract_pdf_links
    html = '<a href="/system/files/decision-document/foo_scrutineering.pdf">x</a>'
    urls = _extract_pdf_links(html, "https://www.fia.com/documents/foo")
    assert urls == [
        "https://www.fia.com/system/files/decision-document/foo_scrutineering.pdf"
    ]


def test_extract_pdf_links_dedupes():
    from editorial.fia_poller import _extract_pdf_links
    html = """
    <a href="/x/scrutineering.pdf">a</a>
    <a href="/x/scrutineering.pdf">b</a>
    """
    urls = _extract_pdf_links(html, "https://www.fia.com/")
    assert len(urls) == 1


def test_extract_pdf_links_empty_html():
    from editorial.fia_poller import _extract_pdf_links
    assert _extract_pdf_links("", "https://x") == []


def test_is_useful_pdf_rejects_non_pdf():
    from editorial.fia_poller import _is_useful_pdf
    assert _is_useful_pdf("/foo/scrutineering.html") is False
    assert _is_useful_pdf("/foo/scrutineering.pdf") is True


def test_is_useful_pdf_rejects_unrelated_pdf():
    from editorial.fia_poller import _is_useful_pdf
    assert _is_useful_pdf("/system/files/some_random.pdf") is False


def test_is_useful_pdf_matches_event_notes_and_sporting_info():
    """2024-2025 backfill additions: race director event notes + sporting info."""
    from editorial.fia_poller import _is_useful_pdf
    assert _is_useful_pdf(
        "/system/files/decision-document/2025_bahrain_grand_prix_-_race_directors_event_notes.pdf"
    ) is True
    # 2024 filenames use literal spaces, not underscores.
    assert _is_useful_pdf(
        "/sites/default/files/decision-document/2024 Bahrain Grand Prix - Event Notes - Pirelli Preview.pdf"
    ) is True
    assert _is_useful_pdf(
        "/system/files/decision-document/2025_bahrain_grand_prix_-_sporting_information.pdf"
    ) is True


def test_extract_event_urls_from_season_page():
    from editorial.fia_poller import _extract_event_urls
    html = """
    <select>
      <option value="0">Event</option>
      <option value="/documents/championships/fia-formula-one-world-championship-14/season/season-2024-2043/event/Bahrain%20Grand%20Prix">Bahrain</option>
      <option value="/documents/championships/fia-formula-one-world-championship-14/season/season-2024-2043/event/Australian%20Grand%20Prix">Australia</option>
      <option value="/documents/championships/fia-formula-one-world-championship-14/season/season-2024-2043/event/Bahrain%20Grand%20Prix">Bahrain dup</option>
    </select>
    """
    urls = _extract_event_urls(html, "https://www.fia.com/")
    assert len(urls) == 2
    assert urls[0].endswith("/event/Bahrain%20Grand%20Prix")
    assert urls[1].endswith("/event/Australian%20Grand%20Prix")


def _make_season_html(season_id: str, events: list[str], pdfs_first: list[str]) -> str:
    """Build a synthetic season landing page: event selector + first-event PDFs."""
    opts = "\n".join(
        f'<option value="/documents/championships/fia-formula-one-world-championship-14/season/{season_id}/event/{e}">{e}</option>'
        for e in events
    )
    pdfs = "\n".join(f'<a href="{p}">x</a>' for p in pdfs_first)
    return f"<html><body><select>{opts}</select>{pdfs}</body></html>"


def _make_event_html(pdfs: list[str]) -> str:
    return "<html><body>" + "\n".join(f'<a href="{p}">x</a>' for p in pdfs) + "</body></html>"


def _build_fake_requests_get(html_by_url: dict[str, str]):
    """Return a fake requests.get that yields canned HTML per URL, 404 otherwise."""
    def fake_get(url, headers=None, timeout=None):
        resp = MagicMock()
        if url in html_by_url:
            resp.status_code = 200
            resp.text = html_by_url[url]
        else:
            resp.status_code = 404
            resp.text = ""
        return resp
    return fake_get


def test_poll_accepts_list_of_urls():
    """poll_fia_documents should iterate every season URL and accumulate results."""
    from editorial import fia_poller

    s1 = "https://www.fia.com/documents/championships/fia-formula-one-world-championship-14/season/season-2024-2043"
    s2 = "https://www.fia.com/documents/championships/fia-formula-one-world-championship-14/season/season-2025-2071"
    e1 = "https://www.fia.com/documents/championships/fia-formula-one-world-championship-14/season/season-2024-2043/event/Bahrain%20Grand%20Prix"
    e2 = "https://www.fia.com/documents/championships/fia-formula-one-world-championship-14/season/season-2025-2071/event/Bahrain%20Grand%20Prix"

    html_by_url = {
        s1: _make_season_html(
            "season-2024-2043",
            ["Bahrain%20Grand%20Prix"],
            ["/x/2024 Bahrain Grand Prix - Race scrutineering.pdf"],
        ),
        e1: _make_event_html([
            "/x/2024 Bahrain Grand Prix - Race scrutineering.pdf",
            "/x/2024 Bahrain Grand Prix - Stewards Decision Car 1.pdf",
        ]),
        s2: _make_season_html(
            "season-2025-2071",
            ["Bahrain%20Grand%20Prix"],
            ["/y/2025_bahrain_grand_prix_-_race_scrutineering.pdf"],
        ),
        e2: _make_event_html([
            "/y/2025_bahrain_grand_prix_-_race_scrutineering.pdf",
            "/y/2025_bahrain_grand_prix_-_race_directors_event_notes.pdf",
        ]),
    }
    fake_ingest = MagicMock(return_value={"action": "inserted"})

    with patch.object(fia_poller, "ingest_fia_pdf", fake_ingest), \
         patch("requests.get", side_effect=_build_fake_requests_get(html_by_url)):
        result = fia_poller.poll_fia_documents([s1, s2])

    assert result["feeds_polled"] == 2
    # 2 from 2024 event (scrutineering + stewards) + 2 from 2025 event (scrutineering + event_notes)
    assert result["new_articles"] == 4, result
    assert result["errors"] == 0
    # ingest called once per unique PDF URL.
    assert fake_ingest.call_count == 4


def test_poll_accepts_single_url_string_for_backcompat():
    from editorial import fia_poller

    s = "https://www.fia.com/documents/championships/fia-formula-one-world-championship-14/season/season-2026-2072"
    e = "https://www.fia.com/documents/championships/fia-formula-one-world-championship-14/season/season-2026-2072/event/Bahrain%20Grand%20Prix"
    html_by_url = {
        s: _make_season_html("season-2026-2072", ["Bahrain%20Grand%20Prix"], []),
        e: _make_event_html(["/z/2026_bahrain_grand_prix_-_race_scrutineering.pdf"]),
    }
    fake_ingest = MagicMock(return_value={"action": "inserted"})
    with patch.object(fia_poller, "ingest_fia_pdf", fake_ingest), \
         patch("requests.get", side_effect=_build_fake_requests_get(html_by_url)):
        result = fia_poller.poll_fia_documents(s)
    assert result["feeds_polled"] == 1
    assert result["new_articles"] == 1


def test_default_polls_three_seasons():
    """Calling with no args should poll the 2024 + 2025 + 2026 default URLs."""
    from editorial import fia_poller

    assert len(fia_poller.DEFAULT_FIA_SEASON_URLS) == 3
    assert any("season-2024-2043" in u for u in fia_poller.DEFAULT_FIA_SEASON_URLS)
    assert any("season-2025-2071" in u for u in fia_poller.DEFAULT_FIA_SEASON_URLS)
    assert any("season-2026-2072" in u for u in fia_poller.DEFAULT_FIA_SEASON_URLS)

    fake_ingest = MagicMock(return_value={"action": "inserted"})
    # All season URLs return empty season pages (no events, no PDFs) — we only
    # care that all three were fetched.
    html_by_url = {u: "<html><body></body></html>" for u in fia_poller.DEFAULT_FIA_SEASON_URLS}
    seen_urls: list[str] = []

    def tracking_get(url, headers=None, timeout=None):
        seen_urls.append(url)
        return _build_fake_requests_get(html_by_url)(url, headers=headers, timeout=timeout)

    with patch.object(fia_poller, "ingest_fia_pdf", fake_ingest), \
         patch("requests.get", side_effect=tracking_get):
        result = fia_poller.poll_fia_documents()

    assert result["feeds_polled"] == 3
    assert sorted(seen_urls) == sorted(fia_poller.DEFAULT_FIA_SEASON_URLS)


def test_classify_fia_doc_handles_space_separated_filenames():
    """2024 FIA filenames use literal spaces, not underscores — classifier must match."""
    from editorial.extract import classify_fia_doc

    assert classify_fia_doc("/x/2024 Bahrain Grand Prix - Race scrutineering.pdf") == "fia_scrutineering"
    assert classify_fia_doc("/x/2024 Bahrain Grand Prix - Pirelli Preview.pdf") == "fia_pirelli_preview"
    assert classify_fia_doc("/x/2024 Bahrain Grand Prix - Event Notes.pdf") == "other"
