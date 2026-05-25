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


from unittest.mock import MagicMock, patch


def _make_hexagonal_lap(noise: float = 0.0, n_samples: int = 1200):
    """6 left-handers (90° R=40m arcs) connecting 6 straights of length 400m."""
    R = 40.0
    L = 400.0
    arc_len = math.pi * R / 2
    segments = []
    for _ in range(6):
        segments.append(("straight", L))
        segments.append(("arc", arc_len))
    total = sum(seg[1] for seg in segments)
    s = np.linspace(0, total, n_samples, endpoint=False)
    x = np.zeros_like(s)
    y = np.zeros_like(s)
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
            ch_new = ch + math.pi / 2
            cx += R * math.sin(ch_new) - R * math.sin(ch)
            cy += -R * math.cos(ch_new) + R * math.cos(ch)
            ch = ch_new
        cumul += length
    for i, si in enumerate(s):
        for start_s, kind, length, sx, sy, sh in seg_starts:
            if start_s <= si < start_s + length:
                local = si - start_s
                if kind == "straight":
                    x[i] = sx + local * math.cos(sh)
                    y[i] = sy + local * math.sin(sh)
                else:
                    theta = local / R
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
    R = 40.0
    L = 400.0
    arc_len = math.pi * R / 2
    mv = []
    cumul = 0.0
    for n in range(1, 7):
        cumul += L
        cumul += arc_len / 2
        mv.append({"number": n, "letter": "", "distance_m": cumul})
        cumul += arc_len / 2
    return mv


def test_build_corner_regions_validates_minimum_count():
    x = np.linspace(0, 3000, 1500)
    y = np.zeros_like(x)
    with pytest.raises(cs.SegmentationOutputError):
        cs._build_and_validate_regions(x, y, multiviewer_corners=[])


def test_build_corner_regions_validates_lap_length():
    x = np.linspace(0, 100, 200)
    y = np.zeros_like(x)
    with pytest.raises(cs.SegmentationOutputError):
        cs._build_and_validate_regions(x, y, multiviewer_corners=[])


def test_build_corner_regions_on_synthetic_hexagonal_circuit():
    x, y, expected_total = _make_hexagonal_lap(noise=0.0)
    mv = _make_hexagonal_mv()
    regions, lap_length = cs._build_and_validate_regions(x, y, mv)
    assert 4 <= len(regions) <= 8
    assert all(r.sign == 1 for r in regions)
    assert lap_length == pytest.approx(expected_total, rel=0.02)


def test_build_corner_regions_tolerates_realistic_noise():
    x, y, _expected_total = _make_hexagonal_lap(noise=0.5)
    mv = _make_hexagonal_mv()
    regions, _lap_length = cs._build_and_validate_regions(x, y, mv)
    assert len(regions) >= cs.MIN_REGIONS


def test_get_corner_regions_uses_disk_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(cs, "_MV_BY_KEY", {})
    monkeypatch.setattr(cs, "_LAP_LENGTH_BY_KEY", {})
    cached = {
        "schema_version": cs.SCHEMA_VERSION,
        "lap_length_m": 5410.0,
        "multiviewer_corners": [
            {"number": 1, "letter": "", "distance_m": 706.0},
        ],
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
    monkeypatch.setattr(cs, "_MV_BY_KEY", {})
    monkeypatch.setattr(cs, "_LAP_LENGTH_BY_KEY", {})
    cached = {
        "schema_version": cs.SCHEMA_VERSION - 1,
        "lap_length_m": 5410.0,
        "regions": [{"corner_number": 1, "label_suffix": "", "entry_m": 10.0,
                     "apex_m": 20.0, "exit_m": 30.0, "sign": 1}],
    }
    (tmp_path / "2025_4.json").write_text(json.dumps(cached))
    with patch.object(cs, "_load_session", side_effect=RuntimeError("forced rebuild")):
        # Old schema falls back to degraded read of v1 cache when rebuild fails.
        regions = cs.get_corner_regions(2025, 4)
    assert len(regions) == 1
    assert cs._MV_BY_KEY[(2025, 4)] == []


def test_get_corner_regions_writes_current_schema_on_rebuild(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(cs, "_MV_BY_KEY", {})
    monkeypatch.setattr(cs, "_LAP_LENGTH_BY_KEY", {})
    x, y, expected_total = _make_hexagonal_lap()
    mv = _make_hexagonal_mv()
    fake_session = MagicMock()
    fake_session.get_circuit_info.return_value.corners.iterrows.return_value = [
        (i, {"X": 0, "Y": 0, "Number": m["number"], "Letter": m["letter"], "Distance": m["distance_m"]})
        for i, m in enumerate(mv)
    ]
    fake_lap = MagicMock()
    # FastF1 publishes pos data in decimeters; _load_reference_lap_xy
    # scales by 0.1 to get meters. Our synthetic fixture is already in
    # meters, so we pre-multiply by 10 to match the real-FastF1 contract.
    fake_lap.get_pos_data.return_value = {"X": x * 10.0, "Y": y * 10.0}
    fake_session.laps.pick_fastest.return_value = fake_lap
    with patch.object(cs, "_load_session", return_value=fake_session):
        cs.get_corner_regions(2025, 4)
    written = json.loads((tmp_path / "2025_4.json").read_text())
    assert written["schema_version"] == cs.SCHEMA_VERSION
    assert written["lap_length_m"] == pytest.approx(expected_total, rel=0.02)
    assert len(written["multiviewer_corners"]) == len(mv)
    assert {c["number"] for c in written["multiviewer_corners"]} == {1, 2, 3, 4, 5, 6}
    assert cs._lap_length_for(2025, 4) == pytest.approx(expected_total, rel=0.02)
    assert cs._MV_BY_KEY[(2025, 4)] == written["multiviewer_corners"]


def test_get_corner_regions_loads_mv_from_disk_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(cs, "_MV_BY_KEY", {})
    monkeypatch.setattr(cs, "_LAP_LENGTH_BY_KEY", {})
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


def test_get_corner_regions_rejects_invalid_year(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "CACHE_DIR", str(tmp_path))
    with pytest.raises(cs.SegmentationInputError):
        cs.get_corner_regions(None, 4)
    with pytest.raises(cs.SegmentationInputError):
        cs.get_corner_regions(0, 4)
    with pytest.raises(cs.SegmentationInputError):
        cs.get_corner_regions(-2025, 4)
    assert not list(tmp_path.glob("*.json"))


def test_get_corner_regions_does_not_write_invalid_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(cs, "_MV_BY_KEY", {})
    monkeypatch.setattr(cs, "_LAP_LENGTH_BY_KEY", {})
    fake_session = MagicMock()
    fake_session.get_circuit_info.return_value.corners.iterrows.return_value = []
    fake_lap = MagicMock()
    fake_lap.get_pos_data.return_value = {"X": np.array([0.0, 1.0]), "Y": np.array([0.0, 1.0])}
    fake_session.laps.pick_fastest.return_value = fake_lap
    with patch.object(cs, "_load_session", return_value=fake_session):
        with pytest.raises(cs.SegmentationInputError):
            cs.get_corner_regions(2025, 4)
    assert not (tmp_path / "2025_4.json").exists()


def test_write_cache_rejects_region_with_out_of_bounds_boundary(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "CACHE_DIR", str(tmp_path))
    bad_region = cs.CornerRegion(
        corner_number=1, label_suffix="", entry_m=100.0,
        apex_m=130.0, exit_m=6000.0, sign=1,
    )
    with pytest.raises(cs.SegmentationOutputError):
        cs._write_cache(2025, 4, [bad_region], lap_length_m=5400.0, multiviewer_corners=[])
    assert not (tmp_path / "2025_4.json").exists()


def test_write_cache_clamps_boundary_within_tolerance(tmp_path, monkeypatch):
    """Tiny floating-point overshoot must be clamped, not rejected."""
    monkeypatch.setattr(cs, "CACHE_DIR", str(tmp_path))
    region = cs.CornerRegion(
        corner_number=1, label_suffix="", entry_m=100.0,
        apex_m=130.0, exit_m=5400.0001, sign=1,
    )
    cs._write_cache(2025, 4, [region], lap_length_m=5400.0, multiviewer_corners=[])
    written = json.loads((tmp_path / "2025_4.json").read_text())
    assert written["regions"][0]["exit_m"] == pytest.approx(5400.0, abs=1e-9)


def test_read_cache_rejects_invalid_lap_length(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "CACHE_DIR", str(tmp_path))
    cached = {
        "schema_version": cs.SCHEMA_VERSION,
        "lap_length_m": 0.001,
        "multiviewer_corners": [],
        "regions": [{"corner_number": 1, "label_suffix": "", "entry_m": 0.0,
                     "apex_m": 0.0005, "exit_m": 0.001, "sign": 1}],
    }
    (tmp_path / "2025_6.json").write_text(json.dumps(cached))
    assert cs._read_cache(2025, 6) is None


def test_read_cache_rejects_out_of_bounds_region(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "CACHE_DIR", str(tmp_path))
    cached = {
        "schema_version": cs.SCHEMA_VERSION,
        "lap_length_m": 5400.0,
        "multiviewer_corners": [],
        "regions": [{"corner_number": 1, "label_suffix": "", "entry_m": 100.0,
                     "apex_m": 130.0, "exit_m": 9999.0, "sign": 1}],
    }
    (tmp_path / "2025_6.json").write_text(json.dumps(cached))
    assert cs._read_cache(2025, 6) is None


def test_get_corner_regions_falls_back_to_degraded_v1_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(cs, "_MV_BY_KEY", {})
    monkeypatch.setattr(cs, "_LAP_LENGTH_BY_KEY", {})
    v1_cache = {
        "schema_version": 1,
        "lap_length_m": 5410.0,
        "regions": [{"corner_number": 1, "label_suffix": "", "entry_m": 100.0,
                     "apex_m": 130.0, "exit_m": 160.0, "sign": 1}],
    }
    (tmp_path / "2025_6.json").write_text(json.dumps(v1_cache))
    with patch.object(cs, "_load_session", side_effect=RuntimeError("network down")):
        regions = cs.get_corner_regions(2025, 6)
    assert len(regions) == 1
    assert regions[0].corner_number == 1
    assert cs._MV_BY_KEY[(2025, 6)] == []


def test_get_corner_regions_raises_when_no_cache_and_rebuild_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(cs, "_MV_BY_KEY", {})
    monkeypatch.setattr(cs, "_LAP_LENGTH_BY_KEY", {})
    with patch.object(cs, "_load_session", side_effect=RuntimeError("network down")):
        with pytest.raises(RuntimeError, match="network down"):
            cs.get_corner_regions(2025, 6)


def _stub_regions(monkeypatch, regions, lap_length=5400.0, mv_corners=None):
    monkeypatch.setattr(cs, "get_corner_regions", lambda *_: regions)
    monkeypatch.setattr(cs, "_lap_length_for", lambda *_: lap_length)
    monkeypatch.setattr(cs, "_load_multiviewer_corners_for_resolve",
                        lambda *_: (mv_corners or []))


def test_resolve_inside_region_returns_corner_label(monkeypatch):
    regions = [
        cs.CornerRegion(corner_number=11, label_suffix="", entry_m=3000.0,
                        apex_m=3083.0, exit_m=3160.0, sign=1),
    ]
    _stub_regions(monkeypatch, regions)
    result = cs.resolve_corner_for_distance(2025, 6, 3083.0)
    assert result["corner_number"] == 11
    assert result["corner_name"] == "Turn 11"
    assert result["location_label"] == "Turn 11"


def test_resolve_between_regions_returns_straight_label(monkeypatch):
    regions = [
        cs.CornerRegion(corner_number=10, label_suffix="", entry_m=2400.0,
                        apex_m=2440.0, exit_m=2500.0, sign=-1),
        cs.CornerRegion(corner_number=11, label_suffix="", entry_m=3000.0,
                        apex_m=3083.0, exit_m=3160.0, sign=1),
    ]
    _stub_regions(monkeypatch, regions)
    result = cs.resolve_corner_for_distance(2025, 6, 2700.0)
    assert result["corner_number"] is None
    assert result["location_label"] == "Turn 10 → Turn 11 straight"


def test_resolve_after_final_corner_wraps_to_first(monkeypatch):
    regions = [
        cs.CornerRegion(corner_number=1, label_suffix="", entry_m=200.0,
                        apex_m=250.0, exit_m=320.0, sign=1),
        cs.CornerRegion(corner_number=19, label_suffix="", entry_m=5000.0,
                        apex_m=5100.0, exit_m=5200.0, sign=-1),
    ]
    _stub_regions(monkeypatch, regions, lap_length=5400.0)
    result = cs.resolve_corner_for_distance(2025, 6, 5350.0)
    assert result["location_label"] == "Turn 19 → Turn 1 straight"


def test_resolve_inside_wrap_around_region(monkeypatch):
    regions = [
        cs.CornerRegion(corner_number=1, label_suffix="", entry_m=5300.0,
                        apex_m=20.0, exit_m=80.0, sign=1),
    ]
    _stub_regions(monkeypatch, regions, lap_length=5400.0)
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
        cs.CornerRegion(corner_number=4, label_suffix="a", entry_m=1100.0,
                        apex_m=1131.0, exit_m=1160.0, sign=1),
    ]
    _stub_regions(monkeypatch, regions)
    result = cs.resolve_corner_for_distance(2025, 6, 1131.0)
    assert result["corner_name"] == "Turn 4a"


def test_resolve_falls_back_to_nearest_mv_when_region_untagged(monkeypatch):
    regions = [
        cs.CornerRegion(corner_number=None, label_suffix="", entry_m=3000.0,
                        apex_m=3083.0, exit_m=3160.0, sign=1),
    ]
    mv = [{"number": 11, "letter": "", "distance_m": 3090.0}]
    _stub_regions(monkeypatch, regions, mv_corners=mv)
    result = cs.resolve_corner_for_distance(2025, 6, 3083.0)
    assert result["corner_number"] == 11
    assert result["corner_name"] == "Turn 11"


def test_resolve_rejects_non_finite_distance(monkeypatch):
    regions = [
        cs.CornerRegion(corner_number=1, label_suffix="", entry_m=100.0,
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
    regions = [
        cs.CornerRegion(corner_number=1, label_suffix="", entry_m=100.0,
                        apex_m=130.0, exit_m=160.0, sign=1),
    ]
    _stub_regions(monkeypatch, regions, lap_length=5400.0)
    result = cs.resolve_corner_for_distance(2025, 6, 5530.0)
    assert result["corner_number"] == 1


def test_resolve_straight_lookup_skips_wrap_around_as_prev(monkeypatch):
    regions = [
        cs.CornerRegion(corner_number=1, label_suffix="", entry_m=200.0,
                        apex_m=250.0, exit_m=320.0, sign=1),
        cs.CornerRegion(corner_number=5, label_suffix="", entry_m=5300.0,
                        apex_m=10.0, exit_m=80.0, sign=1),
    ]
    _stub_regions(monkeypatch, regions, lap_length=5400.0)
    result = cs.resolve_corner_for_distance(2025, 6, 500.0)
    assert result["location_label"] == "Turn 1 → Turn 5 straight"


# ── _split_merged_regions tests ──────────────────────────────────────


def _make_two_peak_kappa(spacing=2.0):
    """Two curvature peaks separated by a valley that stays above a typical exit threshold.

    Returns (s, kappa, lap_length_m) where the single region spans roughly [100, 300].
    Peak 1 apex ~150, peak 2 apex ~250, valley minimum ~200.
    """
    s = np.arange(0, 400, spacing)
    kappa = np.zeros_like(s)
    for i, si in enumerate(s):
        if 100 <= si < 200:
            kappa[i] = 0.03 * np.sin(np.pi * (si - 100) / 100)
        elif 200 <= si < 300:
            kappa[i] = 0.03 * np.sin(np.pi * (si - 200) / 100)
    # Valley at s=200 is 0 in the sin, but we want it above exit threshold
    # so _detect_regions sees one merged region. Raise the whole corner block.
    mask = (s >= 100) & (s < 300)
    kappa[mask] = kappa[mask] + 0.012
    return s, kappa, float(s[-1])


def test_split_merged_regions_separates_two_peaks():
    s, kappa, lap_length = _make_two_peak_kappa()
    # Detect with thresholds that produce one merged region
    regions = cs._detect_regions(s, kappa, kappa_enter=0.015, kappa_exit=0.01,
                                 lap_length_m=lap_length)
    assert len(regions) == 1, f"expected 1 merged region, got {len(regions)}"

    mv = [
        {"number": 1, "letter": "", "distance_m": 150.0},
        {"number": 2, "letter": "", "distance_m": 250.0},
    ]
    split = cs._split_merged_regions(regions, mv, s, kappa, lap_length)
    assert len(split) == 2
    # First sub-region should contain distance 150
    assert split[0][0] <= 150.0 <= split[0][2]
    # Second sub-region should contain distance 250
    assert split[1][0] <= 250.0 <= split[1][2]


def test_split_merged_regions_handles_three_apexes():
    s = np.arange(0, 600, 2.0)
    kappa = np.zeros_like(s)
    # Three peaks at ~150, ~250, ~350 with valleys staying above exit threshold
    for center in [150, 250, 350]:
        for i, si in enumerate(s):
            if abs(si - center) < 50:
                kappa[i] += 0.03 * np.cos(np.pi * (si - center) / 100)
    mask = (s >= 100) & (s < 400)
    kappa[mask] = kappa[mask] + 0.015

    regions = cs._detect_regions(s, kappa, kappa_enter=0.018, kappa_exit=0.01,
                                 lap_length_m=float(s[-1]))
    assert len(regions) == 1, f"expected 1 merged region, got {len(regions)}"

    mv = [
        {"number": 13, "letter": "", "distance_m": 150.0},
        {"number": 14, "letter": "", "distance_m": 250.0},
        {"number": 15, "letter": "", "distance_m": 350.0},
    ]
    split = cs._split_merged_regions(regions, mv, s, kappa, float(s[-1]))
    assert len(split) == 3
    assert split[0][0] <= 150.0 <= split[0][2]
    assert split[1][0] <= 250.0 <= split[1][2]
    assert split[2][0] <= 350.0 <= split[2][2]


def test_split_merged_regions_leaves_single_apex_region():
    s = np.arange(0, 400, 2.0)
    kappa = np.zeros_like(s)
    kappa[(s >= 100) & (s < 200)] = 0.03
    regions = cs._detect_regions(s, kappa, kappa_enter=0.02, kappa_exit=0.01,
                                 lap_length_m=float(s[-1]))
    assert len(regions) == 1

    mv = [{"number": 5, "letter": "", "distance_m": 150.0}]
    split = cs._split_merged_regions(regions, mv, s, kappa, float(s[-1]))
    assert len(split) == 1
    assert split[0] == regions[0]
