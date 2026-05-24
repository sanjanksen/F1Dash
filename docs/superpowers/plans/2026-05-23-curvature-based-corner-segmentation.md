# Curvature-Based Corner Segmentation Implementation Plan (v4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the nearest-apex-within-150m corner resolver with geometric segmentation derived from track centerline curvature κ(s). Each corner is identified by an explicit `(entry_m, apex_m, exit_m)` region rather than a fixed-radius bubble around a hand-authored apex point.

**Architecture:** A new `corner_segmentation` module computes per-circuit corner regions once and caches them on disk. The pipeline is: pull X/Y from a clean reference lap → drop NaN / deduplicate → cumulative arc length → uniform resample at Δs = 2m using actual computed spacing → Savitzky-Golay smoothing → finite-difference curvature κ(s) → hysteresis threshold to detect corner regions → merge wrap-around boundary regions → one-to-one match each region to FastF1's MultiViewer corner number → validate result → write versioned JSON cache. The existing `f1_data._resolve_corner_for_distance` becomes a thin delegator that requires `year` (no longer optional), and `year` is threaded down from `analyze_qualifying_battle` via the loaded session's `event.year` attribute.

**Tech Stack:** Python, NumPy, SciPy (`scipy.signal.savgol_filter`, `scipy.interpolate.interp1d`), FastF1, pytest. Disk cache: versioned JSON under `server/cache/corner_regions/`.

**Revisions from v1 (driven by Codex round 1):**
- Year is now required, not optional — Task 0a audits and threads it through the entire stack so the new path actually fires in production.
- New Task 1 cleans the position trace before interpolation (NaN, duplicates, minimum sample count).
- Resampling uses `np.arange` with the real computed spacing — fixes a subtle curvature mis-scaling bug.
- `_detect_regions` merges wrap-around regions when both flank `s=0`.
- `_tag_regions` is now greedy one-to-one (no duplicate names, no dropped MultiViewer corners).
- `_resolve_corner_for_distance` supports wrap-around "final → first straight" semantics.
- Cache files carry a `schema_version` field; mismatches force rebuild.
- `get_corner_regions` validates the build before writing (region count, total arc length plausibility); refuses to write garbage.
- Integration test list expanded with FastF1-shape synthetic fixtures (sparse, noisy, NaN) and edge-case hysteresis tests.

**Revisions from v2 (driven by Codex round 2):**
- Task 0a Step 7 now explicitly updates `_make_mock_session` (line 501 in `test_f1_data.py`) and every inline `session.event = {...}` mock to include `"Year": 2025`. Without this, every test routing through `analyze_qualifying_battle` raises `KeyError: 'Year'`.
- Task 2's `_resample_uniform` returns the true total arc length as a fifth tuple element instead of `s_u[-1] + spacing` reconstructing it (which overshoots by up to one spacing).
- Task 4 adds region-width filtering (`MIN_REGION_WIDTH_M=20`) and same-sign-adjacent-region merging (gap < `DEBOUNCE_GAP_M=10`) before the validation gate, so noisy κ doesn't blow past `MAX_REGIONS=40`.
- Task 6 rewrites the synthetic test fixture from a 2-corner oval to a 6-corner synthetic circuit — the previous fixture could never pass `MIN_REGIONS=4`.
- Task 6 schema-rebuild test now asserts the rebuilt JSON has `schema_version == SCHEMA_VERSION` and that `_lap_length_for(year, round)` is populated.
- Task 7 replaces linear `apex_m` sorting with explicit circular arithmetic (`_arc_distance_forward` / `_arc_distance_backward`) for the straight-lookup branch — wrap-around regions no longer produce "Turn 1 → Turn 1 straight" nonsense.
- Task 7 falls back to legacy nearest-MV-apex when the matched region is untagged (`corner_number is None`), so callers always get a useful label even if `_tag_regions` ran out of unclaimed MV corners.
- Task 6 and Task 7 validate `year` at the segmentation API boundary — `get_corner_regions(None, ...)` raises `SegmentationInputError` rather than building a garbage `None_<round>.json` cache file.

**Revisions from v3 (driven by Codex round 3):**
- Task 4 reorders `_detect_regions` so wrap-merge runs BEFORE width-filter. A wrap-around corner that produced two 18m halves used to get filtered as noise before getting merged — fix preserves the full merged width. Wrap-around-aware region width helper handles `entry_m > exit_m`. New test `test_detect_regions_wrap_around_corner_survives_width_filter`.
- Schema bumped from `1` to `2`. v2 cache JSON now includes a `multiviewer_corners` array alongside `regions`. `_read_cache` returns a 3-tuple `(regions, lap_length, mv)`; `_write_cache` validates that every region boundary is within `[0, lap_length]` before writing. The resolver's untagged-region fallback reads MV from the in-process `_MV_BY_KEY` cache (populated by `get_corner_regions` from disk or fresh build) — **never** hits FastF1/network.
- Task 7 `resolve_corner_for_distance` normalizes `target` via `target % lap_length` after validation, so floating-point drift or multi-lap distances don't break circular arithmetic. New test `test_resolve_normalizes_distance_outside_lap_length`.
- Task 7 `resolve_corner_for_distance` validates `distance_m` finiteness at the API entry — raises `SegmentationInputError` for `None`, `NaN`, or `inf`. The legacy f1_data path already guarded this; the new public API now matches. New test `test_resolve_rejects_non_finite_distance`.

**Revisions from v4 (driven by Codex round 4):**
- `get_corner_regions` now has a degraded-mode fallback: if the v2 rebuild fails (network down, FastF1 hiccup) AND an older-schema cache exists on disk, the function returns the older cache's regions with an empty MV list rather than raising every call. The `_MV_BY_KEY` cache is set to `[]` in the degraded case, so the resolver's untagged-region fallback emits `"in corner"` rather than a named label — still better than total failure. Two new tests: `test_get_corner_regions_falls_back_to_degraded_v1_cache` and `test_get_corner_regions_raises_when_no_cache_and_rebuild_fails`.
- `_read_cache` re-applies the `MIN_LAP_LENGTH_M`/`MAX_LAP_LENGTH_M` and per-region boundary gates to anything it reads from disk. A corrupt or hand-edited cache with `lap_length=0.001` no longer slips past the `lap_length > 0` resolver guard. New tests: `test_read_cache_rejects_invalid_lap_length`, `test_read_cache_rejects_out_of_bounds_region`.
- `_write_cache` uses an adaptive boundary tolerance `tol = max(1e-3, lap_length * 1e-9)` and clamps values within tolerance back into `[0, lap_length]` instead of rejecting. Values outside tolerance still raise. New test: `test_write_cache_clamps_boundary_within_tolerance`.
- Document heading bumped from v2 to v4.

---

## File Structure

**New files:**
- `server/corner_segmentation.py` — public API: `get_corner_regions(year, round_number) -> list[CornerRegion]`, `resolve_corner_for_distance(year, round_number, distance_m) -> dict`. Internal helpers for cleaning, arc length, resampling, smoothing, curvature, hysteresis segmentation, wrap-around merging, one-to-one tagging, validation, disk caching.
- `server/tests/test_corner_segmentation.py` — unit tests covering data cleaning, arc length, resampling, curvature on synthetic geometry, hysteresis edge cases, wrap-around merging, one-to-one tagging, cache version checks, FastF1-shape fixtures.
- `server/tests/test_corner_segmentation_integration.py` — opt-in (`INTEGRATION=1`) FastF1-backed smoke tests for Miami T17/T18 and Eau Rouge.

**Modified files:**
- `server/f1_data.py`:
  - `_summarize_telemetry_battle` signature gains a required `year: int` parameter.
  - `_telemetry_location_context` signature gains a required `year: int` parameter.
  - `_resolve_corner_for_distance` signature changes to `(round_number, distance_m, year)` — `year` required, not optional.
  - `analyze_qualifying_battle` extracts `year = session.event['Year']` after `_get_comparable_qualifying_laps` returns the session, then passes `year=year` to both downstream callers.
- `server/tests/test_f1_data.py` — update all existing resolver/context tests to pass `year` explicitly and mock `corner_segmentation.resolve_corner_for_distance` where needed.
- `server/features/qualifying_battle.py` — no signature change (it calls `analyze_qualifying_battle` which extracts year internally).

**Cache directory:** `server/cache/corner_regions/<year>_<round>.json`. JSON shape:

```json
{
  "schema_version": 2,
  "lap_length_m": 5410.0,
  "multiviewer_corners": [
    {"number": 1, "letter": "", "distance_m": 706.0},
    ...
  ],
  "regions": [
    {"corner_number": 1, "label_suffix": "", "entry_m": 660.0, "apex_m": 706.0, "exit_m": 760.0, "sign": -1},
    ...
  ]
}
```

`multiviewer_corners` is persisted alongside `regions` so the resolver's untagged-region fallback never needs to call FastF1 at lookup time. Schema version is **2** in v3 because v1's shape lacked the MV array.

---

## Task 0a: Audit current call sites and thread `year` through the analysis stack

This is the prerequisite that v1 missed. Until `year` is reachable inside `_summarize_telemetry_battle` and `_telemetry_location_context`, the new resolver cannot run in production.

**Files:**
- Modify: `server/f1_data.py` — `_summarize_telemetry_battle` signature (line 3819), `_telemetry_location_context` signature (line 3635), `analyze_qualifying_battle` body (line 4234), call sites at lines ~4368, ~4505, ~4530, and call to `_resolve_corner_for_distance` at line 3945
- Modify: `server/tests/test_f1_data.py` — every test calling these functions

- [ ] **Step 1: Locate all call sites**

Run: `grep -n "_summarize_telemetry_battle\|_telemetry_location_context\|_resolve_corner_for_distance" server/f1_data.py server/features/qualifying_battle.py server/tests/test_f1_data.py`

Expected: matches in `f1_data.py` (def + 4 internal calls), `tests/test_f1_data.py` (~12 test cases). Confirm `qualifying_battle.py` does NOT call these helpers directly — only the public `analyze_qualifying_battle`.

- [ ] **Step 2: Confirm year is reachable from the analysis entry point**

Open `server/f1_data.py` and locate `analyze_qualifying_battle` (line 4234). Confirm the call:

```python
session, compared_segment, chosen_laps = _get_comparable_qualifying_laps(round_number, [driver_a, driver_b], session_type)
```

immediately after this line, add:

```python
    year = int(session.event["Year"])
```

This is the canonical source of year used elsewhere in the file. Do not change `analyze_qualifying_battle`'s public signature.

- [ ] **Step 3: Add `year` as a required parameter to `_resolve_corner_for_distance`**

Find this signature at line 3445:

```python
def _resolve_corner_for_distance(
    round_number: int,
    distance_m: int | float | None,
) -> dict:
```

Change to:

```python
def _resolve_corner_for_distance(
    round_number: int,
    distance_m: int | float | None,
    year: int,
) -> dict:
```

Leave the body untouched in this task — Task 8 wires in the segmentation call.

- [ ] **Step 4: Add `year` as a required parameter to `_telemetry_location_context`**

Find the signature at line 3635:

```python
def _telemetry_location_context(round_number: int, distance_m: int | float | None, cause_type: str | None) -> dict:
```

Change to:

```python
def _telemetry_location_context(round_number: int, distance_m: int | float | None, cause_type: str | None, year: int) -> dict:
```

- [ ] **Step 5: Add `year` as a required parameter to `_summarize_telemetry_battle`**

Find the signature at line 3819-3829. Add `year: int` as a required keyword-only parameter after the existing keyword parameters:

```python
def _summarize_telemetry_battle(
    samples: list[dict],
    faster_driver: str,
    driver_a: str,
    driver_b: str,
    sector_boundary_distances: list | tuple | None = None,
    top_k: int = 4,
    min_spacing_m: float = 200.0,
    round_number: int | None = None,
    authoritative_sector_gaps_s: dict | None = None,
    year: int | None = None,
) -> dict | None:
```

Mark `year` as Optional with default `None` here so the existing unit tests in `test_f1_data.py` that hand-craft samples but don't load a session can still run. Inside the body, when calling `_resolve_corner_for_distance` at line 3945, pass `year=year` — but only when `year is not None`:

Replace line 3945:

```python
corner_info = _resolve_corner_for_distance(round_number, marker["distance_m"])
```

with:

```python
corner_info = _resolve_corner_for_distance(round_number, marker["distance_m"], year) if year is not None else _resolve_corner_for_distance_legacy(round_number, marker["distance_m"])
```

Add this immediately before `_resolve_corner_for_distance`'s definition in `f1_data.py` (a one-line alias for test back-compat):

```python
def _resolve_corner_for_distance_legacy(round_number: int, distance_m: int | float | None) -> dict:
    """Back-compat for unit tests that don't have a year. New code MUST pass year."""
    return _resolve_corner_for_distance(round_number, distance_m, year=-1)
```

In `_resolve_corner_for_distance`, treat `year=-1` (or any non-positive year) as "skip segmentation, use fallback only." Document this in the docstring.

- [ ] **Step 6: Update call sites in `analyze_qualifying_battle`**

Find the call to `_summarize_telemetry_battle` at line 4368-4376. Add `year=year`:

```python
telemetry_summary = _summarize_telemetry_battle(
    comparison_samples,
    faster_driver,
    driver_a_code,
    driver_b_code,
    sector_boundary_distances=sector_boundary_distances,
    round_number=round_number,
    authoritative_sector_gaps_s=authoritative_sector_gaps_s,
    year=year,
)
```

Find the two calls to `_telemetry_location_context` at lines 4505 and 4530. Add `year=year` to each.

- [ ] **Step 7: Update existing tests that call these functions**

Three separate changes — apply ALL of them:

**(a) Update `_make_mock_session` to include "Year".** Locate the helper at `server/tests/test_f1_data.py:501`:

```python
def _make_mock_session(fastest_laps_by_driver: dict, event_name="Monaco Grand Prix"):
    mock_session = MagicMock()
    mock_session.event = {'EventName': event_name}
    # ...rest unchanged...
```

Change the signature and assignment to:

```python
def _make_mock_session(fastest_laps_by_driver: dict, event_name="Monaco Grand Prix", year=2025):
    mock_session = MagicMock()
    mock_session.event = {'EventName': event_name, 'Year': year}
    # ...rest unchanged...
```

**(b) Update every inline `session.event = {...}` mock to include `'Year'`.** Locations to fix (verify with `grep -n "session\.event\s*=" server/tests/test_f1_data.py`):
- Line 707: `mock_session.event = {'EventName': 'Monaco Grand Prix'}` → add `, 'Year': 2025`
- Line 729: same
- Line 1695: `mock_session.event = {"EventName": "Test GP"}` → add `, "Year": 2025`
- Line 1713: same with Bahrain → add `, "Year": 2025`
- Line 1764: same with Bahrain → add `, "Year": 2025`

Run `grep -n "session\.event\s*=" server/tests/test_f1_data.py` after editing to confirm no remaining mocks without `'Year'`.

**(c) Update direct-call tests of the renamed helpers.** For `_resolve_corner_for_distance` tests (lines 1192-1257), pass `year=-1` to force the fallback path:

```python
result = f1_data._resolve_corner_for_distance(1, 720, year=-1)
```

For `_telemetry_location_context` tests (lines 1087-1185), pass `year=-1` similarly.

For `_summarize_telemetry_battle` tests that hand-construct samples and don't go through `analyze_qualifying_battle`, pass `year=None` so the function uses the legacy resolver — those tests already mock `get_circuit_corners`, so behavior is preserved.

- [ ] **Step 8: Run the full test suite**

Run from `server/`:

```bash
python -m pytest tests/ -v
```

Expected: all tests pass. If any fail with `TypeError: missing required argument 'year'`, that call site was missed in Step 7 — fix it.

- [ ] **Step 9: Commit**

```bash
git add server/f1_data.py server/tests/test_f1_data.py
git commit -m "refactor(corner-resolver): thread year through telemetry-battle analysis stack"
```

---

## Task 0b: Verify dependencies and scaffold module

**Files:**
- Create: `server/corner_segmentation.py`
- Modify: `server/requirements.txt`

- [ ] **Step 1: Check whether scipy is already a project dependency**

Run: `python -c "import scipy; print(scipy.__version__)"`

If ModuleNotFoundError, proceed to Step 2. Otherwise skip to Step 3.

- [ ] **Step 2: Add scipy**

Append to `server/requirements.txt`:

```
scipy>=1.11
```

Run: `pip install -r server/requirements.txt`

- [ ] **Step 3: Create the module skeleton**

Create `server/corner_segmentation.py`:

```python
"""Curvature-based corner segmentation.

Builds a list of CornerRegion records per circuit by computing curvature
κ(s) along the track centerline derived from a clean reference lap's
position telemetry. Each region exposes explicit (entry_m, apex_m, exit_m)
bounds — replacing the nearest-apex-within-radius heuristic with proper
geometric segmentation. Track is treated as circular (wrap-around handled).

Public API:
    get_corner_regions(year, round_number) -> list[CornerRegion]
    resolve_corner_for_distance(year, round_number, distance_m) -> dict
"""

from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import asdict, dataclass
from typing import Optional

import numpy as np

LOGGER = logging.getLogger(__name__)

# Bump when serialization shape or pipeline math changes; old cache files
# with a different version are ignored and rebuilt. v2 added the
# `multiviewer_corners` field to support resolver fallback without
# triggering a network FastF1 load.
SCHEMA_VERSION = 2

CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache", "corner_regions")

# Hysteresis thresholds expressed as percentiles of |κ| over the lap.
# Entering a corner requires |κ| to exceed κ_enter; staying only requires
# |κ| above κ_exit. Prevents jitter near boundaries.
KAPPA_ENTER_PERCENTILE = 70.0
KAPPA_EXIT_PERCENTILE = 50.0

# Target spacing for arc-length resampling. Real spacing is computed from
# total length and passed explicitly to the differentiator (do not assume).
RESAMPLE_SPACING_M = 2.0

# Savitzky-Golay smoother applied to resampled X/Y before differentiation.
SAVGOL_WINDOW = 21
SAVGOL_POLY = 3

# Minimum number of position samples required to attempt segmentation.
# Below this, raise so the caller falls back to the legacy resolver.
MIN_RAW_SAMPLES = 100

# Detected regions narrower than this are discarded as noise (single-
# sample κ blips, GPS chatter near walls).
MIN_REGION_WIDTH_M = 20.0

# Same-sign adjacent regions with a gap smaller than this are merged
# back together (handles a single-sample dip below κ_exit inside a
# real corner that shouldn't fragment it).
DEBOUNCE_GAP_M = 10.0

# Validity gates applied to the freshly built region list before writing
# to disk. If any gate fails the cache is NOT written.
MIN_REGIONS = 4   # below this, segmentation almost certainly failed
MAX_REGIONS = 40  # F1 circuits have at most ~25 named corners
MIN_LAP_LENGTH_M = 2000.0
MAX_LAP_LENGTH_M = 8500.0


@dataclass
class CornerRegion:
    corner_number: Optional[int]
    label_suffix: str  # "", "a", "b" for chicane sub-corners
    entry_m: float
    apex_m: float
    exit_m: float
    sign: int  # +1 = left, -1 = right


def get_corner_regions(year: int, round_number: int) -> list[CornerRegion]:
    """Return cached or freshly computed corner regions, with lap length."""
    raise NotImplementedError


def resolve_corner_for_distance(
    year: int, round_number: int, distance_m: float
) -> dict:
    """Resolve a distance to {corner_number, corner_name, location_label}."""
    raise NotImplementedError
```

- [ ] **Step 4: Commit the scaffold**

```bash
git add server/corner_segmentation.py server/requirements.txt
git commit -m "scaffold: corner_segmentation module skeleton"
```

---

## Task 1: Data cleaning (NaN, duplicate, minimum-sample guard)

**Files:**
- Modify: `server/corner_segmentation.py`
- Test: `server/tests/test_corner_segmentation.py`

- [ ] **Step 1: Write the failing tests**

Create `server/tests/test_corner_segmentation.py`:

```python
import json
import math

import numpy as np
import pytest

import corner_segmentation as cs


def test_clean_xy_drops_non_finite():
    x = np.array([0.0, 1.0, np.nan, 3.0, np.inf, 5.0])
    y = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
    cx, cy = cs._clean_xy(x, y)
    assert cx.tolist() == [0.0, 1.0, 3.0, 5.0]
    assert cy.tolist() == [0.0, 1.0, 3.0, 5.0]


def test_clean_xy_drops_zero_arc_length_duplicates():
    # Adjacent identical (x, y) — second must be dropped because it
    # produces a zero-length segment that breaks cubic interpolation.
    x = np.array([0.0, 1.0, 1.0, 2.0])
    y = np.array([0.0, 0.0, 0.0, 0.0])
    cx, cy = cs._clean_xy(x, y)
    assert cx.tolist() == [0.0, 1.0, 2.0]
    assert cy.tolist() == [0.0, 0.0, 0.0]


def test_clean_xy_raises_when_below_minimum_samples():
    x = np.array([0.0, 1.0, 2.0])
    y = np.array([0.0, 1.0, 2.0])
    with pytest.raises(cs.SegmentationInputError):
        cs._clean_xy(x, y)
```

- [ ] **Step 2: Run the failing tests**

Run: `cd server; python -m pytest tests/test_corner_segmentation.py -v`

Expected: FAIL with `AttributeError: module 'corner_segmentation' has no attribute '_clean_xy'`.

- [ ] **Step 3: Implement cleaning**

Add to `server/corner_segmentation.py` after the dataclass:

```python
class SegmentationInputError(ValueError):
    """Raised when input data is too sparse or corrupt to segment safely."""


def _clean_xy(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Drop non-finite rows and zero-arc-length duplicates.

    Raises SegmentationInputError if fewer than MIN_RAW_SAMPLES rows
    survive — caller is expected to fall back to a legacy resolver.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    finite = np.isfinite(x) & np.isfinite(y)
    x = x[finite]
    y = y[finite]
    if len(x) < 2:
        raise SegmentationInputError(f"only {len(x)} finite samples")
    # Drop any sample identical to the previous one (zero arc-length).
    keep = np.ones(len(x), dtype=bool)
    keep[1:] = (x[1:] != x[:-1]) | (y[1:] != y[:-1])
    x = x[keep]
    y = y[keep]
    if len(x) < MIN_RAW_SAMPLES:
        raise SegmentationInputError(
            f"only {len(x)} valid samples after cleaning (need >= {MIN_RAW_SAMPLES})"
        )
    return x, y
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd server; python -m pytest tests/test_corner_segmentation.py -v`

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add server/corner_segmentation.py server/tests/test_corner_segmentation.py
git commit -m "feat(corner-segmentation): clean non-finite and duplicate samples"
```

---

## Task 2: Arc length and resampling (correct spacing)

**Files:**
- Modify: `server/corner_segmentation.py`
- Test: `server/tests/test_corner_segmentation.py`

- [ ] **Step 1: Write the failing tests**

Append to `server/tests/test_corner_segmentation.py`:

```python
def test_cumulative_arc_length_for_straight_line():
    x = np.array([0.0, 3.0, 6.0, 9.0])
    y = np.array([0.0, 4.0, 8.0, 12.0])
    s = cs._cumulative_arc_length(x, y)
    assert s == pytest.approx([0.0, 5.0, 10.0, 15.0])


def test_resample_uses_exact_arange_spacing():
    x = np.array([0.0, 7.0, 23.0, 50.0])
    y = np.zeros_like(x)
    xs, ys, s_new, dx, total = cs._resample_uniform(x, y, spacing_m=5.0)
    # arange semantics: 0, 5, 10, ..., last point <= 50.
    assert s_new[0] == pytest.approx(0.0)
    assert s_new[-1] <= 50.0
    deltas = np.diff(s_new)
    assert np.all(np.abs(deltas - 5.0) < 1e-9)
    assert dx == pytest.approx(5.0)
    # total must equal the true arc length, not s_new[-1] + spacing.
    assert total == pytest.approx(50.0)


def test_resample_returns_true_total_when_not_divisible():
    # Total length 11m, spacing 4m → samples at 0, 4, 8 (last <= 11)
    # but `total` must be the actual 11m arc length, not 12m.
    x = np.array([0.0, 11.0])
    y = np.array([0.0, 0.0])
    xs, ys, s_new, dx, total = cs._resample_uniform(x, y, spacing_m=4.0)
    assert s_new.tolist() == [0.0, 4.0, 8.0]
    assert dx == pytest.approx(4.0)
    assert total == pytest.approx(11.0)
```

- [ ] **Step 2: Run failing tests**

Run: `cd server; python -m pytest tests/test_corner_segmentation.py -v`

Expected: FAIL on the new tests with `AttributeError: module 'corner_segmentation' has no attribute '_cumulative_arc_length'`.

- [ ] **Step 3: Implement arc length and resampling**

Add to `server/corner_segmentation.py`:

```python
from scipy.interpolate import interp1d


def _cumulative_arc_length(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    dx = np.diff(x)
    dy = np.diff(y)
    seg = np.sqrt(dx * dx + dy * dy)
    return np.concatenate(([0.0], np.cumsum(seg)))


def _resample_uniform(
    x: np.ndarray, y: np.ndarray, spacing_m: float = RESAMPLE_SPACING_M
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float, float]:
    """Resample (x, y) at exact `spacing_m` arc-length spacing.

    Returns (x_new, y_new, s_new, spacing, total) where `spacing` is the
    actual spacing used (always == spacing_m) and `total` is the true
    cumulative arc length of the input polyline. The last point of
    s_new is the largest multiple of spacing_m that does not exceed
    `total` — DO NOT reconstruct total as `s_new[-1] + spacing`,
    that overshoots by up to one spacing.
    """
    s = _cumulative_arc_length(x, y)
    total = float(s[-1])
    s_new = np.arange(0.0, total + 1e-9, spacing_m)
    # arange may overshoot total by floating dust; trim.
    s_new = s_new[s_new <= total]
    if len(s_new) < 2:
        raise SegmentationInputError(
            f"total arc length {total}m too short for spacing {spacing_m}m"
        )
    x_interp = interp1d(s, x, kind="cubic", assume_sorted=True)
    y_interp = interp1d(s, y, kind="cubic", assume_sorted=True)
    return x_interp(s_new), y_interp(s_new), s_new, float(spacing_m), total
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd server; python -m pytest tests/test_corner_segmentation.py -v`

Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add server/corner_segmentation.py server/tests/test_corner_segmentation.py
git commit -m "feat(corner-segmentation): arc length + exact-spacing arange resampling"
```

---

## Task 3: Curvature computation

**Files:**
- Modify: `server/corner_segmentation.py`
- Test: `server/tests/test_corner_segmentation.py`

- [ ] **Step 1: Write the failing tests**

Append to `server/tests/test_corner_segmentation.py`:

```python
def test_curvature_is_zero_for_straight_line():
    x = np.linspace(0, 100, 51)  # exact 2m spacing
    y = np.zeros_like(x)
    kappa = cs._compute_curvature(x, y, spacing_m=2.0)
    assert np.all(np.abs(kappa[10:-10]) < 1e-3)


def test_curvature_matches_circle_radius():
    R = 50.0
    # half circle resampled at exact 1m spacing along arc
    arc_length = math.pi * R
    s = np.arange(0.0, arc_length + 1e-9, 1.0)
    theta = s / R
    x = R * np.cos(theta)
    y = R * np.sin(theta)
    kappa = cs._compute_curvature(x, y, spacing_m=1.0)
    interior = kappa[30:-30]
    assert np.median(np.abs(interior)) == pytest.approx(1.0 / R, rel=0.05)


def test_curvature_returns_zeros_for_too_few_samples():
    x = np.array([0.0, 1.0, 2.0])  # below SAVGOL window
    y = np.array([0.0, 0.0, 0.0])
    kappa = cs._compute_curvature(x, y, spacing_m=1.0)
    assert kappa.tolist() == [0.0, 0.0, 0.0]
```

- [ ] **Step 2: Run failing tests**

Run: `cd server; python -m pytest tests/test_corner_segmentation.py -v`

Expected: FAIL with `AttributeError: module 'corner_segmentation' has no attribute '_compute_curvature'`.

- [ ] **Step 3: Implement curvature**

Add to `server/corner_segmentation.py`:

```python
from scipy.signal import savgol_filter


def _compute_curvature(
    x: np.ndarray, y: np.ndarray, spacing_m: float
) -> np.ndarray:
    """Signed curvature κ(s) for uniformly resampled (x, y).

    Sign convention: positive κ = left turn (counter-clockwise),
    negative = right turn.
    """
    n = len(x)
    # Pick the largest valid odd window <= SAVGOL_WINDOW and <= n.
    window = min(SAVGOL_WINDOW, n if n % 2 == 1 else n - 1)
    if window < 5 or window <= SAVGOL_POLY:
        return np.zeros_like(x)
    dx = savgol_filter(x, window, SAVGOL_POLY, deriv=1, delta=spacing_m)
    dy = savgol_filter(y, window, SAVGOL_POLY, deriv=1, delta=spacing_m)
    ddx = savgol_filter(x, window, SAVGOL_POLY, deriv=2, delta=spacing_m)
    ddy = savgol_filter(y, window, SAVGOL_POLY, deriv=2, delta=spacing_m)
    denom = (dx * dx + dy * dy) ** 1.5
    denom = np.where(denom < 1e-9, 1e-9, denom)
    return (dx * ddy - dy * ddx) / denom
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd server; python -m pytest tests/test_corner_segmentation.py -v`

Expected: 9 PASS.

- [ ] **Step 5: Commit**

```bash
git add server/corner_segmentation.py server/tests/test_corner_segmentation.py
git commit -m "feat(corner-segmentation): signed curvature via Savitzky-Golay derivatives"
```

---

## Task 4: Hysteresis region detection (with edge cases and wrap-around merging)

**Files:**
- Modify: `server/corner_segmentation.py`
- Test: `server/tests/test_corner_segmentation.py`

- [ ] **Step 1: Write the failing tests**

Append to `server/tests/test_corner_segmentation.py`:

```python
def test_detect_regions_picks_single_corner_from_kappa_bump():
    s = np.arange(0, 280, 2.0)
    kappa = np.zeros_like(s)
    kappa[(s >= 100) & (s < 180)] = 0.02
    regions = cs._detect_regions(s, kappa, kappa_enter=0.015, kappa_exit=0.01, lap_length_m=float(s[-1]))
    assert len(regions) == 1
    entry, apex, exit_, sign = regions[0]
    assert entry == pytest.approx(100.0, abs=2.0)
    assert exit_ == pytest.approx(178.0, abs=2.0)
    assert 100.0 <= apex <= 180.0
    assert sign == 1


def test_detect_regions_separates_chicane_with_opposite_signs():
    s = np.arange(0, 300, 2.0)
    kappa = np.zeros_like(s)
    kappa[(s >= 100) & (s < 140)] = 0.02
    kappa[(s >= 160) & (s < 200)] = -0.02
    regions = cs._detect_regions(s, kappa, kappa_enter=0.015, kappa_exit=0.01, lap_length_m=float(s[-1]))
    assert len(regions) == 2
    assert regions[0][3] == 1
    assert regions[1][3] == -1


def test_detect_regions_handles_open_region_at_lap_start():
    # κ already above enter threshold at s=0 — region opens immediately.
    s = np.arange(0, 200, 2.0)
    kappa = np.zeros_like(s)
    kappa[s < 50] = 0.02
    regions = cs._detect_regions(s, kappa, kappa_enter=0.015, kappa_exit=0.01, lap_length_m=float(s[-1]))
    assert len(regions) == 1
    assert regions[0][0] == pytest.approx(0.0)


def test_detect_regions_handles_open_region_at_lap_end():
    s = np.arange(0, 200, 2.0)
    kappa = np.zeros_like(s)
    kappa[s >= 150] = 0.02
    regions = cs._detect_regions(s, kappa, kappa_enter=0.015, kappa_exit=0.01, lap_length_m=float(s[-1]))
    assert len(regions) == 1
    entry, apex, exit_, sign = regions[0]
    assert entry == pytest.approx(150.0, abs=2.0)
    assert exit_ == pytest.approx(s[-1], abs=2.0)


def test_detect_regions_merges_wrap_around_corner():
    # Corner straddles the start/finish line: high κ at both ends.
    lap_length = 200.0
    s = np.arange(0, lap_length, 2.0)
    kappa = np.zeros_like(s)
    kappa[s < 20] = 0.02      # tail of the corner
    kappa[s >= 180] = 0.02    # head of the corner
    regions = cs._detect_regions(s, kappa, kappa_enter=0.015, kappa_exit=0.01, lap_length_m=lap_length)
    # The two halves are the same corner — must merge to one region with
    # entry_m > exit_m (wrap-around marker) so callers know it crosses 0.
    assert len(regions) == 1
    entry, apex, exit_, sign = regions[0]
    assert entry == pytest.approx(180.0, abs=2.0)
    assert exit_ == pytest.approx(18.0, abs=2.0)
    assert sign == 1


def test_detect_regions_does_not_merge_when_only_one_end_active():
    s = np.arange(0, 200, 2.0)
    kappa = np.zeros_like(s)
    kappa[s >= 180] = 0.02
    regions = cs._detect_regions(s, kappa, kappa_enter=0.015, kappa_exit=0.01, lap_length_m=200.0)
    assert len(regions) == 1
    entry, apex, exit_, sign = regions[0]
    assert entry == pytest.approx(180.0, abs=2.0)
    assert exit_ <= 200.0
    # Not a wrap-around — entry < exit.
    assert entry < exit_


def test_detect_regions_drops_too_narrow_regions():
    # Two κ bumps: a 4m wide blip (noise) and a 50m real corner.
    s = np.arange(0, 200, 2.0)
    kappa = np.zeros_like(s)
    kappa[(s >= 30) & (s < 34)] = 0.02   # 4m wide — drop
    kappa[(s >= 100) & (s < 150)] = 0.02 # 50m wide — keep
    regions = cs._detect_regions(s, kappa, kappa_enter=0.015, kappa_exit=0.01, lap_length_m=200.0)
    assert len(regions) == 1
    assert regions[0][0] == pytest.approx(100.0, abs=2.0)


def test_detect_regions_merges_same_sign_adjacent_after_brief_gap():
    # One real corner with a single-sample dip below κ_exit at s=120.
    s = np.arange(0, 200, 2.0)
    kappa = np.zeros_like(s)
    kappa[(s >= 100) & (s < 150)] = 0.02
    kappa[s == 120] = 0.005  # one-sample dip
    regions = cs._detect_regions(s, kappa, kappa_enter=0.015, kappa_exit=0.01, lap_length_m=200.0)
    assert len(regions) == 1
    entry, apex, exit_, sign = regions[0]
    assert entry == pytest.approx(100.0, abs=2.0)
    assert exit_ == pytest.approx(148.0, abs=2.0)


def test_detect_regions_wrap_around_corner_survives_width_filter():
    # Two 18m wrap-around halves of a real corner. Each half alone is
    # below MIN_REGION_WIDTH_M=20, but the merged region is 36m and
    # must survive.
    lap_length = 200.0
    s = np.arange(0, lap_length, 2.0)
    kappa = np.zeros_like(s)
    kappa[s < 18] = 0.02       # 18m at lap start
    kappa[s >= 182] = 0.02     # 18m at lap end
    regions = cs._detect_regions(s, kappa, kappa_enter=0.015, kappa_exit=0.01, lap_length_m=lap_length)
    assert len(regions) == 1
    entry, apex, exit_, sign = regions[0]
    # Merged wrap-around region: entry near 182, exit near 16, width ~36m.
    assert entry == pytest.approx(182.0, abs=2.0)
    assert exit_ == pytest.approx(16.0, abs=2.0)


def test_detect_regions_does_not_merge_real_chicane():
    # Two same-sign corners with a 30m gap — must stay separate
    # because the gap exceeds DEBOUNCE_GAP_M.
    s = np.arange(0, 300, 2.0)
    kappa = np.zeros_like(s)
    kappa[(s >= 100) & (s < 140)] = 0.02
    kappa[(s >= 170) & (s < 220)] = 0.02
    regions = cs._detect_regions(s, kappa, kappa_enter=0.015, kappa_exit=0.01, lap_length_m=300.0)
    assert len(regions) == 2
```

- [ ] **Step 2: Run failing tests**

Run: `cd server; python -m pytest tests/test_corner_segmentation.py -v`

Expected: FAIL with `AttributeError: module 'corner_segmentation' has no attribute '_detect_regions'`.

- [ ] **Step 3: Implement region detection + wrap-around merging**

Add to `server/corner_segmentation.py`:

```python
def _detect_regions(
    s: np.ndarray,
    kappa: np.ndarray,
    kappa_enter: float,
    kappa_exit: float,
    lap_length_m: float,
) -> list[tuple[float, float, float, int]]:
    """Walk κ(s) with hysteresis; merge wrap-around regions at s=0.

    Each region is (entry_m, apex_m, exit_m, sign). For wrap-around
    regions, entry_m > exit_m (i.e. the region crosses the lap boundary).
    Sign is +1 for a left turn, -1 for a right turn.
    """
    abs_k = np.abs(kappa)
    in_corner = False
    start_idx = 0
    raw: list[tuple[float, float, float, int]] = []
    for i in range(len(s)):
        if not in_corner and abs_k[i] >= kappa_enter:
            in_corner = True
            start_idx = i
        elif in_corner and abs_k[i] < kappa_exit:
            in_corner = False
            raw.append(_finalize_region(s, kappa, start_idx, i - 1))
    if in_corner:
        raw.append(_finalize_region(s, kappa, start_idx, len(s) - 1))

    # Debounce pass: merge same-sign adjacent regions with gap < DEBOUNCE_GAP_M.
    # Done before the wrap-around merge so the wrap merge sees fully-merged halves.
    merged: list[tuple[float, float, float, int]] = []
    for region in raw:
        if merged and merged[-1][3] == region[3] and region[0] - merged[-1][2] < DEBOUNCE_GAP_M:
            prev = merged[-1]
            # Re-pick apex from the union: higher |κ| wins.
            prev_apex_k = abs(kappa[_nearest_idx(s, prev[1])])
            cur_apex_k = abs(kappa[_nearest_idx(s, region[1])])
            new_apex = prev[1] if prev_apex_k >= cur_apex_k else region[1]
            merged[-1] = (prev[0], new_apex, region[2], prev[3])
        else:
            merged.append(region)
    raw = merged

    # Wrap-around merge: if the first region starts near s=0 and the
    # last region ends near lap_length, they are halves of the same
    # corner. Combine into a single region with entry_m > exit_m.
    # MUST run before the width filter — otherwise two 18m halves of
    # a real wrap-around corner get filtered as noise before they
    # have a chance to combine into a single 36m region.
    if len(raw) >= 2:
        first = raw[0]
        last = raw[-1]
        start_at_zero = first[0] <= 2.0
        end_at_lap_end = last[2] >= lap_length_m - 2.0
        same_sign = first[3] == last[3]
        if start_at_zero and end_at_lap_end and same_sign:
            entry = last[0]
            exit_ = first[2]
            # Apex: whichever half has the higher |κ| there.
            apex = first[1] if abs(kappa[_nearest_idx(s, first[1])]) >= abs(kappa[_nearest_idx(s, last[1])]) else last[1]
            raw = [(entry, apex, exit_, first[3])] + raw[1:-1]

    # Width filter — drop regions narrower than MIN_REGION_WIDTH_M as
    # noise. Runs AFTER wrap-merge so a real wrap-around corner that
    # produces two narrow halves keeps its full merged width.
    def _region_width(region):
        entry, _apex, exit_, _sign = region
        if entry <= exit_:
            return exit_ - entry
        # Wrap-around: width = (lap_length - entry) + exit_.
        return (lap_length_m - entry) + exit_

    raw = [r for r in raw if _region_width(r) >= MIN_REGION_WIDTH_M]

    return raw


def _finalize_region(
    s: np.ndarray,
    kappa: np.ndarray,
    start_idx: int,
    end_idx: int,
) -> tuple[float, float, float, int]:
    slice_ = kappa[start_idx : end_idx + 1]
    apex_local = int(np.argmax(np.abs(slice_)))
    apex_global = start_idx + apex_local
    return (
        float(s[start_idx]),
        float(s[apex_global]),
        float(s[end_idx]),
        1 if kappa[apex_global] >= 0 else -1,
    )


def _nearest_idx(s: np.ndarray, value: float) -> int:
    return int(np.argmin(np.abs(s - value)))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd server; python -m pytest tests/test_corner_segmentation.py -v`

Expected: 15 PASS.

- [ ] **Step 5: Commit**

```bash
git add server/corner_segmentation.py server/tests/test_corner_segmentation.py
git commit -m "feat(corner-segmentation): hysteresis regions with wrap-around merge"
```

---

## Task 5: One-to-one MultiViewer tagging

**Files:**
- Modify: `server/corner_segmentation.py`
- Test: `server/tests/test_corner_segmentation.py`

- [ ] **Step 1: Write the failing tests**

Append to `server/tests/test_corner_segmentation.py`:

```python
def test_tag_regions_one_to_one_matching():
    regions = [
        (100.0, 130.0, 160.0, 1),
        (400.0, 450.0, 500.0, -1),
    ]
    multiviewer = [
        {"number": 1, "letter": "", "distance_m": 132.0},
        {"number": 2, "letter": "", "distance_m": 451.0},
    ]
    tagged = cs._tag_regions(regions, multiviewer, lap_length_m=600.0)
    assert tagged[0].corner_number == 1
    assert tagged[1].corner_number == 2


def test_tag_regions_does_not_duplicate_labels_when_apexes_are_close():
    # Two adjacent curvature regions, only one MV corner — must NOT
    # assign that corner to both regions.
    regions = [
        (100.0, 120.0, 135.0, 1),
        (140.0, 160.0, 175.0, 1),
    ]
    multiviewer = [
        {"number": 4, "letter": "", "distance_m": 122.0},
    ]
    tagged = cs._tag_regions(regions, multiviewer, lap_length_m=300.0)
    numbers = [r.corner_number for r in tagged]
    # One region gets the MV match, the other gets None (no spare MV corner).
    assert numbers.count(4) == 1
    assert numbers.count(None) == 1


def test_tag_regions_handles_chicane_subcorners():
    regions = [
        (100.0, 120.0, 135.0, 1),
        (140.0, 160.0, 175.0, -1),
    ]
    multiviewer = [
        {"number": 4, "letter": "a", "distance_m": 122.0},
        {"number": 4, "letter": "b", "distance_m": 162.0},
    ]
    tagged = cs._tag_regions(regions, multiviewer, lap_length_m=300.0)
    assert tagged[0].label_suffix == "a"
    assert tagged[1].label_suffix == "b"
    assert tagged[0].corner_number == 4
    assert tagged[1].corner_number == 4


def test_tag_regions_handles_wrap_around_apex_for_distance_check():
    # Wrap-around region: entry_m=950, exit_m=50, apex_m=10.
    # MV corner at distance_m=5 — should match this region.
    regions = [
        (950.0, 10.0, 50.0, 1),
    ]
    multiviewer = [
        {"number": 1, "letter": "", "distance_m": 5.0},
    ]
    tagged = cs._tag_regions(regions, multiviewer, lap_length_m=1000.0)
    assert tagged[0].corner_number == 1
```

- [ ] **Step 2: Run failing tests**

Expected: FAIL with `AttributeError: module 'corner_segmentation' has no attribute '_tag_regions'`.

- [ ] **Step 3: Implement greedy one-to-one tagging**

Add to `server/corner_segmentation.py`:

```python
def _distance_inside_region(
    region: tuple[float, float, float, int], distance: float, lap_length_m: float
) -> bool:
    entry, _apex, exit_, _sign = region
    if entry <= exit_:
        return entry <= distance <= exit_
    # Wrap-around region: matches if distance >= entry OR distance <= exit_.
    return distance >= entry or distance <= exit_


def _circular_apex_distance(apex_m: float, mv_dist_m: float, lap_length_m: float) -> float:
    raw = abs(apex_m - mv_dist_m)
    return min(raw, lap_length_m - raw)


def _tag_regions(
    regions: list[tuple[float, float, float, int]],
    multiviewer_corners: list[dict],
    lap_length_m: float,
) -> list[CornerRegion]:
    """Greedy one-to-one match: each region claims at most one MV corner.

    Step 1: every region prefers a MV corner whose distance_m falls
    inside the region (preferring the closest-to-apex match).
    Step 2: any region without a match picks the closest unclaimed
    MV corner by circular distance.
    """
    unmatched_mv = list(multiviewer_corners)
    tagged: list[CornerRegion] = []
    assignments: list[Optional[dict]] = [None] * len(regions)

    # Pass 1: regions with one or more MV corners inside.
    for idx, region in enumerate(regions):
        inside = [
            c for c in unmatched_mv
            if _distance_inside_region(region, float(c["distance_m"]), lap_length_m)
        ]
        if inside:
            chosen = min(
                inside,
                key=lambda c: _circular_apex_distance(region[1], float(c["distance_m"]), lap_length_m),
            )
            assignments[idx] = chosen
            unmatched_mv.remove(chosen)

    # Pass 2: regions still without a match — closest unclaimed by circular distance.
    for idx, region in enumerate(regions):
        if assignments[idx] is not None or not unmatched_mv:
            continue
        chosen = min(
            unmatched_mv,
            key=lambda c: _circular_apex_distance(region[1], float(c["distance_m"]), lap_length_m),
        )
        # Only claim if reasonably close — otherwise leave unnamed.
        if _circular_apex_distance(region[1], float(chosen["distance_m"]), lap_length_m) <= 250.0:
            assignments[idx] = chosen
            unmatched_mv.remove(chosen)

    for region, chosen in zip(regions, assignments):
        entry, apex, exit_, sign = region
        tagged.append(
            CornerRegion(
                corner_number=(chosen.get("number") if chosen else None),
                label_suffix=(chosen.get("letter") or "" if chosen else ""),
                entry_m=entry,
                apex_m=apex,
                exit_m=exit_,
                sign=sign,
            )
        )
    return tagged
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd server; python -m pytest tests/test_corner_segmentation.py -v`

Expected: 19 PASS.

- [ ] **Step 5: Commit**

```bash
git add server/corner_segmentation.py server/tests/test_corner_segmentation.py
git commit -m "feat(corner-segmentation): greedy one-to-one MV corner tagging"
```

---

## Task 6: Validated builder + versioned disk cache

**Files:**
- Modify: `server/corner_segmentation.py`
- Test: `server/tests/test_corner_segmentation.py`

- [ ] **Step 1: Write the failing tests**

Append to `server/tests/test_corner_segmentation.py`:

```python
from unittest.mock import MagicMock, patch


def _make_hexagonal_lap(noise: float = 0.0, n_samples: int = 1200):
    """A ~3km synthetic lap with 6 well-separated corners and straights.

    Produces enough regions to exercise MIN_REGIONS=4, MIN_REGION_WIDTH_M,
    and validates the full pipeline against a known geometry. Each
    corner is a 90° turn of radius R=40m connecting straights of
    length L=400m.
    """
    R = 40.0
    L = 400.0
    arc_len = math.pi * R / 2  # 90° turn
    # 6 straight + 6 arc segments.
    segments = []
    for _ in range(6):
        segments.append(("straight", L))
        segments.append(("arc", arc_len))
    total = sum(seg[1] for seg in segments)
    s = np.linspace(0, total, n_samples, endpoint=False)
    x = np.zeros_like(s)
    y = np.zeros_like(s)
    heading = 0.0
    pos_x = 0.0
    pos_y = 0.0
    # Pre-compute segment start positions and headings.
    seg_starts = []
    cumul = 0.0
    cx, cy, ch = 0.0, 0.0, 0.0
    for kind, length in segments:
        seg_starts.append((cumul, kind, length, cx, cy, ch))
        if kind == "straight":
            cx += length * math.cos(ch)
            cy += length * math.sin(ch)
        else:
            # Left-hand 90° arc: center is perpendicular to current heading.
            ch_new = ch + math.pi / 2
            cx += R * math.sin(ch_new) - R * math.sin(ch)
            cy += -R * math.cos(ch_new) + R * math.cos(ch)
            ch = ch_new
        cumul += length
    for i, si in enumerate(s):
        # Find the segment containing si.
        for start_s, kind, length, sx, sy, sh in seg_starts:
            if start_s <= si < start_s + length:
                local = si - start_s
                if kind == "straight":
                    x[i] = sx + local * math.cos(sh)
                    y[i] = sy + local * math.sin(sh)
                else:
                    theta = local / R
                    # Arc center is to the LEFT of starting heading.
                    cx_arc = sx - R * math.sin(sh)
                    cy_arc = sy + R * math.cos(sh)
                    x[i] = cx_arc + R * math.sin(sh + theta)
                    y[i] = cy_arc - R * math.cos(sh + theta)
                break
    if noise > 0:
        rng = np.random.default_rng(42)
        x = x + rng.normal(0, noise, size=x.shape)
        y = y + rng.normal(0, noise, size=y.shape)
    return x, y, total


def _make_hexagonal_mv():
    """MultiViewer corners for the hexagonal lap (6 corners at known distances)."""
    R = 40.0
    L = 400.0
    arc_len = math.pi * R / 2
    mv = []
    cumul = 0.0
    for n in range(1, 7):
        cumul += L                  # straight
        cumul += arc_len / 2        # mid-arc = apex
        mv.append({"number": n, "letter": "", "distance_m": cumul})
        cumul += arc_len / 2        # rest of arc
    return mv


def test_build_corner_regions_validates_minimum_count():
    # Straight-only "lap" → zero detected corners → validation rejects.
    x = np.linspace(0, 3000, 1500)
    y = np.zeros_like(x)
    with pytest.raises(cs.SegmentationOutputError):
        cs._build_and_validate_regions(x, y, multiviewer_corners=[])


def test_build_corner_regions_validates_lap_length():
    # 100m "lap" — below MIN_LAP_LENGTH_M.
    x = np.linspace(0, 100, 200)
    y = np.zeros_like(x)
    with pytest.raises(cs.SegmentationOutputError):
        cs._build_and_validate_regions(x, y, multiviewer_corners=[])


def test_build_corner_regions_on_synthetic_hexagonal_circuit():
    x, y, expected_total = _make_hexagonal_lap(noise=0.0)
    mv = _make_hexagonal_mv()
    regions, lap_length = cs._build_and_validate_regions(x, y, mv)
    # 6 corners → 6 regions detected.
    assert 4 <= len(regions) <= 8
    # All corners are left-handers in our construction → all sign == 1.
    assert all(r.sign == 1 for r in regions)
    assert lap_length == pytest.approx(expected_total, rel=0.02)


def test_build_corner_regions_tolerates_realistic_noise():
    # 0.5m GPS-equivalent jitter — pipeline must still produce ≥ MIN_REGIONS.
    x, y, _expected_total = _make_hexagonal_lap(noise=0.5)
    mv = _make_hexagonal_mv()
    regions, _lap_length = cs._build_and_validate_regions(x, y, mv)
    assert len(regions) >= cs.MIN_REGIONS


def test_get_corner_regions_uses_disk_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "CACHE_DIR", str(tmp_path))
    cached = {
        "schema_version": cs.SCHEMA_VERSION,
        "lap_length_m": 5410.0,
        "regions": [
            {"corner_number": 1, "label_suffix": "", "entry_m": 10.0,
             "apex_m": 20.0, "exit_m": 30.0, "sign": 1},
        ],
    }
    (tmp_path / "2025_4.json").write_text(json.dumps(cached))
    regions = cs.get_corner_regions(2025, 4)
    assert len(regions) == 1
    assert regions[0].corner_number == 1


def test_get_corner_regions_ignores_cache_with_old_schema(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "CACHE_DIR", str(tmp_path))
    cached = {
        "schema_version": cs.SCHEMA_VERSION - 1,
        "lap_length_m": 5410.0,
        "regions": [{"corner_number": 1, "label_suffix": "", "entry_m": 10.0,
                     "apex_m": 20.0, "exit_m": 30.0, "sign": 1}],
    }
    (tmp_path / "2025_4.json").write_text(json.dumps(cached))
    with patch.object(cs, "_load_session", side_effect=RuntimeError("forced rebuild")):
        with pytest.raises(RuntimeError, match="forced rebuild"):
            cs.get_corner_regions(2025, 4)


def test_get_corner_regions_writes_current_schema_on_rebuild(tmp_path, monkeypatch):
    """After a rebuild, the new cache must carry SCHEMA_VERSION, lap length, and MV corners."""
    monkeypatch.setattr(cs, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(cs, "_MV_BY_KEY", {})
    x, y, expected_total = _make_hexagonal_lap()
    mv = _make_hexagonal_mv()
    fake_session = MagicMock()
    fake_session.get_circuit_info.return_value.corners.iterrows.return_value = [
        (i, {"X": 0, "Y": 0, "Number": m["number"], "Letter": m["letter"], "Distance": m["distance_m"]})
        for i, m in enumerate(mv)
    ]
    fake_lap = MagicMock()
    fake_lap.get_pos_data.return_value = {"X": x, "Y": y}
    fake_session.laps.pick_fastest.return_value = fake_lap
    with patch.object(cs, "_load_session", return_value=fake_session):
        cs.get_corner_regions(2025, 4)
    written = json.loads((tmp_path / "2025_4.json").read_text())
    assert written["schema_version"] == cs.SCHEMA_VERSION
    assert written["lap_length_m"] == pytest.approx(expected_total, rel=0.02)
    # MV corners must be persisted alongside regions.
    assert len(written["multiviewer_corners"]) == len(mv)
    assert {c["number"] for c in written["multiviewer_corners"]} == {1, 2, 3, 4, 5, 6}
    # In-process caches populated after the rebuild.
    assert cs._lap_length_for(2025, 4) == pytest.approx(expected_total, rel=0.02)
    assert cs._MV_BY_KEY[(2025, 4)] == written["multiviewer_corners"]


def test_get_corner_regions_loads_mv_from_disk_cache(tmp_path, monkeypatch):
    """Reading a v2 cache file must populate _MV_BY_KEY so resolver fallback never hits network."""
    monkeypatch.setattr(cs, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(cs, "_MV_BY_KEY", {})
    cached = {
        "schema_version": cs.SCHEMA_VERSION,
        "lap_length_m": 5410.0,
        "multiviewer_corners": [
            {"number": 1, "letter": "", "distance_m": 706.0},
            {"number": 17, "letter": "", "distance_m": 4830.0},
        ],
        "regions": [
            {"corner_number": 1, "label_suffix": "", "entry_m": 660.0,
             "apex_m": 706.0, "exit_m": 760.0, "sign": -1},
        ],
    }
    (tmp_path / "2025_6.json").write_text(json.dumps(cached))
    cs.get_corner_regions(2025, 6)
    assert len(cs._MV_BY_KEY[(2025, 6)]) == 2
    assert cs._MV_BY_KEY[(2025, 6)][1]["number"] == 17


def test_write_cache_rejects_region_with_out_of_bounds_boundary(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "CACHE_DIR", str(tmp_path))
    bad_region = cs.CornerRegion(
        corner_number=1, label_suffix="", entry_m=100.0,
        apex_m=130.0, exit_m=6000.0, sign=1,  # exit_m > lap_length
    )
    with pytest.raises(cs.SegmentationOutputError):
        cs._write_cache(2025, 4, [bad_region], lap_length_m=5400.0, multiviewer_corners=[])
    assert not (tmp_path / "2025_4.json").exists()


def test_write_cache_clamps_boundary_within_tolerance(tmp_path, monkeypatch):
    """Tiny floating-point overshoot must be clamped, not rejected."""
    monkeypatch.setattr(cs, "CACHE_DIR", str(tmp_path))
    # Region exit overshoots lap_length by 0.0001m — within adaptive tol.
    region = cs.CornerRegion(
        corner_number=1, label_suffix="", entry_m=100.0,
        apex_m=130.0, exit_m=5400.0001, sign=1,
    )
    cs._write_cache(2025, 4, [region], lap_length_m=5400.0, multiviewer_corners=[])
    written = json.loads((tmp_path / "2025_4.json").read_text())
    # Clamped back to 5400.0.
    assert written["regions"][0]["exit_m"] == pytest.approx(5400.0, abs=1e-9)


def test_read_cache_rejects_invalid_lap_length(tmp_path, monkeypatch):
    """A corrupt v2 cache with lap_length=0.001 must be ignored, not served."""
    monkeypatch.setattr(cs, "CACHE_DIR", str(tmp_path))
    cached = {
        "schema_version": cs.SCHEMA_VERSION,
        "lap_length_m": 0.001,  # below MIN_LAP_LENGTH_M
        "multiviewer_corners": [],
        "regions": [{"corner_number": 1, "label_suffix": "", "entry_m": 0.0,
                     "apex_m": 0.0005, "exit_m": 0.001, "sign": 1}],
    }
    (tmp_path / "2025_6.json").write_text(json.dumps(cached))
    assert cs._read_cache(2025, 6) is None


def test_read_cache_rejects_out_of_bounds_region(tmp_path, monkeypatch):
    """A v2 cache where a region boundary exceeds lap_length must be ignored."""
    monkeypatch.setattr(cs, "CACHE_DIR", str(tmp_path))
    cached = {
        "schema_version": cs.SCHEMA_VERSION,
        "lap_length_m": 5400.0,
        "multiviewer_corners": [],
        "regions": [{"corner_number": 1, "label_suffix": "", "entry_m": 100.0,
                     "apex_m": 130.0, "exit_m": 9999.0, "sign": 1}],  # > lap_length
    }
    (tmp_path / "2025_6.json").write_text(json.dumps(cached))
    assert cs._read_cache(2025, 6) is None


def test_get_corner_regions_falls_back_to_degraded_v1_cache(tmp_path, monkeypatch):
    """If v2 rebuild fails AND a v1 cache exists, return v1 in degraded mode."""
    monkeypatch.setattr(cs, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(cs, "_MV_BY_KEY", {})
    monkeypatch.setattr(cs, "_LAP_LENGTH_BY_KEY", {})
    # Write a v1-shape cache (no multiviewer_corners field).
    v1_cache = {
        "schema_version": 1,
        "lap_length_m": 5410.0,
        "regions": [{"corner_number": 1, "label_suffix": "", "entry_m": 100.0,
                     "apex_m": 130.0, "exit_m": 160.0, "sign": 1}],
    }
    (tmp_path / "2025_6.json").write_text(json.dumps(v1_cache))
    # Force the rebuild to fail.
    with patch.object(cs, "_load_session", side_effect=RuntimeError("network down")):
        regions = cs.get_corner_regions(2025, 6)
    assert len(regions) == 1
    assert regions[0].corner_number == 1
    # Degraded read leaves _MV_BY_KEY empty.
    assert cs._MV_BY_KEY[(2025, 6)] == []


def test_get_corner_regions_raises_when_no_cache_and_rebuild_fails(tmp_path, monkeypatch):
    """No cache + rebuild failure → propagate so f1_data falls back to legacy."""
    monkeypatch.setattr(cs, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(cs, "_MV_BY_KEY", {})
    monkeypatch.setattr(cs, "_LAP_LENGTH_BY_KEY", {})
    with patch.object(cs, "_load_session", side_effect=RuntimeError("network down")):
        with pytest.raises(RuntimeError, match="network down"):
            cs.get_corner_regions(2025, 6)


def test_get_corner_regions_rejects_invalid_year(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "CACHE_DIR", str(tmp_path))
    with pytest.raises(cs.SegmentationInputError):
        cs.get_corner_regions(None, 4)
    with pytest.raises(cs.SegmentationInputError):
        cs.get_corner_regions(0, 4)
    with pytest.raises(cs.SegmentationInputError):
        cs.get_corner_regions(-2025, 4)
    # No bogus cache file should have been created.
    assert not list(tmp_path.glob("*.json"))


def test_resolve_corner_for_distance_rejects_invalid_year(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "CACHE_DIR", str(tmp_path))
    with pytest.raises(cs.SegmentationInputError):
        cs.resolve_corner_for_distance(None, 4, 3000.0)


def test_get_corner_regions_does_not_write_invalid_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "CACHE_DIR", str(tmp_path))
    fake_session = MagicMock()
    # Mock the multiviewer corner df as empty.
    fake_session.get_circuit_info.return_value.corners.iterrows.return_value = []
    # Reference lap with too few samples → SegmentationInputError.
    fake_lap = MagicMock()
    fake_lap.get_pos_data.return_value = {"X": np.array([0.0, 1.0]), "Y": np.array([0.0, 1.0])}
    fake_session.laps.pick_fastest.return_value = fake_lap
    with patch.object(cs, "_load_session", return_value=fake_session):
        with pytest.raises(cs.SegmentationInputError):
            cs.get_corner_regions(2025, 4)
    # Cache file must NOT exist.
    assert not (tmp_path / "2025_4.json").exists()
```

- [ ] **Step 2: Run failing tests**

Expected: FAIL with multiple AttributeError on missing builder/cache helpers.

- [ ] **Step 3: Implement builder, validation, and versioned cache**

Add to `server/corner_segmentation.py`:

```python
class SegmentationOutputError(ValueError):
    """Raised when the segmentation output fails validity checks."""


def _build_and_validate_regions(
    x: np.ndarray,
    y: np.ndarray,
    multiviewer_corners: list[dict],
) -> tuple[list[CornerRegion], float]:
    """Run the full pipeline and validate the result. Returns (regions, lap_length_m)."""
    x_clean, y_clean = _clean_xy(x, y)
    x_u, y_u, s_u, spacing, lap_length = _resample_uniform(x_clean, y_clean, RESAMPLE_SPACING_M)
    kappa = _compute_curvature(x_u, y_u, spacing_m=spacing)
    abs_k = np.abs(kappa)
    kappa_enter = float(np.percentile(abs_k, KAPPA_ENTER_PERCENTILE))
    kappa_exit = float(np.percentile(abs_k, KAPPA_EXIT_PERCENTILE))
    raw_regions = _detect_regions(s_u, kappa, kappa_enter, kappa_exit, lap_length)
    tagged = _tag_regions(raw_regions, multiviewer_corners, lap_length)

    if not (MIN_LAP_LENGTH_M <= lap_length <= MAX_LAP_LENGTH_M):
        raise SegmentationOutputError(
            f"lap length {lap_length}m outside [{MIN_LAP_LENGTH_M}, {MAX_LAP_LENGTH_M}]"
        )
    if not (MIN_REGIONS <= len(tagged) <= MAX_REGIONS):
        raise SegmentationOutputError(
            f"detected {len(tagged)} regions outside [{MIN_REGIONS}, {MAX_REGIONS}]"
        )
    return tagged, lap_length


def _load_session(year: int, round_number: int):
    """Thin wrapper around fastf1 so tests can patch it."""
    import fastf1
    session = fastf1.get_session(year, round_number, "Q")
    session.load(laps=True, telemetry=True, weather=False, messages=False)
    return session


def _load_multiviewer_corners(session) -> list[dict]:
    rows = []
    for _, row in session.get_circuit_info().corners.iterrows():
        rows.append({
            "number": int(row["Number"]),
            "letter": str(row.get("Letter") or "") or "",
            "distance_m": float(row["Distance"]),
        })
    return rows


def _load_reference_lap_xy(session) -> tuple[np.ndarray, np.ndarray]:
    lap = session.laps.pick_fastest()
    pos = lap.get_pos_data()
    return np.asarray(pos["X"], dtype=float), np.asarray(pos["Y"], dtype=float)


def _cache_path(year: int, round_number: int) -> str:
    return os.path.join(CACHE_DIR, f"{year}_{round_number}.json")


def _read_cache(
    year: int,
    round_number: int,
    accept_legacy: bool = False,
) -> Optional[tuple[list[CornerRegion], float, list[dict]]]:
    """Read cached regions for a session.

    Returns None on missing/corrupt/invalid cache. When ``accept_legacy``
    is True, a v1 schema cache (no `multiviewer_corners` field) is read
    in degraded mode with an empty MV list — used as a fallback when
    the v2 rebuild itself fails.
    """
    path = _cache_path(year, round_number)
    if not os.path.isfile(path):
        return None
    try:
        with open(path) as f:
            raw = json.load(f)
        version = raw.get("schema_version")
        if version != SCHEMA_VERSION:
            if not (accept_legacy and isinstance(version, int) and version >= 1):
                LOGGER.info(
                    "corner_regions cache schema mismatch at %s (%s != %s) — rebuilding",
                    path, version, SCHEMA_VERSION,
                )
                return None
            # Degraded read of older schema: regions only, empty MV list.
            regions = [CornerRegion(**entry) for entry in raw["regions"]]
            lap_length = float(raw["lap_length_m"])
        else:
            regions = [CornerRegion(**entry) for entry in raw["regions"]]
            lap_length = float(raw["lap_length_m"])
            mv = list(raw["multiviewer_corners"])

        # Re-validate values against the same gates as _write_cache.
        # A corrupt or externally-modified cache with lap_length=0.001
        # would otherwise pass `lap_length > 0` and break circular math.
        if not (MIN_LAP_LENGTH_M <= lap_length <= MAX_LAP_LENGTH_M):
            LOGGER.warning(
                "corner_regions cache at %s has invalid lap_length=%s — ignoring",
                path, lap_length,
            )
            return None
        tol = max(1e-3, lap_length * 1e-9)
        for r in regions:
            for field in (r.entry_m, r.apex_m, r.exit_m):
                if field < -tol or field > lap_length + tol:
                    LOGGER.warning(
                        "corner_regions cache at %s has out-of-bounds boundary %s — ignoring",
                        path, field,
                    )
                    return None
        if version != SCHEMA_VERSION:
            return regions, lap_length, []  # degraded
        return regions, lap_length, mv
    except (json.JSONDecodeError, TypeError, KeyError, ValueError) as exc:
        LOGGER.warning("corner_regions cache unreadable at %s: %s", path, exc)
        return None


def _write_cache(
    year: int,
    round_number: int,
    regions: list[CornerRegion],
    lap_length_m: float,
    multiviewer_corners: list[dict],
) -> None:
    # Boundary sanity: every region boundary must lie within [0, lap_length],
    # with an adaptive tolerance for floating-point drift. Values that
    # exceed the tolerance are rejected; values within tolerance get
    # clamped into range before serialization.
    tol = max(1e-3, lap_length_m * 1e-9)
    clean_regions: list[CornerRegion] = []
    for r in regions:
        boundaries = []
        for field in (r.entry_m, r.apex_m, r.exit_m):
            if field < -tol or field > lap_length_m + tol:
                raise SegmentationOutputError(
                    f"region boundary {field}m outside [0, {lap_length_m}m] — cache write rejected"
                )
            boundaries.append(min(max(field, 0.0), lap_length_m))
        clean_regions.append(
            CornerRegion(
                corner_number=r.corner_number,
                label_suffix=r.label_suffix,
                entry_m=boundaries[0],
                apex_m=boundaries[1],
                exit_m=boundaries[2],
                sign=r.sign,
            )
        )
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _cache_path(year, round_number)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "lap_length_m": lap_length_m,
        "multiviewer_corners": multiviewer_corners,
        "regions": [asdict(r) for r in clean_regions],
    }
    with open(path, "w") as f:
        json.dump(payload, f)


# Module-level state so resolve_corner_for_distance can reuse lap_length
# and MV corners without re-reading the cache file on every call.
_LAP_LENGTH_BY_KEY: dict[tuple[int, int], float] = {}
_MV_BY_KEY: dict[tuple[int, int], list[dict]] = {}


def _require_positive_int(value, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise SegmentationInputError(f"{name} must be a positive int, got {value!r}")


def get_corner_regions(year: int, round_number: int) -> list[CornerRegion]:
    _require_positive_int(year, "year")
    _require_positive_int(round_number, "round_number")
    key = (year, round_number)
    cached = _read_cache(year, round_number)
    if cached is not None:
        regions, lap_length, mv = cached
        _LAP_LENGTH_BY_KEY[key] = lap_length
        _MV_BY_KEY[key] = mv
        return regions
    # Cache miss or schema mismatch — attempt a fresh build.
    try:
        session = _load_session(year, round_number)
        multiviewer = _load_multiviewer_corners(session)
        x, y = _load_reference_lap_xy(session)
        regions, lap_length = _build_and_validate_regions(x, y, multiviewer)
        _write_cache(year, round_number, regions, lap_length, multiviewer)
        _LAP_LENGTH_BY_KEY[key] = lap_length
        _MV_BY_KEY[key] = multiviewer
        return regions
    except Exception as build_exc:
        # Rebuild failed (network down, FastF1 hiccup, etc.). If an older
        # schema cache exists on disk, fall back to a DEGRADED read so the
        # resolver can return something useful rather than raising every
        # call. The degraded path returns an empty MV list — the resolver
        # untagged-region fallback will produce "in corner" labels instead
        # of named ones, which is still better than total failure.
        LOGGER.warning(
            "corner_regions rebuild failed for year=%s round=%s: %s — trying degraded read",
            year, round_number, build_exc,
        )
        degraded = _read_cache(year, round_number, accept_legacy=True)
        if degraded is not None:
            regions, lap_length, mv = degraded
            _LAP_LENGTH_BY_KEY[key] = lap_length
            _MV_BY_KEY[key] = mv  # empty in the degraded case
            return regions
        # No usable cache and rebuild failed — propagate so the f1_data
        # wrapper can fall back to the legacy nearest-apex resolver.
        raise


def _lap_length_for(year: int, round_number: int) -> Optional[float]:
    return _LAP_LENGTH_BY_KEY.get((year, round_number))
```

- [ ] **Step 4: Run tests**

Run: `cd server; python -m pytest tests/test_corner_segmentation.py -v`

Expected: 26 PASS.

- [ ] **Step 5: Commit**

```bash
git add server/corner_segmentation.py server/tests/test_corner_segmentation.py
git commit -m "feat(corner-segmentation): validated builder with versioned cache"
```

---

## Task 7: Public `resolve_corner_for_distance` with circular semantics

**Files:**
- Modify: `server/corner_segmentation.py`
- Test: `server/tests/test_corner_segmentation.py`

- [ ] **Step 1: Write the failing tests**

Append to `server/tests/test_corner_segmentation.py`:

```python
def _stub_regions(monkeypatch, regions, lap_length=5400.0, mv_corners=None):
    monkeypatch.setattr(cs, "get_corner_regions", lambda *_: regions)
    monkeypatch.setattr(cs, "_lap_length_for", lambda *_: lap_length)
    monkeypatch.setattr(cs, "_load_multiviewer_corners_for_resolve",
                        lambda *_: (mv_corners or []))


def test_resolve_inside_region_returns_corner_label(monkeypatch):
    regions = [
        CornerRegion(corner_number=11, label_suffix="", entry_m=3000.0,
                     apex_m=3083.0, exit_m=3160.0, sign=1),
    ]
    _stub_regions(monkeypatch, regions)
    result = cs.resolve_corner_for_distance(2025, 6, 3083.0)
    assert result["corner_number"] == 11
    assert result["corner_name"] == "Turn 11"
    assert result["location_label"] == "Turn 11"


def test_resolve_between_regions_returns_straight_label(monkeypatch):
    regions = [
        CornerRegion(corner_number=10, label_suffix="", entry_m=2400.0,
                     apex_m=2440.0, exit_m=2500.0, sign=-1),
        CornerRegion(corner_number=11, label_suffix="", entry_m=3000.0,
                     apex_m=3083.0, exit_m=3160.0, sign=1),
    ]
    _stub_regions(monkeypatch, regions)
    result = cs.resolve_corner_for_distance(2025, 6, 2700.0)
    assert result["corner_number"] is None
    assert result["location_label"] == "Turn 10 → Turn 11 straight"


def test_resolve_after_final_corner_wraps_to_first(monkeypatch):
    # Distance is past the final corner — straight wraps around to T1.
    regions = [
        CornerRegion(corner_number=1, label_suffix="", entry_m=200.0,
                     apex_m=250.0, exit_m=320.0, sign=1),
        CornerRegion(corner_number=19, label_suffix="", entry_m=5000.0,
                     apex_m=5100.0, exit_m=5200.0, sign=-1),
    ]
    _stub_regions(monkeypatch, regions, lap_length=5400.0)
    result = cs.resolve_corner_for_distance(2025, 6, 5350.0)
    assert result["location_label"] == "Turn 19 → Turn 1 straight"


def test_resolve_inside_wrap_around_region(monkeypatch):
    # Wrap-around region: entry=5300, exit=80.
    regions = [
        CornerRegion(corner_number=1, label_suffix="", entry_m=5300.0,
                     apex_m=20.0, exit_m=80.0, sign=1),
    ]
    _stub_regions(monkeypatch, regions, lap_length=5400.0)
    # Both 5350m and 50m fall inside the wrap-around region.
    assert cs.resolve_corner_for_distance(2025, 6, 5350.0)["corner_number"] == 1
    assert cs.resolve_corner_for_distance(2025, 6, 50.0)["corner_number"] == 1


def test_resolve_returns_empty_when_no_regions(monkeypatch):
    _stub_regions(monkeypatch, [])
    result = cs.resolve_corner_for_distance(2025, 6, 3083.0)
    assert result["corner_number"] is None
    assert result["corner_name"] is None
    assert result["location_label"] is None


def test_resolve_handles_chicane_letter_suffix(monkeypatch):
    regions = [
        CornerRegion(corner_number=4, label_suffix="a", entry_m=1100.0,
                     apex_m=1131.0, exit_m=1160.0, sign=1),
    ]
    _stub_regions(monkeypatch, regions)
    result = cs.resolve_corner_for_distance(2025, 6, 1131.0)
    assert result["corner_name"] == "Turn 4a"


def test_resolve_falls_back_to_nearest_mv_when_region_untagged(monkeypatch):
    # Untagged region (corner_number=None) — resolver must fall back
    # to the nearest MV corner rather than returning location_label=None.
    regions = [
        CornerRegion(corner_number=None, label_suffix="", entry_m=3000.0,
                     apex_m=3083.0, exit_m=3160.0, sign=1),
    ]
    mv = [{"number": 11, "letter": "", "distance_m": 3090.0}]
    _stub_regions(monkeypatch, regions, mv_corners=mv)
    result = cs.resolve_corner_for_distance(2025, 6, 3083.0)
    assert result["corner_number"] == 11
    assert result["corner_name"] == "Turn 11"


def test_resolve_rejects_non_finite_distance(monkeypatch):
    regions = [
        CornerRegion(corner_number=1, label_suffix="", entry_m=100.0,
                     apex_m=130.0, exit_m=160.0, sign=1),
    ]
    _stub_regions(monkeypatch, regions)
    with pytest.raises(cs.SegmentationInputError):
        cs.resolve_corner_for_distance(2025, 6, float("nan"))
    with pytest.raises(cs.SegmentationInputError):
        cs.resolve_corner_for_distance(2025, 6, float("inf"))
    with pytest.raises(cs.SegmentationInputError):
        cs.resolve_corner_for_distance(2025, 6, None)


def test_resolve_normalizes_distance_outside_lap_length(monkeypatch):
    # Distance > lap_length wraps to the equivalent point on the lap.
    regions = [
        CornerRegion(corner_number=1, label_suffix="", entry_m=100.0,
                     apex_m=130.0, exit_m=160.0, sign=1),
    ]
    _stub_regions(monkeypatch, regions, lap_length=5400.0)
    # 5400 + 130 = 5530 should normalize to 130 → inside Turn 1.
    result = cs.resolve_corner_for_distance(2025, 6, 5530.0)
    assert result["corner_number"] == 1


def test_resolve_straight_lookup_skips_wrap_around_as_prev(monkeypatch):
    # Wrap-around region exists. Target is 100m AFTER the regular T1 exit.
    # The straight bracket must be Turn 1 → Turn 5 (the next forward
    # non-wrap region), not Turn 5 → Turn 5 nonsense from including
    # the wrap region as "previous".
    regions = [
        CornerRegion(corner_number=1, label_suffix="", entry_m=200.0,
                     apex_m=250.0, exit_m=320.0, sign=1),
        CornerRegion(corner_number=5, label_suffix="", entry_m=5300.0,
                     apex_m=10.0, exit_m=80.0, sign=1),  # wrap-around T5
    ]
    _stub_regions(monkeypatch, regions, lap_length=5400.0)
    result = cs.resolve_corner_for_distance(2025, 6, 500.0)
    # Forward from 500m: next region by entry is T5 (5300m). Backward:
    # T1 (exit_m=320). Label must be "Turn 1 → Turn 5 straight".
    assert result["location_label"] == "Turn 1 → Turn 5 straight"
```

- [ ] **Step 2: Run failing tests**

Expected: FAIL on resolve tests with NotImplementedError.

- [ ] **Step 3: Implement resolve_corner_for_distance with circular logic**

Replace the stub `resolve_corner_for_distance` in `server/corner_segmentation.py`:

```python
def _corner_name(region: CornerRegion) -> Optional[str]:
    if region.corner_number is None:
        return None
    return f"Turn {region.corner_number}{region.label_suffix}"


def _arc_distance_forward(target: float, point_m: float, lap_length_m: float) -> float:
    """Arc length from target moving forward to point_m, with wrap."""
    if lap_length_m <= 0:
        return abs(point_m - target)
    d = point_m - target
    if d < 0:
        d += lap_length_m
    return d


def _arc_distance_backward(target: float, point_m: float, lap_length_m: float) -> float:
    """Arc length from target moving backward to point_m, with wrap."""
    if lap_length_m <= 0:
        return abs(target - point_m)
    d = target - point_m
    if d < 0:
        d += lap_length_m
    return d


def _load_multiviewer_corners_for_resolve(year: int, round_number: int) -> list[dict]:
    """Return MV corners cached in-process. NEVER hits FastF1/network.

    Populated as a side effect of `get_corner_regions` (which is called
    before any resolve), reading from the on-disk cache or from the fresh
    build. If somehow neither happened, returns an empty list — caller
    should treat that as "no fallback available."
    """
    return _MV_BY_KEY.get((year, round_number), [])


def resolve_corner_for_distance(
    year: int, round_number: int, distance_m: float
) -> dict:
    _require_positive_int(year, "year")
    _require_positive_int(round_number, "round_number")
    if distance_m is None or not math.isfinite(float(distance_m)):
        raise SegmentationInputError(
            f"distance_m must be finite, got {distance_m!r}"
        )
    regions = get_corner_regions(year, round_number)
    if not regions:
        return {"corner_number": None, "corner_name": None, "location_label": None}
    lap_length = _lap_length_for(year, round_number) or 0.0
    target = float(distance_m)
    # Normalize target into [0, lap_length) so circular arithmetic is safe
    # against floating-point drift or distances that wrapped multiple laps.
    if lap_length > 0:
        target = target % lap_length

    # Step 1: inside any region?
    for region in regions:
        if _distance_inside_region(
            (region.entry_m, region.apex_m, region.exit_m, region.sign),
            target,
            lap_length,
        ):
            if region.corner_number is not None:
                label = _corner_name(region)
                return {
                    "corner_number": region.corner_number,
                    "corner_name": label,
                    "location_label": label,
                }
            # Untagged region — fall back to nearest MV apex circularly.
            mv = _load_multiviewer_corners_for_resolve(year, round_number)
            if mv:
                chosen = min(
                    mv,
                    key=lambda c: _circular_apex_distance(
                        region.apex_m, float(c["distance_m"]), lap_length
                    ),
                )
                label = f"Turn {chosen['number']}{chosen.get('letter') or ''}"
                return {
                    "corner_number": int(chosen["number"]),
                    "corner_name": label,
                    "location_label": label,
                }
            return {"corner_number": None, "corner_name": None, "location_label": "in corner"}

    # Step 2: straight between regions, with circular bracket lookup.
    # "Previous" = region whose exit_m has the smallest backward arc
    # distance to target. "Next" = region whose entry_m has the smallest
    # forward arc distance. Skip regions the target is INSIDE (handled above).
    prev_region = min(
        regions,
        key=lambda r: _arc_distance_backward(target, r.exit_m, lap_length),
    )
    next_region = min(
        regions,
        key=lambda r: _arc_distance_forward(target, r.entry_m, lap_length),
    )
    prev_name = _corner_name(prev_region)
    next_name = _corner_name(next_region)
    if prev_name and next_name and prev_region is not next_region:
        label = f"{prev_name} → {next_name} straight"
    elif next_name:
        label = f"approach to {next_name}"
    elif prev_name:
        label = f"run out of {prev_name}"
    else:
        label = None
    return {"corner_number": None, "corner_name": None, "location_label": label}
```

- [ ] **Step 4: Run tests**

Run: `cd server; python -m pytest tests/test_corner_segmentation.py -v`

Expected: 32 PASS.

- [ ] **Step 5: Commit**

```bash
git add server/corner_segmentation.py server/tests/test_corner_segmentation.py
git commit -m "feat(corner-segmentation): public resolver with circular straight semantics"
```

---

## Task 8: Wire `f1_data._resolve_corner_for_distance` to delegate

**Files:**
- Modify: `server/f1_data.py` — body of `_resolve_corner_for_distance` (line 3445)
- Modify: `server/tests/test_f1_data.py`

- [ ] **Step 1: Write the failing test**

Append to `server/tests/test_f1_data.py` after the existing resolver tests (around line 1257):

```python
def test_resolve_corner_for_distance_delegates_to_segmentation():
    seg_return = {
        "corner_number": 18,
        "corner_name": "Turn 18",
        "location_label": "Turn 18",
    }
    with patch("corner_segmentation.resolve_corner_for_distance", return_value=seg_return) as seg:
        result = f1_data._resolve_corner_for_distance(6, 4900, year=2025)
    seg.assert_called_once_with(2025, 6, 4900.0)
    assert result["corner_number"] == 18


def test_resolve_corner_for_distance_falls_back_when_year_negative():
    # year=-1 is the sentinel used by _resolve_corner_for_distance_legacy.
    with patch("corner_segmentation.resolve_corner_for_distance") as seg, \
         patch("f1_data.get_circuit_corners", return_value=[
             {"number": 17, "distance_m": 4830},
             {"number": 18, "distance_m": 4967},
         ]):
        result = f1_data._resolve_corner_for_distance(6, 4900, year=-1)
    seg.assert_not_called()
    assert result["corner_number"] == 18


def test_resolve_corner_for_distance_falls_back_on_segmentation_error():
    with patch("corner_segmentation.resolve_corner_for_distance",
               side_effect=RuntimeError("no pos data")), \
         patch("f1_data.get_circuit_corners", return_value=[
             {"number": 17, "distance_m": 4830},
             {"number": 18, "distance_m": 4967},
         ]):
        result = f1_data._resolve_corner_for_distance(6, 4900, year=2025)
    assert result["corner_number"] == 18


def test_resolve_corner_for_distance_falls_back_on_empty_segmentation():
    # Segmentation returned but location_label is None — don't trust it,
    # fall back to legacy.
    seg_return = {"corner_number": None, "corner_name": None, "location_label": None}
    with patch("corner_segmentation.resolve_corner_for_distance", return_value=seg_return), \
         patch("f1_data.get_circuit_corners", return_value=[
             {"number": 18, "distance_m": 4967},
         ]):
        result = f1_data._resolve_corner_for_distance(6, 4900, year=2025)
    assert result["corner_number"] == 18  # via legacy fallback
```

- [ ] **Step 2: Run failing tests**

Run: `cd server; python -m pytest tests/test_f1_data.py -v -k "resolve_corner"`

Expected: 4 new tests fail.

- [ ] **Step 3: Modify the resolver body to delegate and fall back**

In `server/f1_data.py`, locate `_resolve_corner_for_distance` (line 3445, signature now `(round_number, distance_m, year)` after Task 0a). Add the delegation block at the top of the body, before the existing `fallback_label, _fallback_plain = _distance_fallback_label(...)` line:

```python
def _resolve_corner_for_distance(
    round_number: int,
    distance_m: int | float | None,
    year: int,
) -> dict:
    """Resolve a telemetry distance to a named-corner label.

    When ``year > 0`` and the corner_segmentation module produces a
    non-empty result, returns that. Otherwise falls back to the legacy
    nearest-apex-within-150m heuristic against FastF1's MultiViewer data.
    """
    if year is not None and year > 0 and _is_finite_distance(distance_m):
        try:
            import corner_segmentation
            seg_result = corner_segmentation.resolve_corner_for_distance(
                year, round_number, float(distance_m)
            )
            if seg_result.get("location_label"):
                return seg_result
        except Exception as exc:  # noqa: BLE001 — log and fall back
            LOGGER.debug(
                "corner_segmentation failed for year=%s round=%s d=%s: %s",
                year, round_number, distance_m, exc,
            )
    # Legacy path: nearest-apex within ±150m, with tiebreak by closeness.
    fallback_label, _fallback_plain = _distance_fallback_label(distance_m)
    empty = {"corner_number": None, "corner_name": None, "location_label": fallback_label}
    # ... rest of the existing function body unchanged ...
```

Keep the entire post-delegation body (the nearest-apex logic we shipped earlier today, lines ~3462-3513) untouched. The delegation block is purely additive.

- [ ] **Step 4: Run the resolver tests**

Run: `cd server; python -m pytest tests/test_f1_data.py -v -k "resolve_corner"`

Expected: All resolver tests pass (5 existing + 4 new = 9).

- [ ] **Step 5: Run the full test suite**

Run: `cd server; python -m pytest tests/ -v`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add server/f1_data.py server/tests/test_f1_data.py
git commit -m "feat(f1-data): delegate corner resolution to curvature segmentation"
```

---

## Task 9: Real-data integration smoke tests

**Files:**
- Create: `server/tests/test_corner_segmentation_integration.py`

- [ ] **Step 1: Create the integration test file**

Create `server/tests/test_corner_segmentation_integration.py`:

```python
"""Real-data smoke tests for corner_segmentation.

Hits FastF1 — only runs when INTEGRATION=1 is set. Skipped by default.
"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("INTEGRATION") != "1",
    reason="INTEGRATION=1 not set; skipping FastF1-dependent smoke test",
)

import corner_segmentation as cs


def test_miami_t17_and_t18_distinguished():
    # Bug: marker at 4900m used to resolve to T17. T17 apex is 4830m,
    # T18 apex is 4967m. Curvature segmentation must place 4900m in T18.
    result_4900 = cs.resolve_corner_for_distance(2025, 6, 4900.0)
    result_4830 = cs.resolve_corner_for_distance(2025, 6, 4830.0)
    assert result_4830["corner_number"] == 17, result_4830
    assert result_4900["corner_number"] == 18, result_4900


def test_eau_rouge_full_extent_covered():
    # Spa is round 13 in 2025. Eau Rouge / Raidillon are corners 3-4 —
    # the combined complex spans ~400m of arc. The detected region(s)
    # for those corners must cover at least 200m.
    regions = cs.get_corner_regions(2025, 13)
    eau_rouge = [r for r in regions if r.corner_number in (3, 4)]
    assert eau_rouge, "no Eau Rouge region detected"
    total_extent = 0.0
    for r in eau_rouge:
        if r.entry_m <= r.exit_m:
            total_extent += r.exit_m - r.entry_m
        else:
            # wrap-around region — uses cached lap length
            lap_len = cs._lap_length_for(2025, 13) or 0.0
            total_extent += (lap_len - r.entry_m) + r.exit_m
    assert total_extent >= 200.0, f"Eau Rouge extent only {total_extent}m"


def test_lap_length_is_plausible_for_known_circuit():
    cs.get_corner_regions(2025, 6)  # Miami
    miami_length = cs._lap_length_for(2025, 6)
    # Miami International Autodrome is 5.412 km.
    assert 5200.0 <= miami_length <= 5600.0, miami_length
```

- [ ] **Step 2: Run integration tests manually**

From `server/`:

```powershell
$env:INTEGRATION="1"; python -m pytest tests/test_corner_segmentation_integration.py -v
```

Expected: 3 PASS.

If `test_miami_t17_and_t18_distinguished` fails, the cache may have been built from an earlier run with different thresholds — delete it and retry:

```powershell
Remove-Item server/cache/corner_regions/*.json -Force
```

If `test_eau_rouge_full_extent_covered` fails with `<200m`, the percentile threshold is too aggressive — lower `KAPPA_ENTER_PERCENTILE` from 70 to 60, delete the cache, and re-run.

- [ ] **Step 3: Verify default-skip behavior**

Without the env var:

```powershell
python -m pytest tests/test_corner_segmentation_integration.py -v
```

Expected: 3 SKIPPED.

- [ ] **Step 4: Commit**

```bash
git add server/tests/test_corner_segmentation_integration.py
git commit -m "test(corner-segmentation): real-data integration smokes (Miami, Spa)"
```

---

## Task 10: End-to-end manual verification

**Files:** none modified — manual verification step.

- [ ] **Step 1: Clear the corner_regions cache so the new pipeline builds fresh**

From `server/`:

```powershell
Remove-Item cache/corner_regions/*.json -Force -ErrorAction SilentlyContinue
```

- [ ] **Step 2: Start the backend**

From `server/`:

```bash
python -m uvicorn main:app --reload --port 8000
```

Wait for "Application startup complete".

- [ ] **Step 3: Start the frontend**

From `client/`:

```bash
npm run dev
```

- [ ] **Step 4: Run the original query**

Open `http://localhost:5173`. Ask: "How did Leclerc outqualify Norris in Miami 2025?"

Verify:
- The marker that was previously labeled "Turn 17" at ~4900m now shows "Turn 18", matching the prose narrative
- A marker on a long sweeping corner (T1 banked left at Miami, or any high-speed corner at Spa/Silverstone if re-queried) shows the correct corner label and isn't reported as a straight
- No marker shows duplicate corner names (e.g., two markers both saying "Turn 17") unless they really are in the same corner

If anything mismatches, surface the specific case immediately rather than just noting it — the prose generator may still be hallucinating corner names, which is a separate bug in `_cause_explanation`.

- [ ] **Step 5: Ensure the cache directory is gitignored**

If `server/cache/` is not already in `.gitignore`, add this entry to `server/.gitignore`:

```
cache/corner_regions/
```

Commit if necessary:

```bash
git add server/.gitignore
git commit -m "chore: ignore corner_regions cache directory"
```

If it's already ignored, skip this step.

---

## Self-Review Checklist

**Spec coverage (Codex rounds 1-3 issues addressed):**
- [x] Task 0a: year threading + mock fixture updates (R1#1, R2#1)
- [x] Task 0b: scaffold
- [x] Task 1: data cleaning — NaN, duplicates, min sample count (R1#3)
- [x] Task 2: exact-spacing resample returning true total arc length (R1#5, R2#4)
- [x] Task 3: curvature
- [x] Task 4: hysteresis + debounce + wrap-merge-before-width-filter + edge cases (R1#2, R1#8, R2#6, R3#1)
- [x] Task 5: one-to-one MV tagging (R1#6)
- [x] Task 6: validated builder + versioned cache + MV persistence + year guard + boundary validation + hexagonal fixture (R1#4, R1#7, R2#2, R2#7, R2#8, R3#2)
- [x] Task 7: resolver with circular straight bracket + untagged-region MV fallback + year guard + distance normalization + finiteness validation (R1#9, R2#3, R2#5, R3#3, R3#4)
- [x] Task 8: f1_data delegation with fallback
- [x] Task 9: real-data smoke + FastF1-shape fixtures (R1#10)
- [x] Task 10: manual verification

**Placeholder scan:** none found.

**Type consistency:** `CornerRegion` shape consistent across definition, construction in `_tag_regions`, serialization in `_write_cache`, deserialization in `_read_cache`, and consumption in `resolve_corner_for_distance`. The `lap_length_m` value is plumbed from the builder through the cache and into `resolve_corner_for_distance` via the module-level `_LAP_LENGTH_BY_KEY` dict so circular logic has the value it needs.

**Surfaced risks still NOT addressed by this plan (deferred to follow-up):**
1. **Wet/red-flag qualifying sessions** — `session.laps.pick_fastest()` may return a slow/invalidated lap. Mitigation: the validity gates in `_build_and_validate_regions` will reject obvious garbage (region count, lap length). If they pass but the lap was still suboptimal, segmentation may still be slightly off. A V2 follow-up could iterate over multiple drivers' fast laps and pick the one with the most regions detected.
2. **Sprint qualifying / non-Q sessions** — `_load_session` hardcodes `"Q"`. If someone asks about Sprint Quali, they'll get the Q session's corner map (which is the same circuit, so the result is correct — but the lap data is from the wrong session). Future-proof by parameterizing the session type.
3. **Multi-region same MV corner (e.g., Maggotts-Becketts complex)** — Greedy one-to-one will assign the MV corner to one region and leave the others unnamed. Acceptable for a v1; a v2 could emit suffix labels ("Turn 11 entry", "Turn 11 mid", "Turn 11 exit") when curvature regions outnumber MV corners by a small factor.

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-23-curvature-based-corner-segmentation.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
