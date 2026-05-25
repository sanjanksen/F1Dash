# Corner-Guided Segmentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the curvature-based corner segmentation so it detects all officially numbered corners, not just those with curvature above the global threshold. Miami currently detects 12 of 19 official corners — merged complexes (turns 6-7-8 become one region) and missed gentle corners (turns 9, 10 below threshold) cause mislabeled straights like "Turn 14 → Turn 17 straight".

**Architecture:** Add two post-processing steps to `_build_and_validate_regions` that run between `_detect_regions` and `_tag_regions`. Step 1 splits merged regions that contain multiple official corner apexes by cutting at `|κ|` local minima between them. Step 2 rescues undetected official corners by creating regions around their positions using a locally-lowered curvature threshold. Both steps produce raw region tuples; `_tag_regions` is called once at the end on the complete set. Schema version bumped to 3 to invalidate old caches.

**Tech Stack:** Python, NumPy, SciPy, FastF1, pytest. No new dependencies.

**Key Codex review points incorporated:**
- All splitting uses `abs(kappa)`, never signed kappa
- Splitting and rescuing produce raw tuples; `_tag_regions` called once at the end
- Wrap-around regions handled with circular arithmetic throughout
- Sub-regions pass through `MIN_REGION_WIDTH_M` filter
- Overlap prevention: rescued regions are trimmed to not overlap existing regions
- Cache schema bumped to 3
- `_tag_regions` unmatched list not relied upon — unmatched corners computed externally

---

## File Structure

**Modified files:**
- `server/corner_segmentation.py` — add `_split_merged_regions()`, `_rescue_missing_corners()`, wire into `_build_and_validate_regions`, bump `SCHEMA_VERSION` to 3, add new constants
- `server/tests/test_corner_segmentation.py` — add tests for split, rescue, and end-to-end detection with a synthetic multi-apex complex circuit

**No new files.** All changes are within the existing module and its test file.

---

### Task 1: Split merged regions

A merged region contains 2+ official corner apexes. We split it at `|κ|` local minima between each consecutive pair of official apexes inside the region.

**Files:**
- Modify: `server/corner_segmentation.py:29` (SCHEMA_VERSION)
- Modify: `server/corner_segmentation.py:157-223` (after `_detect_regions`)
- Modify: `server/tests/test_corner_segmentation.py`

- [ ] **Step 1: Write the failing test for splitting a merged region**

In `test_corner_segmentation.py`, add a test that constructs a kappa array with two distinct curvature peaks separated by a valley, but where curvature stays above the exit threshold through the whole section (so `_detect_regions` produces one region). Provide two MV corners inside the region and assert that after the new `_split_merged_regions` call, we get two separate regions.

```python
def test_split_merged_regions_separates_two_peaks():
    """A single detected region containing two MV apexes should be split at the |κ| valley."""
    s = np.arange(0, 600, 2.0)
    kappa = np.zeros_like(s)
    # Two curvature peaks with a valley between them — valley stays above exit threshold
    kappa[(s >= 100) & (s < 200)] = 0.03
    kappa[(s >= 200) & (s < 250)] = 0.012  # valley — above exit (0.01) but below enter (0.015)
    kappa[(s >= 250) & (s < 350)] = 0.03
    # _detect_regions will see one merged region from 100–350
    raw = cs._detect_regions(s, kappa, kappa_enter=0.015, kappa_exit=0.01, lap_length_m=600.0)
    assert len(raw) == 1, "precondition: should be one merged region"

    mv = [
        {"number": 5, "letter": "", "distance_m": 150.0},
        {"number": 6, "letter": "", "distance_m": 300.0},
    ]
    split = cs._split_merged_regions(raw, mv, s, kappa, 600.0)
    assert len(split) == 2
    # First sub-region covers the first peak, second covers the second
    assert split[0][0] <= 150.0 <= split[0][2]  # entry <= apex5 <= exit
    assert split[1][0] <= 300.0 <= split[1][2]  # entry <= apex6 <= exit
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd server && python -m pytest tests/test_corner_segmentation.py::test_split_merged_regions_separates_two_peaks -v`
Expected: FAIL with `AttributeError: module 'corner_segmentation' has no attribute '_split_merged_regions'`

- [ ] **Step 3: Implement `_split_merged_regions`**

Add to `corner_segmentation.py` after `_detect_regions` (around line 224):

```python
def _split_merged_regions(
    regions: list[tuple[float, float, float, int]],
    multiviewer_corners: list[dict],
    s: np.ndarray,
    kappa: np.ndarray,
    lap_length_m: float,
) -> list[tuple[float, float, float, int]]:
    """Split regions that contain 2+ official corner apexes at |κ| valleys between them."""
    result: list[tuple[float, float, float, int]] = []
    for region in regions:
        entry, apex, exit_, sign = region
        # Find all MV corners whose distance_m falls inside this region
        inside_mv = sorted(
            [c for c in multiviewer_corners
             if _distance_inside_region(region, float(c["distance_m"]), lap_length_m)],
            key=lambda c: c["distance_m"],
        )
        if len(inside_mv) < 2:
            result.append(region)
            continue

        # For each consecutive pair of MV corners, find the |κ| minimum between them
        # and split there. Handle non-wrap regions only (entry <= exit_).
        # Wrap-around regions with multiple MV corners are rare; keep them unsplit.
        if entry > exit_:
            result.append(region)
            continue

        abs_k = np.abs(kappa)
        cut_points = [entry]
        for i in range(len(inside_mv) - 1):
            left_d = float(inside_mv[i]["distance_m"])
            right_d = float(inside_mv[i + 1]["distance_m"])
            left_idx = _nearest_idx(s, left_d)
            right_idx = _nearest_idx(s, right_d)
            if left_idx >= right_idx:
                continue
            valley_slice = abs_k[left_idx:right_idx + 1]
            valley_local = int(np.argmin(valley_slice))
            valley_idx = left_idx + valley_local
            cut_points.append(float(s[valley_idx]))
        cut_points.append(exit_)

        # Build sub-regions from consecutive cut points
        for j in range(len(cut_points) - 1):
            sub_entry = cut_points[j]
            sub_exit = cut_points[j + 1]
            if sub_exit - sub_entry < MIN_REGION_WIDTH_M:
                # Too narrow — merge with next or keep as-is
                if j + 2 < len(cut_points):
                    cut_points[j + 1] = cut_points[j + 2]
                continue
            start_idx = _nearest_idx(s, sub_entry)
            end_idx = _nearest_idx(s, sub_exit)
            if start_idx >= end_idx:
                continue
            result.append(_finalize_region(s, kappa, start_idx, end_idx))

    return result
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd server && python -m pytest tests/test_corner_segmentation.py::test_split_merged_regions_separates_two_peaks -v`
Expected: PASS

- [ ] **Step 5: Write test for splitting a 3-apex merged region**

```python
def test_split_merged_regions_handles_three_apexes():
    """A region with 3 MV corners produces 3 sub-regions."""
    s = np.arange(0, 800, 2.0)
    kappa = np.zeros_like(s)
    # Three peaks with valleys between them
    kappa[(s >= 100) & (s < 180)] = 0.03
    kappa[(s >= 180) & (s < 220)] = 0.012  # valley 1
    kappa[(s >= 220) & (s < 300)] = 0.025
    kappa[(s >= 300) & (s < 340)] = 0.012  # valley 2
    kappa[(s >= 340) & (s < 420)] = 0.03
    raw = cs._detect_regions(s, kappa, kappa_enter=0.015, kappa_exit=0.01, lap_length_m=800.0)
    assert len(raw) == 1

    mv = [
        {"number": 13, "letter": "", "distance_m": 140.0},
        {"number": 14, "letter": "", "distance_m": 260.0},
        {"number": 15, "letter": "", "distance_m": 380.0},
    ]
    split = cs._split_merged_regions(raw, mv, s, kappa, 800.0)
    assert len(split) == 3
```

- [ ] **Step 6: Run to verify it passes** (should pass with existing implementation)

Run: `cd server && python -m pytest tests/test_corner_segmentation.py::test_split_merged_regions_handles_three_apexes -v`
Expected: PASS

- [ ] **Step 7: Write test for region with single MV corner (no split needed)**

```python
def test_split_merged_regions_leaves_single_apex_region():
    """A region with only 1 MV corner is returned unchanged."""
    s = np.arange(0, 400, 2.0)
    kappa = np.zeros_like(s)
    kappa[(s >= 100) & (s < 200)] = 0.03
    raw = cs._detect_regions(s, kappa, kappa_enter=0.015, kappa_exit=0.01, lap_length_m=400.0)
    assert len(raw) == 1

    mv = [{"number": 1, "letter": "", "distance_m": 150.0}]
    split = cs._split_merged_regions(raw, mv, s, kappa, 400.0)
    assert len(split) == 1
    assert split[0] == raw[0]
```

- [ ] **Step 8: Run to verify it passes**

Run: `cd server && python -m pytest tests/test_corner_segmentation.py::test_split_merged_regions_leaves_single_apex_region -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add server/corner_segmentation.py server/tests/test_corner_segmentation.py
git commit -m "feat(corner-segmentation): split merged regions at |κ| valleys between official apexes"
```

---

### Task 2: Rescue missed corners

Official corners that fall in gaps between detected regions (curvature below global threshold) need to be detected using a locally-lowered threshold around the official position.

**Files:**
- Modify: `server/corner_segmentation.py` (new function + constants)
- Modify: `server/tests/test_corner_segmentation.py`

- [ ] **Step 1: Write the failing test for rescuing a missed corner**

```python
def test_rescue_missing_corners_creates_region_for_gentle_kink():
    """An MV corner at 500m with low curvature (below global threshold) should be rescued."""
    s = np.arange(0, 1000, 2.0)
    kappa = np.zeros_like(s)
    # One real corner detected normally
    kappa[(s >= 100) & (s < 200)] = 0.03
    # A gentle kink at 500m — below global enter threshold but nonzero
    kappa[(s >= 480) & (s < 520)] = 0.008

    existing_regions = [
        (100.0, 150.0, 200.0, 1),  # the detected corner
    ]
    mv = [
        {"number": 1, "letter": "", "distance_m": 150.0},
        {"number": 2, "letter": "", "distance_m": 500.0},  # missed
    ]
    rescued = cs._rescue_missing_corners(existing_regions, mv, s, kappa, 1000.0)
    # Should have original region + one rescued region
    assert len(rescued) == 2
    new_region = [r for r in rescued if r != existing_regions[0]]
    assert len(new_region) == 1
    entry, apex, exit_, sign = new_region[0]
    assert 470.0 <= entry <= 500.0
    assert 480.0 <= apex <= 520.0
    assert 500.0 <= exit_ <= 530.0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd server && python -m pytest tests/test_corner_segmentation.py::test_rescue_missing_corners_creates_region_for_gentle_kink -v`
Expected: FAIL with `AttributeError: module 'corner_segmentation' has no attribute '_rescue_missing_corners'`

- [ ] **Step 3: Add constants and implement `_rescue_missing_corners`**

Add new constants near the existing ones (around line 43):

```python
RESCUE_WINDOW_M = 100.0
RESCUE_KAPPA_FLOOR = 0.001
RESCUE_MIN_WIDTH_M = 10.0
RESCUE_FALLBACK_HALF_WIDTH_M = 20.0
```

Add the function after `_split_merged_regions`:

```python
def _rescue_missing_corners(
    regions: list[tuple[float, float, float, int]],
    multiviewer_corners: list[dict],
    s: np.ndarray,
    kappa: np.ndarray,
    lap_length_m: float,
) -> list[tuple[float, float, float, int]]:
    """Create regions for official corners that have no matching detected region."""
    # Find which MV corners are already inside an existing region
    matched_mv_dists: set[float] = set()
    for c in multiviewer_corners:
        d = float(c["distance_m"])
        for region in regions:
            if _distance_inside_region(region, d, lap_length_m):
                matched_mv_dists.add(d)
                break

    unmatched = [c for c in multiviewer_corners if float(c["distance_m"]) not in matched_mv_dists]
    if not unmatched:
        return list(regions)

    abs_k = np.abs(kappa)
    result = list(regions)
    for corner in unmatched:
        center = float(corner["distance_m"])
        # Search window around the official position
        lo = center - RESCUE_WINDOW_M
        hi = center + RESCUE_WINDOW_M
        mask = (s >= lo) & (s <= hi)
        if not np.any(mask):
            continue

        window_abs_k = abs_k.copy()
        window_abs_k[~mask] = 0.0
        peak_idx = int(np.argmax(window_abs_k))
        peak_val = float(abs_k[peak_idx])

        if peak_val < RESCUE_KAPPA_FLOOR:
            # Curvature is essentially zero — create a minimal synthetic region
            center_idx = _nearest_idx(s, center)
            half_n = max(1, int(RESCUE_FALLBACK_HALF_WIDTH_M / RESAMPLE_SPACING_M))
            start_idx = max(0, center_idx - half_n)
            end_idx = min(len(s) - 1, center_idx + half_n)
        else:
            # Walk outward from peak until |κ| drops below RESCUE_KAPPA_FLOOR
            start_idx = peak_idx
            while start_idx > 0 and abs_k[start_idx - 1] >= RESCUE_KAPPA_FLOOR and s[start_idx] >= lo:
                start_idx -= 1
            end_idx = peak_idx
            while end_idx < len(s) - 1 and abs_k[end_idx + 1] >= RESCUE_KAPPA_FLOOR and s[end_idx] <= hi:
                end_idx += 1

        if start_idx >= end_idx:
            continue

        new_region = _finalize_region(s, kappa, start_idx, end_idx)
        new_entry, new_apex, new_exit, new_sign = new_region

        # Skip if too narrow
        width = new_exit - new_entry if new_entry <= new_exit else (lap_length_m - new_entry) + new_exit
        if width < RESCUE_MIN_WIDTH_M:
            continue

        # Trim to avoid overlapping existing regions
        overlaps = False
        for existing in result:
            if _distance_inside_region(existing, new_entry, lap_length_m) or \
               _distance_inside_region(existing, new_exit, lap_length_m):
                overlaps = True
                break
        if overlaps:
            continue

        result.append(new_region)

    return result
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd server && python -m pytest tests/test_corner_segmentation.py::test_rescue_missing_corners_creates_region_for_gentle_kink -v`
Expected: PASS

- [ ] **Step 5: Write test for already-matched corner (no rescue needed)**

```python
def test_rescue_missing_corners_skips_already_matched():
    """An MV corner already inside a detected region should not create a duplicate."""
    s = np.arange(0, 600, 2.0)
    kappa = np.zeros_like(s)
    kappa[(s >= 100) & (s < 200)] = 0.03

    existing_regions = [(100.0, 150.0, 200.0, 1)]
    mv = [{"number": 1, "letter": "", "distance_m": 150.0}]
    rescued = cs._rescue_missing_corners(existing_regions, mv, s, kappa, 600.0)
    assert len(rescued) == 1
    assert rescued[0] == existing_regions[0]
```

- [ ] **Step 6: Run to verify it passes**

Run: `cd server && python -m pytest tests/test_corner_segmentation.py::test_rescue_missing_corners_skips_already_matched -v`
Expected: PASS

- [ ] **Step 7: Write test for zero-curvature corner (synthetic fallback)**

```python
def test_rescue_missing_corners_creates_synthetic_for_zero_curvature():
    """An MV corner with no measurable curvature gets a narrow synthetic region."""
    s = np.arange(0, 600, 2.0)
    kappa = np.zeros_like(s)
    # Only one real corner; MV corner at 400m has zero curvature
    kappa[(s >= 100) & (s < 200)] = 0.03

    existing_regions = [(100.0, 150.0, 200.0, 1)]
    mv = [
        {"number": 1, "letter": "", "distance_m": 150.0},
        {"number": 2, "letter": "", "distance_m": 400.0},
    ]
    rescued = cs._rescue_missing_corners(existing_regions, mv, s, kappa, 600.0)
    assert len(rescued) == 2
    synthetic = [r for r in rescued if r != existing_regions[0]][0]
    entry, apex, exit_, sign = synthetic
    # Should be a narrow region centered around 400m
    assert 370.0 <= entry <= 400.0
    assert 400.0 <= exit_ <= 430.0
```

- [ ] **Step 8: Run to verify it passes**

Run: `cd server && python -m pytest tests/test_corner_segmentation.py::test_rescue_missing_corners_creates_synthetic_for_zero_curvature -v`
Expected: PASS

- [ ] **Step 9: Write test for overlap prevention**

```python
def test_rescue_missing_corners_skips_if_overlapping():
    """A rescued region that would overlap an existing region is skipped."""
    s = np.arange(0, 600, 2.0)
    kappa = np.zeros_like(s)
    kappa[(s >= 100) & (s < 250)] = 0.03
    kappa[(s >= 230) & (s < 260)] = 0.008  # gentle kink right at edge of existing region

    existing_regions = [(100.0, 170.0, 250.0, 1)]
    mv = [
        {"number": 1, "letter": "", "distance_m": 170.0},
        {"number": 2, "letter": "", "distance_m": 245.0},  # inside existing region
    ]
    rescued = cs._rescue_missing_corners(existing_regions, mv, s, kappa, 600.0)
    assert len(rescued) == 1  # no new region added
```

- [ ] **Step 10: Run to verify it passes**

Run: `cd server && python -m pytest tests/test_corner_segmentation.py::test_rescue_missing_corners_skips_if_overlapping -v`
Expected: PASS

- [ ] **Step 11: Commit**

```bash
git add server/corner_segmentation.py server/tests/test_corner_segmentation.py
git commit -m "feat(corner-segmentation): rescue undetected official corners with locally-lowered threshold"
```

---

### Task 3: Wire into pipeline and bump schema version

Connect `_split_merged_regions` and `_rescue_missing_corners` into `_build_and_validate_regions`, bump `SCHEMA_VERSION` to 3, and update the validation bounds.

**Files:**
- Modify: `server/corner_segmentation.py:29` (SCHEMA_VERSION)
- Modify: `server/corner_segmentation.py:297-320` (`_build_and_validate_regions`)
- Modify: `server/tests/test_corner_segmentation.py`

- [ ] **Step 1: Write the end-to-end test**

A synthetic circuit with a merged complex and a missed gentle corner, run through the full `_build_and_validate_regions` pipeline.

```python
def _make_complex_circuit():
    """Synthetic circuit: 3 real corners, 1 tight complex (2 peaks merged), 1 gentle kink.
    
    Layout: straight → corner1 → straight → corner2+corner3 complex → 
            straight → gentle_kink → straight → corner4 → back to start.
    Total ~3500m. 5 official corners, but _detect_regions finds only 3 
    (complex merged, kink missed).
    """
    R = 40.0
    arc_90 = math.pi * R / 2  # ~62.8m per 90° arc
    segments = []
    # Corner 1: left 90° at ~300m
    segments.append(("straight", 300.0))
    segments.append(("arc_left", arc_90))
    # Straight to complex
    segments.append(("straight", 200.0))
    # Corner 2: left 45° (tight)
    segments.append(("arc_left", arc_90 / 2))
    # Brief straight in complex (20m — too short for exit threshold to drop)
    segments.append(("straight", 15.0))
    # Corner 3: left 45°
    segments.append(("arc_left", arc_90 / 2))
    # Straight to gentle kink
    segments.append(("straight", 400.0))
    # Corner 4: very gentle left (large radius = 200m, 20°)
    gentle_arc = math.pi * 200.0 * (20.0 / 180.0)  # ~70m
    segments.append(("arc_gentle_left", gentle_arc))
    # Straight to corner 5
    segments.append(("straight", 500.0))
    # Corner 5: left 90°
    segments.append(("arc_left", arc_90))
    # Straight back
    segments.append(("straight", 800.0))
    # Corner 6: left 90° (to close the loop-ish)
    segments.append(("arc_left", arc_90))
    segments.append(("straight", 300.0))

    total = sum(seg[1] for seg in segments)
    n_samples = max(int(total / 1.0), 2000)
    s_arr = np.linspace(0, total, n_samples, endpoint=False)
    x = np.zeros_like(s_arr)
    y = np.zeros_like(s_arr)
    
    # Build geometry
    seg_starts = []
    cumul = 0.0
    cx, cy, ch = 0.0, 0.0, 0.0
    for kind, length in segments:
        seg_starts.append((cumul, kind, length, cx, cy, ch))
        if kind == "straight":
            cx += length * math.cos(ch)
            cy += length * math.sin(ch)
        elif kind == "arc_left":
            r = R
            dtheta = length / r
            cx += r * (math.sin(ch + dtheta) - math.sin(ch))
            cy += r * (-math.cos(ch + dtheta) + math.cos(ch))
            ch += dtheta
        elif kind == "arc_gentle_left":
            r = 200.0
            dtheta = length / r
            cx += r * (math.sin(ch + dtheta) - math.sin(ch))
            cy += r * (-math.cos(ch + dtheta) + math.cos(ch))
            ch += dtheta
        cumul += length

    for i, si in enumerate(s_arr):
        for start_s, kind, length, sx, sy, sh in reversed(seg_starts):
            if si >= start_s:
                local = si - start_s
                if kind == "straight":
                    x[i] = sx + local * math.cos(sh)
                    y[i] = sy + local * math.sin(sh)
                elif kind == "arc_left":
                    r = R
                    theta = local / r
                    cx_a = sx - r * math.sin(sh)
                    cy_a = sy + r * math.cos(sh)
                    x[i] = cx_a + r * math.sin(sh + theta)
                    y[i] = cy_a - r * math.cos(sh + theta)
                elif kind == "arc_gentle_left":
                    r = 200.0
                    theta = local / r
                    cx_a = sx - r * math.sin(sh)
                    cy_a = sy + r * math.cos(sh)
                    x[i] = cx_a + r * math.sin(sh + theta)
                    y[i] = cy_a - r * math.cos(sh + theta)
                break

    # MV corners at approximate arc midpoints
    mv = []
    cumul = 0.0
    corner_num = 0
    for kind, length in segments:
        if kind != "straight":
            corner_num += 1
            mv.append({"number": corner_num, "letter": "", "distance_m": cumul + length / 2})
        cumul += length

    return x, y, total, mv


def test_build_and_validate_detects_all_official_corners():
    """End-to-end: merged complex and gentle kink both get individual regions."""
    x, y, total, mv = _make_complex_circuit()
    regions, lap_length = cs._build_and_validate_regions(x, y, mv)
    detected_numbers = {r.corner_number for r in regions if r.corner_number is not None}
    expected_numbers = {c["number"] for c in mv}
    # Every official corner should have a tagged region
    assert expected_numbers.issubset(detected_numbers), (
        f"missing corners: {expected_numbers - detected_numbers}"
    )
```

- [ ] **Step 2: Run the test to verify it fails** (because pipeline doesn't call split/rescue yet)

Run: `cd server && python -m pytest tests/test_corner_segmentation.py::test_build_and_validate_detects_all_official_corners -v`
Expected: FAIL — some corners missing from detected set

- [ ] **Step 3: Wire `_split_merged_regions` and `_rescue_missing_corners` into `_build_and_validate_regions`**

Replace the current `_build_and_validate_regions` (lines 297-320) with:

```python
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

    # Post-processing: use official corner positions to fix detection gaps
    if multiviewer_corners:
        raw_regions = _split_merged_regions(raw_regions, multiviewer_corners, s_u, kappa, lap_length)
        raw_regions = _rescue_missing_corners(raw_regions, multiviewer_corners, s_u, kappa, lap_length)

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
```

- [ ] **Step 4: Bump SCHEMA_VERSION to 3**

Change line 29:

```python
SCHEMA_VERSION = 3
```

- [ ] **Step 5: Run the end-to-end test to verify it passes**

Run: `cd server && python -m pytest tests/test_corner_segmentation.py::test_build_and_validate_detects_all_official_corners -v`
Expected: PASS

- [ ] **Step 6: Run all existing corner segmentation tests to check for regressions**

Run: `cd server && python -m pytest tests/test_corner_segmentation.py -v`
Expected: All tests pass. Some cache-related tests may need their `schema_version` values updated from `2` to `3` — fix any that fail by updating the version in the test fixture JSON.

- [ ] **Step 7: Fix any cache test fixtures that reference old schema version**

Search for `"schema_version": cs.SCHEMA_VERSION` and `"schema_version": 2` in the test file. Tests that construct cache JSON with a hardcoded `2` should be updated. Tests that use `cs.SCHEMA_VERSION` dynamically are already correct.

Specifically, `test_get_corner_regions_ignores_cache_with_old_schema` uses `cs.SCHEMA_VERSION - 1` which is now `2` — this is correct (old = 2, current = 3, rebuild triggered). No change needed there.

- [ ] **Step 8: Commit**

```bash
git add server/corner_segmentation.py server/tests/test_corner_segmentation.py
git commit -m "feat(corner-segmentation): wire split + rescue into pipeline, bump schema to v3"
```

---

### Task 4: Delete stale caches and run full test suite

Old v2 cache files will prevent the new algorithm from running. Delete them so fresh builds use the improved pipeline.

**Files:**
- Delete: `server/cache/corner_regions/*.json` (all cached segmentation files)
- Run: full test suite

- [ ] **Step 1: Delete all cached corner region files**

```bash
cd server && python -c "import os, glob; [os.remove(f) for f in glob.glob('cache/corner_regions/*.json')]"
```

- [ ] **Step 2: Run the full corner segmentation test suite**

Run: `cd server && python -m pytest tests/test_corner_segmentation.py -v`
Expected: All PASS

- [ ] **Step 3: Run the f1_data resolver tests**

Run: `cd server && python -m pytest tests/test_f1_data.py -k "resolve_corner" -v`
Expected: All PASS

- [ ] **Step 4: Run the full test suite**

Run: `cd server && python -m pytest tests/ -v --timeout=120`
Expected: All PASS (or pre-existing failures only — no new failures)

- [ ] **Step 5: Commit cache deletion**

```bash
git add -u server/cache/corner_regions/
git commit -m "chore: delete stale v2 corner region caches — v3 algorithm will rebuild"
```

---

### Task 5: Verify with real data (manual)

Run the server and test with the Miami qualifying query that originally showed "Turn 14 → Turn 17 straight".

- [ ] **Step 1: Start the backend**

```bash
cd server && python -m uvicorn main:app --reload --port 8000
```

- [ ] **Step 2: Start the frontend**

```bash
cd client && npm run dev
```

- [ ] **Step 3: Test the query**

Ask: "How did Leclerc outqualify Norris at Miami?"

Verify that:
- The speed trace markers reference Turn 16 or Turn 15 instead of "Turn 14 → Turn 17 straight"
- No server errors in the console
- The widget renders correctly

- [ ] **Step 4: Check the rebuilt cache file**

```bash
cd server && python -c "import json; d = json.load(open('cache/corner_regions/2026_4.json')); print(f'regions: {len(d[\"regions\"])}'); print([r['corner_number'] for r in d['regions']])"
```

Verify: more than 12 regions, and corner numbers include 9, 10, 13, 15, 16 (the previously missing ones).

- [ ] **Step 5: Commit if any adjustments were needed**

```bash
git add -A && git commit -m "fix(corner-segmentation): adjustments from manual verification"
```
