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
