# Bayesian Driver Rating Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a full Bayesian driver skill + constructor-year decomposition using a multilevel Bradley-Terry model (PyMC), exposing the result as a new `get_driver_skill_rating` tool with posterior credible intervals. Answers "how good is this driver independent of the car?" with a principled uncertainty estimate.

**Architecture:** Five sequential layers:
1. `_fetch_race_comparison_pairs(seasons)` — pull Jolpica multi-season results, generate pairwise comparisons (A finished ahead of B)
2. `_fit_elo_baseline(comparisons)` — simple car-adjusted Elo for quick validation and warm-start
3. `_fit_bayesian_driver_model(comparisons)` — PyMC multilevel Bradley-Terry NUTS sampler (offline, cached weekly)
4. `server/driver_rating.py` — standalone module: data pipeline + model fitting + disk cache
5. `get_driver_skill_rating(driver_name)` tool → widget

**Tech Stack:** PyMC ≥ 5.0, arviz, numpy, scipy (all new except numpy). Jolpica REST API (already used). Model runs offline as a background task; results served from disk cache. No FastF1 required — Jolpica race results only.

**Reference:** van Kesteren & Bergkamp arXiv:2203.08489 (JQAS 2023). Replication code at Zenodo. This plan implements the same Bradley-Terry approximation, not the full rank-ordered logit, for tractability.

---

### Task 1: Data Pipeline — Race Comparison Pairs

**Files:**
- Create: `server/driver_rating.py` — new module, all model code lives here
- Test: `server/tests/test_driver_rating.py`

**What it produces:** A list of comparison dicts `{'winner': 'NOR', 'loser': 'LEC', 'constructor_winner': 'McLaren_2024', 'constructor_loser': 'Ferrari_2024', 'season': 2024, 'round': 5}` for every pair of finishers in every race across the specified seasons.

- [ ] **Write the failing tests**

Create `server/tests/test_driver_rating.py`:

```python
import sys
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
```

- [ ] **Run tests to confirm they fail**

```
cd server && python -m pytest tests/test_driver_rating.py -v
```

Expected: all four `FAILED` — `driver_rating` module does not exist.

- [ ] **Create `server/driver_rating.py` with data pipeline**

```python
"""
Bayesian driver skill + constructor-year decomposition.

Model: Bradley-Terry multilevel (van Kesteren & Bergkamp, JQAS 2023).
P(A beats B | car_A, car_B) = sigmoid(θ_A + φ_ctor_A - θ_B - φ_ctor_B)
θ_driver ~ ZeroSumNormal(0, 1); φ_constructor_year ~ Normal(0, 0.5)

Run offline; results cached to server/cache/driver_ratings.json.
"""
from __future__ import annotations
import json
import os
import time
import itertools
from pathlib import Path

import numpy as np
import requests

_JOLPICA_BASE = "https://api.jolpi.ca/ergast/f1"
_CACHE_PATH = Path(__file__).parent / "cache" / "driver_ratings.json"
_CACHE_TTL_S = 7 * 24 * 3600  # 1 week


def _parse_race_to_comparisons(
    results: list[dict], season: int, round_num: int
) -> list[dict]:
    """
    Convert a Jolpica race Results list into pairwise comparison dicts.
    Each pair: {winner, loser, constructor_winner, constructor_loser, season, round}.
    Excludes DNF/DSQ finishers (position > 20 or status not 'Finished'/'Lapped').
    """
    finished = []
    for r in results:
        try:
            pos = int(r.get('position', 99))
        except (TypeError, ValueError):
            continue
        status = r.get('status', '')
        if pos > 20 or 'Retired' in status or 'Disqualified' in status or 'Accident' in status:
            continue
        code = r['Driver'].get('code', '')
        ctor = r['Constructor'].get('name', 'Unknown')
        if not code:
            continue
        finished.append({
            'code':        code,
            'constructor': f"{ctor}_{season}",
            'position':    pos,
        })

    # Sort by position ascending (winner first)
    finished.sort(key=lambda x: x['position'])

    # Generate all C(n, 2) pairs
    pairs = []
    for a, b in itertools.combinations(finished, 2):
        # a has lower position = finished ahead = a is winner
        pairs.append({
            'winner':               a['code'],
            'loser':                b['code'],
            'constructor_winner':   a['constructor'],
            'constructor_loser':    b['constructor'],
            'season':               season,
            'round':                round_num,
        })
    return pairs


def fetch_comparison_pairs(seasons: list[int]) -> list[dict]:
    """
    Fetch Jolpica race results for each season and generate comparison pairs.
    Caches nothing — caller is responsible for caching the model output.
    """
    all_pairs = []
    for season in seasons:
        url = f"{_JOLPICA_BASE}/{season}/results.json?limit=30&offset=0"
        while url:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()['MRData']
            races = data['RaceTable']['Races']
            for race in races:
                round_num = int(race['round'])
                results = race.get('Results', [])
                pairs = _parse_race_to_comparisons(results, season, round_num)
                all_pairs.extend(pairs)
            # Jolpica pagination
            total = int(data.get('total', 0))
            offset = int(data.get('offset', 0))
            limit = int(data.get('limit', 30))
            if offset + limit < total:
                url = f"{_JOLPICA_BASE}/{season}/results.json?limit={limit}&offset={offset + limit}"
            else:
                url = None
    return all_pairs
```

- [ ] **Run the tests to confirm they pass**

```
cd server && python -m pytest tests/test_driver_rating.py -v
```

Expected: all four `PASSED`.

- [ ] **Run full test suite to check no regressions**

```
cd server && python -m pytest tests/ -v
```

- [ ] **Commit**

```
git add server/driver_rating.py server/tests/test_driver_rating.py
git commit -m "feat: add driver rating data pipeline — Jolpica multi-season pairwise comparison pairs"
```

---

### Task 2: Car-Adjusted Elo Baseline

**Files:**
- Modify: `server/driver_rating.py` — add `_fit_elo_baseline()`
- Modify: `server/tests/test_driver_rating.py` — add Elo tests

**Why Elo first:** Elo provides a fast sanity check (< 1 second) before running the 5-minute Bayesian NUTS sampler. If Elo rankings are nonsensical, the data pipeline is broken. Elo also gives warm-start values for PyMC initial conditions.

- [ ] **Write the failing tests**

Add to `server/tests/test_driver_rating.py`:

```python
def test_elo_winner_gains_rating():
    """Driver who wins a match must have higher rating than before."""
    from driver_rating import _fit_elo_baseline

    pairs = [
        {'winner': 'NOR', 'loser': 'LEC',
         'constructor_winner': 'McLaren_2024', 'constructor_loser': 'Ferrari_2024'}
    ] * 20  # repeated to move ratings clearly

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
```

- [ ] **Run tests to confirm they fail**

```
cd server && python -m pytest tests/test_driver_rating.py::test_elo_winner_gains_rating tests/test_driver_rating.py::test_elo_same_constructor_isolates_driver tests/test_driver_rating.py::test_elo_returns_all_drivers -v
```

Expected: all three `FAILED`.

- [ ] **Add `_fit_elo_baseline` to `driver_rating.py`**

```python
def _fit_elo_baseline(
    comparisons: list[dict],
    k_driver: float = 16.0,
    k_constructor: float = 8.0,
    initial_rating: float = 1500.0,
) -> dict:
    """
    Car-adjusted Elo: rating_eff_A = theta_A + phi_ctor_A.
    Update both driver and constructor ratings after each match.
    Returns {'driver_ratings': {code: rating}, 'constructor_ratings': {ctor: rating}}.
    """
    driver_r: dict[str, float] = {}
    ctor_r:   dict[str, float] = {}

    def _r(drv: str) -> float:
        return driver_r.setdefault(drv, initial_rating)

    def _c(ctor: str) -> float:
        return ctor_r.setdefault(ctor, initial_rating)

    for cmp in comparisons:
        w, l = cmp['winner'], cmp['loser']
        cw, cl = cmp['constructor_winner'], cmp['constructor_loser']

        # Effective ratings
        eff_w = _r(w) + _c(cw)
        eff_l = _r(l) + _c(cl)

        # Expected score
        exp_w = 1.0 / (1.0 + 10.0 ** ((eff_l - eff_w) / 400.0))

        # Update drivers
        driver_r[w] = _r(w) + k_driver * (1.0 - exp_w)
        driver_r[l] = _r(l) + k_driver * (0.0 - (1.0 - exp_w))

        # Update constructors (smaller K — car is shared)
        ctor_r[cw] = _c(cw) + k_constructor * (1.0 - exp_w)
        ctor_r[cl] = _c(cl) + k_constructor * (0.0 - (1.0 - exp_w))

    return {
        'driver_ratings':      {k: round(v, 1) for k, v in driver_r.items()},
        'constructor_ratings': {k: round(v, 1) for k, v in ctor_r.items()},
    }
```

- [ ] **Run the tests to confirm they pass**

```
cd server && python -m pytest tests/test_driver_rating.py::test_elo_winner_gains_rating tests/test_driver_rating.py::test_elo_same_constructor_isolates_driver tests/test_driver_rating.py::test_elo_returns_all_drivers -v
```

Expected: all three `PASSED`.

- [ ] **Run full test suite**

```
cd server && python -m pytest tests/ -v
```

- [ ] **Commit**

```
git add server/driver_rating.py server/tests/test_driver_rating.py
git commit -m "feat: add car-adjusted Elo baseline for driver skill validation"
```

---

### Task 3: PyMC Bayesian Driver Model

**Files:**
- Modify: `server/driver_rating.py` — add `_fit_bayesian_driver_model()`
- Modify: `server/tests/test_driver_rating.py` — add Bayesian model tests
- Modify: `server/requirements.txt` (or `pyproject.toml`) — add `pymc>=5.0` and `arviz`

**What it produces:** For each driver: `{'mean': float, 'std': float, 'hdi_5': float, 'hdi_95': float}` — the posterior over driver skill θ in standard deviation units. A driver at +1.0 is ~1 standard deviation above average, translating to roughly 0.3s/lap faster than a median driver in a median car.

- [ ] **Add PyMC to dependencies**

Open `server/requirements.txt` (or equivalent). Add:

```
pymc>=5.0
arviz>=0.16
```

Then install:
```
cd server && pip install pymc>=5.0 arviz>=0.16
```

- [ ] **Write the failing tests**

The Bayesian test uses a synthetic dataset where driver A wins every race (dominant). After fitting, driver A must have clearly higher mean skill than driver B.

Add to `server/tests/test_driver_rating.py`:

```python
def test_bayesian_dominant_driver_higher_skill():
    """
    Driver A dominates all races against B. Posterior mean for A must exceed B by > 0.5 SD.
    Uses 50 comparisons to get clear signal without long sampling.
    """
    import importlib
    # Skip if pymc is not installed
    try:
        import pymc  # noqa: F401
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
```

- [ ] **Run tests to confirm they fail** (or skip if pymc not yet installed)

```
cd server && python -m pytest tests/test_driver_rating.py::test_bayesian_dominant_driver_higher_skill tests/test_driver_rating.py::test_bayesian_result_has_credible_interval tests/test_driver_rating.py::test_bayesian_constructor_ratings_present -v
```

Expected: all three `FAILED` (or `SKIPPED` if pymc not yet installed — install pymc first, then re-run).

- [ ] **Add `_fit_bayesian_driver_model` to `driver_rating.py`**

```python
def _fit_bayesian_driver_model(
    comparisons: list[dict],
    draws: int = 1000,
    tune: int = 500,
    chains: int = 2,
    target_accept: float = 0.9,
) -> dict:
    """
    Fit a Bayesian Bradley-Terry model on F1 race comparisons.

    Model specification (van Kesteren & Bergkamp, JQAS 2023):
      θ_driver ~ ZeroSumNormal(0, 1)         # sums to zero across all drivers
      φ_constructor ~ Normal(0, 0.5)          # constructor-year advantage
      logit P(A beats B) = θ_A + φ_ctor_A - θ_B - φ_ctor_B
      outcome ~ Bernoulli(logit_p)            # winner always = 1

    Returns dict with posterior summaries for drivers and constructors.
    """
    import pymc as pm
    import arviz as az

    drivers      = sorted(set(c['winner'] for c in comparisons) | set(c['loser'] for c in comparisons))
    constructors = sorted(set(c['constructor_winner'] for c in comparisons) | set(c['constructor_loser'] for c in comparisons))

    drv_idx = {d: i for i, d in enumerate(drivers)}
    con_idx = {c: i for i, c in enumerate(constructors)}

    n = len(comparisons)
    winner_drv = np.array([drv_idx[c['winner']]               for c in comparisons])
    loser_drv  = np.array([drv_idx[c['loser']]                for c in comparisons])
    winner_con = np.array([con_idx[c['constructor_winner']]   for c in comparisons])
    loser_con  = np.array([con_idx[c['constructor_loser']]    for c in comparisons])

    with pm.Model():
        # Driver skill — zero-sum constraint: sum(θ) = 0
        driver_skill       = pm.ZeroSumNormal('driver_skill',   sigma=1.0, shape=len(drivers))
        constructor_strength = pm.Normal('constructor_strength', mu=0, sigma=0.5, shape=len(constructors))

        delta = (
            driver_skill[winner_drv] + constructor_strength[winner_con]
            - driver_skill[loser_drv]  - constructor_strength[loser_con]
        )

        pm.Bernoulli('outcome', logit_p=delta, observed=np.ones(n))

        trace = pm.sample(
            draws=draws,
            tune=tune,
            chains=chains,
            target_accept=target_accept,
            progressbar=False,
            cores=1,        # single-core for server safety; increase for offline runs
            return_inferencedata=True,
        )

    def _summarise(samples_2d: np.ndarray, index: int) -> dict:
        s = samples_2d[:, :, index].flatten()
        return {
            'mean':  round(float(np.mean(s)), 4),
            'std':   round(float(np.std(s)),  4),
            'hdi_5': round(float(np.percentile(s,  5)), 4),
            'hdi_95':round(float(np.percentile(s, 95)), 4),
        }

    driver_skill_arr = trace.posterior['driver_skill'].values
    ctor_strength_arr = trace.posterior['constructor_strength'].values

    driver_skills = {drv: _summarise(driver_skill_arr, i) for i, drv in enumerate(drivers)}
    ctor_strengths = {ctor: _summarise(ctor_strength_arr, i) for i, ctor in enumerate(constructors)}

    return {
        'driver_skills':         driver_skills,
        'constructor_strengths': ctor_strengths,
        'n_comparisons':         n,
        'n_drivers':             len(drivers),
        'n_constructors':        len(constructors),
        'draws':                 draws,
        'chains':                chains,
    }
```

- [ ] **Run the tests to confirm they pass** (this will take ~2–5 minutes with `draws=200`)

```
cd server && python -m pytest tests/test_driver_rating.py::test_bayesian_dominant_driver_higher_skill tests/test_driver_rating.py::test_bayesian_result_has_credible_interval tests/test_driver_rating.py::test_bayesian_constructor_ratings_present -v -s
```

Expected: all three `PASSED`.

- [ ] **Run full test suite**

```
cd server && python -m pytest tests/ -v
```

- [ ] **Commit**

```
git add server/driver_rating.py server/tests/test_driver_rating.py server/requirements.txt
git commit -m "feat: add PyMC Bayesian Bradley-Terry driver skill model with posterior credible intervals"
```

---

### Task 4: Caching Layer — Persist Ratings to Disk

**Files:**
- Modify: `server/driver_rating.py` — add `build_and_cache_ratings()` + `load_cached_ratings()` + `refresh_if_stale()`
- Modify: `server/tests/test_driver_rating.py` — add cache tests

**Why:** The full model (2021–2025, ~3500 comparisons, 1000 draws × 2 chains) takes 5–10 minutes. It must run offline and serve results from disk cache. Cache TTL: 7 days. Cache invalidation: manual via a `/api/admin/rebuild-driver-ratings` endpoint (added in Task 5).

- [ ] **Write the failing tests**

```python
import tempfile
from pathlib import Path


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
        'built_at': time.time() - 8 * 24 * 3600,  # 8 days ago
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
        'built_at': time.time() - 1 * 24 * 3600,  # 1 day ago
    }
    cache_path = tmp_path / "ratings.json"
    _save_ratings_cache(fresh_data, cache_path)
    assert not _is_cache_stale(cache_path, ttl_seconds=7 * 24 * 3600)
```

Add `import time` at the top of `test_driver_rating.py`.

- [ ] **Run tests to confirm they fail**

```
cd server && python -m pytest tests/test_driver_rating.py::test_cache_round_trip tests/test_driver_rating.py::test_cache_stale_detection tests/test_driver_rating.py::test_cache_fresh_not_stale -v
```

Expected: all three `FAILED`.

- [ ] **Add caching functions to `driver_rating.py`**

```python
def _save_ratings_cache(data: dict, path: Path = _CACHE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


def _load_ratings_cache(path: Path = _CACHE_PATH) -> dict | None:
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def _is_cache_stale(
    path: Path = _CACHE_PATH, ttl_seconds: float = _CACHE_TTL_S
) -> bool:
    data = _load_ratings_cache(path)
    if data is None:
        return True
    built_at = data.get('built_at', 0)
    return (time.time() - built_at) > ttl_seconds


def build_and_cache_ratings(
    seasons: list[int] | None = None,
    draws: int = 1000,
    tune: int = 500,
    chains: int = 2,
    cache_path: Path = _CACHE_PATH,
) -> dict:
    """
    Full pipeline: fetch data → Elo validation → Bayesian model → cache.
    Takes 5–15 minutes. Intended for offline/scheduled runs, not the request path.
    """
    if seasons is None:
        seasons = [2021, 2022, 2023, 2024, 2025]

    print(f"[driver_rating] Fetching comparisons for seasons {seasons}...")
    comparisons = fetch_comparison_pairs(seasons)
    print(f"[driver_rating] {len(comparisons)} comparison pairs collected.")

    elo = _fit_elo_baseline(comparisons)
    print(f"[driver_rating] Elo baseline: top-5 = {sorted(elo['driver_ratings'].items(), key=lambda x: -x[1])[:5]}")

    print(f"[driver_rating] Fitting Bayesian model ({draws} draws × {chains} chains)...")
    bayesian = _fit_bayesian_driver_model(
        comparisons, draws=draws, tune=tune, chains=chains
    )
    print("[driver_rating] Bayesian model complete.")

    output = {
        **bayesian,
        'elo_driver_ratings':      elo['driver_ratings'],
        'elo_constructor_ratings': elo['constructor_ratings'],
        'seasons':                 seasons,
        'n_comparisons':           len(comparisons),
        'built_at':                time.time(),
    }

    _save_ratings_cache(output, cache_path)
    print(f"[driver_rating] Ratings cached to {cache_path}")
    return output


def load_cached_ratings(cache_path: Path = _CACHE_PATH) -> dict | None:
    """Return cached ratings, or None if cache doesn't exist or is stale."""
    if _is_cache_stale(cache_path):
        return None
    return _load_ratings_cache(cache_path)


def refresh_if_stale(cache_path: Path = _CACHE_PATH, **kwargs) -> dict:
    """Return cached ratings if fresh; rebuild and cache if stale."""
    cached = load_cached_ratings(cache_path)
    if cached is not None:
        return cached
    return build_and_cache_ratings(cache_path=cache_path, **kwargs)
```

- [ ] **Run the tests to confirm they pass**

```
cd server && python -m pytest tests/test_driver_rating.py::test_cache_round_trip tests/test_driver_rating.py::test_cache_stale_detection tests/test_driver_rating.py::test_cache_fresh_not_stale -v
```

Expected: all three `PASSED`.

- [ ] **Run full test suite**

```
cd server && python -m pytest tests/ -v
```

- [ ] **Commit**

```
git add server/driver_rating.py server/tests/test_driver_rating.py
git commit -m "feat: add disk cache layer for driver ratings with TTL staleness check"
```

---

### Task 5: Tool, Widget, and Prompt Update

**Files:**
- Modify: `server/f1_data.py` — add `get_driver_skill_rating()` wrapper
- Modify: `server/tools.py` — add tool definition + import + dispatch
- Modify: `server/chat.py` — add `_make_driver_skill_rating_widget()` + dispatch
- Create: `client/src/components/chat-widgets/DriverSkillRating.jsx`
- Modify: `client/src/components/AnswerRenderer.jsx`
- Modify: `server/main.py` — add `POST /api/admin/rebuild-driver-ratings` endpoint
- Test: `server/tests/test_driver_rating.py`

- [ ] **Write the failing test for the wrapper function**

Add to `server/tests/test_driver_rating.py`:

```python
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
        'built_at': time.time() - 3600,  # 1 hour old — fresh
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
```

- [ ] **Run tests to confirm they fail**

```
cd server && python -m pytest tests/test_driver_rating.py::test_get_driver_skill_rating_from_cache tests/test_driver_rating.py::test_get_driver_skill_rating_unknown_driver -v
```

Expected: both `FAILED`.

- [ ] **Add `get_driver_skill_rating` to `server/f1_data.py`**

Add at the bottom of `f1_data.py`, after existing functions:

```python
def get_driver_skill_rating(driver_name: str) -> dict:
    """
    Return Bayesian skill estimate for a driver from the pre-computed cache.
    driver_name: 3-letter code (NOR) or surname (normalised internally).
    Includes rank among all rated drivers, credible interval, and Elo cross-check.
    """
    from driver_rating import load_cached_ratings, _CACHE_PATH

    cache = load_cached_ratings(_CACHE_PATH)
    if cache is None:
        return {
            'error': 'Driver rating cache not built yet. Run POST /api/admin/rebuild-driver-ratings to generate ratings.',
            'driver': driver_name.upper(),
        }

    driver_code = driver_name.upper().strip()[:3]
    skills = cache.get('driver_skills', {})

    if driver_code not in skills:
        return {
            'error': f"Driver '{driver_code}' not found in ratings. Available: {sorted(skills.keys())}",
            'driver': driver_code,
        }

    skill = skills[driver_code]

    # Rank by mean skill
    sorted_drivers = sorted(skills.items(), key=lambda x: x[1]['mean'], reverse=True)
    rank = next(i + 1 for i, (k, _) in enumerate(sorted_drivers) if k == driver_code)

    # Skill to seconds: each 1 SD unit ≈ 0.3s/lap in a median car (van Kesteren & Bergkamp calibration)
    skill_in_seconds = round(skill['mean'] * 0.3, 2)

    elo = cache.get('elo_driver_ratings', {}).get(driver_code)
    seasons = cache.get('seasons', [])

    return {
        'driver':            driver_code,
        'skill_mean':        skill['mean'],
        'skill_std':         skill['std'],
        'hdi_5':             skill['hdi_5'],
        'hdi_95':            skill['hdi_95'],
        'rank':              rank,
        'n_drivers_rated':   len(skills),
        'skill_in_seconds':  skill_in_seconds,
        'elo_rating':        elo,
        'seasons_used':      seasons,
        'n_comparisons':     cache.get('n_comparisons'),
        'built_at_iso':      time.strftime('%Y-%m-%d', time.gmtime(cache.get('built_at', 0))),
        'interpretation': (
            f"{driver_code} is ranked #{rank} of {len(skills)} rated drivers. "
            f"Posterior mean skill: {skill['mean']:+.2f} SD units "
            f"({'+' if skill_in_seconds >= 0 else ''}{skill_in_seconds}s/lap vs median driver in median car). "
            f"90% credible interval: [{skill['hdi_5']:+.2f}, {skill['hdi_95']:+.2f}] SD. "
            f"Model trained on {cache.get('n_comparisons', '?')} comparisons from {seasons}."
        ),
    }
```

Add `import time` at the top of `f1_data.py` if not already present.

- [ ] **Add tool definition to `server/tools.py`**

In `PRIMITIVE_TOOL_DEFINITIONS`:

```python
    _tool(
        "get_driver_skill_rating",
        "PRIMITIVE TOOL. Bayesian driver skill estimate: how good is this driver independent of the car? "
        "Returns posterior mean skill in standard deviation units (1 SD ≈ 0.3s/lap), "
        "90%% credible interval, rank among all rated drivers, and a plain-English interpretation. "
        "Model trained on pairwise race finishes across 2021–2025, with car-year effects removed. "
        "Use for questions like 'how good is Norris really?' or 'is Hamilton still elite?'",
        {
            "driver_name": {"type": "string", "description": "Driver full name, surname, or 3-letter code."},
        },
        ["driver_name"],
    ),
```

Add import:
```python
from f1_data import (
    ...
    get_driver_skill_rating,
    ...
)
```

Add dispatch in `execute_tool()`:
```python
    if name == "get_driver_skill_rating":
        return get_driver_skill_rating(args["driver_name"])
```

- [ ] **Add `POST /api/admin/rebuild-driver-ratings` to `server/main.py`**

Find the existing FastAPI route definitions and add:

```python
@app.post("/api/admin/rebuild-driver-ratings")
async def rebuild_driver_ratings(background_tasks: BackgroundTasks):
    """
    Trigger an offline rebuild of the Bayesian driver ratings cache.
    This takes 5-15 minutes. The endpoint returns immediately; the build runs in background.
    """
    from driver_rating import build_and_cache_ratings
    background_tasks.add_task(
        build_and_cache_ratings,
        seasons=[2021, 2022, 2023, 2024, 2025],
        draws=1000, tune=500, chains=2,
    )
    return {"status": "rebuild started", "note": "check server logs; cache updates in ~10 minutes"}
```

Add `BackgroundTasks` to the FastAPI import at the top of `main.py`:
```python
from fastapi import FastAPI, BackgroundTasks
```

- [ ] **Add widget builder to `server/chat.py`**

```python
def _make_driver_skill_rating_widget(result: dict) -> dict:
    if 'error' in result:
        return {'type': 'driver_skill_rating', 'error': result['error'], 'driver': result.get('driver')}
    return {
        'type':              'driver_skill_rating',
        'driver':            result.get('driver'),
        'skill_mean':        result.get('skill_mean'),
        'skill_std':         result.get('skill_std'),
        'hdi_5':             result.get('hdi_5'),
        'hdi_95':            result.get('hdi_95'),
        'rank':              result.get('rank'),
        'n_drivers_rated':   result.get('n_drivers_rated'),
        'skill_in_seconds':  result.get('skill_in_seconds'),
        'elo_rating':        result.get('elo_rating'),
        'seasons_used':      result.get('seasons_used'),
        'interpretation':    result.get('interpretation'),
        'built_at_iso':      result.get('built_at_iso'),
    }
```

```python
        if tool_name == "get_driver_skill_rating":
            widgets.append(_make_driver_skill_rating_widget(tool_result))
```

- [ ] **Create `client/src/components/chat-widgets/DriverSkillRating.jsx`**

```jsx
const W = 480
const H = 60
const PAD = { left: 12, right: 12 }
const IW = W - PAD.left - PAD.right

function CIBar({ mean, hdi5, hdi95, min, max }) {
  const span = max - min || 1
  const toX = (v) => PAD.left + ((v - min) / span) * IW

  const zeroX = toX(0)
  const meanX = toX(mean)
  const lo = toX(hdi5)
  const hi = toX(hdi95)
  const isPositive = mean >= 0

  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="block w-full">
      {/* Zero reference */}
      <line x1={zeroX} x2={zeroX} y1={8} y2={H - 16}
        stroke="hsl(var(--muted-foreground))" strokeWidth={1} strokeOpacity={0.4} />
      <text x={zeroX} y={H - 4} textAnchor="middle" fontSize={9}
        fill="hsl(var(--muted-foreground))">0</text>

      {/* CI band */}
      <rect x={lo} y={H / 2 - 6} width={hi - lo} height={12}
        fill="hsl(var(--primary))" fillOpacity={0.2} rx={3} />

      {/* Mean marker */}
      <rect x={meanX - 2} y={H / 2 - 10} width={4} height={20}
        fill={isPositive ? 'hsl(var(--primary))' : 'hsl(var(--speed))'}
        rx={2} />

      {/* Labels */}
      <text x={lo} y={H - 4} textAnchor="middle" fontSize={8}
        fill="hsl(var(--muted-foreground))">{hdi5 >= 0 ? '+' : ''}{hdi5.toFixed(2)}</text>
      <text x={hi} y={H - 4} textAnchor="middle" fontSize={8}
        fill="hsl(var(--muted-foreground))">{hdi95 >= 0 ? '+' : ''}{hdi95.toFixed(2)}</text>
    </svg>
  )
}

export default function DriverSkillRating({ widget }) {
  if (widget.error) {
    return (
      <div className="widget-enter max-w-md rounded-xl border border-border/80 bg-card px-4 py-3">
        <p className="text-sm text-muted-foreground">{widget.error}</p>
      </div>
    )
  }

  const {
    driver, skill_mean, hdi_5, hdi_95, rank, n_drivers_rated,
    skill_in_seconds, elo_rating, seasons_used, interpretation, built_at_iso,
  } = widget

  const allValues = [hdi_5, hdi_95, -1, 1]
  const chartMin = Math.min(...allValues) - 0.2
  const chartMax = Math.max(...allValues) + 0.2
  const skillColor = skill_mean >= 0 ? 'hsl(var(--primary))' : 'hsl(var(--speed))'

  return (
    <div className="widget-enter max-w-lg overflow-hidden rounded-xl border border-border/80 bg-card">
      <div className="border-b border-border/80 px-4 py-3">
        <div className="flex items-center justify-between">
          <div className="text-sm font-medium text-foreground">{driver} — Bayesian skill rating</div>
          <div className="text-xs text-muted-foreground">
            #{rank} of {n_drivers_rated} · {seasons_used?.join('–')}
          </div>
        </div>
        <div className="mt-0.5 text-xs text-muted-foreground">
          Model: Bradley-Terry multilevel · {built_at_iso}
        </div>
      </div>

      <div className="px-4 py-4">
        {/* Main metric */}
        <div className="mb-4 flex items-baseline gap-3">
          <span className="font-mono-data text-3xl font-bold"
            style={{ color: skillColor }}>
            {skill_mean >= 0 ? '+' : ''}{skill_mean?.toFixed(2)}
          </span>
          <span className="text-sm text-muted-foreground">SD units</span>
          {skill_in_seconds != null && (
            <span className="ml-1 text-sm" style={{ color: skillColor }}>
              ({skill_in_seconds >= 0 ? '+' : ''}{skill_in_seconds}s/lap vs median)
            </span>
          )}
        </div>

        {/* CI chart */}
        <div className="mb-1 text-xs text-muted-foreground">
          90% credible interval
        </div>
        <CIBar mean={skill_mean ?? 0} hdi5={hdi_5 ?? -0.5} hdi95={hdi_95 ?? 0.5}
          min={chartMin} max={chartMax} />

        {/* Secondary stats */}
        <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-muted-foreground">
          {elo_rating != null && (
            <>
              <span>Elo rating</span>
              <span className="font-mono-data text-foreground">{elo_rating.toFixed(0)}</span>
            </>
          )}
          <span>Uncertainty (SD)</span>
          <span className="font-mono-data text-foreground">{widget.skill_std?.toFixed(3)}</span>
        </div>

        {interpretation && (
          <p className="mt-3 text-xs leading-relaxed text-muted-foreground">{interpretation}</p>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Add import and case to `AnswerRenderer.jsx`**

```jsx
import DriverSkillRating from './chat-widgets/DriverSkillRating.jsx'
```

```jsx
  if (widget.type === 'driver_skill_rating') {
    return <DriverSkillRating widget={widget} />
  }
```

- [ ] **Run the two new tests to confirm they pass**

```
cd server && python -m pytest tests/test_driver_rating.py::test_get_driver_skill_rating_from_cache tests/test_driver_rating.py::test_get_driver_skill_rating_unknown_driver -v
```

Expected: both `PASSED`.

- [ ] **Run full test suite**

```
cd server && python -m pytest tests/ -v
```

- [ ] **Commit**

```
git add server/f1_data.py server/tools.py server/chat.py server/main.py \
        server/driver_rating.py \
        client/src/components/chat-widgets/DriverSkillRating.jsx \
        client/src/components/AnswerRenderer.jsx \
        server/tests/test_driver_rating.py
git commit -m "feat: add get_driver_skill_rating tool, widget, and admin rebuild endpoint"
```

---

### Task 6: Update LLM System Prompt

**Files:**
- Modify: `server/chat.py` — update system prompt to describe driver skill rating semantics

**Why:** Without prompt guidance the LLM will not know how to interpret SD units or credible intervals. The prompt must explain what the Bayesian rating means and how to translate it to natural language.

- [ ] **Write the failing test**

```python
def test_system_prompt_contains_bayesian_skill_guidance():
    """The system prompt must explain how to interpret SD-unit driver skills."""
    import chat
    prompt = chat._build_system_prompt()
    assert 'SD units' in prompt or 'standard deviation' in prompt.lower(), \
        "System prompt must explain driver skill SD units"
    assert 'credible interval' in prompt.lower() or 'hdi' in prompt.lower(), \
        "System prompt must mention credible intervals"
```

- [ ] **Run the test to confirm it fails**

```
cd server && python -m pytest tests/test_chat.py::test_system_prompt_contains_bayesian_skill_guidance -v
```

Expected: `FAILED`.

- [ ] **Find and update the system prompt in `chat.py`**

Locate `_build_system_prompt()` (or equivalent) in `chat.py`. Add a new section for driver skill interpretation:

```python
DRIVER_SKILL_PROMPT = """
## Driver Skill Ratings (Bayesian)

When `get_driver_skill_rating` returns data, interpret it as follows:
- **skill_mean** is in standard deviation (SD) units. Each 1 SD ≈ 0.3 seconds per lap advantage over a median driver in a median car.
- **skill_in_seconds** converts this to lap-time units for plain English.
- The **90% credible interval** [hdi_5, hdi_95] expresses uncertainty. A driver at +0.5 SD with interval [+0.2, +0.8] is clearly above average. A driver at +0.3 SD with interval [-0.1, +0.7] overlaps zero — less certain.
- Do NOT say "avg_ggv_util_pct" or "skill_mean" directly. Translate: "+0.72 SD = roughly 0.22s/lap faster than a typical driver in a typical car".
- The **rank** is among all drivers rated across 2021–2025. Contextualise: "ranked 3rd of 32 drivers analysed".
- Always mention that **constructor effects are removed** — this is driver skill, not car+driver combined.
- When credible interval spans zero, say the rating is "approximately average" or "uncertain — consistent with average".
"""
```

Add `DRIVER_SKILL_PROMPT` to the system prompt assembly, after the GGV/telemetry guidance block.

- [ ] **Run the test to confirm it passes**

```
cd server && python -m pytest tests/test_chat.py::test_system_prompt_contains_bayesian_skill_guidance -v
```

Expected: `PASSED`.

- [ ] **Run full test suite**

```
cd server && python -m pytest tests/ -v
```

- [ ] **Commit**

```
git add server/chat.py server/tests/test_chat.py
git commit -m "feat: add Bayesian driver skill interpretation guidance to LLM system prompt"
```

---

### Task 7: End-to-End Smoke Test — Build Real Ratings

**Files:**
- No code changes — this is a manual validation step

After all code is in place, build the real rating cache and verify the output makes sense:

- [ ] **Trigger an offline rating build** (run from the server directory, not via HTTP — avoids the 15-min background task timeout)

```python
# Run in a Python shell or a one-off script: server/scripts/build_ratings.py
from driver_rating import build_and_cache_ratings

result = build_and_cache_ratings(
    seasons=[2021, 2022, 2023, 2024, 2025],
    draws=1000,
    tune=500,
    chains=2,
)
```

Expected output:
- `[driver_rating] Fetching comparisons...` then a count like `~4000 comparison pairs`
- Elo top-5 should show established top drivers (VER, NOR, HAM, LEC, ALO in plausible order)
- Bayesian model NUTS sampling with progress shown in server logs
- Cache written to `server/cache/driver_ratings.json`

- [ ] **Sanity-check the output**

```python
from driver_rating import load_cached_ratings

cache = load_cached_ratings()
skills = cache['driver_skills']

# Sort by mean
ranked = sorted(skills.items(), key=lambda x: x[1]['mean'], reverse=True)
for i, (drv, s) in enumerate(ranked[:10]):
    print(f"#{i+1} {drv}: {s['mean']:+.3f} SD ({s['hdi_5']:+.3f} to {s['hdi_95']:+.3f})")
```

Expected sanity check: top 5 should be broadly consistent with expert consensus and Elo baseline. If VER/HAM/NOR/ALO are not in the top 5 with a clear separation from P15+, the model or data pipeline has a bug — re-examine `fetch_comparison_pairs` for season coverage.

- [ ] **Test the API endpoint**

With the server running:
```
curl -X POST http://localhost:8000/api/admin/rebuild-driver-ratings
```

Then ask the chat: "How good is Norris really?" — the LLM should call `get_driver_skill_rating`, receive the cached result, and produce an interpretation using the credible interval.

- [ ] **Final commit**

```
git add server/cache/driver_ratings.json
git commit -m "data: add initial Bayesian driver ratings cache (2021–2025)"
```

---

### Final: Regression Run

- [ ] **Run the complete test suite**

```
cd server && python -m pytest tests/ -v --tb=short
```

Expected: all tests pass. PyMC tests that require the library will `SKIP` if it's not installed; all others pass unconditionally.
