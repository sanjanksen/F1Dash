import sys
import time
import types

# Stub heavy deps not needed for pure functions
for mod in ('pymc', 'arviz', 'fastf1', 'fastf1.Cache'):
    if mod not in sys.modules:
        sys.modules[mod] = types.ModuleType(mod)

import pytest


def _make_race_result(drivers: list[tuple[str, str, int, int]]) -> list[dict]:
    """
    drivers: list of (driver_code, constructor_name, position, grid).
    Returns a fake Jolpica-style Races[0]['Results'] list.
    """
    return [
        {
            'position': str(pos),
            'grid':     str(grid),
            'Driver':       {'code': code},
            'Constructor':  {'name': ctor},
            'status': 'Finished',
        }
        for code, ctor, pos, grid in drivers
    ]


def test_parse_single_race_produces_all_pairs():
    """A 3-driver race produces 3 comparison pairs (C(3,2))."""
    from driver_rating import _parse_race_to_comparisons

    results = _make_race_result([
        ('NOR', 'McLaren', 1, 3),
        ('LEC', 'Ferrari', 2, 1),
        ('VER', 'Red Bull', 3, 2),
    ])
    pairs = _parse_race_to_comparisons(results, season=2024, round_num=1)
    assert len(pairs) == 3
    winners = {p['winner'] for p in pairs}
    assert 'NOR' in winners


def test_parse_race_winner_is_lower_position():
    """Winner (lower finish position) is always in 'winner' field."""
    from driver_rating import _parse_race_to_comparisons

    results = _make_race_result([
        ('NOR', 'McLaren', 1, 3),
        ('LEC', 'Ferrari', 2, 1),
    ])
    pairs = _parse_race_to_comparisons(results, season=2024, round_num=1)
    assert len(pairs) == 1
    assert pairs[0]['winner'] == 'NOR'
    assert pairs[0]['loser'] == 'LEC'


def test_parse_race_excludes_dnf():
    """Drivers with position > 20 or status containing 'Retired' are excluded."""
    from driver_rating import _parse_race_to_comparisons

    results = _make_race_result([
        ('NOR', 'McLaren', 1, 3),
        ('LEC', 'Ferrari', 2, 1),
    ])
    results.append({
        'position': '21', 'grid': '5',
        'Driver': {'code': 'HAM'}, 'Constructor': {'name': 'Mercedes'},
        'status': 'Retired',
    })
    pairs = _parse_race_to_comparisons(results, season=2024, round_num=1)
    for p in pairs:
        assert 'HAM' not in (p['winner'], p['loser'])


def test_constructor_key_includes_season():
    """Constructor key must be '<Name>_<year>' to separate car vintages."""
    from driver_rating import _parse_race_to_comparisons

    results = _make_race_result([
        ('NOR', 'McLaren', 1, 2),
        ('PIA', 'McLaren', 2, 1),
    ])
    pairs = _parse_race_to_comparisons(results, season=2024, round_num=1)
    assert len(pairs) == 1
    assert pairs[0]['constructor_winner'] == 'McLaren_2024'
    assert pairs[0]['constructor_loser'] == 'McLaren_2024'


def test_elo_winner_gains_rating():
    """Driver who wins a match must have higher rating than before."""
    from driver_rating import _fit_elo_baseline

    pairs = [
        {'winner': 'NOR', 'loser': 'LEC',
         'constructor_winner': 'McLaren_2024', 'constructor_loser': 'Ferrari_2024'}
    ] * 20

    result = _fit_elo_baseline(pairs)
    assert result['driver_ratings']['NOR'] > 1500
    assert result['driver_ratings']['LEC'] < 1500


def test_elo_same_constructor_isolates_driver():
    """Two drivers in the same car: rating difference = pure driver effect."""
    from driver_rating import _fit_elo_baseline

    pairs = [
        {'winner': 'NOR', 'loser': 'PIA',
         'constructor_winner': 'McLaren_2024', 'constructor_loser': 'McLaren_2024'}
    ] * 30

    result = _fit_elo_baseline(pairs)
    nor = result['driver_ratings']['NOR']
    pia = result['driver_ratings']['PIA']
    assert nor > pia, "NOR won all races against PIA — should have higher rating"


def test_elo_returns_all_drivers():
    from driver_rating import _fit_elo_baseline

    pairs = [
        {'winner': 'NOR', 'loser': 'LEC',
         'constructor_winner': 'McLaren_2024', 'constructor_loser': 'Ferrari_2024'},
        {'winner': 'VER', 'loser': 'HAM',
         'constructor_winner': 'Red Bull_2024', 'constructor_loser': 'Mercedes_2024'},
    ]
    result = _fit_elo_baseline(pairs)
    for drv in ('NOR', 'LEC', 'VER', 'HAM'):
        assert drv in result['driver_ratings']


def test_bayesian_dominant_driver_higher_skill():
    """
    Driver A dominates all races against B. Posterior mean for A must exceed B by > 0.5 SD.
    Uses 50 comparisons to get clear signal without long sampling.
    """
    try:
        import pymc  # noqa: F401
        if not hasattr(pymc, 'Model'):
            pytest.skip("pymc stub — not real library")
    except ImportError:
        pytest.skip("pymc not installed")

    from driver_rating import _fit_bayesian_driver_model

    pairs = [
        {'winner': 'AAA', 'loser': 'BBB',
         'constructor_winner': 'TeamX_2024', 'constructor_loser': 'TeamY_2024'}
    ] * 50

    result = _fit_bayesian_driver_model(pairs, draws=200, tune=100, chains=1)
    skills = result['driver_skills']
    assert 'AAA' in skills
    assert 'BBB' in skills
    assert skills['AAA']['mean'] > skills['BBB']['mean'] + 0.5, (
        f"AAA skill {skills['AAA']['mean']:.2f} should exceed BBB {skills['BBB']['mean']:.2f} by >0.5"
    )


def test_bayesian_result_has_credible_interval():
    """Result must include hdi_5 and hdi_95 fields."""
    try:
        import pymc  # noqa: F401
        if not hasattr(pymc, 'Model'):
            pytest.skip("pymc stub — not real library")
    except ImportError:
        pytest.skip("pymc not installed")

    from driver_rating import _fit_bayesian_driver_model

    pairs = [
        {'winner': 'NOR', 'loser': 'LEC',
         'constructor_winner': 'McLaren_2024', 'constructor_loser': 'Ferrari_2024'}
    ] * 20

    result = _fit_bayesian_driver_model(pairs, draws=100, tune=100, chains=1)
    for drv in ('NOR', 'LEC'):
        s = result['driver_skills'][drv]
        assert 'hdi_5' in s and 'hdi_95' in s
        assert s['hdi_5'] < s['mean'] < s['hdi_95']


def test_bayesian_constructor_ratings_present():
    """Constructor-year strengths must also be in the result."""
    try:
        import pymc  # noqa: F401
        if not hasattr(pymc, 'Model'):
            pytest.skip("pymc stub — not real library")
    except ImportError:
        pytest.skip("pymc not installed")

    from driver_rating import _fit_bayesian_driver_model

    pairs = [
        {'winner': 'NOR', 'loser': 'LEC',
         'constructor_winner': 'McLaren_2024', 'constructor_loser': 'Ferrari_2024'}
    ] * 20

    result = _fit_bayesian_driver_model(pairs, draws=100, tune=100, chains=1)
    assert 'constructor_strengths' in result
    assert 'McLaren_2024' in result['constructor_strengths']


def test_cache_round_trip(tmp_path):
    """Saved ratings can be loaded back and match the original."""
    from driver_rating import _save_ratings_cache, _load_ratings_cache

    fake_ratings = {
        'driver_skills': {'NOR': {'mean': 0.8, 'std': 0.1, 'hdi_5': 0.6, 'hdi_95': 1.0}},
        'constructor_strengths': {'McLaren_2024': {'mean': 0.3, 'std': 0.05, 'hdi_5': 0.2, 'hdi_95': 0.4}},
        'n_comparisons': 100,
        'seasons': [2022, 2023, 2024],
        'built_at': 1700000000.0,
    }
    cache_path = tmp_path / "ratings.json"
    _save_ratings_cache(fake_ratings, cache_path)
    loaded = _load_ratings_cache(cache_path)
    assert loaded['driver_skills']['NOR']['mean'] == 0.8
    assert loaded['seasons'] == [2022, 2023, 2024]


def test_cache_stale_detection(tmp_path):
    """Cache written 8 days ago is considered stale."""
    from driver_rating import _save_ratings_cache, _is_cache_stale

    stale_data = {
        'driver_skills': {},
        'constructor_strengths': {},
        'n_comparisons': 0,
        'built_at': time.time() - 8 * 24 * 3600,
    }
    cache_path = tmp_path / "ratings.json"
    _save_ratings_cache(stale_data, cache_path)
    assert _is_cache_stale(cache_path, ttl_seconds=7 * 24 * 3600)


def test_cache_fresh_not_stale(tmp_path):
    from driver_rating import _save_ratings_cache, _is_cache_stale

    fresh_data = {
        'driver_skills': {},
        'constructor_strengths': {},
        'n_comparisons': 0,
        'built_at': time.time() - 1 * 24 * 3600,
    }
    cache_path = tmp_path / "ratings.json"
    _save_ratings_cache(fresh_data, cache_path)
    assert not _is_cache_stale(cache_path, ttl_seconds=7 * 24 * 3600)


def test_get_driver_skill_rating_from_cache(tmp_path, monkeypatch):
    """
    get_driver_skill_rating returns correct data for a driver found in cache.
    Monkeypatches _CACHE_PATH so no real file IO to the project cache dir.
    """
    import driver_rating as dr
    from f1_data import get_driver_skill_rating

    fake_cache = {
        'driver_skills': {
            'NOR': {'mean': 0.72, 'std': 0.09, 'hdi_5': 0.56, 'hdi_95': 0.88},
            'LEC': {'mean': 0.41, 'std': 0.10, 'hdi_5': 0.24, 'hdi_95': 0.58},
        },
        'constructor_strengths': {
            'McLaren_2024': {'mean': 0.35, 'std': 0.05, 'hdi_5': 0.26, 'hdi_95': 0.44},
        },
        'elo_driver_ratings': {'NOR': 1580.0, 'LEC': 1540.0},
        'seasons': [2022, 2023, 2024],
        'n_comparisons': 3000,
        'built_at': time.time() - 3600,
    }
    cache_path = tmp_path / "ratings.json"
    dr._save_ratings_cache(fake_cache, cache_path)
    monkeypatch.setattr(dr, '_CACHE_PATH', cache_path)

    result = get_driver_skill_rating('NOR')
    assert result['driver'] == 'NOR'
    assert abs(result['skill_mean'] - 0.72) < 0.01
    assert result['hdi_5'] < result['skill_mean'] < result['hdi_95']
    assert 'rank' in result


def test_get_driver_skill_rating_unknown_driver(tmp_path, monkeypatch):
    """Unknown driver code returns an informative error dict."""
    import driver_rating as dr
    from f1_data import get_driver_skill_rating

    fake_cache = {
        'driver_skills': {'NOR': {'mean': 0.5, 'std': 0.1, 'hdi_5': 0.3, 'hdi_95': 0.7}},
        'constructor_strengths': {},
        'elo_driver_ratings': {'NOR': 1540.0},
        'seasons': [2024],
        'n_comparisons': 100,
        'built_at': time.time(),
    }
    cache_path = tmp_path / "ratings.json"
    dr._save_ratings_cache(fake_cache, cache_path)
    monkeypatch.setattr(dr, '_CACHE_PATH', cache_path)

    result = get_driver_skill_rating('XYZ')
    assert 'error' in result
