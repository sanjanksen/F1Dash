"""Tests for editorial.extract — doc_type classifier, source mapping, F1Technical fallback."""
from unittest.mock import patch


def test_classify_fia_doc_scrutineering():
    from editorial.extract import classify_fia_doc
    assert classify_fia_doc(
        "https://www.fia.com/system/files/decision-document/"
        "2026_canadian_grand_prix_-_race_scrutineering.pdf"
    ) == "fia_scrutineering"


def test_classify_fia_doc_pirelli_preview():
    from editorial.extract import classify_fia_doc
    assert classify_fia_doc(
        "https://www.fia.com/system/files/decision-document/"
        "2026_canadian_grand_prix_-_competition_notes_-_pirelli_preview.pdf"
    ) == "fia_pirelli_preview"


def test_classify_fia_doc_stewards_decision_penalty():
    from editorial.extract import classify_fia_doc
    assert classify_fia_doc(".../stewards_decision_car_55.pdf") == "fia_stewards"
    assert classify_fia_doc(".../decision_document.pdf") == "fia_stewards"
    assert classify_fia_doc(".../penalty_notice.pdf") == "fia_stewards"


def test_classify_fia_doc_pu_info():
    from editorial.extract import classify_fia_doc
    assert classify_fia_doc(".../power_unit_information.pdf") == "fia_pu_info"
    assert classify_fia_doc(".../new_pu_elements_for_this_competition.pdf") == "fia_pu_info"


def test_classify_fia_doc_post_race_check():
    from editorial.extract import classify_fia_doc
    assert classify_fia_doc(
        ".../2026_canadian_grand_prix_-_post-race_checks_on_car_55.pdf"
    ) == "fia_post_race_check"


def test_classify_fia_doc_competition_visa():
    from editorial.extract import classify_fia_doc
    assert classify_fia_doc(
        ".../2026_canadian_grand_prix_-_competition_visa.pdf"
    ) == "fia_competition_visa"


def test_classify_fia_doc_unknown_returns_other():
    from editorial.extract import classify_fia_doc
    assert classify_fia_doc(".../something_unrelated.pdf") == "other"


def test_source_from_url_for_crash_net():
    from editorial.extract import _source_from_url
    assert _source_from_url("https://www.crash.net/f1/news/xyz") == "Crash.net"
    assert _source_from_url("https://crash.net/f1/news/xyz") == "Crash.net"


def test_source_from_url_for_total_motorsport():
    from editorial.extract import _source_from_url
    assert _source_from_url(
        "https://www.total-motorsport.com/news/foo"
    ) == "Total Motorsport"


def test_source_from_url_for_f1technical():
    from editorial.extract import _source_from_url
    assert _source_from_url("https://www.f1technical.net/news/28531") == "F1Technical"
    assert _source_from_url("https://f1technical.net/news/28531") == "F1Technical"


def test_f1technical_fallback_extracts_article_body():
    """Fallback should pull from <article class="a-body"> when trafilatura returns empty."""
    from editorial.extract import _f1technical_fallback
    html = """
    <html><body>
      <div id="main-content">
        <div class="content article">
          <article class="a-body">
            <header><h1>Some F1Technical headline</h1></header>
            <p>""" + ("First substantial paragraph about cars and aero. " * 10) + """</p>
            <p>""" + ("Second paragraph with more technical detail. " * 10) + """</p>
          </article>
        </div>
      </div>
    </body></html>
    """
    text = _f1technical_fallback(html)
    assert text is not None
    assert "First substantial paragraph" in text
    assert "Second paragraph" in text
    assert len(text) > 200


def test_f1technical_fallback_returns_none_for_empty_html():
    from editorial.extract import _f1technical_fallback
    assert _f1technical_fallback("") is None
    assert _f1technical_fallback("<html><body><p>tiny</p></body></html>") is None


def test_extract_url_falls_back_for_f1technical_when_trafilatura_empty():
    """If trafilatura.extract returns empty, f1technical.net URLs should use the BS4 fallback."""
    from editorial import extract as extract_mod

    long_body_html = (
        '<html><body><article class="a-body">'
        + "<p>" + ("F1Technical fallback paragraph " * 30) + "</p>"
        + "</article></body></html>"
    )

    fake_trafilatura = type("T", (), {
        "fetch_url": staticmethod(lambda url: long_body_html),
        "extract": staticmethod(lambda *a, **kw: ""),
        "extract_metadata": staticmethod(lambda *a, **kw: None),
    })

    with patch.dict("sys.modules", {"trafilatura": fake_trafilatura}):
        result = extract_mod.extract_url("https://www.f1technical.net/news/28531")

    assert result is not None
    assert result["source"] == "F1Technical"
    assert "F1Technical fallback paragraph" in result["body"]


def test_extract_url_no_fallback_for_non_f1technical_when_empty():
    """Empty trafilatura output for other hosts should still return None (no over-aggressive fallback)."""
    from editorial import extract as extract_mod

    fake_trafilatura = type("T", (), {
        "fetch_url": staticmethod(lambda url: "<html><body><p>stuff</p></body></html>"),
        "extract": staticmethod(lambda *a, **kw: ""),
        "extract_metadata": staticmethod(lambda *a, **kw: None),
    })

    with patch.dict("sys.modules", {"trafilatura": fake_trafilatura}):
        result = extract_mod.extract_url("https://www.the-race.com/f1/news/whatever")

    assert result is None
