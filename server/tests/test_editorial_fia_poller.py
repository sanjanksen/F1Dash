"""Tests for editorial.fia_poller — broadened doc-type matching, link extraction."""


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
