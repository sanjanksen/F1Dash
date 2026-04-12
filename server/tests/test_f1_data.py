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


# ─── Helpers ────────────────────────────────────────────────

def _make_constructor_standings_response():
    mock = MagicMock()
    mock.json.return_value = {
        "MRData": {
            "StandingsTable": {
                "StandingsLists": [{
                    "ConstructorStandings": [
                        {
                            "position": "1",
                            "points": "200",
                            "wins": "4",
                            "Constructor": {
                                "constructorId": "red_bull",
                                "name": "Red Bull Racing",
                                "nationality": "Austrian",
                            },
                        },
                        {
                            "position": "2",
                            "points": "160",
                            "wins": "2",
                            "Constructor": {
                                "constructorId": "mclaren",
                                "name": "McLaren",
                                "nationality": "British",
                            },
                        },
                    ]
                }]
            }
        }
    }
    mock.raise_for_status.return_value = None
    return mock


def _make_race_results_response():
    mock = MagicMock()
    mock.json.return_value = {
        "MRData": {
            "RaceTable": {
                "Races": [{
                    "raceName": "Bahrain Grand Prix",
                    "date": "2025-03-02",
                    "Circuit": {"circuitName": "Bahrain International Circuit"},
                    "Results": [
                        {
                            "position": "1",
                            "points": "25",
                            "status": "Finished",
                            "Driver": {
                                "driverId": "verstappen",
                                "givenName": "Max",
                                "familyName": "Verstappen",
                                "code": "VER",
                            },
                            "Constructor": {"name": "Red Bull Racing"},
                            "FastestLap": {"rank": "1"},
                        },
                        {
                            "position": "2",
                            "points": "18",
                            "status": "Finished",
                            "Driver": {
                                "driverId": "norris",
                                "givenName": "Lando",
                                "familyName": "Norris",
                                "code": "NOR",
                            },
                            "Constructor": {"name": "McLaren"},
                        },
                    ],
                }]
            }
        }
    }
    mock.raise_for_status.return_value = None
    return mock


def _make_qualifying_response():
    mock = MagicMock()
    mock.json.return_value = {
        "MRData": {
            "RaceTable": {
                "Races": [{
                    "raceName": "Bahrain Grand Prix",
                    "date": "2025-03-01",
                    "QualifyingResults": [
                        {
                            "position": "1",
                            "Driver": {
                                "driverId": "verstappen",
                                "givenName": "Max",
                                "familyName": "Verstappen",
                                "code": "VER",
                            },
                            "Constructor": {"name": "Red Bull Racing"},
                            "Q1": "1:29.832",
                            "Q2": "1:29.100",
                            "Q3": "1:28.658",
                        },
                        {
                            "position": "2",
                            "Driver": {
                                "driverId": "norris",
                                "givenName": "Lando",
                                "familyName": "Norris",
                                "code": "NOR",
                            },
                            "Constructor": {"name": "McLaren"},
                            "Q1": "1:29.900",
                            "Q2": "1:29.200",
                            "Q3": "1:28.900",
                        },
                    ],
                }]
            }
        }
    }
    mock.raise_for_status.return_value = None
    return mock


# ─── Tests ──────────────────────────────────────────────────

def test_get_constructor_standings():
    with patch('f1_data.requests.get', return_value=_make_constructor_standings_response()):
        import f1_data
        result = f1_data.get_constructor_standings()

    assert len(result) == 2
    assert result[0]['team'] == 'Red Bull Racing'
    assert result[0]['position'] == 1
    assert result[0]['points'] == 200.0
    assert result[0]['wins'] == 4
    assert result[0]['nationality'] == 'Austrian'
    assert result[1]['team'] == 'McLaren'


def test_get_constructor_standings_empty():
    mock = MagicMock()
    mock.json.return_value = {
        "MRData": {"StandingsTable": {"StandingsLists": []}}
    }
    mock.raise_for_status.return_value = None
    with patch('f1_data.requests.get', return_value=mock):
        import f1_data
        result = f1_data.get_constructor_standings()
    assert result == []


def test_get_race_results():
    with patch('f1_data.requests.get', return_value=_make_race_results_response()):
        import f1_data
        result = f1_data.get_race_results(1)

    assert result['race_name'] == 'Bahrain Grand Prix'
    assert result['date'] == '2025-03-02'
    assert result['circuit'] == 'Bahrain International Circuit'
    assert len(result['results']) == 2
    assert result['results'][0]['position'] == 1
    assert result['results'][0]['driver'] == 'Max Verstappen'
    assert result['results'][0]['code'] == 'VER'
    assert result['results'][0]['fastest_lap'] is True
    assert result['results'][1]['position'] == 2
    assert result['results'][1]['fastest_lap'] is False


def test_get_race_results_empty_round():
    mock = MagicMock()
    mock.json.return_value = {"MRData": {"RaceTable": {"Races": []}}}
    mock.raise_for_status.return_value = None
    with patch('f1_data.requests.get', return_value=mock):
        import f1_data
        result = f1_data.get_race_results(99)
    assert result == {}


def test_get_qualifying_results():
    with patch('f1_data.requests.get', return_value=_make_qualifying_response()):
        import f1_data
        result = f1_data.get_qualifying_results(1)

    assert result['race_name'] == 'Bahrain Grand Prix'
    assert len(result['results']) == 2
    assert result['results'][0]['position'] == 1
    assert result['results'][0]['driver'] == 'Max Verstappen'
    assert result['results'][0]['q3'] == '1:28.658'
    assert result['results'][1]['q3'] == '1:28.900'


def test_get_head_to_head():
    standings_mock = _make_standings_response()

    # Two separate results fetches — one per driver
    results_ver = _make_results_response('verstappen')
    results_nor = MagicMock()
    results_nor.raise_for_status.return_value = None
    results_nor.json.return_value = {
        "MRData": {
            "RaceTable": {
                "Races": [
                    {
                        "raceName": "Bahrain Grand Prix",
                        "Results": [{"position": "2", "points": "18",
                                     "Driver": {"driverId": "norris"}}]
                    },
                    {
                        "raceName": "Saudi Arabian Grand Prix",
                        "Results": [{"position": "1", "points": "25",
                                     "Driver": {"driverId": "norris"}}]
                    },
                ]
            }
        }
    }

    # Call order: standings, races_verstappen, standings, races_norris
    with patch('f1_data.requests.get',
               side_effect=[standings_mock, results_ver, standings_mock, results_nor]):
        import f1_data
        result = f1_data.get_head_to_head('verstappen', 'norris')

    assert result['driver_a'] == 'Max Verstappen'
    assert result['driver_b'] == 'Lando Norris'
    # Bahrain: VER P1 vs NOR P2 → VER ahead
    # Saudi: VER P3 vs NOR P1 → NOR ahead
    assert result['races_a_ahead'] == 1
    assert result['races_b_ahead'] == 1
    assert result['races_compared'] == 2


def test_get_head_to_head_driver_not_found():
    standings_mock = _make_standings_response()
    with patch('f1_data.requests.get', return_value=standings_mock):
        import f1_data
        with pytest.raises(ValueError, match="not found"):
            f1_data.get_head_to_head('nobody', 'verstappen')


# ─── FastF1 session data tests ──────────────────────────────

import pandas as pd


def _make_mock_fastest_lap(driver="NOR", team="McLaren",
                            lap_time_s=86.456,
                            s1=28.123, s2=29.200, s3=29.133,
                            compound="SOFT", tyre_life=3, lap_num=12,
                            speed_i1=220.5, speed_i2=185.3,
                            speed_fl=295.0, speed_st=315.2):
    return pd.Series({
        'Driver': driver,
        'Team': team,
        'LapTime': pd.Timedelta(seconds=lap_time_s),
        'Sector1Time': pd.Timedelta(seconds=s1),
        'Sector2Time': pd.Timedelta(seconds=s2),
        'Sector3Time': pd.Timedelta(seconds=s3),
        'Compound': compound,
        'TyreLife': float(tyre_life),
        'LapNumber': float(lap_num),
        'IsPersonalBest': True,
        'SpeedI1': speed_i1,
        'SpeedI2': speed_i2,
        'SpeedFL': speed_fl,
        'SpeedST': speed_st,
        'PitInTime': pd.NaT,
        'PitOutTime': pd.NaT,
    })


def _make_mock_session(fastest_laps_by_driver: dict, event_name="Monaco Grand Prix"):
    """Build a mock FastF1 session given {driver_code: pd.Series}."""
    mock_session = MagicMock()
    mock_session.event = {'EventName': event_name}
    mock_session.drivers = list(fastest_laps_by_driver.keys())

    def pick_driver(code):
        if code not in fastest_laps_by_driver:
            mock_laps = MagicMock()
            mock_laps.empty = True
            return mock_laps
        fastest = fastest_laps_by_driver[code]
        # Build a 1-row DataFrame so iterrows() works too
        lap_df = pd.DataFrame([fastest])
        mock_laps = MagicMock()
        mock_laps.empty = False
        mock_laps.pick_fastest.return_value = fastest
        mock_laps.__iter__ = lambda self: iter([fastest])
        mock_laps.iterrows.return_value = iter(lap_df.iterrows())
        return mock_laps

    mock_session.laps.pick_driver.side_effect = pick_driver
    return mock_session


def _make_mock_telemetry(n_points=50, circuit_length_m=5000):
    distances = [i * circuit_length_m / n_points for i in range(n_points)]
    speeds = [150 + 150 * abs(i / n_points - 0.5) for i in range(n_points)]
    return pd.DataFrame({
        'Distance': distances,
        'Speed': speeds,
        'Throttle': [100.0 if i > 10 else 0.0 for i in range(n_points)],
        'Brake': [i <= 10 for i in range(n_points)],
        'nGear': [8 if i > 10 else 4 for i in range(n_points)],
        'DRS': [12 if i > 30 else 0 for i in range(n_points)],
    })


def test_get_session_fastest_laps():
    nor_lap = _make_mock_fastest_lap("NOR", lap_time_s=86.456)
    lec_lap = _make_mock_fastest_lap("LEC", "Ferrari", lap_time_s=86.712,
                                     s1=28.200, s2=29.400, s3=29.112,
                                     speed_i1=218.0, speed_st=312.0)
    mock_session = _make_mock_session({"NOR": nor_lap, "LEC": lec_lap})

    with patch('f1_data.fastf1.get_session', return_value=mock_session):
        import f1_data
        result = f1_data.get_session_fastest_laps(8, 'Q')

    assert len(result) == 2
    # Sorted fastest first
    assert result[0]['driver'] == 'NOR'
    assert result[0]['position'] == 1
    assert result[1]['driver'] == 'LEC'
    assert result[1]['position'] == 2
    assert result[0]['sector1'] == '0:28.123'
    assert result[0]['speed_st'] == 315.2
    assert result[0]['compound'] == 'SOFT'


def test_get_driver_lap_times():
    nor_lap = _make_mock_fastest_lap("NOR")
    mock_session = _make_mock_session({"NOR": nor_lap})

    with patch('f1_data.fastf1.get_session', return_value=mock_session):
        import f1_data
        result = f1_data.get_driver_lap_times(8, 'Q', 'NOR')

    assert result['driver'] == 'NOR'
    assert result['event'] == 'Monaco Grand Prix'
    assert result['session'] == 'Q'
    assert len(result['laps']) == 1
    assert result['laps'][0]['lap_number'] == 12
    assert result['laps'][0]['compound'] == 'SOFT'
    assert result['laps'][0]['speed_st'] == 315.2


def test_get_driver_lap_times_driver_not_found():
    mock_session = _make_mock_session({})

    with patch('f1_data.fastf1.get_session', return_value=mock_session):
        import f1_data
        with pytest.raises(ValueError, match="No data"):
            f1_data.get_driver_lap_times(8, 'Q', 'ZZZ')


def test_get_sector_comparison():
    nor_lap = _make_mock_fastest_lap("NOR", lap_time_s=86.456,
                                     s1=28.123, s2=29.200, s3=29.133,
                                     speed_i2=185.3)
    lec_lap = _make_mock_fastest_lap("LEC", "Ferrari", lap_time_s=86.712,
                                     s1=28.200, s2=29.400, s3=29.112,
                                     speed_i2=180.1)
    mock_session = _make_mock_session({"NOR": nor_lap, "LEC": lec_lap})

    with patch('f1_data.fastf1.get_session', return_value=mock_session):
        import f1_data
        result = f1_data.get_sector_comparison(8, 'Q', 'NOR', 'LEC')

    assert result['driver_a'] == 'NOR'
    assert result['driver_b'] == 'LEC'
    # NOR faster overall: gap should be negative (NOR - LEC < 0)
    assert result['overall_gap_s'] < 0
    # NOR faster in S2: gap_s negative
    assert result['sector2']['gap_s'] < 0
    # Speed I2 delta: NOR 185.3 - LEC 180.1 = positive (NOR faster through that point)
    assert result['sector2']['speed_i2_delta'] > 0


def test_get_lap_telemetry():
    nor_lap = _make_mock_fastest_lap("NOR")
    mock_session = _make_mock_session({"NOR": nor_lap})

    mock_tel = _make_mock_telemetry(n_points=50, circuit_length_m=3300)

    # The fastest lap Series needs get_telemetry().add_distance() to work
    # Since we use a real pd.Series for nor_lap, we need to make get_telemetry
    # work. In practice this is a FastF1 Lap method — we patch it at the module level.
    mock_lap_obj = MagicMock()
    mock_lap_obj.__getitem__.side_effect = lambda k: nor_lap[k]
    mock_lap_obj.get.side_effect = lambda k, d=None: nor_lap.get(k, d)
    mock_lap_obj.get_telemetry.return_value.add_distance.return_value = mock_tel

    def pick_driver_tel(code):
        mock_laps = MagicMock()
        mock_laps.empty = False
        mock_laps.pick_fastest.return_value = mock_lap_obj
        return mock_laps

    mock_session.laps.pick_driver.side_effect = pick_driver_tel

    with patch('f1_data.fastf1.get_session', return_value=mock_session):
        import f1_data
        result = f1_data.get_lap_telemetry(8, 'Q', 'NOR')

    assert result['driver'] == 'NOR'
    assert result['circuit_length_m'] > 0
    assert result['max_speed_kph'] > 0
    # Sampled every 100m — should have ~33 samples for a 3300m circuit
    assert len(result['telemetry']) > 0
    first = result['telemetry'][0]
    assert 'distance_m' in first
    assert 'speed_kph' in first
    assert 'throttle_pct' in first
    assert 'brake' in first
    assert 'gear' in first
    assert 'drs_open' in first


# ─── Telemetry comparison + circuit context tests ───────────


def _make_tel_df(n_points=6, circuit_length_m=500,
                 base_speed=150.0, speed_boost=0.0):
    distances = [i * circuit_length_m / (n_points - 1) for i in range(n_points)]
    return pd.DataFrame({
        'Distance': distances,
        'Speed': [base_speed + speed_boost + i * 10 for i in range(n_points)],
        'Throttle': [50.0 + i * 5 for i in range(n_points)],
        'Brake': [i == 0 for i in range(n_points)],
        'nGear': [4 + min(i, 4) for i in range(n_points)],
        'DRS': [12 if i > 3 else 0 for i in range(n_points)],
    })


def test_get_telemetry_comparison():
    nor_lap_series = _make_mock_fastest_lap("NOR")
    lec_lap_series = _make_mock_fastest_lap("LEC", "Ferrari")

    tel_nor = _make_tel_df(base_speed=150.0, speed_boost=5.0)
    tel_lec = _make_tel_df(base_speed=150.0, speed_boost=0.0)

    mock_lap_nor = MagicMock()
    mock_lap_nor.__getitem__.side_effect = lambda k: nor_lap_series[k]
    mock_lap_nor.get.side_effect = lambda k, d=None: nor_lap_series.get(k, d)
    mock_lap_nor.get_telemetry.return_value.add_distance.return_value = tel_nor

    mock_lap_lec = MagicMock()
    mock_lap_lec.__getitem__.side_effect = lambda k: lec_lap_series[k]
    mock_lap_lec.get.side_effect = lambda k, d=None: lec_lap_series.get(k, d)
    mock_lap_lec.get_telemetry.return_value.add_distance.return_value = tel_lec

    def pick_driver_tel(code):
        mock_laps = MagicMock()
        mock_laps.empty = False
        mock_laps.pick_fastest.return_value = mock_lap_nor if code.upper() == "NOR" else mock_lap_lec
        return mock_laps

    mock_session = MagicMock()
    mock_session.event = {'EventName': 'Monaco Grand Prix'}
    mock_session.laps.pick_driver.side_effect = pick_driver_tel

    with patch('f1_data.fastf1.get_session', return_value=mock_session):
        import f1_data
        result = f1_data.get_telemetry_comparison(8, 'Q', 'NOR', 'LEC')

    assert result['driver_a'] == 'NOR'
    assert result['driver_b'] == 'LEC'
    assert result['circuit_length_m'] == 500
    assert len(result['comparison']) > 0
    first = result['comparison'][0]
    assert first['delta_speed'] == pytest.approx(5.0, abs=0.5)
    assert 'brake_a' in first
    assert 'drs_a' in first
    assert 'gear_a' in first


def test_get_telemetry_comparison_driver_not_found():
    mock_session = MagicMock()
    mock_session.event = {'EventName': 'Monaco Grand Prix'}

    def pick_empty(code):
        m = MagicMock()
        m.empty = True
        return m

    mock_session.laps.pick_driver.side_effect = pick_empty

    with patch('f1_data.fastf1.get_session', return_value=mock_session):
        import f1_data
        with pytest.raises(ValueError, match="No data"):
            f1_data.get_telemetry_comparison(8, 'Q', 'NOR', 'ZZZ')


def test_get_circuit_corners():
    mock_corners_df = pd.DataFrame({
        'Number': [1, 2, 3],
        'Letter': ['', 'A', ''],
        'X': [100.0, 200.0, 300.0],
        'Y': [50.0, 60.0, 70.0],
        'Angle': [45.0, 90.0, 135.0],
        'Distance': [150.5, 800.2, 2200.7],
    })
    mock_circuit_info = MagicMock()
    mock_circuit_info.corners = mock_corners_df

    with patch('f1_data.fastf1.get_circuit_info', return_value=mock_circuit_info):
        import f1_data
        result = f1_data.get_circuit_corners(8)

    assert len(result) == 3
    assert result[0]['number'] == 1
    assert result[0]['distance_m'] == 151
    assert result[0]['label'] is None
    assert result[1]['label'] == 'A'
    assert result[2]['distance_m'] == 2201


def test_get_historical_circuit_performance():
    def _circuit_lookup():
        m = MagicMock()
        m.raise_for_status.return_value = None
        m.json.return_value = {
            "MRData": {"RaceTable": {"Races": [{
                "raceName": "Monaco Grand Prix",
                "Circuit": {"circuitId": "monaco", "circuitName": "Circuit de Monaco"},
                "Results": [],
            }]}}
        }
        return m

    def _quali_resp():
        m = MagicMock()
        m.raise_for_status.return_value = None
        m.json.return_value = {
            "MRData": {"RaceTable": {"Races": [{"QualifyingResults": [{
                "position": "1",
                "Driver": {"driverId": "norris", "givenName": "Lando",
                           "familyName": "Norris", "code": "NOR"},
                "Constructor": {"name": "McLaren"},
                "Q1": "1:10.000", "Q2": "1:09.500", "Q3": "1:09.100",
            }]}]}}
        }
        return m

    def _race_resp():
        m = MagicMock()
        m.raise_for_status.return_value = None
        m.json.return_value = {
            "MRData": {"RaceTable": {"Races": [{"Results": [{
                "position": "1",
                "Driver": {"driverId": "norris", "givenName": "Lando",
                           "familyName": "Norris", "code": "NOR"},
                "Constructor": {"name": "McLaren"},
                "FastestLap": {"rank": "1"},
            }]}]}}
        }
        return m

    with patch('f1_data.requests.get', side_effect=[
        _circuit_lookup(),
        _quali_resp(), _race_resp(),
        _quali_resp(), _race_resp(),
    ]):
        import f1_data
        result = f1_data.get_historical_circuit_performance(8, years=[2024, 2025])

    assert result['circuit_id'] == 'monaco'
    assert result['circuit_name'] == 'Circuit de Monaco'
    assert len(result['history']) == 2
    assert result['history'][0]['year'] == 2024
    assert result['history'][0]['qualifying_top5'][0]['code'] == 'NOR'
    assert result['history'][0]['qualifying_top5'][0]['q3'] == '1:09.100'
    assert result['history'][0]['race_top5'][0]['fastest_lap'] is True
    assert result['history'][1]['year'] == 2025
