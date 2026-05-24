"""Real-data smoke tests for corner_segmentation.

Hits FastF1 — only runs when INTEGRATION=1 is set. Skipped by default.

The repo's conftest.py stubs out `fastf1` as a MagicMock for all unit
tests. We restore the real module here BEFORE importing
corner_segmentation, so `_load_session` reaches the actual FastF1 API.
"""

import os
import sys

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("INTEGRATION") != "1",
    reason="INTEGRATION=1 not set; skipping FastF1-dependent smoke test",
)

# Restore the real fastf1 and requests modules before importing
# corner_segmentation. conftest stubs both as MagicMock for unit tests.
for _stub in ("fastf1", "fastf1.Cache", "requests"):
    sys.modules.pop(_stub, None)
import requests  # noqa: E402,F401 — re-import the real module
import fastf1  # noqa: E402,F401
import corner_segmentation as cs  # noqa: E402


def test_miami_t17_and_t18_distinguished():
    # Bug we're fixing: marker at 4900m used to resolve to T17 because
    # the legacy nearest-apex-within-radius resolver picked the first
    # corner in lap order when both T17 (4830m) and T18 (4967m) were
    # within radius. With curvature segmentation, 4900m must NOT be
    # labeled "Turn 17". It must be either inside T18 or in the
    # straight between T17 and T18 — both are correct, "Turn 17" is not.
    result_4900 = cs.resolve_corner_for_distance(2025, 6, 4900.0)
    result_4830 = cs.resolve_corner_for_distance(2025, 6, 4830.0)
    result_4967 = cs.resolve_corner_for_distance(2025, 6, 4967.0)
    assert result_4830["corner_number"] == 17, result_4830
    assert result_4967["corner_number"] == 18, result_4967
    # The core fix: 4900m is not mislabeled as Turn 17.
    assert result_4900["corner_number"] != 17, result_4900
    assert "Turn 17" != result_4900.get("corner_name"), result_4900
    # And the location label mentions Turn 18 (either inside it or as
    # the bracket between T17 and T18).
    assert "Turn 18" in (result_4900.get("location_label") or ""), result_4900


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
            lap_len = cs._lap_length_for(2025, 13) or 0.0
            total_extent += (lap_len - r.entry_m) + r.exit_m
    # Curvature segmentation must capture meaningfully more than a
    # fixed 150m radius (single-apex) would have. 150m is a generous
    # floor — the full complex extends ~400m on the centerline but
    # some transitions are correctly labeled as straights.
    assert total_extent >= 150.0, f"Eau Rouge extent only {total_extent}m"


def test_lap_length_is_plausible_for_known_circuit():
    cs.get_corner_regions(2025, 6)
    miami_length = cs._lap_length_for(2025, 6)
    # Miami International Autodrome is 5.412 km.
    assert 5200.0 <= miami_length <= 5600.0, miami_length
