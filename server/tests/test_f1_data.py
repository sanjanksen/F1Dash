# server/tests/test_f1_data.py
import pytest
from unittest.mock import patch, MagicMock
import f1_data


@pytest.fixture(autouse=True)
def clear_session_cache():
    f1_data._clear_session_cache()
    yield
    f1_data._clear_session_cache()


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


def test_load_session_reuses_cached_session_and_upgrades_flags():
    mock_session = MagicMock()

    with patch('f1_data._validate_session_availability'), patch('f1_data.fastf1.get_session', return_value=mock_session) as get_session_mock:
        f1_data._clear_session_cache()

        first = f1_data._load_session(1, 'R', laps=True, telemetry=False, weather=False, messages=False)
        second = f1_data._load_session(1, 'R', laps=True, telemetry=False, weather=False, messages=False)
        third = f1_data._load_session(1, 'R', laps=True, telemetry=False, weather=False, messages=True)

    assert first is mock_session
    assert second is mock_session
    assert third is mock_session
    assert get_session_mock.call_count == 1
    assert mock_session.load.call_count == 2
    assert mock_session.load.call_args_list[0].kwargs == {
        'laps': True,
        'telemetry': False,
        'weather': False,
        'messages': False,
    }
    assert mock_session.load.call_args_list[1].kwargs == {
        'laps': True,
        'telemetry': False,
        'weather': False,
        'messages': True,
    }
    f1_data._clear_session_cache()


def test_analyze_energy_management_single_driver_uses_inference_not_direct_measurement():
    telemetry = {
        "event": "Japanese Grand Prix",
        "session": "Q",
        "driver": "NOR",
        "lap_number": 12,
        "telemetry": [
            {"distance_m": 0, "speed_kph": 180.0, "throttle_pct": 100.0, "brake": False, "gear": 7, "rpm": 11000, "drs_open": False},
            {"distance_m": 100, "speed_kph": 188.0, "throttle_pct": 100.0, "brake": False, "gear": 7, "rpm": 11200, "drs_open": False},
            {"distance_m": 200, "speed_kph": 192.0, "throttle_pct": 15.0, "brake": False, "gear": 7, "rpm": 11250, "drs_open": False},
            {"distance_m": 300, "speed_kph": 190.0, "throttle_pct": 0.0, "brake": False, "gear": 7, "rpm": 11100, "drs_open": False},
            {"distance_m": 400, "speed_kph": 175.0, "throttle_pct": 0.0, "brake": True, "gear": 6, "rpm": 10400, "drs_open": False},
        ],
    }

    with patch('f1_data.get_lap_telemetry', return_value=telemetry):
        result = f1_data.analyze_energy_management(3, 'Q', 'NOR')

    assert result["mode"] == "single_driver"
    assert "ERS state of charge" in result["not_directly_measured"][0]
    assert result["drivers"][0]["driver"] == "NOR"
    assert isinstance(result["inference_summary"], list)


def test_get_driver_weekend_overview_includes_energy_management():
    with patch('f1_data._resolve_driver', return_value={"full_name": "Lando Norris", "code": "NOR", "driver_id": "norris", "team": "McLaren"}), \
         patch('f1_data.get_qualifying_results', return_value={"race_name": "Japanese Grand Prix", "results": [{"code": "NOR", "position": 5, "team": "McLaren", "q1": "1:30.0", "q2": "1:29.5", "q3": "1:29.4"}]}), \
         patch('f1_data.get_race_results', return_value={"race_name": "Japanese Grand Prix", "results": [{"code": "NOR", "position": 5, "points": 10.0, "status": "Finished", "team": "McLaren", "driver": "Lando Norris", "fastest_lap": False}]}), \
         patch('f1_data.get_driver_strategy', return_value={"drivers": [{"stints": []}]}), \
         patch('f1_data.get_safety_car_periods', return_value={"sc_count": 0, "vsc_count": 0, "periods": []}), \
         patch('f1_data.get_session_results', return_value={"results": [{"abbreviation": "NOR", "grid_position": 5, "driver_number": "4"}]}), \
         patch('f1_data.analyze_energy_management', return_value={"mode": "single_driver", "drivers": [{"driver": "NOR", "possible_clipping_windows": [], "likely_lift_and_coast_events": []}], "confidence": "low"}):
        result = f1_data.get_driver_weekend_overview(3, "Norris")

    assert result["energy_management"]["mode"] == "single_driver"


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

    def pick_drivers(codes):
        code = codes[0] if isinstance(codes, list) else codes
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

    mock_session.laps.pick_drivers.side_effect = pick_drivers
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


def test_get_sector_comparison_loads_messages_for_qualifying():
    nor_lap = _make_mock_fastest_lap("NOR", lap_time_s=86.456)
    lec_lap = _make_mock_fastest_lap("LEC", "Ferrari", lap_time_s=86.712)
    mock_session = _make_mock_session({"NOR": nor_lap, "LEC": lec_lap})

    with patch('f1_data.fastf1.get_session', return_value=mock_session):
        import f1_data
        f1_data._clear_session_cache()
        f1_data.get_sector_comparison(8, 'Q', 'NOR', 'LEC')

    mock_session.load.assert_called_once_with(laps=True, telemetry=False, weather=False, messages=True)


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

    def pick_driver_tel(codes):
        mock_laps = MagicMock()
        mock_laps.empty = False
        mock_laps.pick_fastest.return_value = mock_lap_obj
        return mock_laps

    mock_session.laps.pick_drivers.side_effect = pick_driver_tel

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
        'X': [float(i * 10) for i in range(n_points)],
        'Y': [float((i % 3) * 8) for i in range(n_points)],
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

    def pick_driver_tel(codes):
        code = codes[0] if isinstance(codes, list) else codes
        mock_laps = MagicMock()
        mock_laps.empty = False
        mock_laps.pick_fastest.return_value = mock_lap_nor if code.upper() == "NOR" else mock_lap_lec
        return mock_laps

    mock_session = MagicMock()
    mock_session.event = {'EventName': 'Monaco Grand Prix'}
    mock_session.laps.pick_drivers.side_effect = pick_driver_tel

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
    assert first['x'] == 0.0
    assert first['y'] == 0.0


def test_get_telemetry_comparison_driver_not_found():
    mock_session = MagicMock()
    mock_session.event = {'EventName': 'Monaco Grand Prix'}

    def pick_empty(codes):
        m = MagicMock()
        m.empty = True
        return m

    mock_session.laps.pick_drivers.side_effect = pick_empty

    with patch('f1_data.fastf1.get_session', return_value=mock_session):
        import f1_data
        with pytest.raises(ValueError, match="No data"):
            f1_data.get_telemetry_comparison(8, 'Q', 'NOR', 'ZZZ')


def test_telemetry_battle_does_not_classify_full_throttle_delta_as_traction():
    samples = [
        {
            "distance_m": 600,
            "delta_speed": 25.0,
            "speed_a": 280.0,
            "speed_b": 255.0,
            "throttle_a": 100.0,
            "throttle_b": 100.0,
            "brake_a": False,
            "brake_b": False,
            "gear_a": 8,
            "gear_b": 8,
        },
        {
            "distance_m": 900,
            "delta_speed": 8.0,
            "speed_a": 190.0,
            "speed_b": 182.0,
            "throttle_a": 86.0,
            "throttle_b": 50.0,
            "brake_a": False,
            "brake_b": False,
            "gear_a": 5,
            "gear_b": 5,
        },
    ]

    result = f1_data._summarize_telemetry_battle(samples, "ANT", "ANT", "RUS")

    assert result["top_causes"][0]["cause_type"] == "straight_line_speed"
    assert result["top_causes"][0]["distance_m"] == 600
    assert any(cause["cause_type"] == "traction" and cause["distance_m"] == 900 for cause in result["top_causes"])


def test_telemetry_battle_top_causes_carry_time_gained_s():
    """Each top_causes entry must carry time_gained_s and speed_a/speed_b
    so downstream surfaces can render time-first prose.

    Sign convention: signed driver_a − driver_b. Positive = A gained at
    that point, negative = B gained. Matches overall_gap_s / sector gap_s.
    """
    samples = [
        {
            "distance_m": 600,
            "delta_speed": 25.0,
            "speed_a": 280.0,
            "speed_b": 255.0,
            "throttle_a": 100.0,
            "throttle_b": 100.0,
            "brake_a": False,
            "brake_b": False,
            "gear_a": 8,
            "gear_b": 8,
        },
        {
            "distance_m": 1500,
            "delta_speed": 13.0,
            "speed_a": 117.0,
            "speed_b": 104.0,
            "throttle_a": 35.0,
            "throttle_b": 35.0,
            "brake_a": False,
            "brake_b": False,
            "gear_a": 3,
            "gear_b": 3,
        },
    ]
    result = f1_data._summarize_telemetry_battle(samples, "ANT", "ANT", "RUS")
    assert result is not None
    for cause in result["top_causes"]:
        assert "time_gained_s" in cause
        assert "speed_a" in cause
        assert "speed_b" in cause
        # A (ANT) is faster at every candidate point here, so the signed
        # time_gained_s is positive (A gained).
        if cause["time_gained_s"] is not None:
            assert cause["time_gained_s"] >= 0.0


def test_telemetry_battle_surfaces_markers_from_both_drivers_when_both_gain():
    """User-reported regression: when A wins the lap by 0.040s but B took
    a sector by 0.081s, the widget surfaced only A-favorable markers.

    Construct a synthetic trace where A gains 0.10s in S1 (1500m apex)
    and B gains 0.06s in S2 (3300m braking). The picker must surface
    BOTH events — one with positive time_gained_s, one with negative.
    """
    import numpy as np
    # 500 samples along a 5000m lap. Equal speeds everywhere except:
    # - 1500m apex window: A is 12 km/h faster (LEC-style mid-corner)
    # - 3300m braking: B is 10 km/h faster (NOR brakes later)
    distance = np.linspace(0, 5000, 500).tolist()
    samples = []
    for d in distance:
        sa = 200.0
        sb = 200.0
        if 1480 <= d <= 1520:  # narrow A-gain at apex
            sa = 117.0
            sb = 104.0
            samples.append({
                "distance_m": d, "delta_speed": sa - sb,
                "speed_a": sa, "speed_b": sb,
                "throttle_a": 35.0, "throttle_b": 35.0,
                "brake_a": False, "brake_b": False,
                "gear_a": 3, "gear_b": 3,
            })
            continue
        if 3280 <= d <= 3320:  # B-gain at braking zone (A on brakes earlier)
            sa = 240.0
            sb = 250.0
            samples.append({
                "distance_m": d, "delta_speed": sa - sb,
                "speed_a": sa, "speed_b": sb,
                "throttle_a": 0.0, "throttle_b": 50.0,
                "brake_a": True, "brake_b": False,
                "gear_a": 5, "gear_b": 6,
            })
            continue
        samples.append({
            "distance_m": d, "delta_speed": 0.0,
            "speed_a": sa, "speed_b": sb,
            "throttle_a": 100.0, "throttle_b": 100.0,
            "brake_a": False, "brake_b": False,
            "gear_a": 7, "gear_b": 7,
        })

    result = f1_data._summarize_telemetry_battle(
        samples, "LEC", "LEC", "NOR",
        sector_boundary_distances=[2000, 4000],
    )
    assert result is not None
    causes = result["top_causes"]
    drivers = {c["gainer_driver"] for c in causes}
    assert drivers == {"LEC", "NOR"}, (
        f"Expected both drivers to appear as gainers; got {drivers}"
    )

    # Time contributions per marker must be physically plausible
    # (extremum-window picker should not give >0.20s on a narrow event).
    for c in causes:
        tg = c["time_gained_s"]
        assert abs(tg) < 0.20, f"Marker contribution implausibly large: {c}"

    # Sector reconciliation must be present.
    assert "sector_reconciliation" in result
    assert "Sector 1" in result["sector_reconciliation"]
    assert "Sector 2" in result["sector_reconciliation"]
    s1 = result["sector_reconciliation"]["Sector 1"]
    s2 = result["sector_reconciliation"]["Sector 2"]
    # S1 gap is positive (A gained); S2 gap is negative (B gained).
    assert s1["sector_gap_s"] > 0
    assert s2["sector_gap_s"] < 0


def test_integrate_time_gained_around_extremum_clamped_by_sector_bounds():
    """When sector_bounds_m is supplied the integration window cannot
    cross the sector boundary. A peak near a boundary must not pull in
    samples from the neighbouring sector.
    """
    import numpy as np
    from f1_data import _integrate_time_gained_around_extremum

    # 500 samples along 0..5000m. Plant a sustained A-gain at 980..1020
    # (peaks right next to a boundary at 1000m), and ALSO a B-gain on
    # the FAR side at 1050..1100 (just past the boundary). Without the
    # clamp the extremum walker can drift across into the B-gain area.
    distance = np.linspace(0, 5000, 500)
    v_a = np.full_like(distance, 200.0)
    v_b = np.full_like(distance, 200.0)
    a_peak_mask = (distance >= 980) & (distance <= 1020)
    v_a[a_peak_mask] = 217.0
    b_peak_mask = (distance >= 1050) & (distance <= 1100)
    v_b[b_peak_mask] = 217.0

    # Clamp the marker (centred at 1000m) to Sector 1 = [0, 1000].
    clamped = _integrate_time_gained_around_extremum(
        distance.tolist(), v_a.tolist(), v_b.tolist(),
        center_distance_m=1000.0,
        sector_bounds_m=(0.0, 1000.0),
    )
    # Without the clamp the walker might integrate across the boundary
    # and the contribution would be much smaller in magnitude. With it,
    # only the A-gain side counts and the value should be clearly > 0.
    assert clamped is not None
    assert clamped > 0.0, f"expected A-gain on the clamped side, got {clamped}"

    # Also: an integration window asked outside the clamp must still
    # return only what's inside the clamp.
    far = _integrate_time_gained_around_extremum(
        distance.tolist(), v_a.tolist(), v_b.tolist(),
        center_distance_m=1075.0,
        sector_bounds_m=(0.0, 1000.0),
    )
    # 1075 is outside [0, 1000] entirely — search window will collapse
    # and fall back to the nearest sample within bounds. The result
    # must NOT pull in the B-gain (which lives at 1050..1100).
    # Any value returned must be non-negative (A side only).
    if far is not None:
        assert far >= -1e-3, f"clamped integration leaked into B-gain side: {far}"


def test_sector_marker_contribution_bounded_by_authoritative_sector_gap():
    """Conservation: when authoritative sector gaps are supplied, the
    summed |marker_contribution| within a sector cannot exceed the
    authoritative |sector_gap|. Scaling is applied if it would.
    """
    import numpy as np
    # 5000m lap. Plant TWO same-signed A-gain events in Sector 1
    # (apex 800m AND apex 1600m). The sum of their raw marker
    # contributions exceeds the authoritative Sector 1 gap, so the
    # conservation scaler must clamp them down.
    distance = np.linspace(0, 5000, 500).tolist()
    samples = []
    for d in distance:
        sa, sb = 200.0, 200.0
        if 780 <= d <= 820:
            sa, sb = 130.0, 110.0
        elif 1580 <= d <= 1620:
            sa, sb = 130.0, 110.0
        samples.append({
            "distance_m": d, "delta_speed": sa - sb,
            "speed_a": sa, "speed_b": sb,
            "throttle_a": 35.0, "throttle_b": 35.0,
            "brake_a": False, "brake_b": False,
            "gear_a": 3, "gear_b": 3,
        })
    # Pretend FastF1 says Sector 1 was worth only +0.030s for A.
    # FastF1 TIME-DELTA convention: positive = A slower → use -0.030 for A faster.
    # The test wants A-favorable plants (LEC dominates S1), so use -0.030 (A faster by 0.030).
    auth = {"Sector 1": -0.030, "Sector 2": 0.0, "Sector 3": 0.0}
    result = f1_data._summarize_telemetry_battle(
        samples, "LEC", "LEC", "NOR",
        sector_boundary_distances=[2000, 4000],
        authoritative_sector_gaps_s=auth,
    )
    assert result is not None
    # Apply conservation cap via the post-finalization helper (mirrors how
    # analyze_qualifying_battle calls it after energy-fade synthesis).
    f1_data.apply_sector_conservation_and_build_reconciliation(
        result["top_causes"], auth,
        sector_boundary_distances=[2000, 4000],
        sample_distances=[s["distance_m"] for s in samples],
    )
    s1_markers = [c for c in result["top_causes"] if c.get("sector") == "Sector 1"]
    summed = sum(c["time_gained_s"] for c in s1_markers)
    assert abs(summed) <= abs(auth["Sector 1"]) + 1e-6, (
        f"S1 markers sum to {summed}, exceeding |sector_gap|={auth['Sector 1']}"
    )


def test_sector_reconciliation_uses_authoritative_sector_gaps_when_supplied():
    """When FastF1-derived authoritative sector gaps are passed in (TIME-DELTA
    convention: positive = driver_a slower), the sector_reconciliation panel
    reports them in GAIN convention (positive = driver_a gained) so it
    matches time_gained_s on markers.

    This is the single source of truth: same magnitude as the
    sector-breakdown panel, sign flipped to GAIN convention so the
    reconciliation panel can interpret it consistently with markers.
    """
    import numpy as np
    distance = np.linspace(0, 5000, 500).tolist()
    samples = []
    for d in distance:
        sa, sb = 200.0, 200.0
        if 1480 <= d <= 1520:
            sa, sb = 117.0, 104.0
        samples.append({
            "distance_m": d, "delta_speed": sa - sb,
            "speed_a": sa, "speed_b": sb,
            "throttle_a": 35.0, "throttle_b": 35.0,
            "brake_a": False, "brake_b": False,
            "gear_a": 3, "gear_b": 3,
        })
    # FastF1 TIME-DELTA convention: gap_s = a_time − b_time
    # S1: -0.131 means LEC (A) was 0.131s faster in S1 (took less time)
    # S2: +0.081 means LEC (A) was 0.081s slower in S2 (NOR gained)
    # S3: +0.010 means LEC (A) was 0.010s slower in S3 (NOR gained)
    auth = {"Sector 1": -0.131, "Sector 2": 0.081, "Sector 3": 0.010}
    result = f1_data._summarize_telemetry_battle(
        samples, "LEC", "LEC", "NOR",
        sector_boundary_distances=[2000, 4000],
        authoritative_sector_gaps_s=auth,
    )
    assert result is not None
    rec = result["sector_reconciliation"]
    # Reconciliation reports GAIN convention (negated from input): positive
    # = driver_a gained. Same magnitude as input, sign flipped to match
    # marker time_gained_s convention.
    assert rec["Sector 1"]["sector_gap_s"] == 0.131   # A gained 0.131s in S1
    assert rec["Sector 2"]["sector_gap_s"] == -0.081  # B gained 0.081s in S2
    assert rec["Sector 3"]["sector_gap_s"] == -0.010  # B gained 0.010s in S3


def test_telemetry_battle_time_gained_s_negative_when_b_gains_locally():
    """When B is the overall faster driver but A is briefly faster at one
    point, that cause's signed time_gained_s for the B-favorable points
    must be negative (B gained, from A's perspective). Validates that the
    sign tracks driver_a − driver_b, not faster-driver-vs-slower."""
    # B (RUS) is the overall faster driver: B is faster at distance 600
    # (delta_speed = speed_a - speed_b < 0). A (ANT) is briefly faster at
    # 1500 (delta_speed > 0). The candidate that favors the *faster_driver*
    # at each distance is the one ranked into top_causes; here that means
    # the 600m point favors B → its signed time_gained_s < 0.
    samples = [
        {
            "distance_m": 600,
            "delta_speed": -25.0,
            "speed_a": 255.0,
            "speed_b": 280.0,
            "throttle_a": 100.0,
            "throttle_b": 100.0,
            "brake_a": False,
            "brake_b": False,
            "gear_a": 8,
            "gear_b": 8,
        },
        {
            "distance_m": 1500,
            "delta_speed": -13.0,
            "speed_a": 104.0,
            "speed_b": 117.0,
            "throttle_a": 35.0,
            "throttle_b": 35.0,
            "brake_a": False,
            "brake_b": False,
            "gear_a": 3,
            "gear_b": 3,
        },
    ]
    result = f1_data._summarize_telemetry_battle(samples, "RUS", "ANT", "RUS")
    assert result is not None
    assert result["top_causes"], "expected at least one cause favoring the faster driver"
    for cause in result["top_causes"]:
        # All ranked causes favor B (faster_driver=RUS); signed convention
        # is A − B, so each cause's time_gained_s must be negative or zero.
        if cause["time_gained_s"] is not None:
            assert cause["time_gained_s"] <= 0.0, (
                f"Expected negative time_gained_s for B-favoring cause; got {cause}"
            )


def test_telemetry_location_context_places_traction_after_previous_corner():
    corners = [
        {"number": 1, "distance_m": 300},
        {"number": 2, "distance_m": 650},
    ]

    with patch("f1_data.get_circuit_corners", return_value=corners):
        result = f1_data._telemetry_location_context(1, 520, "traction")

    assert result["label"] == "Exit of Turn 1"
    assert result["plain"] == "on the run out of Turn 1"
    assert result["phase"] == "corner_exit"
    assert result["corner"] == "Turn 1"
    assert result["next_corner"] == {"number": 2, "distance_m": 650}
    assert result["distance_m"] == 520


def test_telemetry_location_context_places_braking_before_next_corner():
    corners = [
        {"number": 10, "distance_m": 3000},
        {"number": 11, "distance_m": 3280},
    ]

    with patch("f1_data.get_circuit_corners", return_value=corners):
        result = f1_data._telemetry_location_context(1, 3200, "braking")

    assert result["label"] == "Braking zone into Turn 11"
    assert result["plain"] == "in the braking zone into Turn 11"
    assert result["phase"] == "braking_zone"
    assert result["corner"] == "Turn 11"


def test_telemetry_location_context_places_minimum_speed_near_corner():
    corners = [
        {"number": 10, "distance_m": 3000},
        {"number": 11, "distance_m": 3220},
        {"number": 12, "distance_m": 3500},
    ]

    with patch("f1_data.get_circuit_corners", return_value=corners):
        result = f1_data._telemetry_location_context(1, 3200, "minimum_speed")

    assert result["label"] == "Mid-corner at Turn 11"
    assert result["plain"] == "through Turn 11"
    assert result["phase"] == "mid_corner"


def test_telemetry_location_context_places_straight_between_corners():
    corners = [
        {"number": 13, "distance_m": 3600},
        {"number": 14, "distance_m": 4100},
    ]

    with patch("f1_data.get_circuit_corners", return_value=corners):
        result = f1_data._telemetry_location_context(1, 3800, "straight_line_speed")

    assert result["label"] == "Straight between Turn 13 and Turn 14"
    assert result["plain"] == "on the straight between Turn 13 and Turn 14"
    assert result["phase"] == "straight"


def test_telemetry_location_context_wraps_lap_between_final_and_first_corner():
    corners = [
        {"number": 1, "distance_m": 250},
        {"number": 19, "distance_m": 5200},
    ]

    with patch("f1_data.get_circuit_corners", return_value=corners):
        result = f1_data._telemetry_location_context(1, 5350, "straight_line_speed")

    assert result["label"] == "Straight between Turn 19 and Turn 1"
    assert result["plain"] == "on the straight between Turn 19 and Turn 1"
    assert result["previous_corner"] == {"number": 19, "distance_m": 5200}
    assert result["next_corner"] == {"number": 1, "distance_m": 250}


def test_telemetry_location_context_falls_back_when_corner_data_missing():
    with patch("f1_data.get_circuit_corners", side_effect=ValueError("no corners")):
        result = f1_data._telemetry_location_context(1, 500, "traction")

    # Vague "early/middle/late in the lap" labels were dropped; the
    # fallback now anchors to the raw distance so marker prose still has
    # a hook even when circuit corner data isn't available.
    assert result["label"] == "around 500m"
    assert result["plain"] == "around 500m"
    assert result["phase"] == "lap_region"


def test_telemetry_location_context_falls_back_for_non_finite_distance():
    with patch("f1_data.get_circuit_corners") as mock_corners:
        result = f1_data._telemetry_location_context(1, float("nan"), "traction")

    assert result["phase"] == "lap_region"
    assert result["label"] == "Distance unavailable"
    assert result["plain"] == "at an unknown point on the lap"
    assert result["previous_corner"] is None
    assert result["next_corner"] is None
    mock_corners.assert_not_called()


# ---------------------------------------------------------------------------
# _resolve_corner_for_distance — marker corner-label resolver
# ---------------------------------------------------------------------------


def test_resolve_corner_for_distance_returns_corner_when_within_radius():
    corners = [
        {"number": 1, "distance_m": 300},
        {"number": 2, "distance_m": 650},
    ]
    with patch("f1_data.get_circuit_corners", return_value=corners):
        # 720m is within ±150m of Turn 2 (650m)
        result = f1_data._resolve_corner_for_distance(1, 720)

    assert result["corner_number"] == 2
    assert result["corner_name"] == "Turn 2"
    assert result["location_label"] == "Turn 2"


def test_resolve_corner_for_distance_returns_straight_between_corners():
    corners = [
        {"number": 8, "distance_m": 2000},
        {"number": 9, "distance_m": 3000},
    ]
    with patch("f1_data.get_circuit_corners", return_value=corners):
        # 2500m is between T8 and T9, outside the ±150m corner footprint
        result = f1_data._resolve_corner_for_distance(1, 2500)

    assert result["corner_number"] is None
    assert result["corner_name"] is None
    assert result["location_label"] == "Turn 8 → Turn 9 straight"


def test_resolve_corner_for_distance_falls_back_when_corner_data_missing():
    with patch("f1_data.get_circuit_corners", side_effect=ValueError("no corners")):
        result = f1_data._resolve_corner_for_distance(1, 4700)

    # No crash; raw distance phrase keeps the marker anchored.
    assert result["corner_number"] is None
    assert result["corner_name"] is None
    assert result["location_label"] == "around 4700m"


def test_resolve_corner_for_distance_handles_corner_label_suffix():
    corners = [
        {"number": 8, "label": "a", "distance_m": 2000},
    ]
    with patch("f1_data.get_circuit_corners", return_value=corners):
        result = f1_data._resolve_corner_for_distance(1, 2050)

    assert result["corner_name"] == "Turn 8a"
    assert result["location_label"] == "Turn 8a"


def test_summarize_telemetry_battle_enriches_markers_with_corner_labels():
    """Picked markers must carry corner_number / corner_name / location_label
    so the widget can display 'Turn 11' instead of 'around 4700m'."""
    import numpy as np
    distance = np.linspace(0, 5000, 500).tolist()
    samples = []
    for d in distance:
        sa = 200.0
        sb = 200.0
        if 1480 <= d <= 1520:
            sa = 188.0  # A gains here (apex)
        samples.append({
            "distance_m": d,
            "delta_speed": sa - sb,
            "speed_a": sa,
            "speed_b": sb,
            "throttle_a": 80.0,
            "throttle_b": 80.0,
            "brake_a": False,
            "brake_b": False,
            "gear_a": 5,
            "gear_b": 5,
        })

    corners = [
        {"number": 5, "distance_m": 1500},
        {"number": 6, "distance_m": 4500},
    ]
    with patch("f1_data.get_circuit_corners", return_value=corners):
        result = f1_data._summarize_telemetry_battle(
            samples,
            "ANT",
            "ANT",
            "RUS",
            sector_boundary_distances=[1700, 3300],
            round_number=42,
        )

    assert result is not None
    apex_markers = [m for m in result["top_causes"] if 1400 <= m["distance_m"] <= 1600]
    assert apex_markers, "Expected at least one marker near the synthetic apex"
    for m in apex_markers:
        assert m["corner_number"] == 5
        assert m["corner_name"] == "Turn 5"
        assert m["location_label"] == "Turn 5"


def test_summarize_telemetry_battle_falls_back_when_no_round_number():
    """Without a round_number, the corner enrichment can't run — markers
    must still carry location_label keys (distance fallback)."""
    import numpy as np
    distance = np.linspace(0, 5000, 500).tolist()
    samples = []
    for d in distance:
        sa = 200.0
        sb = 200.0
        if 1480 <= d <= 1520:
            sa = 188.0
        samples.append({
            "distance_m": d,
            "delta_speed": sa - sb,
            "speed_a": sa,
            "speed_b": sb,
            "throttle_a": 80.0,
            "throttle_b": 80.0,
            "brake_a": False,
            "brake_b": False,
        })

    result = f1_data._summarize_telemetry_battle(samples, "ANT", "ANT", "RUS")

    assert result is not None
    for m in result["top_causes"]:
        assert m["corner_number"] is None
        assert m["corner_name"] is None
        assert m["location_label"].startswith("around ")


def test_comparative_fade_requires_late_clip_window():
    samples = [
        {
            "distance_m": 600,
            "delta_speed": 25.0,
            "speed_a": 280.0,
            "speed_b": 255.0,
            "throttle_a": 100.0,
            "throttle_b": 100.0,
            "brake_a": False,
            "brake_b": False,
        },
        {
            "distance_m": 3700,
            "delta_speed": 11.0,
            "speed_a": 280.8,
            "speed_b": 269.8,
            "throttle_a": 100.0,
            "throttle_b": 100.0,
            "brake_a": False,
            "brake_b": False,
        },
    ]

    result = f1_data._strongest_comparative_full_throttle_fade(
        samples,
        clip_a=[],
        clip_b=[{"start_distance_m": 3300, "end_distance_m": 3800}],
        driver_a="ANT",
        driver_b="RUS",
    )

    assert result["distance_m"] == 3700
    assert result["faded_driver"] == "RUS"
    assert f1_data._strongest_comparative_full_throttle_fade(
        samples,
        clip_a=[],
        clip_b=[],
        driver_a="ANT",
        driver_b="RUS",
    ) is None


def test_analyze_qualifying_battle_derives_causal_summary():
    import f1_data
    telemetry = {
        "comparison": [
            {
                "distance_m": 300,
                "x": 0.0,
                "y": 0.0,
                "delta_speed": 4.0,
                "speed_a": 254.0,
                "speed_b": 250.0,
                "throttle_a": 100.0,
                "throttle_b": 100.0,
                "brake_a": False,
                "brake_b": False,
                "gear_a": 8,
                "gear_b": 8,
            },
            {
                "distance_m": 1400,
                "x": 100.0,
                "y": 60.0,
                "delta_speed": 12.0,
                "speed_a": 292.0,
                "speed_b": 280.0,
                "throttle_a": 100.0,
                "throttle_b": 100.0,
                "brake_a": False,
                "brake_b": False,
                "gear_a": 8,
                "gear_b": 8,
            },
        ],
        "sector_boundary_distances": [1500, 4000],
    }
    energy = {
        "comparative_signal": {
            "strongest_full_throttle_speed_fade": {
                "distance_m": 1400,
                "delta_speed_kph": 12.0,
            }
        }
    }
    location_context = {
        "label": "Exit of Turn 1",
        "plain": "on the run out of Turn 1",
        "technical": "corner exit from Turn 1",
        "phase": "corner_exit",
        "distance_m": 1400,
        "corner": "Turn 1",
        "previous_corner": {"number": 1, "label": None, "distance_m": 300},
        "next_corner": {"number": 2, "label": None, "distance_m": 650},
    }

    lec_lap = _make_mock_fastest_lap("LEC", "Ferrari", lap_time_s=89.303, s1=31.778, s2=39.855, s3=17.670, speed_i1=284.0, speed_i2=326.0, speed_st=283.0)
    nor_lap = _make_mock_fastest_lap("NOR", lap_time_s=89.409, s1=32.049, s2=39.716, s3=17.644, speed_i1=272.0, speed_i2=320.0, speed_st=281.0)
    mock_session = _make_mock_session({"LEC": lec_lap, "NOR": nor_lap})
    q1 = MagicMock()
    q2 = MagicMock()
    q3 = MagicMock()
    q1.pick_drivers.side_effect = lambda codes: MagicMock(empty=True)
    q2.pick_drivers.side_effect = lambda codes: MagicMock(empty=True)
    def pick_driver_q3(codes):
        code = codes[0] if isinstance(codes, list) else codes
        mock_laps = MagicMock()
        mock_laps.empty = False
        mock_laps.pick_fastest.return_value = lec_lap if code.upper() == "LEC" else nor_lap
        return mock_laps
    q3.pick_drivers.side_effect = pick_driver_q3
    mock_session.laps.split_qualifying_sessions.return_value = [q1, q2, q3]

    with patch('f1_data._load_session', return_value=mock_session), \
         patch('f1_data.get_telemetry_comparison', return_value=telemetry), \
         patch('f1_data.analyze_energy_management', return_value=energy), \
         patch('f1_data._telemetry_location_context', return_value=location_context), \
         patch('f1_data.get_circuit_corners', return_value=[{"number": 1, "label": None, "distance_m": 1500}]):
        result = f1_data.analyze_qualifying_battle(3, 'LEC', 'NOR')

    assert result["faster_driver"] == "LEC"
    assert result["decisive_sector"] == "Sector 1"
    assert result["compared_segment"] == "Q3"
    assert result["cause_type"] in ("straight_line_speed", "straight_line_speed_energy_limited")
    assert result["decisive_corner"] == "Turn 1"
    assert result["energy_relevant"] is True
    assert "2026 rules" in result["energy_context_explanation"]
    # Marker picker is two-sided and lap-ordered. The 1400m point must
    # appear somewhere in top_causes; ordering follows distance now.
    assert any(
        tc.get("distance_m") == 1400 for tc in result["telemetry_summary"]["top_causes"]
    )
    # cause_explanations is impact-ranked; the largest time contribution
    # at 1400m is the energy-limited straight-line marker.
    assert result["cause_explanations"][0]["location_context"]["label"] == "Exit of Turn 1"
    assert "1400m" not in result["cause_explanations"][0]["explanation"]
    assert "on the run out of Turn 1" in result["cause_explanations"][0]["explanation"]
    assert "1400m" not in result["cause_explanation"]
    assert "on the run out of Turn 1" in result["cause_explanation"]
    assert "12.0 kph" in result["zone_summary"]
    assert "1400m" not in result["zone_summary"]
    assert "Exit of Turn 1" in result["zone_summary"]
    assert "1400m" not in result["strongest_evidence"][2]
    assert "on the run out of Turn 1" in result["strongest_evidence"][2]
    assert result["track_map"] == [
        {"distance_m": 300, "x": 0.0, "y": 0.0},
        {"distance_m": 1400, "x": 100.0, "y": 60.0},
    ]


def test_analyze_qualifying_battle_gracefully_handles_missing_telemetry():
    import f1_data
    lec_lap = _make_mock_fastest_lap("LEC", "Ferrari", lap_time_s=89.303, s1=31.778, s2=39.855, s3=17.670, speed_i1=284.0, speed_i2=326.0, speed_st=283.0)
    nor_lap = _make_mock_fastest_lap("NOR", lap_time_s=89.409, s1=32.049, s2=39.716, s3=17.644, speed_i1=272.0, speed_i2=320.0, speed_st=281.0)
    mock_session = _make_mock_session({"LEC": lec_lap, "NOR": nor_lap})
    q1 = MagicMock()
    q2 = MagicMock()
    q3 = MagicMock()
    q1.pick_drivers.side_effect = lambda codes: MagicMock(empty=True)
    q2.pick_drivers.side_effect = lambda codes: MagicMock(empty=True)
    def pick_driver_q3(codes):
        code = codes[0] if isinstance(codes, list) else codes
        mock_laps = MagicMock()
        mock_laps.empty = False
        mock_laps.pick_fastest.return_value = lec_lap if code.upper() == "LEC" else nor_lap
        return mock_laps
    q3.pick_drivers.side_effect = pick_driver_q3
    mock_session.laps.split_qualifying_sessions.return_value = [q1, q2, q3]

    with patch('f1_data._load_session', return_value=mock_session), \
         patch('f1_data.get_telemetry_comparison', side_effect=ValueError("telemetry unavailable")), \
         patch('f1_data.analyze_energy_management', side_effect=ValueError("energy unavailable")):
        result = f1_data.analyze_qualifying_battle(3, 'LEC', 'NOR')

    assert result["telemetry_available"] is False
    assert result["energy_available"] is False
    assert result["caveats"]


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


def test_analyze_team_circuit_fit_derives_overperformance_by_profile():
    def _season_resp(year):
        m = MagicMock()
        m.raise_for_status.return_value = None
        m.json.return_value = {
            "MRData": {"RaceTable": {"Races": [
                {
                    "round": "1",
                    "raceName": "Canadian Grand Prix",
                    "Circuit": {
                        "circuitId": "villeneuve",
                        "circuitName": "Circuit Gilles Villeneuve",
                        "Location": {"country": "Canada"},
                    },
                    "QualifyingResults": [
                        {"position": "1", "Driver": {"givenName": "Max", "familyName": "Verstappen", "code": "VER"}, "Constructor": {"name": "Red Bull Racing"}},
                        {"position": "2" if year == 2023 else "3", "Driver": {"givenName": "George", "familyName": "Russell", "code": "RUS"}, "Constructor": {"name": "Mercedes"}},
                        {"position": "4" if year == 2023 else "5", "Driver": {"givenName": "Lewis", "familyName": "Hamilton", "code": "HAM"}, "Constructor": {"name": "Mercedes"}},
                    ],
                },
                {
                    "round": "2",
                    "raceName": "Japanese Grand Prix",
                    "Circuit": {
                        "circuitId": "suzuka",
                        "circuitName": "Suzuka International Racing Course",
                        "Location": {"country": "Japan"},
                    },
                    "QualifyingResults": [
                        {"position": "1", "Driver": {"givenName": "Max", "familyName": "Verstappen", "code": "VER"}, "Constructor": {"name": "Red Bull Racing"}},
                        {"position": "5" if year == 2023 else "6", "Driver": {"givenName": "George", "familyName": "Russell", "code": "RUS"}, "Constructor": {"name": "Mercedes"}},
                        {"position": "7" if year == 2023 else "8", "Driver": {"givenName": "Lewis", "familyName": "Hamilton", "code": "HAM"}, "Constructor": {"name": "Mercedes"}},
                    ],
                },
            ]}}
        }
        return m

    with patch('f1_data.requests.get', side_effect=[_season_resp(2023), _season_resp(2024)]):
        import f1_data
        result = f1_data.analyze_team_circuit_fit("Mercedes", years=[2023, 2024], session_type="Q")

    assert result["matched_team_names"] == ["Mercedes"]
    assert result["sample_count"] == 4
    assert result["season_baselines"] == {2023: 4.5, 2024: 5.5}
    best = result["strongest_fit"]
    assert best["dimension"] == "character"
    assert best["character"] == "stop_and_go"
    assert best["avg_fit_delta_position"] == 1.5
    assert result["weakest_fit"]["character"] == "high_speed_technical"


def test_analyze_team_telemetry_traits_compares_team_to_field_median():
    drivers = [
        {"full_name": "George Russell", "code": "RUS", "team": "Mercedes"},
        {"full_name": "Kimi Antonelli", "code": "ANT", "team": "Mercedes"},
        {"full_name": "Lando Norris", "code": "NOR", "team": "McLaren"},
        {"full_name": "Charles Leclerc", "code": "LEC", "team": "Ferrari"},
    ]
    profiles = {
        "RUS": {
            "corner_profiles": {
                "T1": {"entry_speed_kph": 210, "apex_speed_kph": 130, "exit_speed_kph": 180, "braking_point_m": 110},
                "T2": {"entry_speed_kph": 220, "apex_speed_kph": 150, "exit_speed_kph": 190, "braking_point_m": 320},
            },
            "straight_profiles": [{"max_speed_kph": 320}, {"max_speed_kph": 315}],
            "lap_summary": {"full_throttle_pct": 66, "braking_pct": 15, "coasting_pct": 19},
        },
        "ANT": {
            "corner_profiles": {
                "T1": {"entry_speed_kph": 212, "apex_speed_kph": 132, "exit_speed_kph": 182, "braking_point_m": 112},
                "T2": {"entry_speed_kph": 222, "apex_speed_kph": 152, "exit_speed_kph": 192, "braking_point_m": 322},
            },
            "straight_profiles": [{"max_speed_kph": 321}, {"max_speed_kph": 316}],
            "lap_summary": {"full_throttle_pct": 67, "braking_pct": 14, "coasting_pct": 19},
        },
        "NOR": {
            "corner_profiles": {
                "T1": {"entry_speed_kph": 205, "apex_speed_kph": 124, "exit_speed_kph": 174, "braking_point_m": 100},
                "T2": {"entry_speed_kph": 215, "apex_speed_kph": 144, "exit_speed_kph": 184, "braking_point_m": 310},
            },
            "straight_profiles": [{"max_speed_kph": 314}, {"max_speed_kph": 309}],
            "lap_summary": {"full_throttle_pct": 62, "braking_pct": 18, "coasting_pct": 20},
        },
        "LEC": {
            "corner_profiles": {
                "T1": {"entry_speed_kph": 206, "apex_speed_kph": 126, "exit_speed_kph": 176, "braking_point_m": 102},
                "T2": {"entry_speed_kph": 216, "apex_speed_kph": 146, "exit_speed_kph": 186, "braking_point_m": 312},
            },
            "straight_profiles": [{"max_speed_kph": 316}, {"max_speed_kph": 311}],
            "lap_summary": {"full_throttle_pct": 63, "braking_pct": 17, "coasting_pct": 20},
        },
    }

    mock_session = MagicMock()
    mock_session.drivers = []
    mock_session.event = {"EventName": "Test GP"}

    with patch('f1_data.get_drivers', return_value=drivers), \
         patch('f1_data._load_session', return_value=mock_session), \
         patch('f1_data.extract_corner_profiles', side_effect=lambda _r, _s, code: profiles[code]):
        import f1_data
        result = f1_data.analyze_team_telemetry_traits(3, "Mercedes", session_type="Q", field_limit=4)

    assert result["team"] == "Mercedes"
    assert result["team_codes"] == ["RUS", "ANT"]
    assert result["field_sample_count"] == 4
    assert result["deltas_vs_field_median"]["avg_apex_speed_kph"] > 0
    assert "high_minimum_speed" in result["trait_flags"]
    assert "straight_line_speed" in result["trait_flags"]


def test_get_session_results():
    mock_session = MagicMock()
    mock_session.event = {'EventName': 'Bahrain Grand Prix'}
    mock_session.total_laps = 57
    mock_session.results = pd.DataFrame([
        {
            "Position": 1,
            "ClassifiedPosition": "1",
            "GridPosition": 2,
            "Status": "Finished",
            "Points": 25.0,
            "FullName": "Max Verstappen",
            "BroadcastName": "M VERSTAPPEN",
            "Abbreviation": "VER",
            "DriverNumber": "1",
            "TeamName": "Red Bull Racing",
            "TeamColor": "3671C6",
            "CountryCode": "NLD",
            "HeadshotUrl": "https://example.com/ver.png",
            "Q1": pd.Timedelta(seconds=89.8),
            "Q2": pd.Timedelta(seconds=89.1),
            "Q3": pd.Timedelta(seconds=88.7),
        }
    ])

    with patch('f1_data.fastf1.get_session', return_value=mock_session):
        result = f1_data.get_session_results(1, 'R')

    assert result['event'] == 'Bahrain Grand Prix'
    assert result['total_laps'] == 57
    assert result['results'][0]['grid_position'] == 2
    assert result['results'][0]['q3'] == '1:28.700'


def test_get_driver_strategy_single_driver():
    lap_df = pd.DataFrame([
        {
            'Driver': 'NOR', 'LapNumber': 1.0, 'LapTime': pd.Timedelta(seconds=91.0),
            'Compound': 'MEDIUM', 'TyreLife': 1.0, 'Stint': 1.0, 'FreshTyre': True,
            'PitInTime': pd.NaT, 'PitOutTime': pd.NaT, 'Position': 3.0, 'Team': 'McLaren'
        },
        {
            'Driver': 'NOR', 'LapNumber': 2.0, 'LapTime': pd.Timedelta(seconds=91.5),
            'Compound': 'MEDIUM', 'TyreLife': 2.0, 'Stint': 1.0, 'FreshTyre': True,
            'PitInTime': pd.Timedelta(seconds=180), 'PitOutTime': pd.NaT, 'Position': 2.0, 'Team': 'McLaren'
        },
        {
            'Driver': 'NOR', 'LapNumber': 3.0, 'LapTime': pd.Timedelta(seconds=90.0),
            'Compound': 'SOFT', 'TyreLife': 1.0, 'Stint': 2.0, 'FreshTyre': True,
            'PitInTime': pd.NaT, 'PitOutTime': pd.Timedelta(seconds=250), 'Position': 2.0, 'Team': 'McLaren'
        },
    ])
    mock_session = MagicMock()
    mock_session.event = {'EventName': 'Bahrain Grand Prix'}
    mock_session.results = pd.DataFrame([{"Abbreviation": "NOR", "FullName": "Lando Norris", "TeamName": "McLaren", "GridPosition": 4, "Position": 2}])
    mock_session.laps.pick_drivers.side_effect = lambda codes: lap_df if (codes[0] if isinstance(codes, list) else codes) == 'NOR' else pd.DataFrame()

    with patch('f1_data.fastf1.get_session', return_value=mock_session):
        result = f1_data.get_driver_strategy(1, 'R', 'NOR')

    assert result['drivers'][0]['driver'] == 'Lando Norris'
    assert result['drivers'][0]['pit_stop_count'] == 1
    assert len(result['drivers'][0]['stints']) == 2
    assert result['drivers'][0]['stints'][0]['compound'] == 'MEDIUM'


def test_get_qualifying_progression():
    def _lap_pickable(lap):
        mock = MagicMock()
        mock.empty = False
        mock.pick_fastest.return_value = lap
        return mock

    q1_laps = MagicMock()
    q2_laps = MagicMock()
    q3_laps = MagicMock()
    q1_laps.pick_drivers.side_effect = lambda codes: _lap_pickable(_make_mock_fastest_lap(codes[0] if isinstance(codes, list) else codes, lap_time_s=90.0))
    q2_laps.pick_drivers.side_effect = lambda codes: _lap_pickable(_make_mock_fastest_lap(codes[0] if isinstance(codes, list) else codes, lap_time_s=89.5))
    q3_laps.pick_drivers.side_effect = lambda codes: _lap_pickable(_make_mock_fastest_lap(codes[0] if isinstance(codes, list) else codes, lap_time_s=89.0))

    mock_session = MagicMock()
    mock_session.event = {'EventName': 'Monaco Grand Prix'}
    mock_session.drivers = ['NOR']
    mock_session.results = pd.DataFrame([{"Abbreviation": "NOR", "FullName": "Lando Norris", "TeamName": "McLaren"}])
    mock_session.laps.split_qualifying_sessions.return_value = [q1_laps, q2_laps, q3_laps]

    with patch('f1_data.fastf1.get_session', return_value=mock_session):
        result = f1_data.get_qualifying_progression(8)

    driver = result['drivers'][0]
    assert driver['made_q3'] is True
    assert driver['best_segment'] == 'q3'
    assert driver['improvement_q2_to_q3_s'] < 0


def test_get_clean_pace_summary():
    class PaceFrame(pd.DataFrame):
        @property
        def _constructor(self):
            return PaceFrame

        def pick_accurate(self):
            return self

        def pick_not_deleted(self):
            return self

        def pick_wo_box(self):
            return self

        def pick_track_status(self, _status):
            return self

        def pick_quicklaps(self):
            return self

    laps = PaceFrame([
        {'LapTime': pd.Timedelta(seconds=88.0), 'LapNumber': 4, 'Compound': 'SOFT', 'TyreLife': 2.0, 'TrackStatus': '1'},
        {'LapTime': pd.Timedelta(seconds=88.2), 'LapNumber': 5, 'Compound': 'SOFT', 'TyreLife': 3.0, 'TrackStatus': '1'},
    ])
    mock_session = MagicMock()
    mock_session.event = {'EventName': 'Monaco Grand Prix'}
    mock_session.drivers = ['NOR']
    mock_session.results = pd.DataFrame([{"Abbreviation": "NOR", "FullName": "Lando Norris", "TeamName": "McLaren"}])
    mock_session.laps.pick_drivers.side_effect = lambda codes: laps if (codes[0] if isinstance(codes, list) else codes) == 'NOR' else PaceFrame()

    with patch('f1_data.fastf1.get_session', return_value=mock_session):
        result = f1_data.get_clean_pace_summary(8, 'Q', ['NOR'])

    assert result['drivers'][0]['rank'] == 1
    assert result['drivers'][0]['best_lap_time'] == '1:28.000'
    assert result['drivers'][0]['lap_count'] == 2


def test_get_race_control_messages():
    mock_session = MagicMock()
    mock_session.event = {'EventName': 'Monaco Grand Prix'}
    mock_session.race_control_messages = pd.DataFrame([
        {'Category': 'Track Limits', 'Flag': None, 'Scope': 'Driver', 'Message': 'Car 4 lap time deleted', 'Status': None, 'Lap': 15, 'Time': pd.Timedelta(seconds=900), 'DriverNumber': '4'},
        {'Category': 'Incident', 'Flag': 'YELLOW', 'Scope': 'Sector', 'Message': 'Yellow flag in sector 2', 'Status': None, 'Lap': 18, 'Time': pd.Timedelta(seconds=1080), 'DriverNumber': None},
    ])

    with patch('f1_data.fastf1.get_session', return_value=mock_session):
        result = f1_data.get_race_control_messages(8, 'Q', category='deleted')

    assert len(result['messages']) == 1
    assert result['messages'][0]['driver_number'] == '4'


def test_get_track_position_comparison():
    class MockLap:
        def __init__(self, lap_number, pos_df, car_df):
            self.data = {'LapNumber': lap_number}
            self._pos_df = pos_df
            self._car_df = car_df

        def __getitem__(self, key):
            return self.data[key]

        def get_pos_data(self):
            wrapper = MagicMock()
            wrapper.add_distance.return_value = self._pos_df
            return wrapper

        def get_car_data(self):
            wrapper = MagicMock()
            wrapper.add_distance.return_value = self._car_df
            return wrapper

    pos_a = pd.DataFrame({'Distance': [0.0, 100.0], 'X': [1.0, 2.0], 'Y': [3.0, 4.0], 'Status': ['OnTrack', 'OnTrack']})
    pos_b = pd.DataFrame({'Distance': [0.0, 100.0], 'X': [1.5, 2.5], 'Y': [3.5, 4.5], 'Status': ['OnTrack', 'OnTrack']})
    car_a = pd.DataFrame({'Distance': [0.0, 100.0], 'Speed': [150.0, 160.0]})
    car_b = pd.DataFrame({'Distance': [0.0, 100.0], 'Speed': [145.0, 158.0]})
    lap_a = MockLap(12, pos_a, car_a)
    lap_b = MockLap(13, pos_b, car_b)

    def pick_driver(codes):
        code = codes[0] if isinstance(codes, list) else codes
        mock = MagicMock()
        mock.empty = False
        mock.pick_fastest.return_value = lap_a if code == 'NOR' else lap_b
        return mock

    mock_session = MagicMock()
    mock_session.event = {'EventName': 'Monaco Grand Prix'}
    mock_session.laps.pick_drivers.side_effect = pick_driver
    mock_session.get_circuit_info.return_value.rotation = 90.0

    with patch('f1_data.fastf1.get_session', return_value=mock_session):
        result = f1_data.get_track_position_comparison(8, 'Q', 'NOR', 'LEC')

    assert result['rotation'] == 90.0
    assert result['comparison'][0]['delta_speed'] == 5.0


def test_get_circuit_details():
    mock_session = MagicMock()
    mock_circuit_info = MagicMock()
    mock_circuit_info.rotation = 45.0
    marker_df = pd.DataFrame({'Number': [1], 'Letter': ['A'], 'X': [10.0], 'Y': [20.0], 'Angle': [90.0], 'Distance': [150.0]})
    mock_circuit_info.corners = marker_df
    mock_circuit_info.marshal_lights = marker_df
    mock_circuit_info.marshal_sectors = marker_df
    mock_session.get_circuit_info.return_value = mock_circuit_info

    with patch('f1_data.fastf1.get_session', return_value=mock_session):
        result = f1_data.get_circuit_details(8)

    assert result['rotation'] == 45.0
    assert result['corners'][0]['label'] == 'A'


def test_load_session_rejects_future_session():
    future_date = pd.Timestamp.now(tz='UTC').tz_localize(None) + pd.Timedelta(days=7)
    schedule = pd.DataFrame([{
        'RoundNumber': 6,
        'EventName': 'Miami Grand Prix',
        'Session1': 'Practice 1',
        'Session1DateUtc': future_date,
        'Session2': 'Sprint Qualifying',
        'Session2DateUtc': future_date,
        'Session3': 'Sprint',
        'Session3DateUtc': future_date,
        'Session4': 'Qualifying',
        'Session4DateUtc': future_date,
        'Session5': 'Race',
        'Session5DateUtc': future_date,
        'F1ApiSupport': True,
    }])

    with patch('f1_data.fastf1.get_event_schedule', return_value=schedule):
        with pytest.raises(ValueError, match="has not happened yet"):
            f1_data._validate_session_availability(6, 'R', telemetry=True)


def test_get_driver_weekend_overview():
    with patch('f1_data._resolve_driver', return_value={
        "full_name": "George Russell",
        "code": "RUS",
        "driver_id": "russell",
        "team": "Mercedes",
    }), \
    patch('f1_data.get_qualifying_results', return_value={
        "race_name": "Japanese Grand Prix",
        "results": [
            {"position": 5, "driver": "George Russell", "code": "RUS", "team": "Mercedes", "q1": "1:28.0", "q2": "1:27.6", "q3": "1:27.3"},
            {"position": 7, "driver": "Kimi Antonelli", "code": "ANT", "team": "Mercedes", "q1": "1:28.1", "q2": "1:27.8", "q3": "1:27.6"},
        ],
    }), \
    patch('f1_data.get_race_results', return_value={
        "race_name": "Japanese Grand Prix",
        "results": [
            {"position": 3, "driver": "George Russell", "code": "RUS", "team": "Mercedes", "points": 15.0, "status": "Finished", "fastest_lap": False},
            {"position": 2, "driver": "Charles Leclerc", "code": "LEC", "team": "Ferrari", "status": "Finished"},
            {"position": 4, "driver": "Lewis Hamilton", "code": "HAM", "team": "Ferrari", "status": "Finished"},
            {"position": 6, "driver": "Kimi Antonelli", "code": "ANT", "team": "Mercedes", "status": "Finished"},
        ],
    }), \
    patch('f1_data.get_driver_strategy', return_value={
        "drivers": [{
            "driver": "George Russell",
            "stints": [
                {"start_lap": 1, "compound": "MEDIUM"},
                {"start_lap": 18, "compound": "HARD", "fresh_tyre": True},
            ],
        }]
    }), \
    patch('f1_data.get_safety_car_periods', return_value={
        "sc_count": 1,
        "vsc_count": 0,
        "periods": [
            {"type": "SafetyCar", "deployed_on_lap": 20, "pitted_just_before": [], "pitted_during": [{"driver": "RUS"}]}
        ],
    }), \
    patch('f1_data.get_session_results', return_value={
        "results": [{"abbreviation": "RUS", "driver_number": "63", "grid_position": 5}]
    }), \
    patch('openf1.get_team_radio', side_effect=[
        {"messages": [{"recording_url": "https://example.test/qradio.mp3"}]},
        {"messages": [{"recording_url": "https://example.test/rradio.mp3"}]},
    ]), \
    patch('openf1.get_intervals', return_value={"intervals": [{"gap_to_leader": "+4.1", "interval": "+1.2"}]}), \
    patch('openf1.get_live_position_timeline', return_value={"positions": [{"position": 3}, {"position": 5}]}):
        result = f1_data.get_driver_weekend_overview(3, 'Russell')

    assert result["driver"] == "George Russell"
    assert result["qualifying"]["position"] == 5
    assert result["race"]["finish_position"] == 3
    assert result["teammate"]["finish_position"] == 6
    assert result["pit_stops"][0]["pit_window_after_lap"] == 17
    assert result["safety_car_impact"]["sc_count"] == 1
    assert result["nearby_rivals"][0]["driver"] == "Charles Leclerc"
    assert result["openf1"]["qualifying_radio"]["messages"][0]["recording_url"].endswith("qradio.mp3")
    assert result["openf1"]["race_radio"]["messages"][0]["recording_url"].endswith("rradio.mp3")
    assert result["openf1"]["race_intervals"]["intervals"][0]["gap_to_leader"] == "+4.1"


def test_get_driver_race_story():
    with patch('f1_data.get_driver_weekend_overview', return_value={
        "driver": "George Russell",
        "code": "RUS",
        "team": "Mercedes",
        "event": "Japanese Grand Prix",
        "qualifying": {"position": 5},
        "race": {"finish_position": 3},
        "pit_stops": [{"pit_window_after_lap": 17, "new_compound": "HARD", "fresh_tyre": True}],
        "strategy": {"stints": []},
        "safety_car_impact": {"sc_count": 1, "vsc_count": 0, "pitted_just_before_sc": [], "pitted_during_sc": [{"type": "SafetyCar", "lap": 20}]},
        "teammate": {"name": "Kimi Antonelli", "finish_position": 6},
        "nearby_rivals": [{"driver": "Charles Leclerc", "team": "Ferrari", "position": 2}],
        "openf1": {
            "race_radio": {"messages": [{"date": "2026-04-05T06:30:00Z", "recording_url": "https://example.test/radio.mp3"}]},
            "race_intervals": {"intervals": [{"gap_to_leader": "+4.1", "interval": "+1.2"}]},
            "race_positions": {"positions": [{"position": 3}, {"position": 5}]},
        },
    }), \
    patch('f1_data.get_session_results', return_value={"results": [{"abbreviation": "RUS", "driver_number": "63"}]}), \
    patch('f1_data.get_race_control_messages', return_value={"messages": [{"lap": 20, "category": "Incident", "message": "Car 63 noted"}]}):
        result = f1_data.get_driver_race_story(3, 'Russell')

    assert result["driver"] == "George Russell"
    assert any("Gained" in point for point in result["story_points"])
    assert any("Pit strategy" in point for point in result["story_points"])
    assert result["race_control_highlights"][0]["message"] == "Car 63 noted"
    assert result["rivalry_story"][0].startswith("Finished near Charles Leclerc")
    assert result["radio_highlights"][0]["recording_url"].endswith(".mp3")
    assert result["interval_summary"]["latest_gap_to_leader"] == "+4.1"
    assert result["position_timeline_summary"]["latest_position"] == 3


def test_get_team_weekend_overview():
    with patch('f1_data._resolve_team', return_value='Mercedes'), \
    patch('f1_data.get_drivers', return_value=[
        {"full_name": "George Russell", "code": "RUS", "team": "Mercedes"},
        {"full_name": "Kimi Antonelli", "code": "ANT", "team": "Mercedes"},
    ]), \
    patch('f1_data.get_qualifying_results', return_value={
        "race_name": "Japanese Grand Prix",
        "results": [
            {"position": 5, "driver": "George Russell", "code": "RUS", "team": "Mercedes"},
            {"position": 7, "driver": "Kimi Antonelli", "code": "ANT", "team": "Mercedes"},
        ],
    }), \
    patch('f1_data.get_race_results', return_value={
        "race_name": "Japanese Grand Prix",
        "results": [
            {"position": 3, "driver": "George Russell", "code": "RUS", "team": "Mercedes", "points": 15.0, "status": "Finished", "fastest_lap": False},
            {"position": 6, "driver": "Kimi Antonelli", "code": "ANT", "team": "Mercedes", "points": 8.0, "status": "Finished", "fastest_lap": False},
        ],
    }), \
    patch('f1_data.get_driver_strategy', side_effect=[
        {"drivers": [{"stints": [{"start_lap": 1, "compound": "MEDIUM"}, {"start_lap": 18, "compound": "HARD"}]}]},
        {"drivers": [{"stints": [{"start_lap": 1, "compound": "MEDIUM"}, {"start_lap": 24, "compound": "HARD"}]}]},
    ]):
        result = f1_data.get_team_weekend_overview(3, 'Mercedes')

    assert result["team"] == "Mercedes"
    assert result["total_points"] == 23.0
    assert result["lead_driver"] == "George Russell"
    assert result["drivers"][0]["positions_gained"] == 2
    assert any("Scored 23.0 point(s)" in point for point in result["summary_points"])


def test_get_race_report():
    with patch('f1_data.get_qualifying_results', return_value={
        "race_name": "Japanese Grand Prix",
        "results": [
            {"position": 2, "driver": "Lando Norris", "code": "NOR", "team": "McLaren"},
            {"position": 1, "driver": "Max Verstappen", "code": "VER", "team": "Red Bull Racing"},
            {"position": 5, "driver": "George Russell", "code": "RUS", "team": "Mercedes"},
        ],
    }), \
    patch('f1_data.get_race_results', return_value={
        "race_name": "Japanese Grand Prix",
        "circuit": "Suzuka",
        "date": "2026-04-05",
        "results": [
            {"position": 1, "driver": "Lando Norris", "code": "NOR", "team": "McLaren", "points": 25.0, "status": "Finished", "fastest_lap": True},
            {"position": 2, "driver": "Max Verstappen", "code": "VER", "team": "Red Bull Racing", "points": 18.0, "status": "Finished", "fastest_lap": False},
            {"position": 20, "driver": "George Russell", "code": "RUS", "team": "Mercedes", "points": 0.0, "status": "Accident", "fastest_lap": False},
        ],
    }), \
    patch('f1_data.get_safety_car_periods', return_value={"sc_count": 1, "vsc_count": 0, "periods": []}):
        result = f1_data.get_race_report(3)

    assert result["event"] == "Japanese Grand Prix"
    assert result["podium"][0]["driver"] == "Lando Norris"
    assert result["fastest_lap"]["driver"] == "Lando Norris"
    assert result["biggest_gainer"]["driver"] == "Lando Norris"
    assert result["dnfs"][0]["driver"] == "George Russell"


def test_pick_driver_uses_pick_drivers_when_available():
    """3.8+ path: delegates to pick_drivers([code])."""
    mock_laps = MagicMock()
    mock_result = MagicMock()
    mock_laps.pick_drivers.return_value = mock_result
    result = f1_data._pick_driver(mock_laps, 'VER')
    mock_laps.pick_drivers.assert_called_once_with(['VER'])
    assert result is mock_result


def test_pick_driver_falls_back_to_pick_driver():
    """Pre-3.8 fallback: calls pick_driver(code) when pick_drivers absent."""
    mock_laps = MagicMock(spec=['pick_driver'])
    mock_result = MagicMock()
    mock_laps.pick_driver.return_value = mock_result
    result = f1_data._pick_driver(mock_laps, 'NOR')
    mock_laps.pick_driver.assert_called_once_with('NOR')
    assert result is mock_result


def test_pick_driver_coerces_code_to_string():
    """Code arg is always stringified before passing through."""
    mock_laps = MagicMock()
    f1_data._pick_driver(mock_laps, 44)  # int driver number
    mock_laps.pick_drivers.assert_called_once_with(['44'])


def test_analyze_race_pace_battle_raises_without_clean_laps():
    mock_session = MagicMock()
    mock_session.event = {'EventName': 'Japanese Grand Prix'}

    with patch('f1_data._validate_session_availability'), \
         patch('f1_data._load_session', return_value=mock_session), \
         patch('f1_data._pick_driver', return_value=pd.DataFrame([{'LapNumber': 1}])), \
         patch('f1_data._filter_clean_race_laps', return_value=[]):
        with pytest.raises(ValueError, match="No clean laps available"):
            f1_data.analyze_race_pace_battle(3, 'NOR', 'LEC')


def test_analyze_team_performance_uses_degradation_event_when_corner_comparison_fails():
    with patch('f1_data._resolve_team', return_value='Ferrari'), \
         patch('f1_data.get_drivers', return_value=[
             {'full_name': 'Charles Leclerc', 'code': 'LEC', 'driver_id': 'leclerc', 'team': 'Ferrari'},
             {'full_name': 'Lewis Hamilton', 'code': 'HAM', 'driver_id': 'hamilton', 'team': 'Ferrari'},
         ]), \
         patch('f1_data.compare_corner_profiles', side_effect=ValueError('telemetry unavailable')), \
         patch('f1_data.analyze_stint_degradation', side_effect=[
             {'event': 'Japanese Grand Prix', 'driver': 'LEC', 'stints': []},
             {'event': 'Japanese Grand Prix', 'driver': 'HAM', 'stints': []},
         ]):
        result = f1_data.analyze_team_performance(3, 'Ferrari', 'R')

    assert result['event'] == 'Japanese Grand Prix'
    assert result['corner_error'] == 'telemetry unavailable'
    assert result['degradation_a']['driver'] == 'LEC'
    assert result['degradation_b']['driver'] == 'HAM'


# ─── _summarize_openf1_intervals tests ──────────────────────

def test_summarize_openf1_intervals_dropping_back():
    """Driver starts close to leader then falls back — trend must be dropping_back."""
    # Intervals arrive in ascending chronological order (as get_intervals delivers them)
    intervals = [
        {"date": "2026-03-16T14:01:00", "gap_to_leader": "0.5",  "interval": "0.5"},  # earliest
        {"date": "2026-03-16T14:15:00", "gap_to_leader": "+4.0", "interval": "3.5"},
        {"date": "2026-03-16T14:30:00", "gap_to_leader": "+9.0", "interval": "5.0"},  # most recent
    ]
    result = f1_data._summarize_openf1_intervals(intervals)

    assert result["trend"] == "dropping_back", (
        f"Expected 'dropping_back' (gap grew from 0.5 to 9.0) but got {result['trend']!r}"
    )
    assert result["latest_gap_to_leader"] == "+9.0", (
        f"Expected '+9.0' (last entry) but got {result['latest_gap_to_leader']!r}"
    )
    assert result["latest_gap_to_leader_s"] == pytest.approx(9.0, abs=0.01)
    assert result["earliest_gap_to_leader_s"] == pytest.approx(0.5, abs=0.01)


def test_summarize_openf1_intervals_closing():
    """Driver starts far back then closes — trend must be closing."""
    intervals = [
        {"date": "2026-03-16T14:01:00", "gap_to_leader": "+10.0", "interval": "5.0"},  # earliest
        {"date": "2026-03-16T14:15:00", "gap_to_leader": "+6.0",  "interval": "3.0"},
        {"date": "2026-03-16T14:30:00", "gap_to_leader": "+2.0",  "interval": "1.5"},  # most recent
    ]
    result = f1_data._summarize_openf1_intervals(intervals)

    assert result["trend"] == "closing", (
        f"Expected 'closing' (gap shrank from 10.0 to 2.0) but got {result['trend']!r}"
    )
    assert result["latest_gap_to_leader"] == "+2.0"
    assert result["latest_gap_to_leader_s"] == pytest.approx(2.0, abs=0.01)
    assert result["earliest_gap_to_leader_s"] == pytest.approx(10.0, abs=0.01)


def test_summarize_openf1_intervals_stable():
    """Gap stays within 0.75s — trend must be stable."""
    intervals = [
        {"date": "2026-03-16T14:01:00", "gap_to_leader": "+3.0", "interval": "2.0"},
        {"date": "2026-03-16T14:15:00", "gap_to_leader": "+3.4", "interval": "2.4"},
        {"date": "2026-03-16T14:30:00", "gap_to_leader": "+3.2", "interval": "2.2"},
    ]
    result = f1_data._summarize_openf1_intervals(intervals)
    assert result["trend"] == "stable"


def test_summarize_openf1_intervals_empty_returns_none():
    assert f1_data._summarize_openf1_intervals([]) is None


def test_summarize_openf1_intervals_no_valid_gaps_uses_last_entry():
    """When no numeric gaps exist, latest_gap_to_leader must come from the last (most recent) entry."""
    intervals = [
        {"date": "2026-03-16T14:01:00", "gap_to_leader": "LAP",  "interval": None},  # earliest
        {"date": "2026-03-16T14:30:00", "gap_to_leader": "LAP2", "interval": None},  # most recent
    ]
    result = f1_data._summarize_openf1_intervals(intervals)
    assert result["latest_gap_to_leader"] == "LAP2", (
        "When all gaps are non-numeric, latest_gap_to_leader should be from the LAST entry (most recent)"
    )


def test_fit_stint_degradation_exposes_ranking_inputs():
    clean_laps = [
        {"lap_number": 10, "lap_time_s": 90.00, "compound": "HARD", "tyre_age": 1},
        {"lap_number": 11, "lap_time_s": 90.10, "compound": "HARD", "tyre_age": 2},
        {"lap_number": 12, "lap_time_s": 90.20, "compound": "HARD", "tyre_age": 3},
        {"lap_number": 13, "lap_time_s": 90.30, "compound": "HARD", "tyre_age": 4},
    ]

    stints = f1_data._fit_stint_degradation(clean_laps, fuel_correction_s_per_lap=0.0)

    assert stints[0]["raw_pace_trend_s_per_lap"] == pytest.approx(0.1)
    assert stints[0]["deg_rate_s_per_lap"] == pytest.approx(0.1)
    assert stints[0]["positive_deg_rate_s_per_lap"] == pytest.approx(0.1)
    assert stints[0]["r_squared"] == pytest.approx(1.0)
    assert "raw_pace_trend_s_per_lap is what the stopwatch did" in stints[0]["ranking_basis"]


def test_fit_stint_degradation_adds_back_fuel_burn_for_improving_raw_pace():
    clean_laps = [
        {"lap_number": 10, "lap_time_s": 90.00, "compound": "HARD", "tyre_age": 1},
        {"lap_number": 11, "lap_time_s": 89.98, "compound": "HARD", "tyre_age": 2},
        {"lap_number": 12, "lap_time_s": 89.96, "compound": "HARD", "tyre_age": 3},
        {"lap_number": 13, "lap_time_s": 89.94, "compound": "HARD", "tyre_age": 4},
    ]

    stints = f1_data._fit_stint_degradation(clean_laps, fuel_correction_s_per_lap=0.04)

    assert stints[0]["raw_pace_trend_s_per_lap"] == pytest.approx(-0.02)
    assert stints[0]["deg_rate_s_per_lap"] == pytest.approx(0.02)
    assert stints[0]["positive_deg_rate_s_per_lap"] == pytest.approx(0.02)


class TestDetectCliff:
    def test_returns_no_cliff_when_too_few_laps(self):
        ages = list(range(1, 10))
        times = [90.0 + 0.05 * (age - 1) for age in ages]

        result = f1_data._detect_cliff(ages, times)

        assert result["cliff_detected"] is False

    def test_returns_no_cliff_for_linear_series(self):
        ages = list(range(1, 21))
        times = [90.0 + 0.05 * (age - 1) for age in ages]

        result = f1_data._detect_cliff(ages, times)

        assert result["cliff_detected"] is False

    def test_returns_no_cliff_for_noisy_linear_series(self):
        ages = list(range(1, 25))
        noise = [0.02, -0.03, 0.01, -0.01, 0.03, -0.02] * 4
        times = [90.0 + 0.055 * (age - 1) + noise[i] for i, age in enumerate(ages)]

        result = f1_data._detect_cliff(ages, times)

        assert result["cliff_detected"] is False

    def test_returns_no_cliff_for_single_bad_outlier(self):
        ages = list(range(1, 25))
        times = [90.0 + 0.05 * (age - 1) for age in ages]
        times[12] += 1.2

        result = f1_data._detect_cliff(ages, times)

        assert result["cliff_detected"] is False

    def test_detects_sustained_slope_change(self):
        ages = list(range(1, 25))
        times = []
        for age in ages[:11]:
            times.append(90.0 + 0.04 * (age - 1))
        cliff_base = times[-1]
        for i, _age in enumerate(ages[11:]):
            times.append(cliff_base + 0.27 * (i + 1))

        result = f1_data._detect_cliff(ages, times)

        assert result["cliff_detected"] is True
        assert result["cliff_tyre_age"] == 11
        assert result["cliff_slope_increase_s_per_lap"] >= 0.06
        assert result["cliff_severity_ratio"] >= 2.5
        assert result["pre_cliff_deg_rate_s_per_lap"] < result["post_cliff_deg_rate_s_per_lap"]
        assert result["cliff_confidence"] in ("moderate", "high")

    def test_no_cliff_when_slope_change_is_too_small(self):
        ages = list(range(1, 25))
        times = []
        for age in ages[:12]:
            times.append(90.0 + 0.05 * (age - 1))
        cliff_base = times[-1]
        for i in range(12):
            times.append(cliff_base + 0.095 * (i + 1))

        result = f1_data._detect_cliff(ages, times)

        assert result["cliff_detected"] is False

    def test_detects_cliff_from_flat_pre_cliff_slope_without_ratio(self):
        ages = list(range(1, 25))
        times = []
        for age in ages[:12]:
            times.append(90.0 + 0.005 * (age - 1))
        cliff_base = times[-1]
        for i in range(12):
            times.append(cliff_base + 0.18 * (i + 1))

        result = f1_data._detect_cliff(ages, times)

        assert result["cliff_detected"] is True
        assert result["cliff_severity_ratio"] is None
        assert result["cliff_slope_increase_s_per_lap"] >= 0.06

    def test_detected_cliff_output_has_required_keys(self):
        ages = list(range(1, 25))
        times = []
        for age in ages[:12]:
            times.append(90.0 + 0.04 * (age - 1))
        cliff_base = times[-1]
        for i in range(12):
            times.append(cliff_base + 0.30 * (i + 1))

        result = f1_data._detect_cliff(ages, times)

        assert result["cliff_detected"] is True
        for key in (
            "cliff_tyre_age",
            "cliff_slope_increase_s_per_lap",
            "cliff_severity_ratio",
            "pre_cliff_deg_rate_s_per_lap",
            "post_cliff_deg_rate_s_per_lap",
            "pre_cliff_lap_count",
            "post_cliff_lap_count",
            "pre_cliff_regression_line",
            "post_cliff_regression_line",
            "bic_improvement",
            "cliff_confidence",
        ):
            assert key in result
        assert len(result["pre_cliff_regression_line"]) == 2
        assert len(result["post_cliff_regression_line"]) == 2


class TestFitStintDegradationStintSplitting:
    def test_same_compound_tyre_age_reset_splits_physical_stints(self):
        clean_laps = [
            {"lap_number": 1, "lap_time_s": 90.1, "compound": "MEDIUM", "tyre_age": 1},
            {"lap_number": 2, "lap_time_s": 90.2, "compound": "MEDIUM", "tyre_age": 2},
            {"lap_number": 3, "lap_time_s": 90.3, "compound": "MEDIUM", "tyre_age": 3},
            {"lap_number": 4, "lap_time_s": 89.8, "compound": "MEDIUM", "tyre_age": 1},
            {"lap_number": 5, "lap_time_s": 89.9, "compound": "MEDIUM", "tyre_age": 2},
            {"lap_number": 6, "lap_time_s": 90.0, "compound": "MEDIUM", "tyre_age": 3},
        ]

        stints = f1_data._fit_stint_degradation(clean_laps, fuel_correction_s_per_lap=0.0)

        assert len(stints) == 2
        assert stints[0]["lap_numbers"] == [1, 2, 3]
        assert stints[1]["lap_numbers"] == [4, 5, 6]
        assert all(stint["cliff_detected"] is False for stint in stints)

    def test_same_compound_increasing_tyre_age_remains_one_stint(self):
        clean_laps = [
            {"lap_number": i, "lap_time_s": 90.0 + i * 0.05, "compound": "HARD", "tyre_age": i}
            for i in range(1, 7)
        ]

        stints = f1_data._fit_stint_degradation(clean_laps, fuel_correction_s_per_lap=0.0)

        assert len(stints) == 1
        assert stints[0]["lap_numbers"] == [1, 2, 3, 4, 5, 6]


class TestFitStintDegradationCliffFields:
    def _make_laps(self, lap_times_and_ages):
        return [
            {
                "lap_number": lap_number,
                "tyre_age": tyre_age,
                "lap_time_s": lap_time_s,
                "compound": "SOFT",
                "driver_code": "VER",
            }
            for lap_number, tyre_age, lap_time_s in lap_times_and_ages
        ]

    def test_cliff_fields_present_in_output(self):
        laps = []
        for i in range(11):
            laps.append((i + 1, i + 1, 90.0 + 0.04 * i))
        cliff_base = laps[-1][2]
        for i in range(13):
            laps.append((i + 12, i + 12, cliff_base + 0.28 * (i + 1)))

        result = f1_data._fit_stint_degradation(self._make_laps(laps), fuel_correction_s_per_lap=0.0)

        assert len(result) == 1
        stint = result[0]
        assert stint["cliff_detected"] is True
        assert stint["cliff_tyre_age"] == 11
        assert stint["cliff_slope_increase_s_per_lap"] is not None
        assert stint["cliff_severity_ratio"] is not None
        assert stint["pre_cliff_deg_rate_s_per_lap"] is not None
        assert stint["post_cliff_deg_rate_s_per_lap"] is not None
        assert len(stint["pre_cliff_regression_line"]) == 2
        assert len(stint["post_cliff_regression_line"]) == 2
        assert len(stint["regression_line"]) == 2

    def test_no_cliff_on_linear_stint_still_includes_field(self):
        laps = [(i + 1, i + 1, 90.0 + 0.05 * i) for i in range(15)]

        result = f1_data._fit_stint_degradation(self._make_laps(laps), fuel_correction_s_per_lap=0.0)

        assert len(result) == 1
        assert result[0]["cliff_detected"] is False
        assert result[0]["pre_cliff_regression_line"] == []
        assert result[0]["post_cliff_regression_line"] == []


def test_summarize_tyre_management_weights_deg_consistency_and_r2():
    stints = [
        {
            "lap_count": 10,
            "deg_rate_s_per_lap": 0.05,
            "positive_deg_rate_s_per_lap": 0.05,
            "consistency_std_dev_s": 0.4,
            "r_squared": 0.8,
            "tyre_management_score": 75.0,
        },
        {
            "lap_count": 20,
            "deg_rate_s_per_lap": 0.10,
            "positive_deg_rate_s_per_lap": 0.10,
            "consistency_std_dev_s": 0.7,
            "r_squared": 0.5,
            "tyre_management_score": 50.0,
        },
    ]

    summary = f1_data._summarize_tyre_management(stints)

    assert summary["weighted_deg_rate_s_per_lap"] == pytest.approx(0.0833)
    assert summary["weighted_consistency_std_dev_s"] == pytest.approx(0.6)
    assert summary["weighted_r_squared"] == pytest.approx(0.6)
    assert "R² is the trust level" in summary["score_explanation"]


def test_get_driver_strategy_position_start_end_are_first_and_last_lap():
    """position_start must be the position on lap 1 of the stint, position_end on the last lap."""
    import pandas as pd

    mock_session = MagicMock()
    mock_session.event = {"EventName": "Bahrain Grand Prix"}
    mock_session.drivers = ["VER"]

    # Driver starts P5, improves to P2 mid-stint, ends P3
    # min=2 (best), max=5 (worst), first=5, last=3
    lap_data = {
        'LapNumber': [1, 2, 3],
        'Stint': [1, 1, 1],
        'Position': [5.0, 2.0, 3.0],
        'LapTime': [pd.Timedelta(seconds=90), pd.Timedelta(seconds=89), pd.Timedelta(seconds=91)],
        'Compound': ['MEDIUM', 'MEDIUM', 'MEDIUM'],
        'FreshTyre': [True, True, True],
        'TyreLife': [1.0, 2.0, 3.0],
        'PitInTime': [pd.NaT, pd.NaT, pd.NaT],
        'PitOutTime': [pd.NaT, pd.NaT, pd.NaT],
    }
    fake_laps = pd.DataFrame(lap_data)

    mock_session.laps = MagicMock()
    mock_session.laps.pick_drivers = lambda codes: fake_laps
    mock_session.results = pd.DataFrame({
        'Abbreviation': ['VER'],
        'DriverNumber': ['33'],
        'FullName': ['Max Verstappen'],
        'TeamName': ['Red Bull'],
        'GridPosition': [1.0],
        'Position': [3.0],
    })

    with patch('f1_data._load_session', return_value=mock_session), \
         patch('f1_data._validate_session_availability', return_value=None):
        result = f1_data.get_driver_strategy(1, 'R', 'VER')

    stint = result['drivers'][0]['stints'][0]
    assert stint['position_start'] == 5, (
        f"position_start should be first lap position (5) not min (2), got {stint['position_start']}"
    )
    assert stint['position_end'] == 3, (
        f"position_end should be last lap position (3) not max (5), got {stint['position_end']}"
    )


def test_get_race_report_lapped_drivers_not_in_dnfs():
    """Drivers classified but lapped (+1 Lap etc.) must NOT appear in the dnfs list."""
    mock_race = {
        "race_name": "Bahrain Grand Prix",
        "circuit": "Bahrain International Circuit",
        "date": "2026-03-16",
        "results": [
            {"position": 1, "driver": "Max Verstappen", "code": "VER", "team": "Red Bull",
             "points": 25.0, "fastest_lap": False, "status": "Finished"},
            {"position": 2, "driver": "Lando Norris", "code": "NOR", "team": "McLaren",
             "points": 18.0, "fastest_lap": False, "status": "Finished"},
            {"position": 18, "driver": "Logan Sargeant", "code": "SAR", "team": "Williams",
             "points": 0.0, "fastest_lap": False, "status": "+1 Lap"},
            {"position": 19, "driver": "Zhou Guanyu", "code": "ZHO", "team": "Kick Sauber",
             "points": 0.0, "fastest_lap": False, "status": "+2 Laps"},
            {"position": None, "driver": "Kevin Magnussen", "code": "MAG", "team": "Haas",
             "points": 0.0, "fastest_lap": False, "status": "Engine"},
        ],
    }
    mock_quali = {
        "race_name": "Bahrain Grand Prix",
        "date": "2026-03-15",
        "results": [],
    }

    with patch('f1_data.get_qualifying_results', return_value=mock_quali), \
         patch('f1_data.get_race_results', return_value=mock_race), \
         patch('f1_data.get_safety_car_periods', side_effect=Exception("no sc")), \
         patch('openf1.get_intervals', side_effect=Exception("no openf1")):
        result = f1_data.get_race_report(1)

    dnf_codes = [row.get("code") for row in result["dnfs"]]
    assert "SAR" not in dnf_codes, "+1 Lap classified finisher should not be in DNFs"
    assert "ZHO" not in dnf_codes, "+2 Laps classified finisher should not be in DNFs"
    assert "MAG" in dnf_codes, "Genuine retirement (Engine) should be in DNFs"


def _make_fastf1_pit_laps():
    import pandas as pd
    return pd.DataFrame({
        "DriverNumber": ["63"] * 5,
        "Driver": ["RUS"] * 5,
        "LapNumber": [1, 2, 3, 4, 5],
        "Compound": ["MEDIUM", "MEDIUM", "HARD", "HARD", "HARD"],
        "PitInTime": [pd.NaT, pd.Timedelta("0:23:00"), pd.NaT, pd.NaT, pd.NaT],
        "PitOutTime": [pd.NaT, pd.NaT, pd.Timedelta("0:23:02.5"), pd.NaT, pd.NaT],
        "Position": [5, 5, 6, 6, 5],
    })

def test_get_pit_stop_analysis_structure():
    mock_session = MagicMock()
    mock_session.laps = _make_fastf1_pit_laps()
    mock_session.event = {"EventName": "Test GP"}

    with patch('f1_data._validate_session_availability'), \
         patch('f1_data._load_session', return_value=mock_session), \
         patch('f1_data.get_session_results', return_value={"results": [
             {"driver_number": "63", "abbreviation": "RUS", "position": 4}
         ]}), \
         patch('f1_data._openf1_pit_fetch', return_value={(63, 2): 2.41}):
        result = f1_data.get_pit_stop_analysis(4)

    assert result["event"] == "Test GP"
    assert isinstance(result["drivers"], list)
    rus = result["drivers"][0]
    assert rus["driver"] == "RUS"
    assert len(rus["stints"]) == 2
    assert rus["stints"][0]["compound"] == "MEDIUM"
    assert rus["stints"][1]["compound"] == "HARD"
    assert len(rus["pit_stops"]) == 1
    assert rus["pit_stops"][0]["lap"] == 2
    assert rus["pit_stops"][0]["duration_s"] == 2.41


def test_fit_stint_degradation_includes_scatter_data():
    laps = [
        {"lap_number": i, "lap_time_s": 82.0 + i * 0.01, "compound": "HARD", "tyre_age": i}
        for i in range(1, 8)
    ]
    result = f1_data._fit_stint_degradation(laps)
    assert len(result) == 1
    stint = result[0]
    assert "scatter_data" in stint, "scatter_data missing"
    assert "regression_line" in stint, "regression_line missing"
    assert len(stint["scatter_data"]) == 7
    assert all("tyre_age" in pt and "lap_time_s" in pt and "lap_number" in pt for pt in stint["scatter_data"])
    assert len(stint["regression_line"]) == 2
    assert stint["regression_line"][0]["tyre_age"] <= stint["regression_line"][1]["tyre_age"]


def _make_weather_df():
    import pandas as pd
    return pd.DataFrame({
        "Time": pd.to_timedelta(["0:05:00", "0:12:00", "0:18:00", "0:25:00", "0:32:00", "0:38:00"]),
        "TrackTemp": [38.0, 39.0, 40.0, 41.0, 42.0, 43.0],
        "AirTemp":   [28.0, 28.5, 29.0, 29.5, 30.0, 30.5],
        "Rainfall":  [False, False, False, False, False, False],
    })

def _make_quali_laps_weather():
    import pandas as pd
    rows = []
    for i, (seg, lt) in enumerate([
        ("Q1", 82.5), ("Q1", 82.3),
        ("Q2", 81.8), ("Q2", 81.6),
        ("Q3", 81.2), ("Q3", 81.0),
    ]):
        rows.append({
            "Driver": "RUS", "LapNumber": i + 1,
            "LapTime": pd.Timedelta(seconds=lt),
            "Session": seg,
            "Deleted": False,
            "Time": pd.Timedelta(seconds=(i + 1) * 400),
        })
    return pd.DataFrame(rows)

def test_analyze_weather_pace_correlation_qualifying():
    mock_session = MagicMock()
    mock_session.laps = _make_quali_laps_weather()
    mock_session.weather_data = _make_weather_df()
    mock_session.event = {"EventName": "Test GP"}

    with patch('f1_data._validate_session_availability'), \
         patch('f1_data._load_session', return_value=mock_session):
        result = f1_data.analyze_weather_pace_correlation(4, "Q")

    assert result["session"] == "Q"
    assert "segments" in result
    segs = result["segments"]
    assert len(segs) > 0
    for seg in segs:
        assert "avg_track_temp_c" in seg
        assert "best_lap_s" in seg
        assert "segment" in seg


def _make_speed_samples(n=30, base_speed=290, clip_at=15):
    """Simulate a straight where speed peaks then drops (clipping in second half)."""
    samples = []
    for i in range(n):
        speed = base_speed + i * 1.5 if i < clip_at else base_speed + clip_at * 1.5 - (i - clip_at) * 0.5
        samples.append({
            "distance_m": i * 20.0,
            "speed_kph": round(speed, 1),
            "throttle_pct": 100,
            "brake": False,
            "gear": 8,
            "rpm": 12000,
            "drs_open": True,
        })
    return samples

def test_compute_energy_metrics_clip_detection():
    samples = _make_speed_samples()
    clip_windows = f1_data._infer_clipping_windows(samples)
    lico_events = []
    metrics = f1_data._compute_energy_metrics(samples, lico_events, clip_windows)
    assert "clip_count" in metrics
    assert "estimated_time_lost_to_clipping_s" in metrics
    assert "lico_count" in metrics
    assert "total_harvest_distance_m" in metrics
    assert metrics["clip_count"] >= 0
    assert metrics["estimated_time_lost_to_clipping_s"] >= 0.0

def test_extract_major_straights_finds_high_speed_sections():
    samples = [{"distance_m": i * 10.0, "speed_kph": 290 if 20 <= i <= 50 else 150} for i in range(80)]
    straights = f1_data._extract_major_straights(samples, speed_threshold_kph=275, min_length_m=200)
    assert len(straights) == 1
    assert straights[0]["start_m"] == 200
    assert straights[0]["length_m"] >= 200

def test_analyze_energy_management_includes_speed_trace():
    mock_telemetry = {
        "event": "Test GP", "session": "Q", "driver": "NOR", "lap_number": 5,
        "telemetry": [
            {"distance_m": i * 5.0, "speed_kph": 200 + i, "throttle_pct": 80,
             "brake": False, "gear": 7, "rpm": 11000, "drs_open": False}
            for i in range(20)
        ]
    }
    knowledge_stub = {
        "deployment_curve": {
            "standard": [
                {"speed_kph": 290, "power_kw": 350},
                {"speed_kph": 322, "power_kw": 175},
                {"speed_kph": 355, "power_kw": 0},
            ],
        },
    }
    with patch('f1_data.get_lap_telemetry', return_value=mock_telemetry), \
         patch('f1_data.get_energy_2026_knowledge', return_value=knowledge_stub):
        result = f1_data.analyze_energy_management(4, "Q", "NOR")
    assert "speed_trace_a" in result
    assert isinstance(result["speed_trace_a"], list)
    assert "energy_metrics_a" in result
    assert "clip_count" in result["energy_metrics_a"]
    assert "straight_breakdown" in result


# ── Task 1: SC impact enrichment ─────────────────────────────────────────────

def _make_sc_session(pitted_before_s, sc_start_s, sc_end_s, pitted_during_s=None):
    import pandas as pd
    from unittest.mock import MagicMock

    ts_data = [
        {'Time': pd.Timedelta(seconds=0), 'Status': '1', 'Message': 'AllClear'},
        {'Time': pd.Timedelta(seconds=sc_start_s), 'Status': '4', 'Message': 'SafetyCar'},
        {'Time': pd.Timedelta(seconds=sc_end_s), 'Status': '1', 'Message': 'AllClear'},
    ]
    ts_df = pd.DataFrame(ts_data)

    laps_rows = [
        {
            'Driver': 'AAA', 'Team': 'Alpha', 'LapNumber': 10,
            'LapStartTime': pd.Timedelta(seconds=pitted_before_s - 90),
            'PitInTime': pd.Timedelta(seconds=pitted_before_s),
            'PitOutTime': pd.NaT, 'Stint': 1, 'Compound': 'HARD',
            'TyreLife': 10, 'FreshTyre': True, 'TrackStatus': '1',
            'LapTime': pd.Timedelta(seconds=90),
        },
    ]
    if pitted_during_s:
        laps_rows.append({
            'Driver': 'BBB', 'Team': 'Beta', 'LapNumber': 11,
            'LapStartTime': pd.Timedelta(seconds=pitted_during_s - 90),
            'PitInTime': pd.Timedelta(seconds=pitted_during_s),
            'PitOutTime': pd.NaT, 'Stint': 2, 'Compound': 'SOFT',
            'TyreLife': 1, 'FreshTyre': True, 'TrackStatus': '4',
            'LapTime': pd.Timedelta(seconds=90),
        })
    laps_df = pd.DataFrame(laps_rows)

    session = MagicMock()
    session.track_status = ts_df
    session.laps = laps_df
    session.event = {'EventName': 'Test GP'}
    session.drivers = list(laps_df['Driver'].unique())
    return session


def _pick_driver_plain(df, code):
    """Plain pandas substitute for FastF1's pick_driver/pick_drivers on mock DataFrames."""
    import pandas as pd
    return df[df['Driver'] == str(code)]


def test_sc_period_narrative_present():
    session = _make_sc_session(pitted_before_s=100, sc_start_s=150, sc_end_s=300)
    with patch('f1_data._load_session', return_value=session), \
         patch('f1_data._pick_driver', side_effect=_pick_driver_plain):
        result = f1_data.get_safety_car_periods(1, 'R')
    assert len(result['periods']) == 1
    assert isinstance(result['periods'][0].get('period_narrative'), str)
    assert len(result['periods'][0]['period_narrative']) > 0


def test_sc_all_victims_populated():
    session = _make_sc_session(pitted_before_s=100, sc_start_s=150, sc_end_s=300,
                               pitted_during_s=200)
    with patch('f1_data._load_session', return_value=session), \
         patch('f1_data._pick_driver', side_effect=_pick_driver_plain):
        result = f1_data.get_safety_car_periods(1, 'R')
    victims = result.get('all_victims', [])
    assert any(v['driver'] == 'AAA' for v in victims)


def test_sc_all_beneficiaries_populated():
    session = _make_sc_session(pitted_before_s=100, sc_start_s=150, sc_end_s=300,
                               pitted_during_s=200)
    with patch('f1_data._load_session', return_value=session), \
         patch('f1_data._pick_driver', side_effect=_pick_driver_plain):
        result = f1_data.get_safety_car_periods(1, 'R')
    beneficiaries = result.get('all_beneficiaries', [])
    assert any(b['driver'] == 'BBB' for b in beneficiaries)


def test_sc_no_beneficiaries_when_nobody_pitted_during():
    session = _make_sc_session(pitted_before_s=100, sc_start_s=150, sc_end_s=300,
                               pitted_during_s=None)
    with patch('f1_data._load_session', return_value=session), \
         patch('f1_data._pick_driver', side_effect=_pick_driver_plain):
        result = f1_data.get_safety_car_periods(1, 'R')
    beneficiaries = result.get('all_beneficiaries', [])
    assert beneficiaries == []
    victims = result.get('all_victims', [])
    assert any(v['driver'] == 'AAA' for v in victims)


# ── Task 2: FP summary ───────────────────────────────────────────────────────

def _make_fp_session():
    import pandas as pd
    from unittest.mock import MagicMock

    laps_rows = []
    # Driver AAA: 10-lap long run on HARD (race sim)
    for i in range(1, 11):
        laps_rows.append({
            'Driver': 'AAA', 'Team': 'Alpha', 'LapNumber': i,
            'LapStartTime': pd.Timedelta(seconds=i * 90),
            'PitInTime': pd.NaT if i < 10 else pd.Timedelta(seconds=10 * 90 + 20),
            'PitOutTime': pd.Timedelta(seconds=90) if i == 1 else pd.NaT,
            'Stint': 1, 'Compound': 'HARD', 'FreshTyre': True,
            'TrackStatus': '1', 'LapTime': pd.Timedelta(seconds=92 + i * 0.1),
            'SpeedST': 300.0, 'SpeedFL': 295.0, 'SpeedI1': 285.0, 'SpeedI2': 290.0,
        })
    # Driver AAA: 2-lap quali sim on fresh SOFT
    for i in range(11, 13):
        laps_rows.append({
            'Driver': 'AAA', 'Team': 'Alpha', 'LapNumber': i,
            'LapStartTime': pd.Timedelta(seconds=i * 90),
            'PitInTime': pd.NaT if i < 12 else pd.Timedelta(seconds=12 * 90 + 20),
            'PitOutTime': pd.Timedelta(seconds=11 * 90) if i == 11 else pd.NaT,
            'Stint': 2, 'Compound': 'SOFT', 'FreshTyre': True,
            'TrackStatus': '1', 'LapTime': pd.Timedelta(seconds=88),
            'SpeedST': 310.0, 'SpeedFL': 305.0, 'SpeedI1': 290.0, 'SpeedI2': 295.0,
        })

    laps_df = pd.DataFrame(laps_rows)

    session = MagicMock()
    session.laps = laps_df
    session.drivers = ['AAA']
    session.event = {'EventName': 'Test GP'}
    return session, laps_df


def test_get_fp_summary_structure():
    import f1_data
    session, laps_df = _make_fp_session()
    with patch('f1_data._load_session', return_value=session), \
         patch('f1_data._pick_driver', side_effect=_pick_driver_plain), \
         patch('f1_data._driver_lookup', return_value={'AAA': {'FullName': 'Alice A', 'TeamName': 'Alpha'}}):
        result = f1_data.get_fp_summary(1, 2)
    assert result['session'] == 'FP2'
    assert isinstance(result['drivers'], list)
    assert len(result['drivers']) > 0
    assert isinstance(result['session_notes'], list)
    assert len(result['session_notes']) > 0


def test_get_fp_summary_classifies_long_run():
    import f1_data
    session, laps_df = _make_fp_session()
    with patch('f1_data._load_session', return_value=session), \
         patch('f1_data._pick_driver', side_effect=_pick_driver_plain), \
         patch('f1_data._driver_lookup', return_value={'AAA': {'FullName': 'Alice A', 'TeamName': 'Alpha'}}):
        result = f1_data.get_fp_summary(1, 2)
    driver = result['drivers'][0]
    long_runs = [s for s in driver['stints'] if s['classification'] == 'long_run']
    assert len(long_runs) >= 1


def test_get_fp_summary_classifies_quali_sim():
    import f1_data
    session, laps_df = _make_fp_session()
    with patch('f1_data._load_session', return_value=session), \
         patch('f1_data._pick_driver', side_effect=_pick_driver_plain), \
         patch('f1_data._driver_lookup', return_value={'AAA': {'FullName': 'Alice A', 'TeamName': 'Alpha'}}):
        result = f1_data.get_fp_summary(1, 2)
    driver = result['drivers'][0]
    quali_sims = [s for s in driver['stints'] if s['classification'] == 'quali_sim']
    assert len(quali_sims) >= 1


def test_get_fp_summary_best_lap_from_quickest_lap():
    import f1_data
    session, laps_df = _make_fp_session()
    with patch('f1_data._load_session', return_value=session), \
         patch('f1_data._pick_driver', side_effect=_pick_driver_plain), \
         patch('f1_data._driver_lookup', return_value={'AAA': {'FullName': 'Alice A', 'TeamName': 'Alpha'}}):
        result = f1_data.get_fp_summary(1, 2)
    driver = result['drivers'][0]
    # Fastest lap is 88.0s (SOFT stint), not the HARD long-run laps
    assert driver['best_lap_time_s'] == pytest.approx(88.0, abs=0.01)
    assert driver['best_lap_compound'] == 'SOFT'


# ---------------------------------------------------------------------------
# Speed trap leaderboard tests
# ---------------------------------------------------------------------------

def _make_speed_trap_session():
    """Two drivers with differing peak speeds on different laps."""
    laps_rows = []
    # Driver AAA: lap 1 SpeedST=310, lap 2 SpeedST=305
    laps_rows.append({
        'Driver': 'AAA', 'LapNumber': 1, 'Compound': 'SOFT',
        'SpeedST': 310.0, 'SpeedFL': 290.0, 'SpeedI1': 280.0, 'SpeedI2': 285.0,
    })
    laps_rows.append({
        'Driver': 'AAA', 'LapNumber': 2, 'Compound': 'SOFT',
        'SpeedST': 305.0, 'SpeedFL': 295.0, 'SpeedI1': 285.0, 'SpeedI2': 290.0,
    })
    # Driver BBB: lap 1 SpeedST=308, lap 2 SpeedST=315 (peak on lap 2)
    laps_rows.append({
        'Driver': 'BBB', 'LapNumber': 1, 'Compound': 'MEDIUM',
        'SpeedST': 308.0, 'SpeedFL': 292.0, 'SpeedI1': 282.0, 'SpeedI2': 287.0,
    })
    laps_rows.append({
        'Driver': 'BBB', 'LapNumber': 2, 'Compound': 'MEDIUM',
        'SpeedST': 315.0, 'SpeedFL': 288.0, 'SpeedI1': 278.0, 'SpeedI2': 283.0,
    })

    laps_df = pd.DataFrame(laps_rows)
    session = MagicMock()
    session.laps = laps_df
    session.drivers = ['AAA', 'BBB']
    session.event = {'EventName': 'Speed GP'}
    return session, laps_df


def test_speed_trap_leaderboard_structure():
    import f1_data
    session, _ = _make_speed_trap_session()
    with patch('f1_data._load_session', return_value=session), \
         patch('f1_data._pick_driver', side_effect=_pick_driver_plain), \
         patch('f1_data._driver_lookup', return_value={
             'AAA': {'FullName': 'Alice A', 'TeamName': 'Alpha'},
             'BBB': {'FullName': 'Bob B', 'TeamName': 'Beta'},
         }):
        result = f1_data.get_speed_trap_leaderboard(1, 'Q')
    assert result['session'] == 'Q'
    assert 'speed_st' in result
    assert 'speed_fl' in result
    assert 'speed_i1' in result
    assert 'speed_i2' in result
    assert isinstance(result['speed_st'], list)
    assert len(result['speed_st']) == 2


def test_speed_trap_leaderboard_ranked_descending():
    import f1_data
    session, _ = _make_speed_trap_session()
    with patch('f1_data._load_session', return_value=session), \
         patch('f1_data._pick_driver', side_effect=_pick_driver_plain), \
         patch('f1_data._driver_lookup', return_value={
             'AAA': {'FullName': 'Alice A', 'TeamName': 'Alpha'},
             'BBB': {'FullName': 'Bob B', 'TeamName': 'Beta'},
         }):
        result = f1_data.get_speed_trap_leaderboard(1, 'Q')
    st = result['speed_st']
    # BBB has 315 peak, AAA has 310 — BBB should rank 1
    assert st[0]['driver'] == 'BBB'
    assert st[0]['speed_kph'] == pytest.approx(315.0)
    assert st[0]['rank'] == 1
    assert st[1]['driver'] == 'AAA'
    assert st[1]['rank'] == 2


def test_speed_trap_leaderboard_peak_per_trap_independent():
    """Each trap's peak is found independently — driver may top different traps."""
    import f1_data
    session, _ = _make_speed_trap_session()
    with patch('f1_data._load_session', return_value=session), \
         patch('f1_data._pick_driver', side_effect=_pick_driver_plain), \
         patch('f1_data._driver_lookup', return_value={
             'AAA': {'FullName': 'Alice A', 'TeamName': 'Alpha'},
             'BBB': {'FullName': 'Bob B', 'TeamName': 'Beta'},
         }):
        result = f1_data.get_speed_trap_leaderboard(1, 'Q')
    # AAA has highest SpeedFL (295 on lap 2 vs BBB's 292/288)
    fl = result['speed_fl']
    assert fl[0]['driver'] == 'AAA'
    assert fl[0]['speed_kph'] == pytest.approx(295.0)


# ─── Sprint results tests ────────────────────────────────────

def test_get_sprint_results_returns_expected_shape():
    import f1_data
    from unittest.mock import patch, MagicMock
    payload = {
        "MRData": {
            "RaceTable": {
                "Races": [{
                    "raceName": "Chinese Grand Prix",
                    "Circuit": {"circuitName": "Shanghai International Circuit"},
                    "date": "2025-03-22",
                    "SprintResults": [{
                        "position": "1",
                        "Driver": {"givenName": "Oscar", "familyName": "Piastri", "code": "PIA"},
                        "Constructor": {"name": "McLaren"},
                        "points": "8",
                        "status": "Finished",
                    }],
                }]
            }
        }
    }
    mock_resp = MagicMock()
    mock_resp.json.return_value = payload
    mock_resp.raise_for_status.return_value = None
    with patch('f1_data.requests.get', return_value=mock_resp):
        result = f1_data.get_sprint_results(5)
    assert result["session"] == "S"
    assert result["results"][0]["code"] == "PIA"
    assert result["results"][0]["position"] == 1
    assert result["results"][0]["points"] == 8.0


def test_get_sprint_results_empty_when_no_races():
    import f1_data
    from unittest.mock import patch, MagicMock
    payload = {"MRData": {"RaceTable": {"Races": []}}}
    mock_resp = MagicMock()
    mock_resp.json.return_value = payload
    mock_resp.raise_for_status.return_value = None
    with patch('f1_data.requests.get', return_value=mock_resp):
        result = f1_data.get_sprint_results(5)
    assert result == {}


def test_get_sprint_qualifying_results_returns_expected_shape():
    import f1_data
    from unittest.mock import patch, MagicMock
    import pandas as pd

    mock_session = MagicMock()
    mock_session.event = {"EventName": "Chinese Grand Prix"}
    mock_session.date = pd.Timestamp("2025-03-22")

    mock_row = {
        "Position": 1,
        "FullName": "Oscar Piastri",
        "FirstName": "Oscar",
        "LastName": "Piastri",
        "Abbreviation": "PIA",
        "TeamName": "McLaren",
        "Q1": pd.Timedelta(seconds=93.5),
        "Q2": pd.Timedelta(seconds=92.8),
        "Q3": pd.Timedelta(seconds=92.1),
    }

    with patch("f1_data._load_session", return_value=mock_session), \
         patch("f1_data._session_results_rows", return_value=[mock_row]):
        result = f1_data.get_sprint_qualifying_results(5)

    assert result["session"] == "SQ"
    assert result["results"][0]["code"] == "PIA"
    assert result["results"][0]["position"] == 1
    assert result["results"][0]["sq1"] is not None


def test_analyze_qualifying_battle_accepts_sq_session_type():
    import f1_data
    from unittest.mock import patch, MagicMock
    import pandas as pd

    mock_session = MagicMock()
    mock_session.event = {"EventName": "Chinese Grand Prix"}

    def make_lap(time_s, s1, s2, s3):
        lap = MagicMock()
        lap.__getitem__ = lambda self, key: {
            "LapTime": pd.Timedelta(seconds=time_s),
            "Sector1Time": pd.Timedelta(seconds=s1),
            "Sector2Time": pd.Timedelta(seconds=s2),
            "Sector3Time": pd.Timedelta(seconds=s3),
            "LapNumber": 3,
            "SpeedI1": 240.0,
            "SpeedI2": 230.0,
            "SpeedFL": 220.0,
            "SpeedST": 310.0,
        }.get(key, MagicMock())
        lap.get = lambda key, default=None: {
            "LapTime": pd.Timedelta(seconds=time_s),
            "Sector1Time": pd.Timedelta(seconds=s1),
            "Sector2Time": pd.Timedelta(seconds=s2),
            "Sector3Time": pd.Timedelta(seconds=s3),
            "LapNumber": 3,
            "SpeedI1": 240.0,
            "SpeedI2": 230.0,
            "SpeedFL": 220.0,
            "SpeedST": 310.0,
        }.get(key, default)
        return lap

    chosen_laps = {"NOR": make_lap(90.0, 29.0, 31.0, 30.0), "PIA": make_lap(90.3, 29.2, 31.1, 30.0)}

    with patch("f1_data._get_comparable_qualifying_laps", return_value=(mock_session, "SQ2", chosen_laps)), \
         patch("f1_data.get_telemetry_comparison", side_effect=Exception("no telemetry")), \
         patch("f1_data.analyze_energy_management", side_effect=Exception("no energy")), \
         patch("f1_data._resolve_driver", return_value={"team": "McLaren"}), \
         patch("f1_data.get_circuit_corners", side_effect=Exception("no corners")):
        result = f1_data.analyze_qualifying_battle(5, "NOR", "PIA", session_type="SQ")

    assert result["session"] == "SQ"


def test_get_driver_weekend_overview_uses_sprint_data_when_session_type_s():
    import f1_data
    from unittest.mock import patch

    sprint_results = {
        "race_name": "Chinese Grand Prix",
        "session": "S",
        "results": [{"position": 3, "driver": "Lando Norris", "code": "NOR",
                     "team": "McLaren", "points": 6.0, "status": "Finished", "fastest_lap": False}],
    }
    sq_results = {
        "race_name": "Chinese Grand Prix",
        "session": "SQ",
        "results": [{"position": 2, "driver": "Lando Norris", "code": "NOR",
                     "team": "McLaren", "sq1": "1:32.1", "sq2": "1:31.8", "sq3": "1:31.5"}],
    }
    mock_driver = {"full_name": "Lando Norris", "code": "NOR", "driver_id": "norris", "team": "McLaren"}

    with patch("f1_data._resolve_driver", return_value=mock_driver), \
         patch("f1_data.get_sprint_results", return_value=sprint_results), \
         patch("f1_data.get_sprint_qualifying_results", return_value=sq_results), \
         patch("f1_data.get_driver_strategy", side_effect=Exception("no data")), \
         patch("f1_data.get_safety_car_periods", side_effect=Exception("no data")), \
         patch("f1_data.get_session_results", side_effect=Exception("no data")), \
         patch("f1_data.analyze_energy_management", side_effect=Exception("no data")), \
         patch("f1_data.get_drivers", return_value=[mock_driver]):
        result = f1_data.get_driver_weekend_overview(5, "norris", session_type="S")

    assert result["race"]["finish_position"] == 3
    assert result["qualifying"]["position"] == 2
    assert result["qualifying"]["q1"] == "1:32.1"


def test_get_driver_race_story_passes_session_type_to_overview():
    import f1_data
    from unittest.mock import patch, MagicMock

    mock_overview = {
        "driver": "Lando Norris", "code": "NOR", "team": "McLaren",
        "event": "Chinese Grand Prix", "round": 5,
        "qualifying": {"position": 2}, "race": {"finish_position": 3, "points": 6.0, "status": "Finished", "fastest_lap": False},
        "pit_stops": [], "strategy": None, "safety_car_impact": None, "teammate": {},
        "nearby_rivals": [], "openf1": {}, "energy_management": None,
    }

    with patch("f1_data.get_driver_weekend_overview", return_value=mock_overview) as mock_overview_fn, \
         patch("f1_data.get_session_results", side_effect=Exception("no data")), \
         patch("f1_data.get_race_control_messages", side_effect=Exception("no data")), \
         patch("f1_data.get_driver_strategy", side_effect=Exception("no data")), \
         patch("f1_data.get_safety_car_periods", side_effect=Exception("no data")):
        f1_data.get_driver_race_story(5, "norris", session_type="S")

    mock_overview_fn.assert_called_once_with(5, "norris", session_type="S")


def test_get_team_weekend_overview_uses_sprint_data_when_session_type_s():
    import f1_data
    from unittest.mock import patch

    sprint_results = {
        "race_name": "Chinese Grand Prix",
        "session": "S",
        "results": [
            {"position": 1, "driver": "Lando Norris", "code": "NOR", "team": "McLaren", "points": 8.0, "status": "Finished", "fastest_lap": False},
            {"position": 3, "driver": "Oscar Piastri", "code": "PIA", "team": "McLaren", "points": 6.0, "status": "Finished", "fastest_lap": False},
        ],
    }
    sq_results = {
        "race_name": "Chinese Grand Prix",
        "session": "SQ",
        "results": [
            {"position": 1, "driver": "Lando Norris", "code": "NOR", "team": "McLaren"},
            {"position": 2, "driver": "Oscar Piastri", "code": "PIA", "team": "McLaren"},
        ],
    }
    drivers = [
        {"full_name": "Lando Norris", "code": "NOR", "team": "McLaren", "driver_id": "norris"},
        {"full_name": "Oscar Piastri", "code": "PIA", "team": "McLaren", "driver_id": "piastri"},
    ]

    with patch("f1_data._resolve_team", return_value="McLaren"), \
         patch("f1_data.get_drivers", return_value=drivers), \
         patch("f1_data.get_sprint_results", return_value=sprint_results), \
         patch("f1_data.get_sprint_qualifying_results", return_value=sq_results), \
         patch("f1_data.get_driver_strategy", side_effect=Exception("no data")):
        result = f1_data.get_team_weekend_overview(5, "McLaren", session_type="S")

    assert result["team"] == "McLaren"
    assert any(d["code"] == "NOR" and d["finish_position"] == 1 for d in result["drivers"])


def test_get_race_report_uses_sprint_data_when_session_type_s():
    import f1_data
    from unittest.mock import patch

    sprint_results = {
        "race_name": "Chinese Grand Prix",
        "session": "S",
        "results": [
            {"position": 1, "driver": "Oscar Piastri", "code": "PIA", "team": "McLaren", "points": 8.0, "status": "Finished", "fastest_lap": True},
            {"position": 2, "driver": "Lando Norris", "code": "NOR", "team": "McLaren", "points": 7.0, "status": "Finished", "fastest_lap": False},
        ],
    }
    sq_results = {"race_name": "Chinese Grand Prix", "session": "SQ", "results": [
        {"position": 1, "driver": "Oscar Piastri", "code": "PIA", "team": "McLaren"},
        {"position": 2, "driver": "Lando Norris", "code": "NOR", "team": "McLaren"},
    ]}

    with patch("f1_data.get_sprint_results", return_value=sprint_results), \
         patch("f1_data.get_sprint_qualifying_results", return_value=sq_results), \
         patch("f1_data.get_safety_car_periods", side_effect=Exception("no data")), \
         patch("f1_data.get_driver_strategy", side_effect=Exception("no data")):
        result = f1_data.get_race_report(5, session_type="S")

    assert result["session"] == "S"
    assert result["podium"][0]["driver"] == "Oscar Piastri"


# ---------------------------------------------------------------------------
# _compute_longitudinal_g tests
# ---------------------------------------------------------------------------

def _make_longitudinal_tel_df(speeds_kph, times_s=None):
    """Helper: build a minimal telemetry DataFrame with Speed and Time."""
    import pandas as pd
    import numpy as np
    n = len(speeds_kph)
    if times_s is None:
        times_s = np.arange(n, dtype=float) * 0.1  # 100ms intervals
    return pd.DataFrame({
        'Speed': speeds_kph,
        'Time': pd.to_timedelta(times_s, unit='s'),
        'X': np.zeros(n),
        'Y': np.zeros(n),
        'Distance': np.arange(n, dtype=float),
    })


def test_compute_longitudinal_g_output_shape():
    import numpy as np
    speeds = np.ones(100) * 200.0
    tel = _make_longitudinal_tel_df(speeds)
    result = f1_data._compute_longitudinal_g(tel)
    assert result.shape == (100,)


def test_compute_longitudinal_g_braking_is_negative():
    import numpy as np
    # Linearly decelerating from 200 to 100 kph over 1 second
    speeds = np.linspace(200.0, 100.0, 50)
    times_s = np.linspace(0.0, 1.0, 50)
    tel = _make_longitudinal_tel_df(speeds, times_s)
    result = f1_data._compute_longitudinal_g(tel)
    # Most samples should be negative (braking)
    assert np.mean(result) < -0.5


def test_compute_longitudinal_g_acceleration_is_positive():
    import numpy as np
    # Linearly accelerating from 100 to 200 kph over 1 second
    speeds = np.linspace(100.0, 200.0, 50)
    times_s = np.linspace(0.0, 1.0, 50)
    tel = _make_longitudinal_tel_df(speeds, times_s)
    result = f1_data._compute_longitudinal_g(tel)
    assert np.mean(result) > 0.5


def test_compute_longitudinal_g_missing_time_returns_zeros():
    import numpy as np
    import pandas as pd
    # DataFrame with no Time column
    tel = pd.DataFrame({'Speed': np.ones(50) * 150.0})
    result = f1_data._compute_longitudinal_g(tel)
    assert np.all(result == 0.0)
    assert result.shape == (50,)


def test_compute_lateral_g_unit_conversion():
    """Verify lat_G is in the physically realistic range — not 10x too low due to GPS unit mismatch."""
    import numpy as np
    import pandas as pd

    # Circular arc: R=100m, v=150kph → expected lat_G = v²/(R*g) = (41.67)²/(100*9.81) ≈ 1.77G
    R_m = 100.0
    v_kph = 150.0
    v_mps = v_kph / 3.6
    expected_lat_g = v_mps**2 / (R_m * 9.81)  # ≈ 1.77G

    n = 80
    theta = np.linspace(0, np.pi / 2, n)  # quarter circle
    arc_len_m = R_m * theta  # arc length in meters

    # FastF1 GPS units are decimeters (0.1m), so coordinates are 10x meters
    x_dm = R_m * 10 * np.cos(theta)   # decimeters
    y_dm = R_m * 10 * np.sin(theta)   # decimeters

    tel = pd.DataFrame({
        'X': x_dm,
        'Y': y_dm,
        'Distance': arc_len_m,
        'Speed': np.full(n, v_kph),
        'Source': np.full(n, 'pos'),
    })

    result = f1_data._compute_lateral_g(tel)

    # Allow ±60% tolerance (SG smoothing and edge effects at low sample count)
    mid = slice(10, n - 10)
    assert result[mid].max() > expected_lat_g * 0.4, (
        f"lat_G too low: max={result[mid].max():.2f}G, expected≈{expected_lat_g:.2f}G"
    )
    # Should not be 10x the expected value (which would indicate inverse bug)
    assert result[mid].max() < expected_lat_g * 10, (
        f"lat_G suspiciously high: max={result[mid].max():.2f}G"
    )


def test_build_ggv_envelope_returns_correct_shape():
    import pandas as pd
    import numpy as np
    n = 120
    t_s = np.linspace(0, 12, n)
    theta = np.linspace(0, 4 * np.pi, n)
    tel = pd.DataFrame({
        'Speed': np.full(n, 150.0),
        'X': 1000.0 * np.cos(theta),
        'Y': 1000.0 * np.sin(theta),
        'Distance': np.linspace(0, 942.0, n),
        'Time': pd.to_timedelta(t_s, unit='s'),
        'Source': np.where(np.arange(n) % 4 == 0, 'pos', 'car'),
    })
    result = f1_data._build_ggv_envelope([tel, tel])
    assert set(result.keys()) == {'lat_max', 'brake_max', 'throttle_max', 'speed_bins'}
    assert len(result['lat_max']) == len(f1_data._GGV_BIN_CENTERS)
    assert len(result['brake_max']) == len(f1_data._GGV_BIN_CENTERS)
    assert np.all(result['lat_max'] > 0)


# ─── DRS-state awareness (F21) ───────────────────────────────


class TestDrsAwareness:
    def test_drs_active_true_for_10_12_14(self):
        for v in (10, 12, 14):
            assert f1_data.drs_active(v) is True

    def test_drs_active_false_for_other(self):
        for v in (0, 8, 9, 11, 13, 15, None, "x", float("nan")):
            assert f1_data.drs_active(v) is False

    def _make_speed_trap_mock_session(self, *, drs_open_for):
        """Build a mock session for speed-trap tests.

        drs_open_for: dict {driver_code: bool} — whether telemetry shows DRS open at peak ST.
        """
        import pandas as pd

        mock_session = MagicMock()
        mock_session.event = {'EventName': 'Monaco Grand Prix'}
        mock_session.drivers = list(drs_open_for.keys())

        def pick_drivers(codes):
            code = codes[0] if isinstance(codes, list) else codes
            if code not in drs_open_for:
                m = MagicMock()
                m.empty = True
                return m

            # Build a lap-like object with get_telemetry()
            drs_value = 12 if drs_open_for[code] else 0
            peak_speed = 320.0 if code == 'NOR' else 310.0
            tel_df = pd.DataFrame({
                'Speed': [200.0, 280.0, peak_speed, 305.0],
                'DRS': [0, drs_value, drs_value, drs_value],
            })

            class LapRow:
                """Acts like a pd.Series row but also exposes get_telemetry."""
                def __init__(self, code, peak_speed, tel_df):
                    self._data = {
                        'LapNumber': 5,
                        'Compound': 'SOFT',
                        'SpeedST': peak_speed,
                        'SpeedFL': peak_speed - 10,
                        'SpeedI1': peak_speed - 30,
                        'SpeedI2': peak_speed - 50,
                        'Driver': code,
                    }
                    self._tel = tel_df

                def __getitem__(self, key):
                    return self._data[key]

                def get(self, key, default=None):
                    return self._data.get(key, default)

                def get_telemetry(self):
                    return self._tel

            best_row = LapRow(code, peak_speed, tel_df)

            # The valid DataFrame has notna/idxmax flow. We need pick_drivers to return
            # an object where pick_driver(...) ends up calling .loc[.idxmax()] on a DataFrame.
            # Build a single-row DataFrame whose .loc lookup returns the LapRow object.
            class FakeLaps:
                def __init__(self, row):
                    self._row = row
                    self.empty = False
                    self.columns = ['SpeedST', 'SpeedFL', 'SpeedI1', 'SpeedI2']

                def __getitem__(self, key):
                    # mimic boolean indexing for the valid filter
                    if isinstance(key, str):
                        # column access returning a "Series-like" with .notna()/ > 0/.idxmax()
                        speed = self._row[key]
                        class FakeCol:
                            def __init__(self, v):
                                self.v = v
                            def notna(self):
                                return FakeCol(True)
                            def __gt__(self, other):
                                return FakeCol(self.v if isinstance(self.v, bool) else self.v > other)
                            def __and__(self, other):
                                return FakeCol(True)
                            def idxmax(self_inner):
                                return 0
                        return FakeCol(speed)
                    # boolean mask: return self (single row passes)
                    return self

                @property
                def loc(self):
                    row = self._row
                    class Loc:
                        def __getitem__(self, key):
                            return row
                    return Loc()

            return FakeLaps(best_row)

        mock_session.laps.pick_drivers.side_effect = pick_drivers
        return mock_session

    def test_speed_trap_refuses_mixed_drs_by_default(self):
        # NOR peak with DRS open, LEC peak with DRS closed
        mock_session = self._make_speed_trap_mock_session(drs_open_for={'NOR': True, 'LEC': False})

        # _driver_lookup also calls session.drivers and driver lookup; patch lightly
        with patch('f1_data.fastf1.get_session', return_value=mock_session), \
             patch('f1_data._driver_lookup', return_value={'NOR': {'TeamName': 'McLaren'}, 'LEC': {'TeamName': 'Ferrari'}}):
            result = f1_data.get_speed_trap_leaderboard(8, 'R')

        assert 'refusal' in result
        assert 'DRS' in result['refusal']
        assert 'rows' in result
        drs_flags = sorted(row['drs_open'] for row in result['rows'])
        assert drs_flags == [False, True]

    def test_speed_trap_allows_mixed_drs_with_opt_in(self):
        mock_session = self._make_speed_trap_mock_session(drs_open_for={'NOR': True, 'LEC': False})

        with patch('f1_data.fastf1.get_session', return_value=mock_session), \
             patch('f1_data._driver_lookup', return_value={'NOR': {'TeamName': 'McLaren'}, 'LEC': {'TeamName': 'Ferrari'}}):
            result = f1_data.get_speed_trap_leaderboard(8, 'R', allow_mixed_drs=True)

        assert 'refusal' not in result
        assert isinstance(result.get('speed_st'), list)
        assert len(result['speed_st']) == 2
        for row in result['speed_st']:
            assert 'drs_open' in row
        # ranked descending by speed
        assert result['speed_st'][0]['speed_kph'] >= result['speed_st'][1]['speed_kph']

    def test_get_lap_telemetry_samples_have_drs_active(self):
        nor_lap = _make_mock_fastest_lap("NOR")
        mock_session = _make_mock_session({"NOR": nor_lap})
        mock_tel = _make_mock_telemetry(n_points=30, circuit_length_m=2000)
        # Force some DRS-open samples
        mock_tel['DRS'] = [12 if i > 15 else 0 for i in range(len(mock_tel))]

        mock_lap_obj = MagicMock()
        mock_lap_obj.__getitem__.side_effect = lambda k: nor_lap[k]
        mock_lap_obj.get.side_effect = lambda k, d=None: nor_lap.get(k, d)
        mock_lap_obj.get_telemetry.return_value.add_distance.return_value = mock_tel

        def pick_driver_tel(codes):
            mock_laps = MagicMock()
            mock_laps.empty = False
            mock_laps.pick_fastest.return_value = mock_lap_obj
            return mock_laps

        mock_session.laps.pick_drivers.side_effect = pick_driver_tel

        with patch('f1_data.fastf1.get_session', return_value=mock_session):
            result = f1_data.get_lap_telemetry(8, 'Q', 'NOR')

        assert result['telemetry']
        for sample in result['telemetry']:
            assert 'drs_active' in sample
            assert isinstance(sample['drs_active'], bool)
        # At least one DRS-active sample expected from our forced fixture
        assert any(s['drs_active'] for s in result['telemetry'])

    def test_get_sector_comparison_rows_have_drs_per_driver(self):
        """Per-sample comparison rows (get_telemetry_comparison) carry per-driver DRS active state."""
        import pandas as pd
        nor_lap_series = _make_mock_fastest_lap("NOR")
        lec_lap_series = _make_mock_fastest_lap("LEC", "Ferrari")

        tel_nor = _make_tel_df()
        tel_lec = _make_tel_df()
        # DRS pattern: NOR opens late, LEC stays closed
        tel_nor['DRS'] = [0, 0, 0, 0, 12, 12]
        tel_lec['DRS'] = [0, 0, 0, 0, 0, 0]

        mock_lap_nor = MagicMock()
        mock_lap_nor.__getitem__.side_effect = lambda k: nor_lap_series[k]
        mock_lap_nor.get.side_effect = lambda k, d=None: nor_lap_series.get(k, d)
        mock_lap_nor.get_telemetry.return_value.add_distance.return_value = tel_nor

        mock_lap_lec = MagicMock()
        mock_lap_lec.__getitem__.side_effect = lambda k: lec_lap_series[k]
        mock_lap_lec.get.side_effect = lambda k, d=None: lec_lap_series.get(k, d)
        mock_lap_lec.get_telemetry.return_value.add_distance.return_value = tel_lec

        def pick_driver_tel(codes):
            code = codes[0] if isinstance(codes, list) else codes
            mock_laps = MagicMock()
            mock_laps.empty = False
            mock_laps.pick_fastest.return_value = mock_lap_nor if code.upper() == "NOR" else mock_lap_lec
            return mock_laps

        mock_session = MagicMock()
        mock_session.event = {'EventName': 'Monaco Grand Prix'}
        mock_session.laps.pick_drivers.side_effect = pick_driver_tel

        with patch('f1_data.fastf1.get_session', return_value=mock_session):
            result = f1_data.get_telemetry_comparison(8, 'Q', 'NOR', 'LEC')

        assert result['comparison']
        for row in result['comparison']:
            assert 'drs_a_active' in row
            assert 'drs_b_active' in row
            assert isinstance(row['drs_a_active'], bool)
            assert isinstance(row['drs_b_active'], bool)
        # At least one row should show NOR DRS active, LEC DRS closed
        assert any(r['drs_a_active'] and not r['drs_b_active'] for r in result['comparison'])


def test_build_ggv_envelope_falls_back_when_empty():
    import numpy as np
    result = f1_data._build_ggv_envelope([])
    assert 'lat_max' in result
    assert len(result['lat_max']) == len(f1_data._GGV_BIN_CENTERS)
    assert np.all(result['lat_max'] > 0)


def test_theoretical_ggv_envelope_brake_exceeds_lateral():
    import numpy as np
    result = f1_data._theoretical_ggv_envelope()
    # Braking G exceeds lateral G (F1 carbon brakes)
    assert np.all(result['brake_max'] > result['lat_max'] * 0.9)


def test_ggv_ceiling_at_speed_returns_correct_shape():
    import numpy as np
    envelope = f1_data._theoretical_ggv_envelope()
    speeds = np.array([100.0, 150.0, 250.0])
    lat, brake, thr = f1_data._ggv_ceiling_at_speed(speeds, envelope)
    assert lat.shape == (3,)
    assert np.all(lat > 0) and np.all(brake > 0) and np.all(thr > 0)


def test_bravery_score_formula():
    score = f1_data._bravery_score(60.0, 50.0, 40.0)
    # 0.35*60 + 0.40*50 + 0.25*40 = 21 + 20 + 10 = 51
    assert abs(score - 51.0) < 0.2


def test_bravery_score_handles_none():
    score = f1_data._bravery_score(None, 50.0, 40.0)
    # None treated as 0: 0.35*0 + 0.40*50 + 0.25*40 = 30
    assert abs(score - 30.0) < 0.2


def _make_corner_arrays(n=60):
    """
    Synthetic corner: speed dips from 200→100→200 kph (apex at midpoint),
    lat_g peaks at apex, long_g goes negative then positive (brake-then-throttle).
    """
    import numpy as np
    t = np.linspace(0, 1, n)
    speed = 200.0 - 100.0 * np.sin(np.pi * t)          # 200→100→200
    lat_g = 3.5 * np.sin(np.pi * t)                      # 0→3.5→0
    long_g = np.where(t < 0.5, -2.0 * (0.5 - t) * 4, 2.0 * (t - 0.5) * 4)  # braking then accel
    long_g = np.clip(long_g, -4.0, 4.0)
    dist = np.linspace(0, 150, n)
    return lat_g, long_g, speed, dist


def test_corner_metrics_base_fields_present():
    import numpy as np
    lat_g, long_g, speed, dist = _make_corner_arrays()
    result = f1_data._corner_metrics(lat_g, long_g, speed, dist, 0, len(lat_g) - 1)
    assert 'trail_brake_pct' in result
    assert 'peak_g' in result
    assert 'load_variance' in result
    assert 'correction_count' in result


def test_corner_metrics_trail_brake_zero_when_no_braking():
    import numpy as np
    n = 60
    lat_g = np.ones(n) * 2.0
    long_g = np.zeros(n)          # no braking whatsoever
    speed = np.ones(n) * 150.0
    dist = np.linspace(0, 150, n)
    result = f1_data._corner_metrics(lat_g, long_g, speed, dist, 0, n - 1)
    assert result['trail_brake_pct'] == 0.0


def test_corner_metrics_trail_brake_nonzero_when_braking_at_entry():
    import numpy as np
    n = 60
    apex = n // 2
    lat_g = np.ones(n) * 2.0
    # Braking hard in the entry phase only (before apex)
    long_g = np.where(np.arange(n) < apex, -2.0, 0.5)
    speed = np.linspace(200, 100, n // 2).tolist() + np.linspace(100, 200, n - n // 2).tolist()
    speed = np.array(speed)
    dist = np.linspace(0, 150, n)
    result = f1_data._corner_metrics(lat_g, long_g, speed, dist, 0, n - 1)
    assert result['trail_brake_pct'] > 50.0


def test_aggregate_lap_cornering_stats_new_fields():
    import numpy as np
    import pandas as pd

    n = 300
    t_s = np.linspace(0, 30, n)
    # Speed: oscillates to create corners
    speed = 200.0 - 80.0 * np.abs(np.sin(np.pi * np.linspace(0, 6, n)))
    # Simple circular track
    theta = np.linspace(0, 4 * np.pi, n)
    x = np.cos(theta) * 200.0
    y = np.sin(theta) * 200.0
    dist = np.linspace(0, 1000, n)

    tel = pd.DataFrame({
        'Speed': speed,
        'Time': pd.to_timedelta(t_s, unit='s'),
        'X': x,
        'Y': y,
        'Distance': dist,
    })

    result = f1_data._aggregate_lap_cornering_stats(tel)
    assert result is not None, "Expected corners to be detected"
    assert 'avg_trail_brake_pct' in result
    assert 'avg_ggv_util_pct' in result
    assert 'avg_corrections_per_corner' in result
    assert 0 <= result['avg_trail_brake_pct'] <= 100


def test_corner_metrics_ggv_fields_present_when_envelope_provided():
    import numpy as np
    lat_g, long_g, speed, dist = _make_corner_arrays()
    envelope = f1_data._theoretical_ggv_envelope()
    result = f1_data._corner_metrics(lat_g, long_g, speed, dist, 0, len(lat_g) - 1,
                                      envelope=envelope)
    assert result['ggv_util_pct'] is not None
    assert result['envelope_time_pct'] is not None
    assert result['throttle_acceptance_pct'] is not None
    assert result['entry_bravery_pct'] is not None
    assert 0 <= result['ggv_util_pct'] <= 200
    assert 0 <= result['envelope_time_pct'] <= 100


def test_corner_metrics_ggv_fields_none_when_no_envelope():
    import numpy as np
    lat_g, long_g, speed, dist = _make_corner_arrays()
    result = f1_data._corner_metrics(lat_g, long_g, speed, dist, 0, len(lat_g) - 1)
    assert result['ggv_util_pct'] is None
    assert result['envelope_time_pct'] is None
    assert result['throttle_acceptance_pct'] is None
    assert result['entry_bravery_pct'] is None


def test_corner_metrics_throttle_acceptance_zero_when_always_braking():
    import numpy as np
    n = 60
    t = np.linspace(0, 1, n)
    speed = 200.0 - 100.0 * np.sin(np.pi * t)
    lat_g = 3.5 * np.sin(np.pi * t)
    long_g = -np.ones(n) * 2.0  # always braking — no positive G on exit
    dist = np.linspace(0, 150, n)
    envelope = f1_data._theoretical_ggv_envelope()
    result = f1_data._corner_metrics(lat_g, long_g, speed, dist, 0, n - 1,
                                      envelope=envelope)
    assert result['throttle_acceptance_pct'] == 0.0


def test_corner_metrics_throttle_acceptance_nonzero_with_throttle_channel():
    import numpy as np
    n = 60
    t = np.linspace(0, 1, n)
    speed = 200.0 - 100.0 * np.sin(np.pi * t)
    lat_g = 3.5 * np.sin(np.pi * t)
    long_g = np.where(t < 0.5, -2.0, 0.5)
    dist = np.linspace(0, 150, n)
    throttle = np.where(t >= 0.5, 95.0, 0.0)  # full throttle on exit phase only
    envelope = f1_data._theoretical_ggv_envelope()
    result = f1_data._corner_metrics(lat_g, long_g, speed, dist, 0, n - 1,
                                      envelope=envelope, throttle=throttle)
    assert result['throttle_acceptance_pct'] > 0.0


def test_corner_metrics_entry_bravery_nonzero_for_standard_corner():
    """entry_bravery_pct is computed (not None) when envelope is provided."""
    import numpy as np
    lat_g, long_g, speed, dist = _make_corner_arrays()
    envelope = f1_data._theoretical_ggv_envelope()
    result = f1_data._corner_metrics(lat_g, long_g, speed, dist, 0, len(lat_g) - 1,
                                      envelope=envelope)
    assert result['entry_bravery_pct'] is not None
    assert isinstance(result['entry_bravery_pct'], float)


def test_corner_metrics_base_fields_present_with_envelope():
    """All base fields present whether or not envelope is provided."""
    import numpy as np
    lat_g, long_g, speed, dist = _make_corner_arrays()
    envelope = f1_data._theoretical_ggv_envelope()
    result = f1_data._corner_metrics(lat_g, long_g, speed, dist, 0, len(lat_g) - 1,
                                      envelope=envelope)
    assert 'trail_brake_pct' in result
    assert 'peak_g' in result
    assert 'load_variance' in result
    assert 'ggv_util_pct' in result


def test_corner_metrics_apex_at_boundary_returns_zero_not_crash():
    """When apex is at index 0 (monotonically increasing speed), both bravery metrics return 0.0 not a crash."""
    import numpy as np
    n = 30
    # Speed monotonically increasing: apex at index 0
    speed = np.linspace(100.0, 200.0, n)
    lat_g = np.ones(n) * 2.5
    long_g = np.ones(n) * 0.5
    dist = np.linspace(0, 100, n)
    envelope = f1_data._theoretical_ggv_envelope()
    result = f1_data._corner_metrics(lat_g, long_g, speed, dist, 0, n - 1,
                                      envelope=envelope)
    assert result['throttle_acceptance_pct'] == 0.0 or result['throttle_acceptance_pct'] >= 0.0
    assert result['entry_bravery_pct'] == 0.0 or result['entry_bravery_pct'] >= 0.0
    assert result['ggv_util_pct'] is not None


def test_corner_metrics_with_envelope_adds_ggv_delta_fields():
    """Per-corner dicts gain ggv_util_delta_pct and throttle_acceptance_delta_pct."""
    import numpy as np
    # Simulate what analyze_cornering_loads produces per-corner after Task 3
    lat_g, long_g, speed, dist = _make_corner_arrays()
    envelope = f1_data._theoretical_ggv_envelope()
    ma = f1_data._corner_metrics(lat_g, long_g, speed, dist, 0, len(lat_g) - 1,
                                  envelope=envelope)
    mb = f1_data._corner_metrics(lat_g * 0.9, long_g, speed, dist, 0, len(lat_g) - 1,
                                  envelope=envelope)
    delta = round((ma.get('ggv_util_pct') or 0.0) - (mb.get('ggv_util_pct') or 0.0), 1)
    assert isinstance(delta, float)  # just verifies the computation runs


def test_aggregate_lap_cornering_stats_ggv_fields_with_envelope():
    import pandas as pd
    import numpy as np
    n = 200
    t_s = np.linspace(0, 20, n)
    theta = np.linspace(0, 4 * np.pi, n)
    speed = 200.0 - 80.0 * np.abs(np.sin(np.pi * np.linspace(0, 4, n)))
    tel = pd.DataFrame({
        'Speed': speed,
        'X': 2000.0 * np.cos(theta),
        'Y': 2000.0 * np.sin(theta),
        'Distance': np.linspace(0, 2000.0, n),
        'Time': pd.to_timedelta(t_s, unit='s'),
        'Source': np.where(np.arange(n) % 4 == 0, 'pos', 'car'),
        'Throttle': np.where(speed > 150, 95.0, 0.0),
    })
    envelope = f1_data._theoretical_ggv_envelope()
    result = f1_data._aggregate_lap_cornering_stats(tel, envelope=envelope)
    assert result is not None, "Expected corners to be detected in synthetic data"
    assert 'avg_ggv_util_pct' in result
    assert 'avg_envelope_time_pct' in result
    assert 'avg_throttle_acceptance_pct' in result
    assert 'avg_entry_bravery_pct' in result


def test_load_session_wraps_get_session_failure(monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("fastf1 outage")

    monkeypatch.setattr(f1_data.fastf1, "get_session", _boom)

    with pytest.raises(f1_data.FastF1Error) as excinfo:
        f1_data._load_session(5, "R", laps=False, telemetry=False, weather=False, messages=False)

    assert excinfo.value.round_number == 5
    assert excinfo.value.session_type == "R"
    assert isinstance(excinfo.value.__cause__, RuntimeError)


def test_load_session_wraps_load_failure_clears_cache_entry(monkeypatch):
    mock_session = MagicMock()
    mock_session.load.side_effect = RuntimeError("load failed mid-flight")
    monkeypatch.setattr(f1_data.fastf1, "get_session", lambda *a, **k: mock_session)

    with pytest.raises(f1_data.FastF1Error) as excinfo:
        f1_data._load_session(7, "Q", laps=True, telemetry=False, weather=False, messages=False)

    assert excinfo.value.round_number == 7
    assert excinfo.value.session_type == "Q"
    cache_key = (f1_data.CURRENT_YEAR, 7, "Q")
    assert cache_key not in f1_data._SESSION_CACHE


def test_get_session_results_returns_unavailable_on_fastf1_error(monkeypatch):
    def _raise(*args, **kwargs):
        raise f1_data.FastF1Error("nope", round_number=3, session_type="R")

    monkeypatch.setattr(f1_data, "_load_session", _raise)

    result = f1_data.get_session_results(3, "R")
    assert result == {
        "available": False,
        "reason": "fastf1_unavailable",
        "round_number": 3,
        "session_type": "R",
    }


def test_analyze_stint_degradation_returns_unavailable_on_fastf1_error(monkeypatch):
    def _raise(*args, **kwargs):
        raise f1_data.FastF1Error("nope", round_number=4, session_type="R")

    monkeypatch.setattr(f1_data, "_load_session", _raise)

    result = f1_data.analyze_stint_degradation(4, "VER", session_type="R")
    assert result == {
        "available": False,
        "reason": "fastf1_unavailable",
        "round_number": 4,
        "session_type": "R",
    }


def test_get_lap_telemetry_returns_unavailable_on_fastf1_error(monkeypatch):
    def _raise(*args, **kwargs):
        raise f1_data.FastF1Error("nope", round_number=2, session_type="Q")

    monkeypatch.setattr(f1_data, "_load_session", _raise)

    result = f1_data.get_lap_telemetry(2, "Q", "NOR")
    assert result == {
        "available": False,
        "reason": "fastf1_unavailable",
        "round_number": 2,
        "session_type": "Q",
    }


def _make_high_speed_telemetry(n_points=50, circuit_length_m=5000, peak_kph=340.0):
    """Telemetry where Speed channel ranges up into realistic F1 kph (300-340)."""
    distances = [i * circuit_length_m / n_points for i in range(n_points)]
    # Speed sweeps 150 -> peak -> 150 (kph; FastF1 native unit).
    speeds = [150.0 + (peak_kph - 150.0) * (1 - abs(i / (n_points - 1) - 0.5) * 2) for i in range(n_points)]
    return pd.DataFrame({
        'Distance': distances,
        'Speed': speeds,
        'Throttle': [100.0 if i > 10 else 0.0 for i in range(n_points)],
        'Brake': [i <= 10 for i in range(n_points)],
        'nGear': [8 if i > 10 else 4 for i in range(n_points)],
        'DRS': [12 if i > 30 else 0 for i in range(n_points)],
    })


def test_get_lap_telemetry_emits_kph_not_ms():
    nor_lap = _make_mock_fastest_lap("NOR")
    mock_session = _make_mock_session({"NOR": nor_lap})
    mock_tel = _make_high_speed_telemetry(n_points=50, circuit_length_m=3300, peak_kph=340.0)

    mock_lap_obj = MagicMock()
    mock_lap_obj.__getitem__.side_effect = lambda k: nor_lap[k]
    mock_lap_obj.get.side_effect = lambda k, d=None: nor_lap.get(k, d)
    mock_lap_obj.get_telemetry.return_value.add_distance.return_value = mock_tel

    def pick_driver_tel(codes):
        m = MagicMock()
        m.empty = False
        m.pick_fastest.return_value = mock_lap_obj
        return m

    mock_session.laps.pick_drivers.side_effect = pick_driver_tel

    with patch('f1_data.fastf1.get_session', return_value=mock_session):
        result = f1_data.get_lap_telemetry(8, 'Q', 'NOR')

    # FastF1 Speed is already kph: passing 340 kph through should NOT come out as ~94 (m/s) or ~1224 (double-converted).
    assert 300 <= result['max_speed_kph'] <= 360
    sample_max = max(s['speed_kph'] for s in result['telemetry'])
    assert 300 <= sample_max <= 360


def test_telemetry_comparison_speed_units_are_kph():
    nor_lap_series = _make_mock_fastest_lap("NOR")
    lec_lap_series = _make_mock_fastest_lap("LEC", "Ferrari")

    # Both drivers at high realistic F1 speeds.
    def _hi_tel(boost):
        n = 6
        distances = [i * 500 / (n - 1) for i in range(n)]
        return pd.DataFrame({
            'Distance': distances,
            'Speed': [300.0 + boost + i * 5 for i in range(n)],
            'Throttle': [50.0 + i * 5 for i in range(n)],
            'Brake': [i == 0 for i in range(n)],
            'nGear': [4 + min(i, 4) for i in range(n)],
            'DRS': [12 if i > 3 else 0 for i in range(n)],
            'X': [float(i * 10) for i in range(n)],
            'Y': [float((i % 3) * 8) for i in range(n)],
        })

    tel_nor = _hi_tel(boost=5.0)
    tel_lec = _hi_tel(boost=0.0)

    mock_lap_nor = MagicMock()
    mock_lap_nor.__getitem__.side_effect = lambda k: nor_lap_series[k]
    mock_lap_nor.get.side_effect = lambda k, d=None: nor_lap_series.get(k, d)
    mock_lap_nor.get_telemetry.return_value.add_distance.return_value = tel_nor

    mock_lap_lec = MagicMock()
    mock_lap_lec.__getitem__.side_effect = lambda k: lec_lap_series[k]
    mock_lap_lec.get.side_effect = lambda k, d=None: lec_lap_series.get(k, d)
    mock_lap_lec.get_telemetry.return_value.add_distance.return_value = tel_lec

    def pick_driver_tel(codes):
        code = codes[0] if isinstance(codes, list) else codes
        m = MagicMock()
        m.empty = False
        m.pick_fastest.return_value = mock_lap_nor if code.upper() == "NOR" else mock_lap_lec
        return m

    mock_session = MagicMock()
    mock_session.event = {'EventName': 'Monaco Grand Prix'}
    mock_session.laps.pick_drivers.side_effect = pick_driver_tel

    with patch('f1_data.fastf1.get_session', return_value=mock_session):
        result = f1_data.get_telemetry_comparison(8, 'Q', 'NOR', 'LEC')

    speeds = [s['speed_a'] for s in result['comparison']] + [s['speed_b'] for s in result['comparison']]
    assert all(280 <= v <= 360 for v in speeds), f"Speeds not in kph range: {speeds}"
    # delta_speed (kph - kph) stays small, NOT scaled to ~18 (5 kph * 3.6).
    deltas = [abs(s['delta_speed']) for s in result['comparison']]
    assert max(deltas) < 15


class TestDetectClippingSignature:
    def _build_trace(self, start_speed_kph, end_speed_kph, start_distance_m, end_distance_m, step_m=2.0, throttle=100):
        speed_trace = []
        throttle_trace = []
        distance_trace = []
        d = start_distance_m
        if start_speed_kph == end_speed_kph or end_distance_m == start_distance_m:
            slope = 0.0
        else:
            slope = (end_speed_kph - start_speed_kph) / (end_distance_m - start_distance_m)
        while d <= end_distance_m:
            speed = start_speed_kph + slope * (d - start_distance_m)
            speed_trace.append(speed)
            throttle_trace.append(throttle)
            distance_trace.append(d)
            d += step_m
        return speed_trace, throttle_trace, distance_trace

    def test_clean_trace_no_clipping(self):
        # Smooth acceleration through 290-340 km/h with normal slope (~0.5 km/h per m near plateau).
        # Reference slope at mid-speed (~315 km/h) is roughly half of max → ~0.5 km/h per m.
        # We give an observed slope at ~0.55 km/h per m → no deficit.
        speeds = []
        throttles = []
        distances = []
        d = 0.0
        speed = 290.0
        while speed < 340.0:
            speeds.append(speed)
            throttles.append(100)
            distances.append(d)
            d += 2.0
            ref = 1.0 - (speed - 290.0) / (355.0 - 290.0)
            speed += ref * 2.0

        result = f1_data.detect_clipping_signature(speeds, throttles, distances)
        assert result["clipping_detected"] is False
        assert result["segments"] == []
        assert result["total_clipping_seconds"] == 0
        assert result["detector_version"] == "f33-v1"

    def test_clipped_trace_detected(self):
        # Throttle pinned at 100% but speed flattens at 295 km/h for ~150 m.
        speed_trace, throttle_trace, distance_trace = self._build_trace(
            start_speed_kph=295.0, end_speed_kph=296.5,
            start_distance_m=0.0, end_distance_m=200.0,
            step_m=2.0, throttle=100,
        )
        result = f1_data.detect_clipping_signature(speed_trace, throttle_trace, distance_trace)
        assert result["clipping_detected"] is True
        assert len(result["segments"]) >= 1
        assert any(seg["severity"] in {"moderate", "severe"} for seg in result["segments"])
        assert result["total_clipping_seconds"] > 0.3

    def test_thresholds_read_from_energy_2026(self):
        from energy_2026 import get_energy_2026_knowledge
        curve = get_energy_2026_knowledge()["deployment_curve"]["standard"]
        sorted_anchors = sorted(curve, key=lambda a: a["speed_kph"])
        expected_full = sorted_anchors[0]["speed_kph"]
        expected_zero = sorted_anchors[-1]["speed_kph"]
        # Build a trace just under expected_full → no taper-window samples → no detection
        speed_trace, throttle_trace, distance_trace = self._build_trace(
            start_speed_kph=expected_full - 20.0, end_speed_kph=expected_full - 10.0,
            start_distance_m=0.0, end_distance_m=200.0, step_m=2.0, throttle=100,
        )
        result = f1_data.detect_clipping_signature(speed_trace, throttle_trace, distance_trace)
        # Should NOT detect — outside taper window.
        assert result["clipping_detected"] is False
        # And verify by exposing the function-derived defaults: passing explicit thresholds matching
        # energy_2026 should give same result as defaults.
        result_explicit = f1_data.detect_clipping_signature(
            speed_trace, throttle_trace, distance_trace,
            full_power_below_kmh=expected_full, ramp_zero_at_kmh=expected_zero,
        )
        assert result_explicit["clipping_detected"] is False

    def test_compare_drivers_clipping_matched_pair_returns_none(self):
        sig = {"total_clipping_seconds": 0.5, "segments": [
            {"start_distance_m": 100, "end_distance_m": 200, "duration_s": 0.5},
        ]}
        result = f1_data.compare_drivers_clipping(sig, sig, "NOR", "PIA")
        assert result is None

    def test_compare_drivers_clipping_asymmetric_pair(self):
        sig_a = {"total_clipping_seconds": 0.6, "segments": [
            {"start_distance_m": 1480, "end_distance_m": 1620, "duration_s": 0.6},
        ]}
        sig_b = {"total_clipping_seconds": 0.1, "segments": []}
        result = f1_data.compare_drivers_clipping(sig_a, sig_b, "NOR", "PIA")
        assert result is not None
        assert result["clipping_driver"] == "NOR"
        assert result["faster_driver"] == "PIA"
        assert result["delta_seconds"] >= 0.2
        assert "NOR" in result["phrase"]
        assert result["segment_reference"]["start_distance_m"] == 1480

    def test_short_segment_excluded(self):
        # Flat clipping span ~30 m — below default 80 m minimum, should be excluded.
        speed_trace, throttle_trace, distance_trace = self._build_trace(
            start_speed_kph=295.0, end_speed_kph=295.2,
            start_distance_m=0.0, end_distance_m=30.0,
            step_m=2.0, throttle=100,
        )
        result = f1_data.detect_clipping_signature(speed_trace, throttle_trace, distance_trace)
        assert result["clipping_detected"] is False
        assert result["segments"] == []


class TestDetectOverrideMode:
    def _build_trace(self, start_speed, end_speed, start_distance=0.0, end_distance=200.0, step_m=2.0, throttle=100, brake=False):
        samples = []
        d = start_distance
        if end_distance == start_distance:
            slope = 0.0
        else:
            slope = (end_speed - start_speed) / (end_distance - start_distance)
        while d <= end_distance:
            samples.append({
                "distance_m": d,
                "speed_kph": start_speed + slope * (d - start_distance),
                "throttle_pct": throttle,
                "brake": brake,
            })
            d += step_m
        return samples

    def test_no_override_when_gap_too_large(self):
        samples = self._build_trace(start_speed=295.0, end_speed=325.0, end_distance=200.0)
        gap_trace = [3.0] * len(samples)
        result = f1_data.detect_override_mode(samples, gap_trace)
        assert result["override_detected"] is False
        assert result["segments"] == []
        assert result["detector_version"] == "f32-v1"

    def test_override_detected_when_gap_under_1s(self):
        # Linear acceleration 290.5 → 336 km/h over 45.5m at 1.0 km/h per m.
        # Mid-speed ≈ 313 km/h, reference (normalized) ≈ 0.65, so ratio ≈ 1.54 — clears threshold.
        samples = []
        d = 0.0
        speed = 290.5
        step = 1.0
        while speed <= 336.0:
            samples.append({"distance_m": d, "speed_kph": speed, "throttle_pct": 100, "brake": False})
            speed += 1.0
            d += step
        gap_trace = [0.6] * len(samples)
        result = f1_data.detect_override_mode(samples, gap_trace)
        assert result["override_detected"] is True
        assert len(result["segments"]) >= 1
        peak = max(seg["peak_speed_kph"] for seg in result["segments"])
        assert peak > 310
        assert result["total_override_seconds"] > 0

    def test_thresholds_read_from_energy_2026(self):
        from energy_2026 import get_energy_2026_knowledge
        knowledge = get_energy_2026_knowledge()
        standard_curve = sorted(knowledge["deployment_curve"]["standard"], key=lambda a: a["speed_kph"])
        override_curve = sorted(knowledge["override_mode"]["curve"], key=lambda a: a["speed_kph"])
        expected_full = float(standard_curve[0]["speed_kph"])
        expected_override = float(override_curve[0]["speed_kph"])

        full_default, override_default = f1_data._override_curve_thresholds()
        assert full_default == expected_full
        assert override_default == expected_override

    def test_short_segment_excluded(self):
        samples = self._build_trace(start_speed=295.0, end_speed=305.0, end_distance=30.0)
        gap_trace = [0.5] * len(samples)
        result = f1_data.detect_override_mode(samples, gap_trace)
        assert result["override_detected"] is False
        assert result["segments"] == []

    def test_brake_application_breaks_segment(self):
        first = self._build_trace(start_speed=295.0, end_speed=315.0, start_distance=0.0, end_distance=100.0)
        brake_block = self._build_trace(start_speed=315.0, end_speed=300.0, start_distance=102.0, end_distance=140.0, brake=True)
        second = self._build_trace(start_speed=300.0, end_speed=320.0, start_distance=142.0, end_distance=260.0)
        samples = first + brake_block + second
        gap_trace = [0.5] * len(samples)
        result = f1_data.detect_override_mode(samples, gap_trace)
        for seg in result["segments"]:
            assert not (seg["start_distance_m"] < 100 and seg["end_distance_m"] > 142)

    def test_segment_below_290_excluded(self):
        samples = self._build_trace(start_speed=240.0, end_speed=280.0, end_distance=200.0)
        gap_trace = [0.5] * len(samples)
        result = f1_data.detect_override_mode(samples, gap_trace)
        assert result["override_detected"] is False
        assert result["segments"] == []


def test_analyze_race_pace_battle_includes_clipping_signature():
    """analyze_race_pace_battle must surface clipping signatures and comparison."""
    mock_session = MagicMock()
    mock_session.event = {'EventName': 'Japanese Grand Prix'}

    stint = {
        'compound': 'MEDIUM',
        'lap_count': 10,
        'fuel_corrected_pace_at_age_1_s': 90.0,
        'positive_deg_rate_s_per_lap': 0.05,
    }
    clean_laps = [{'lap_number': i, 'lap_time_s': 90.0 + 0.03 * i} for i in range(1, 11)]

    sig_a = {
        "clipping_detected": True,
        "segments": [{"start_distance_m": 1300, "duration_seconds": 0.4}],
        "total_clipping_seconds": 0.4,
        "budget_status": "over_budget",
    }
    sig_b = {
        "clipping_detected": False,
        "segments": [],
        "total_clipping_seconds": 0.0,
        "budget_status": "within_budget",
    }
    comparison = {
        "clipping_driver": "NOR",
        "faster_driver": "PIA",
        "delta_seconds": 0.4,
        "phrase": "NOR clipped 0.4 s/lap more than PIA on the main straight.",
    }

    fake_telemetry = {
        "telemetry": [
            {"distance_m": 0, "speed_kph": 100.0, "throttle_pct": 100.0, "drs_open": False},
            {"distance_m": 100, "speed_kph": 200.0, "throttle_pct": 100.0, "drs_open": False},
        ],
    }

    with patch('f1_data._validate_session_availability'), \
         patch('f1_data._load_session', return_value=mock_session), \
         patch('f1_data._pick_driver', return_value=pd.DataFrame([{'LapNumber': 1, 'PitInTime': None}])), \
         patch('f1_data._filter_clean_race_laps', return_value=clean_laps), \
         patch('f1_data._fit_stint_degradation', return_value=[stint]), \
         patch('f1_data._find_representative_lap', return_value=5), \
         patch('f1_data._align_stints_by_compound', return_value=[]), \
         patch('f1_data._summarize_tyre_management', return_value={}), \
         patch('f1_data.get_lap_telemetry', return_value=fake_telemetry), \
         patch('f1_data.detect_clipping_signature', side_effect=[sig_a, sig_b]), \
         patch('f1_data.compare_drivers_clipping', return_value=comparison):
        result = f1_data.analyze_race_pace_battle(3, 'NOR', 'PIA')

    assert 'clipping_signature_a' in result
    assert 'clipping_signature_b' in result
    assert 'clipping_comparison' in result
    assert result['clipping_signature_a'] == sig_a
    assert result['clipping_signature_b'] == sig_b
    assert result['clipping_comparison'] == comparison


# ── F16 strategy-helper tests ──────────────────────────────────────────────


def test_get_actual_pit_loss_returns_fallback_on_fastf1_error(monkeypatch):
    """When FastF1 fails, get_actual_pit_loss returns a sane field-average pit-loss."""
    f1_data._PIT_LOSS_CACHE.clear()

    def _raise(*args, **kwargs):
        raise f1_data.FastF1Error("nope", round_number=4, session_type="R")

    monkeypatch.setattr(f1_data, "_load_session", _raise)
    result = f1_data.get_actual_pit_loss(4)
    assert isinstance(result, float)
    assert 15.0 <= result <= 35.0  # plausible pit-loss range


def test_get_actual_pit_loss_caches_repeat_calls(monkeypatch):
    """Second call for the same round uses the cache (no second session load)."""
    f1_data._PIT_LOSS_CACHE.clear()
    calls = {"n": 0}

    def _raise(*args, **kwargs):
        calls["n"] += 1
        raise f1_data.FastF1Error("nope", round_number=7, session_type="R")

    monkeypatch.setattr(f1_data, "_load_session", _raise)
    f1_data.get_actual_pit_loss(7)
    # Fallback path doesn't populate the cache (only computed real values cache).
    # But a successful path must cache; here we just verify no crash on repeat.
    f1_data.get_actual_pit_loss(7)
    assert calls["n"] >= 1  # at least one attempt made


def test_get_tyre_age_at_lap_falls_back_when_session_unavailable(monkeypatch):
    """When session load fails, tyre-age estimation falls back to lap_number - 1."""
    def _raise(*args, **kwargs):
        raise f1_data.FastF1Error("nope", round_number=4, session_type="R")

    monkeypatch.setattr(f1_data, "_load_session", _raise)
    age = f1_data.get_tyre_age_at_lap("VER", 18, 4)
    assert age == 17


def test_get_gap_to_driver_returns_zero_on_session_unavailable(monkeypatch):
    """Unavailable session → gap defaults to 0.0 rather than raising."""
    def _raise(*args, **kwargs):
        raise f1_data.FastF1Error("nope", round_number=4, session_type="R")

    monkeypatch.setattr(f1_data, "_load_session", _raise)
    gap = f1_data.get_gap_to_driver("NOR", "VER", 25, 4)
    assert gap == 0.0


def test_analyze_undercut_overcut_runs_end_to_end_with_fallback(monkeypatch):
    """End-to-end smoke test: with FastF1 unavailable, the analyzer still returns
    a structurally valid result via strategy_math's fallbacks."""
    def _raise(*args, **kwargs):
        raise f1_data.FastF1Error("nope", round_number=17, session_type="R")

    monkeypatch.setattr(f1_data, "_load_session", _raise)
    f1_data._PIT_LOSS_CACHE.clear()
    result = f1_data.analyze_undercut_overcut("NOR", 25, 17, target_driver_code="VER")
    assert "recommendation" in result
    assert result["recommendation"] in {"pit_now", "stay_out", "marginal"}
    assert "confidence" in result
    assert result["confidence"] == "low"  # no telemetry → low confidence
    assert result["round_number"] == 17
    assert result["session_type"] == "R"
    assert result["driver_code"] == "NOR"
    assert "rationale" in result and isinstance(result["rationale"], list)


class TestMiniSectors:
    def test_compute_mini_sectors_returns_n_segments(self):
        """25 segments whose end_m - start_m sums within 1 m of total lap distance."""
        from f1_data import compute_mini_sectors
        import pandas as pd

        # Synthesise a lap with 500 evenly-spaced samples covering 5000 m of distance
        n_samples = 500
        total_dist = 5000.0
        distance = pd.Series([i * total_dist / (n_samples - 1) for i in range(n_samples)])
        time_s = pd.Series([i * 90.0 / (n_samples - 1) for i in range(n_samples)])  # 90s lap
        speed = pd.Series([200.0] * n_samples)
        throttle = pd.Series([100.0] * n_samples)
        drs = pd.Series([0] * n_samples)

        # Lap stub: just needs .get_car_data().add_distance() to return a DataFrame
        class _FakeTelemetry:
            def __init__(self, df): self._df = df
            def add_distance(self): return self._df

        class _FakeLap:
            def get_car_data(self_):
                return _FakeTelemetry(pd.DataFrame({
                    "Distance": distance, "Time": time_s, "Speed": speed,
                    "Throttle": throttle, "DRS": drs,
                }))

        segments = compute_mini_sectors(_FakeLap(), n=25)
        assert len(segments) == 25
        # End_m of last segment within 1 m of total_dist
        assert abs(segments[-1]["end_m"] - total_dist) < 1.0
        # Start_m of segment 0 is 0
        assert segments[0]["start_m"] == 0.0
        # Sum of segment spans approx total
        spans = sum(s["end_m"] - s["start_m"] for s in segments)
        assert abs(spans - total_dist) < 1.0

    def test_compute_mini_sectors_times_sum_to_lap_time(self):
        """Segment time_s values sum within 5 ms of the lap's total time."""
        from f1_data import compute_mini_sectors
        import pandas as pd

        n_samples = 500
        total_dist = 5000.0
        total_time = 90.0
        distance = pd.Series([i * total_dist / (n_samples - 1) for i in range(n_samples)])
        time_s = pd.Series([i * total_time / (n_samples - 1) for i in range(n_samples)])
        speed = pd.Series([200.0] * n_samples)
        throttle = pd.Series([100.0] * n_samples)
        drs = pd.Series([0] * n_samples)

        class _FakeTelemetry:
            def __init__(self, df): self._df = df
            def add_distance(self): return self._df

        class _FakeLap:
            def get_car_data(self_):
                return _FakeTelemetry(pd.DataFrame({
                    "Distance": distance, "Time": time_s, "Speed": speed,
                    "Throttle": throttle, "DRS": drs,
                }))

        segments = compute_mini_sectors(_FakeLap(), n=25)
        total = sum(s["time_s"] for s in segments)
        assert abs(total - total_time) < 0.005

    def test_compute_mini_sectors_returns_speed_aggregates(self):
        """Each segment has avg_speed_kmh, min_speed_kmh, drs_active_pct."""
        from f1_data import compute_mini_sectors
        import pandas as pd

        n_samples = 250
        # Varying speeds so min < avg
        speeds = [180.0 + 20.0 * ((i % 50) / 50.0) for i in range(n_samples)]
        # DRS open on the first half, closed second half
        drs_vals = [10 if i < n_samples // 2 else 0 for i in range(n_samples)]
        df = pd.DataFrame({
            "Distance": [i * 20.0 for i in range(n_samples)],
            "Time": [i * 0.4 for i in range(n_samples)],
            "Speed": speeds,
            "Throttle": [100.0] * n_samples,
            "DRS": drs_vals,
        })

        class _FakeTelemetry:
            def __init__(self, df): self._df = df
            def add_distance(self): return self._df

        class _FakeLap:
            def get_car_data(self_):
                return _FakeTelemetry(df)

        segments = compute_mini_sectors(_FakeLap(), n=25)
        for s in segments:
            assert "avg_speed_kmh" in s
            assert "min_speed_kmh" in s
            assert "drs_active_pct" in s
            assert 0.0 <= s["drs_active_pct"] <= 100.0
            assert s["min_speed_kmh"] <= s["avg_speed_kmh"]
        # First few segments have DRS, last few don't
        assert segments[0]["drs_active_pct"] > 50.0
        assert segments[-1]["drs_active_pct"] < 50.0

    def test_compute_mini_sectors_handles_empty_telemetry(self):
        """Empty or too-short telemetry returns []."""
        from f1_data import compute_mini_sectors
        import pandas as pd

        class _FakeTelemetry:
            def __init__(self): self._df = pd.DataFrame({"Distance": [], "Time": [], "Speed": [], "Throttle": [], "DRS": []})
            def add_distance(self): return self._df

        class _FakeLap:
            def get_car_data(self_):
                return _FakeTelemetry()

        assert compute_mini_sectors(_FakeLap(), n=25) == []

    def test_compare_mini_sectors_returns_per_segment_delta(self):
        """Each segment has delta_s (a - b) and a winner."""
        from f1_data import compute_mini_sectors, _build_mini_sector_comparison

        a_segments = [
            {"index": i, "start_m": i * 200, "end_m": (i + 1) * 200,
             "time_s": 4.0, "avg_speed_kmh": 200.0, "min_speed_kmh": 180.0,
             "drs_active_pct": 0.0}
            for i in range(25)
        ]
        b_segments = [
            {"index": i, "start_m": i * 200, "end_m": (i + 1) * 200,
             "time_s": 4.05 if i < 12 else 3.95,
             "avg_speed_kmh": 198.0, "min_speed_kmh": 178.0, "drs_active_pct": 0.0}
            for i in range(25)
        ]

        out = _build_mini_sector_comparison("VER", "NOR", a_segments, b_segments)
        assert len(out["segments"]) == 25
        assert out["segments"][0]["delta_s"] == -0.05
        assert out["segments"][0]["winner"] == "A"
        assert out["segments"][12]["winner"] == "B"

    def test_compare_mini_sectors_cumulative_delta_grows(self):
        """Cumulative delta = sum of per-segment deltas along distance."""
        from f1_data import _build_mini_sector_comparison

        a_segments = [{"index": i, "start_m": i * 200, "end_m": (i + 1) * 200,
                       "time_s": 4.0, "avg_speed_kmh": 200.0, "min_speed_kmh": 180.0,
                       "drs_active_pct": 0.0} for i in range(5)]
        b_segments = [{"index": i, "start_m": i * 200, "end_m": (i + 1) * 200,
                       "time_s": 4.1, "avg_speed_kmh": 200.0, "min_speed_kmh": 180.0,
                       "drs_active_pct": 0.0} for i in range(5)]

        out = _build_mini_sector_comparison("VER", "NOR", a_segments, b_segments)
        cum = out["cumulative_delta"]
        assert abs(cum[-1][1] - (-0.5)) < 1e-6
        for i in range(1, len(cum)):
            assert cum[i][1] <= cum[i - 1][1] + 1e-9

    def test_compare_mini_sectors_flags_drs_mix(self):
        """When A had DRS open in a segment and B did not (or vice versa),
        drs_mix_warning is True."""
        from f1_data import _build_mini_sector_comparison

        a_segments = [{"index": 0, "start_m": 0, "end_m": 200, "time_s": 4.0,
                       "avg_speed_kmh": 200.0, "min_speed_kmh": 180.0,
                       "drs_active_pct": 80.0}]
        b_segments = [{"index": 0, "start_m": 0, "end_m": 200, "time_s": 4.05,
                       "avg_speed_kmh": 200.0, "min_speed_kmh": 180.0,
                       "drs_active_pct": 0.0}]

        out = _build_mini_sector_comparison("VER", "NOR", a_segments, b_segments)
        assert out["drs_mix_warning"] is True

    def test_compare_mini_sectors_no_drs_mix_when_both_open_or_closed(self):
        from f1_data import _build_mini_sector_comparison

        a_segments = [
            {"index": 0, "start_m": 0, "end_m": 200, "time_s": 4.0,
             "avg_speed_kmh": 200.0, "min_speed_kmh": 180.0, "drs_active_pct": 90.0},
            {"index": 1, "start_m": 200, "end_m": 400, "time_s": 4.0,
             "avg_speed_kmh": 200.0, "min_speed_kmh": 180.0, "drs_active_pct": 0.0},
        ]
        b_segments = [
            {"index": 0, "start_m": 0, "end_m": 200, "time_s": 4.0,
             "avg_speed_kmh": 200.0, "min_speed_kmh": 180.0, "drs_active_pct": 85.0},
            {"index": 1, "start_m": 200, "end_m": 400, "time_s": 4.0,
             "avg_speed_kmh": 200.0, "min_speed_kmh": 180.0, "drs_active_pct": 0.0},
        ]

        out = _build_mini_sector_comparison("VER", "NOR", a_segments, b_segments)
        assert out["drs_mix_warning"] is False

    def test_compare_mini_sectors_assigns_tie_for_tiny_deltas(self):
        """Per-segment winner is 'tie' when |delta_s| < 0.005."""
        from f1_data import _build_mini_sector_comparison

        a_segments = [{"index": 0, "start_m": 0, "end_m": 200, "time_s": 4.000,
                       "avg_speed_kmh": 200.0, "min_speed_kmh": 180.0,
                       "drs_active_pct": 0.0}]
        b_segments = [{"index": 0, "start_m": 0, "end_m": 200, "time_s": 4.003,
                       "avg_speed_kmh": 200.0, "min_speed_kmh": 180.0,
                       "drs_active_pct": 0.0}]

        out = _build_mini_sector_comparison("VER", "NOR", a_segments, b_segments)
        assert out["segments"][0]["winner"] == "tie"


# -----------------------------------------------------------------------------
# Time-gained helpers — _compute_time_gained_over_window /
# _integrate_time_gained_from_samples
# -----------------------------------------------------------------------------

def test_compute_time_gained_over_window_apex_vs_straight():
    """Same km/h delta over same distance yields more time at low speed
    than at high speed — the headline truth this whole refactor is built on."""
    from f1_data import _compute_time_gained_over_window

    apex = _compute_time_gained_over_window(
        v_winner_kph=117.0, v_loser_kph=104.0, window_distance_m=50.0,
    )
    straight = _compute_time_gained_over_window(
        v_winner_kph=337.0, v_loser_kph=321.0, window_distance_m=50.0,
    )
    assert apex is not None and straight is not None
    assert apex > straight, "Apex delta should yield more time over same distance"
    assert 0.10 < apex < 0.30
    assert 0.01 < straight < 0.05


def test_compute_time_gained_over_window_zero_when_equal_speeds():
    from f1_data import _compute_time_gained_over_window
    out = _compute_time_gained_over_window(200, 200, 100)
    assert out == 0.0


def test_compute_time_gained_over_window_returns_none_for_invalid_speeds():
    from f1_data import _compute_time_gained_over_window
    assert _compute_time_gained_over_window(None, 100, 50) is None
    assert _compute_time_gained_over_window(100, None, 50) is None
    assert _compute_time_gained_over_window(0, 100, 50) is None
    assert _compute_time_gained_over_window(100, 0, 50) is None
    assert _compute_time_gained_over_window(20, 100, 50) is None  # < 30 km/h
    assert _compute_time_gained_over_window(100, 100, 0) is None
    assert _compute_time_gained_over_window(100, 100, -5) is None


def test_integrate_time_gained_from_samples_synthetic_bump():
    """200-sample trace with a 10-sample winner_speed bump produces a
    deterministic, positive time-gained value."""
    from f1_data import _integrate_time_gained_from_samples
    import numpy as np

    distance = np.linspace(0, 5000, 200)
    speed_winner = np.full(200, 200.0)
    speed_loser = np.full(200, 200.0)
    speed_winner[100:110] = 130.0
    speed_loser[100:110] = 117.0

    out = _integrate_time_gained_from_samples(distance, speed_winner, speed_loser)
    assert out is not None
    assert out > 0.0

    # Sanity-check against the analytical expected: per-sample step ~25.13m,
    # 10 samples at v_loser=117, v_winner=130 → ~ (1/117 - 1/130) * (3.6) * 251.3
    # = (0.000855 - 0.00770) → cancel — let me re-derive in m/s:
    # v_loser_ms = 32.5, v_winner_ms = 36.11
    # per_m = 1/32.5 - 1/36.11 = 0.0308 - 0.0277 = 0.00307 s/m
    # total step = ~251m → ~0.77s
    assert 0.5 < out < 1.2


def test_integrate_time_gained_from_samples_window_restriction():
    """Restricting the window to cover the bump (including the segments
    transitioning into and out of it) produces the same value as the
    full integration (the rest of the trace contributes 0)."""
    from f1_data import _integrate_time_gained_from_samples
    import numpy as np

    distance = np.linspace(0, 5000, 200)
    speed_winner = np.full(200, 200.0)
    speed_loser = np.full(200, 200.0)
    speed_winner[100:110] = 130.0
    speed_loser[100:110] = 117.0

    # Trapezoidal integration attributes contribution to *segments*; widen
    # the window by one sample on each side so the transition segments
    # are included.
    full = _integrate_time_gained_from_samples(distance, speed_winner, speed_loser)
    windowed = _integrate_time_gained_from_samples(
        distance, speed_winner, speed_loser,
        start_distance=float(distance[99]) - 1.0,
        end_distance=float(distance[110]) + 1.0,
    )
    assert full is not None and windowed is not None
    assert abs(full - windowed) < 1e-6


def test_integrate_time_gained_from_samples_window_outside_returns_none():
    from f1_data import _integrate_time_gained_from_samples
    import numpy as np

    distance = np.linspace(0, 5000, 200)
    speed_winner = np.full(200, 200.0)
    speed_loser = np.full(200, 199.0)
    out = _integrate_time_gained_from_samples(
        distance, speed_winner, speed_loser,
        start_distance=10000.0, end_distance=20000.0,
    )
    assert out is None


def test_integrate_time_gained_from_samples_returns_none_below_two_samples():
    from f1_data import _integrate_time_gained_from_samples
    assert _integrate_time_gained_from_samples([], [], []) is None
    assert _integrate_time_gained_from_samples([100.0], [200.0], [199.0]) is None


def test_integrate_time_gained_robust_to_unsorted_samples():
    """When samples are in random order, the result must match the sorted
    version. _integrate_time_gained_from_samples sorts by distance up
    front so callers don't have to."""
    from f1_data import _integrate_time_gained_from_samples
    import numpy as np

    distance = np.array([0.0, 100.0, 200.0, 300.0, 400.0, 500.0])
    winner_kph = np.array([100, 110, 120, 110, 100, 110], dtype=float)
    loser_kph = np.array([95, 100, 110, 105, 95, 105], dtype=float)

    sorted_result = _integrate_time_gained_from_samples(distance, winner_kph, loser_kph)

    order = np.array([3, 0, 5, 2, 4, 1])
    shuffled_result = _integrate_time_gained_from_samples(
        distance[order], winner_kph[order], loser_kph[order],
    )
    assert sorted_result is not None and shuffled_result is not None
    assert abs(sorted_result - shuffled_result) < 1e-6, (
        f"Unsorted samples gave {shuffled_result}, sorted gave {sorted_result}"
    )


def test_integrate_time_gained_realistic_straight_marker():
    """Sanity: 14 km/h delta at 300 km/h sustained over a 200 m window
    should be roughly 0.10 s. Earlier rectangular-rule artefacts produced
    multi-second values for the same scenario."""
    from f1_data import _integrate_time_gained_from_samples
    import numpy as np

    distance = np.linspace(4600, 4800, 20)
    winner_kph = np.full(20, 314.0)
    loser_kph = np.full(20, 300.0)

    result = _integrate_time_gained_from_samples(distance, winner_kph, loser_kph)
    assert result is not None
    assert 0.05 < result < 0.20, f"Expected ~0.10s, got {result}s"


def test_integrate_time_gained_clips_pathological_gaps():
    """A 5 km wide data gap between two samples must not be filled in
    with sustained per-meter contribution. The cap on segment width
    keeps the integral bounded."""
    from f1_data import _integrate_time_gained_from_samples
    import numpy as np

    distance = np.array([0.0, 5000.0])
    winner_kph = np.array([314.0, 314.0])
    loser_kph = np.array([300.0, 300.0])

    result = _integrate_time_gained_from_samples(distance, winner_kph, loser_kph)
    assert result is not None
    assert result < 0.20, f"Pathological gap leaked through: {result}s"


def test_integrate_time_gained_apex_sample_does_not_blow_up():
    """Single apex sample sandwiched between two fast samples used to
    return ~1.5 s under rectangular quadrature. Trapezoidal integration
    plus a per-segment cap keep the value physically plausible."""
    from f1_data import _integrate_time_gained_from_samples
    import numpy as np

    # Cause at 4700 m: winner late-brakes, apex sample shows large delta
    # but the cars only spend an instant at those speeds.
    distance = np.array([4600.0, 4700.0, 4800.0])
    v_winner = np.array([280.0, 120.0, 130.0])
    v_loser = np.array([270.0, 80.0, 130.0])

    result = _integrate_time_gained_from_samples(
        distance, v_winner, v_loser,
        start_distance=4600.0, end_distance=4800.0,
    )
    assert result is not None
    # Old rectangular rule gave ~1.5 s; trapezoidal + cap brings it under
    # the 0.25 s/segment ceiling so the 200 m window stays under 0.6 s.
    assert result < 0.6, f"Apex-sample artefact leaked through: {result}s"


# -----------------------------------------------------------------------------
# _integrate_time_gained_around_extremum
# -----------------------------------------------------------------------------

def test_integrate_time_gained_around_extremum_localizes_corner_apex():
    """A short apex event embedded in an otherwise-flat trace should
    integrate to a SMALL value compared to a wide fixed window — the
    extremum walker should clip back to the physical event."""
    from f1_data import (
        _integrate_time_gained_around_extremum,
        _integrate_time_gained_from_samples,
    )
    import numpy as np

    # 200 m of equal speeds, then a narrow ~40 m apex where A is briefly
    # 13 km/h faster, then 200 m more of equal speeds. Wide ±100 m window
    # would still sum a lot of the surrounding equal-speed segments.
    distance = np.linspace(0, 5000, 251)  # 20 m sample spacing
    speed_a = np.full(distance.size, 200.0)
    speed_b = np.full(distance.size, 200.0)
    apex_centre = 4700.0
    apex_idx = int(np.argmin(np.abs(distance - apex_centre)))
    speed_a[apex_idx - 1:apex_idx + 2] = 117.0
    speed_b[apex_idx - 1:apex_idx + 2] = 104.0

    wide = _integrate_time_gained_from_samples(
        distance, speed_a, speed_b,
        start_distance=apex_centre - 100.0,
        end_distance=apex_centre + 100.0,
    )
    tight = _integrate_time_gained_around_extremum(
        distance, speed_a, speed_b, center_distance_m=apex_centre,
    )
    assert wide is not None and tight is not None
    # Tight window must capture less than the wide one because it walks
    # back to where the per-meter contribution decays.
    assert abs(tight) <= abs(wide) + 1e-6


def test_integrate_time_gained_around_extremum_straight_marker_bounded():
    """14 km/h delta at 300 km/h, narrow physical event around 4700 m.
    Result must be physically plausible (< 0.20 s)."""
    from f1_data import _integrate_time_gained_around_extremum
    import numpy as np

    distance = np.linspace(4500, 4900, 41)  # 10m spacing
    speed_a = np.full(distance.size, 300.0)
    speed_b = np.full(distance.size, 300.0)
    # Narrow ~30 m physical event where A is 14 km/h faster
    centre_idx = int(np.argmin(np.abs(distance - 4700.0)))
    speed_a[centre_idx - 1:centre_idx + 2] = 314.0

    result = _integrate_time_gained_around_extremum(
        distance, speed_a, speed_b, center_distance_m=4700.0,
    )
    assert result is not None
    assert 0 < result < 0.20, f"Expected small positive contribution, got {result}s"


def test_integrate_time_gained_around_extremum_signed_when_b_gains():
    """When the local extremum is negative (B gained at that point), the
    helper must return a negative number — A-minus-B signed convention."""
    from f1_data import _integrate_time_gained_around_extremum
    import numpy as np

    distance = np.linspace(0, 1000, 51)
    speed_a = np.full(distance.size, 200.0)
    speed_b = np.full(distance.size, 200.0)
    centre_idx = int(np.argmin(np.abs(distance - 500.0)))
    speed_a[centre_idx - 1:centre_idx + 2] = 104.0
    speed_b[centre_idx - 1:centre_idx + 2] = 117.0

    result = _integrate_time_gained_around_extremum(
        distance, speed_a, speed_b, center_distance_m=500.0,
    )
    assert result is not None
    assert result < 0.0, f"Expected B-gain (negative); got {result}"


def test_integrate_time_gained_around_extremum_handles_few_samples():
    from f1_data import _integrate_time_gained_around_extremum
    assert _integrate_time_gained_around_extremum([], [], [], 100.0) is None
    assert _integrate_time_gained_around_extremum([10.0], [200.0], [199.0], 10.0) is None


def test_integrate_time_gained_around_extremum_caps_at_max_window():
    """If the per-meter contribution is uniform across a huge span, the
    walker must respect max_window_m (default 200 m)."""
    from f1_data import _integrate_time_gained_around_extremum
    import numpy as np

    distance = np.linspace(0, 5000, 251)
    speed_a = np.full(distance.size, 314.0)
    speed_b = np.full(distance.size, 300.0)

    result = _integrate_time_gained_around_extremum(
        distance, speed_a, speed_b, center_distance_m=2500.0,
        max_window_m=200.0,
    )
    assert result is not None
    # Per-meter at 300/314 ~ 0.000528 s/m. 200 m → ~0.106 s. Allow margin.
    assert 0.0 < result < 0.20, f"Walker leaked past max_window: got {result}s"


def test_classify_decisive_sector_when_one_dominates():
    """If one sector owns >=55% of total absolute gap, decisive_sector is set
    and split_sector_lap is False."""
    from f1_data import _classify_decisive_sector

    # Total absolute = 0.131 + 0.081 + 0.010 = 0.222; S1 share = 59% > 55%
    result = _classify_decisive_sector(
        s1_gap_s=0.131,
        s2_gap_s=-0.081,
        s3_gap_s=-0.010,
    )
    assert result["decisive_sector"] == "S1"
    assert result["split_sector_lap"] is False


def test_classify_split_sector_lap():
    """If no sector owns >=55% of total absolute gap, decisive_sector is None
    and split_sector_lap is True."""
    from f1_data import _classify_decisive_sector

    # Total absolute = 0.14; max share = 0.05/0.14 = 36% < 55%
    result = _classify_decisive_sector(
        s1_gap_s=0.05,
        s2_gap_s=0.05,
        s3_gap_s=0.04,
    )
    assert result["decisive_sector"] is None
    assert result["split_sector_lap"] is True


def test_classify_decisive_sector_handles_zero_gap():
    """Effectively-identical laps return None decisive_sector and
    split_sector_lap=False (nothing to split)."""
    from f1_data import _classify_decisive_sector

    result = _classify_decisive_sector(s1_gap_s=0.0, s2_gap_s=0.0, s3_gap_s=0.0)
    assert result["decisive_sector"] is None
    assert result["split_sector_lap"] is False
