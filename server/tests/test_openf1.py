from unittest.mock import patch
from unittest.mock import MagicMock

import openf1


class FakeHTTPError(Exception):
    pass


@patch("openf1.get_circuits")
@patch("openf1._openf1_get")
def test_resolve_openf1_session(mock_openf1_get, mock_get_circuits):
    mock_get_circuits.return_value = [
        {"round": 3, "event_name": "Japanese Grand Prix", "country": "Japan"},
    ]
    mock_openf1_get.return_value = [
        {"session_key": 1003, "session_name": "Qualifying", "country_name": "Japan", "circuit_short_name": "Suzuka"}
    ]

    result = openf1._resolve_openf1_session(3, "Q")

    assert result["session_key"] == 1003
    mock_openf1_get.assert_called_once()


@patch("openf1.get_session_results")
@patch("openf1._resolve_driver")
def test_driver_number_for_session(mock_resolve_driver, mock_get_session_results):
    mock_resolve_driver.return_value = {"full_name": "Lando Norris", "code": "NOR"}
    mock_get_session_results.return_value = {
        "results": [{"abbreviation": "NOR", "driver_number": "4"}]
    }

    result = openf1._driver_number_for_session(3, "Q", "NOR")

    assert result == 4


@patch("openf1._openf1_get")
@patch("openf1._resolve_openf1_session")
@patch("openf1._driver_number_for_session")
@patch("openf1._resolve_driver")
def test_get_team_radio(mock_resolve_driver, mock_driver_number, mock_resolve_session, mock_openf1_get):
    mock_resolve_session.return_value = {
        "session_key": 1003,
        "session_name": "Qualifying",
        "country_name": "Japan",
        "circuit_short_name": "Suzuka",
    }
    mock_driver_number.return_value = 4
    mock_resolve_driver.return_value = {"full_name": "Lando Norris"}
    mock_openf1_get.return_value = [
        {"date": "2026-04-05T06:00:00Z", "driver_number": 4, "recording_url": "https://example.test/radio.mp3"}
    ]

    result = openf1.get_team_radio(3, "Q", "NOR", 5)

    assert result["driver"] == "Lando Norris"
    assert result["source"] == "OpenF1"
    assert result["data_type"] == "audio_recording_metadata"
    assert result["messages"][0]["recording_url"].endswith(".mp3")


def test_get_team_radio_returns_empty_for_openf1_404():
    session = {
        "session_key": 11249,
        "session_name": "Qualifying",
        "country_name": "Japan",
        "circuit_short_name": "Suzuka",
    }
    response = MagicMock()
    response.status_code = 404
    error = FakeHTTPError()
    error.response = response

    with patch("openf1._resolve_openf1_session", return_value=session), \
        patch("openf1._driver_number_for_session", return_value=4), \
        patch("openf1._resolve_driver", return_value={"full_name": "Lando Norris"}), \
        patch("openf1.requests.HTTPError", FakeHTTPError), \
        patch("openf1._openf1_get", side_effect=error):
        result = openf1.get_team_radio(3, "Q", "NOR", 5)

    assert result["messages"] == []
    assert result["unavailable_reason"] == "OpenF1 has no team radio rows for this session/driver."


@patch("openf1._openf1_get")
@patch("openf1._resolve_openf1_session")
def test_get_intervals(mock_resolve_session, mock_openf1_get):
    mock_resolve_session.return_value = {
        "session_key": 1004,
        "session_name": "Race",
        "country_name": "Japan",
        "circuit_short_name": "Suzuka",
    }
    mock_openf1_get.return_value = [
        {"date": "2026-04-05T06:15:00Z", "driver_number": 16, "gap_to_leader": "+3.2", "interval": "+1.1"}
    ]

    result = openf1.get_intervals(3)

    assert result["intervals"][0]["gap_to_leader"] == "+3.2"


@patch('openf1._openf1_get')
@patch('openf1.get_circuits')
def test_resolve_openf1_session_caches_schedule(mock_get_circuits, mock_openf1_get):
    import openf1
    openf1._circuits_cache = []
    mock_get_circuits.return_value = [{"round": 3, "event_name": "Japanese Grand Prix", "country": "Japan"}]
    mock_openf1_get.return_value = [{"session_key": 321, "date_start": "2026-04-05T00:00:00"}]

    openf1._resolve_openf1_session(3, "S")
    openf1._resolve_openf1_session(3, "SQ")

    mock_get_circuits.assert_called_once()


@patch('openf1._driver_number_for_session', return_value=4)
@patch('openf1._resolve_driver', return_value={"full_name": "Lando Norris"})
@patch('openf1._openf1_get')
@patch('openf1._resolve_openf1_session')
def test_get_intervals_uses_requested_session_type(mock_resolve_session, mock_openf1_get, mock_resolve_driver, mock_driver_number):
    import openf1
    mock_resolve_session.return_value = {
        "session_key": 456,
        "session_name": "Sprint",
        "country_name": "China",
        "circuit_short_name": "Shanghai",
    }
    mock_openf1_get.return_value = []

    openf1.get_intervals(5, "NOR", limit=5, session_type="S")

    mock_resolve_session.assert_called_once_with(5, "S")
    mock_driver_number.assert_called_once_with(5, "S", "NOR")


@patch("openf1._openf1_get")
@patch("openf1._resolve_openf1_session")
def test_get_live_position_timeline(mock_resolve_session, mock_openf1_get):
    mock_resolve_session.return_value = {
        "session_key": 1004,
        "session_name": "Race",
        "country_name": "Japan",
        "circuit_short_name": "Suzuka",
    }
    mock_openf1_get.return_value = [
        {"date": "2026-04-05T06:20:00Z", "driver_number": 16, "position": 4}
    ]

    result = openf1.get_live_position_timeline(3, "R")

    assert result["positions"][0]["position"] == 4


def _make_openf1_session_row():
    return {"session_key": 9876, "date_start": "2026-04-06", "country_name": "Bahrain",
            "session_name": "Race", "circuit_short_name": "Bahrain"}

def _make_pit_rows():
    return [
        {"driver_number": 63, "lap_number": 14, "pit_duration": 2.41, "session_key": 9876},
        {"driver_number": 4,  "lap_number": 17, "pit_duration": 2.63, "session_key": 9876},
    ]

def test_get_pit_stops_returns_list():
    with patch.object(openf1, '_resolve_openf1_session', return_value=_make_openf1_session_row()), \
         patch.object(openf1, '_openf1_get', return_value=_make_pit_rows()):
        result = openf1.get_pit_stops(1)
    assert isinstance(result, list)
    assert result[0]["driver_number"] == 63
    assert result[0]["pit_duration_s"] == 2.41
    assert result[0]["lap_number"] == 14

def test_get_pit_stops_skips_rows_without_lap_number():
    rows = [{"driver_number": 63, "pit_duration": 2.41}]  # no lap_number
    with patch.object(openf1, '_resolve_openf1_session', return_value=_make_openf1_session_row()), \
         patch.object(openf1, '_openf1_get', return_value=rows):
        result = openf1.get_pit_stops(1)
    assert result == []


class _FakeHTTPError(Exception):
    def __init__(self, msg, response=None):
        super().__init__(msg)
        self.response = response


class _FakeTimeout(Exception):
    pass


class _FakeConnectionError(Exception):
    pass


def _install_fake_requests():
    """Replace openf1.requests with a fake module exposing real exception classes."""
    fake = MagicMock()
    fake.HTTPError = _FakeHTTPError
    fake.Timeout = _FakeTimeout
    fake.ConnectionError = _FakeConnectionError
    return fake


def _make_response(status_code: int, payload=None):
    resp = MagicMock()
    resp.status_code = status_code
    if status_code >= 400:
        def _raise():
            raise _FakeHTTPError(f"{status_code} error", response=resp)
        resp.raise_for_status.side_effect = _raise
    else:
        resp.raise_for_status.return_value = None
    resp.json.return_value = payload if payload is not None else []
    return resp


def test_get_retries_on_502():
    fake_requests = _install_fake_requests()
    fake_requests.get.side_effect = [_make_response(502), _make_response(502), _make_response(200, [{"ok": True}])]
    with patch.object(openf1, "requests", fake_requests), \
         patch.object(openf1.time, "sleep") as mock_sleep:
        result = openf1._openf1_get("sessions", year=2026)
    assert result == [{"ok": True}]
    assert fake_requests.get.call_count == 3
    assert mock_sleep.call_count == 2


def test_get_does_not_retry_404():
    fake_requests = _install_fake_requests()
    fake_requests.get.side_effect = [_make_response(404)]
    with patch.object(openf1, "requests", fake_requests), \
         patch.object(openf1.time, "sleep"):
        try:
            openf1._openf1_get("team_radio")
        except _FakeHTTPError:
            pass
        else:
            raise AssertionError("Expected HTTPError")
    assert fake_requests.get.call_count == 1


def test_get_does_not_retry_401():
    fake_requests = _install_fake_requests()
    fake_requests.get.side_effect = [_make_response(401)]
    with patch.object(openf1, "requests", fake_requests), \
         patch.object(openf1.time, "sleep"):
        try:
            openf1._openf1_get("sessions")
        except _FakeHTTPError:
            pass
        else:
            raise AssertionError("Expected HTTPError")
    assert fake_requests.get.call_count == 1


def test_get_propagates_after_three_failures():
    fake_requests = _install_fake_requests()
    fake_requests.get.side_effect = [_make_response(503), _make_response(503), _make_response(503)]
    with patch.object(openf1, "requests", fake_requests), \
         patch.object(openf1.time, "sleep"):
        try:
            openf1._openf1_get("sessions")
        except _FakeHTTPError as exc:
            assert "503" in str(exc)
        else:
            raise AssertionError("Expected HTTPError")
    assert fake_requests.get.call_count == 3
