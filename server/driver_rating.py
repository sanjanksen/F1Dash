"""
Bayesian driver skill + constructor-year decomposition.

Model: Bradley-Terry multilevel (van Kesteren & Bergkamp, JQAS 2023).
P(A beats B | car_A, car_B) = sigmoid(theta_A + phi_ctor_A - theta_B - phi_ctor_B)
theta_driver ~ ZeroSumNormal(0, 1); phi_constructor_year ~ Normal(0, 0.5)

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
      theta_driver ~ ZeroSumNormal(0, 1)         # sums to zero across all drivers
      phi_constructor ~ Normal(0, 0.5)            # constructor-year advantage
      logit P(A beats B) = theta_A + phi_ctor_A - theta_B - phi_ctor_B
      outcome ~ Bernoulli(logit_p)                # winner always = 1

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
        driver_skill         = pm.ZeroSumNormal('driver_skill',   sigma=1.0, shape=len(drivers))
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
            cores=1,
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

    driver_skill_arr  = trace.posterior['driver_skill'].values
    ctor_strength_arr = trace.posterior['constructor_strength'].values

    driver_skills  = {drv: _summarise(driver_skill_arr, i)  for i, drv in enumerate(drivers)}
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
    Takes 5-15 minutes. Intended for offline/scheduled runs, not the request path.
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
