# server/tests/test_units.py
from units import ms_to_kph, kph_to_ms, ms_to_kph_series


def test_ms_to_kph_handles_none():
    assert ms_to_kph(None) is None
    assert kph_to_ms(None) is None


def test_ms_to_kph_zero_round_trips():
    assert ms_to_kph(0) == 0
    assert kph_to_ms(0) == 0
    assert kph_to_ms(ms_to_kph(0)) == 0


def test_ms_to_kph_canonical_value():
    assert ms_to_kph(100) == 360.0


def test_kph_to_ms_canonical_value():
    assert kph_to_ms(360) == 100.0


def test_ms_to_kph_series_preserves_length_and_nones():
    result = ms_to_kph_series([0, 10, None, 50])
    assert len(result) == 4
    assert result[0] == 0
    assert result[1] == 36.0
    assert result[2] is None
    assert result[3] == 180.0
