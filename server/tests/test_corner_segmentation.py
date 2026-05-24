import json
import math

import numpy as np
import pytest

import corner_segmentation as cs


def test_clean_xy_drops_non_finite():
    x = np.array([0.0, 1.0, np.nan, 3.0, np.inf, 5.0])
    y = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
    # Need at least MIN_RAW_SAMPLES to pass — extend with finite values.
    x = np.concatenate([x, np.linspace(6.0, 200.0, 200)])
    y = np.concatenate([y, np.linspace(6.0, 200.0, 200)])
    cx, cy = cs._clean_xy(x, y)
    # NaN at index 2 and inf at index 4 must be dropped from the prefix.
    assert not np.any(np.isnan(cx))
    assert not np.any(np.isinf(cx))


def test_clean_xy_drops_zero_arc_length_duplicates():
    x = np.array([0.0, 1.0, 1.0, 2.0])
    y = np.array([0.0, 0.0, 0.0, 0.0])
    # Pad above MIN_RAW_SAMPLES.
    x = np.concatenate([x, np.linspace(3.0, 200.0, 200)])
    y = np.concatenate([y, np.linspace(0.0, 0.0, 200)])
    cx, cy = cs._clean_xy(x, y)
    # Duplicate (1.0, 0.0) at index 2 must be dropped.
    assert len(cx) == len(x) - 1


def test_clean_xy_raises_when_below_minimum_samples():
    x = np.array([0.0, 1.0, 2.0])
    y = np.array([0.0, 1.0, 2.0])
    with pytest.raises(cs.SegmentationInputError):
        cs._clean_xy(x, y)


def test_cumulative_arc_length_for_straight_line():
    x = np.array([0.0, 3.0, 6.0, 9.0])
    y = np.array([0.0, 4.0, 8.0, 12.0])
    s = cs._cumulative_arc_length(x, y)
    assert s == pytest.approx([0.0, 5.0, 10.0, 15.0])


def test_resample_uses_exact_arange_spacing():
    x = np.array([0.0, 7.0, 23.0, 50.0])
    y = np.zeros_like(x)
    xs, ys, s_new, dx, total = cs._resample_uniform(x, y, spacing_m=5.0)
    assert s_new[0] == pytest.approx(0.0)
    assert s_new[-1] <= 50.0
    deltas = np.diff(s_new)
    assert np.all(np.abs(deltas - 5.0) < 1e-9)
    assert dx == pytest.approx(5.0)
    assert total == pytest.approx(50.0)


def test_resample_returns_true_total_when_not_divisible():
    # 11m straight along x-axis with enough samples for cubic interpolation.
    x = np.linspace(0.0, 11.0, 5)
    y = np.zeros_like(x)
    xs, ys, s_new, dx, total = cs._resample_uniform(x, y, spacing_m=4.0)
    # s_new sampled at 0, 4, 8 (last <= 11).
    assert s_new.tolist() == [0.0, 4.0, 8.0]
    assert dx == pytest.approx(4.0)
    # True total length = 11m, not 12m (which would be s_new[-1] + spacing).
    assert total == pytest.approx(11.0)


def test_curvature_is_zero_for_straight_line():
    x = np.linspace(0, 100, 51)
    y = np.zeros_like(x)
    kappa = cs._compute_curvature(x, y, spacing_m=2.0)
    assert np.all(np.abs(kappa[10:-10]) < 1e-3)


def test_curvature_matches_circle_radius():
    R = 50.0
    arc_length = math.pi * R
    s = np.arange(0.0, arc_length + 1e-9, 1.0)
    theta = s / R
    x = R * np.cos(theta)
    y = R * np.sin(theta)
    kappa = cs._compute_curvature(x, y, spacing_m=1.0)
    interior = kappa[30:-30]
    assert np.median(np.abs(interior)) == pytest.approx(1.0 / R, rel=0.05)


def test_curvature_returns_zeros_for_too_few_samples():
    x = np.array([0.0, 1.0, 2.0])
    y = np.array([0.0, 0.0, 0.0])
    kappa = cs._compute_curvature(x, y, spacing_m=1.0)
    assert kappa.tolist() == [0.0, 0.0, 0.0]


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
    lap_length = 200.0
    s = np.arange(0, lap_length, 2.0)
    kappa = np.zeros_like(s)
    kappa[s < 20] = 0.02
    kappa[s >= 180] = 0.02
    regions = cs._detect_regions(s, kappa, kappa_enter=0.015, kappa_exit=0.01, lap_length_m=lap_length)
    assert len(regions) == 1
    entry, apex, exit_, sign = regions[0]
    assert entry == pytest.approx(180.0, abs=2.0)
    assert exit_ == pytest.approx(18.0, abs=2.0)
    assert sign == 1


def test_detect_regions_does_not_merge_when_only_one_end_active():
    s = np.arange(0, 200, 2.0)
    kappa = np.zeros_like(s)
    # 30m wide so it survives the MIN_REGION_WIDTH_M=20 filter.
    kappa[s >= 168] = 0.02
    regions = cs._detect_regions(s, kappa, kappa_enter=0.015, kappa_exit=0.01, lap_length_m=200.0)
    assert len(regions) == 1
    entry, apex, exit_, sign = regions[0]
    assert entry == pytest.approx(168.0, abs=2.0)
    assert exit_ <= 200.0
    # Not a wrap-around — entry < exit.
    assert entry < exit_


def test_detect_regions_drops_too_narrow_regions():
    s = np.arange(0, 200, 2.0)
    kappa = np.zeros_like(s)
    kappa[(s >= 30) & (s < 34)] = 0.02
    kappa[(s >= 100) & (s < 150)] = 0.02
    regions = cs._detect_regions(s, kappa, kappa_enter=0.015, kappa_exit=0.01, lap_length_m=200.0)
    assert len(regions) == 1
    assert regions[0][0] == pytest.approx(100.0, abs=2.0)


def test_detect_regions_merges_same_sign_adjacent_after_brief_gap():
    s = np.arange(0, 200, 2.0)
    kappa = np.zeros_like(s)
    kappa[(s >= 100) & (s < 150)] = 0.02
    kappa[s == 120] = 0.005
    regions = cs._detect_regions(s, kappa, kappa_enter=0.015, kappa_exit=0.01, lap_length_m=200.0)
    assert len(regions) == 1
    entry, apex, exit_, sign = regions[0]
    assert entry == pytest.approx(100.0, abs=2.0)
    assert exit_ == pytest.approx(148.0, abs=2.0)


def test_detect_regions_wrap_around_corner_survives_width_filter():
    lap_length = 200.0
    s = np.arange(0, lap_length, 2.0)
    kappa = np.zeros_like(s)
    kappa[s < 18] = 0.02
    kappa[s >= 182] = 0.02
    regions = cs._detect_regions(s, kappa, kappa_enter=0.015, kappa_exit=0.01, lap_length_m=lap_length)
    assert len(regions) == 1
    entry, apex, exit_, sign = regions[0]
    assert entry == pytest.approx(182.0, abs=2.0)
    assert exit_ == pytest.approx(16.0, abs=2.0)


def test_detect_regions_does_not_merge_real_chicane():
    s = np.arange(0, 300, 2.0)
    kappa = np.zeros_like(s)
    kappa[(s >= 100) & (s < 140)] = 0.02
    kappa[(s >= 170) & (s < 220)] = 0.02
    regions = cs._detect_regions(s, kappa, kappa_enter=0.015, kappa_exit=0.01, lap_length_m=300.0)
    assert len(regions) == 2


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
    regions = [
        (100.0, 120.0, 135.0, 1),
        (140.0, 160.0, 175.0, 1),
    ]
    multiviewer = [
        {"number": 4, "letter": "", "distance_m": 122.0},
    ]
    tagged = cs._tag_regions(regions, multiviewer, lap_length_m=300.0)
    numbers = [r.corner_number for r in tagged]
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
    regions = [
        (950.0, 10.0, 50.0, 1),
    ]
    multiviewer = [
        {"number": 1, "letter": "", "distance_m": 5.0},
    ]
    tagged = cs._tag_regions(regions, multiviewer, lap_length_m=1000.0)
    assert tagged[0].corner_number == 1
