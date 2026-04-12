# server/tests/test_f1_data.py
import pytest
from unittest.mock import patch, MagicMock
import f1_data


def _make_standings_response():
    mock = MagicMock()
    mock.json.return_value = {
        "MRData": {
            "StandingsTable": {
                "StandingsLists": [{
                    "DriverStandings": [
                        {
                            "position": "1",
                            "points": "120",
                            "wins": "3",
                            "Driver": {
                                "driverId": "verstappen",
                                "givenName": "Max",
                                "familyName": "Verstappen",
                                "code": "VER",
                                "nationality": "Dutch",
                            },
                            "Constructors": [{"name": "Red Bull Racing"}],
                        },
                        {
                            "position": "2",
                            "points": "95",
                            "wins": "1",
                            "Driver": {
                                "driverId": "norris",
                                "givenName": "Lando",
                                "familyName": "Norris",
                                "code": "NOR",
                                "nationality": "British",
                            },
                            "Constructors": [{"name": "McLaren"}],
                        },
                    ]
                }]
            }
        }
    }
    mock.raise_for_status.return_value = None
    return mock


def test_get_drivers_returns_list_of_dicts():
    with patch('f1_data.requests.get', return_value=_make_standings_response()):
        result = f1_data.get_drivers()

    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]['full_name'] == 'Max Verstappen'
    assert result[0]['code'] == 'VER'
    assert result[0]['standing'] == 1
    assert result[0]['wins'] == 3
    assert result[0]['team'] == 'Red Bull Racing'


def test_get_drivers_empty_standings():
    mock = MagicMock()
    mock.json.return_value = {
        "MRData": {"StandingsTable": {"StandingsLists": []}}
    }
    mock.raise_for_status.return_value = None

    with patch('f1_data.requests.get', return_value=mock):
        result = f1_data.get_drivers()

    assert result == []


def _make_results_response(driver_id='verstappen'):
    mock = MagicMock()
    mock.json.return_value = {
        "MRData": {
            "RaceTable": {
                "Races": [
                    {
                        "raceName": "Bahrain Grand Prix",
                        "Results": [{
                            "position": "1",
                            "points": "25",
                            "FastestLap": {"rank": "1"},
                            "Driver": {"driverId": driver_id},
                        }]
                    },
                    {
                        "raceName": "Saudi Arabian Grand Prix",
                        "Results": [{
                            "position": "3",
                            "points": "15",
                            "Driver": {"driverId": driver_id},
                        }]
                    },
                ]
            }
        }
    }
    mock.raise_for_status.return_value = None
    return mock


def test_get_driver_stats_wins_podiums():
    standings_mock = _make_standings_response()
    results_mock = _make_results_response('verstappen')

    with patch('f1_data.requests.get', side_effect=[standings_mock, results_mock]):
        result = f1_data.get_driver_stats('verstappen')

    assert result is not None
    assert result['wins'] == 1
    assert result['podiums'] == 2
    assert result['fastest_laps'] == 1
    assert result['championship_position'] == 1
    assert len(result['recent_races']) == 2


def test_get_driver_stats_not_found():
    standings_mock = _make_standings_response()

    with patch('f1_data.requests.get', return_value=standings_mock):
        result = f1_data.get_driver_stats('nobody')

    assert result is None


def test_get_circuits_returns_list():
    import pandas as pd

    mock_schedule = pd.DataFrame([
        {
            'RoundNumber': 1,
            'EventName': 'Bahrain Grand Prix',
            'Location': 'Sakhir',
            'Country': 'Bahrain',
            'EventDate': pd.Timestamp('2025-03-02'),
        }
    ])

    with patch('f1_data.fastf1.get_event_schedule', return_value=mock_schedule):
        result = f1_data.get_circuits()

    assert len(result) == 1
    assert result[0]['event_name'] == 'Bahrain Grand Prix'
    assert result[0]['round'] == 1
    assert result[0]['country'] == 'Bahrain'
    assert result[0]['date'] == '2025-03-02'
