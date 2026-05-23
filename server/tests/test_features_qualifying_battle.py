import pytest

pytestmark = pytest.mark.usefixtures("reset_feature_registry")


def _load_feat():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    return FEATURE_REGISTRY["analyze_qualifying_battle"]


def test_qualifying_battle_registered_after_discover():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    assert "analyze_qualifying_battle" in FEATURE_REGISTRY


def test_qualifying_battle_applies_to_pair_of_drivers():
    feat = _load_feat()
    assert "pair_of_drivers" in feat.applies_to


def test_qualifying_battle_make_widget_produces_typed_widget():
    feat = _load_feat()
    sample = {
        "driver_a": "NOR", "driver_b": "PIA",
        "faster_driver": "NOR", "overall_gap_s": 0.12,
        "event": "Imola", "compared_segment": "Q3",
    }
    w = feat.make_widget(sample)
    assert w["type"] == "qualifying_battle"
    assert w["driver_a"] == "NOR"
    assert w["driver_b"] == "PIA"
    assert w["faster_driver"] == "NOR"


def test_qualifying_battle_should_show_widget_respects_availability():
    feat = _load_feat()
    assert feat.should_show_widget({"driver_a": "NOR", "overall_gap_s": 0.15}) is True
    assert feat.should_show_widget({"available": False}) is False


def test_qualifying_battle_should_show_widget_meaningful_signal():
    feat = _load_feat()
    sample = {"available": True, "overall_gap_s": 0.12, "decisive_sector_gap_s": 0.08}
    assert feat.should_show_widget(sample) is True


def test_qualifying_battle_should_show_widget_suppresses_negligible():
    feat = _load_feat()
    # Overall gap below the 0.03 threshold
    sample = {"available": True, "overall_gap_s": 0.01, "decisive_sector_gap_s": 0.08}
    assert feat.should_show_widget(sample) is False


def test_qualifying_battle_declares_triggered_by_modes():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    feat = FEATURE_REGISTRY["analyze_qualifying_battle"]
    assert feat.triggered_by_modes == frozenset({"driver_comparison"})


def test_qualifying_battle_widget_handles_split_sector_lap():
    """When result.split_sector_lap is True and decisive_sector is None,
    the widget must NOT claim a decisive sector. split_sector_lap is passed
    through so the React component can render the appropriate prose."""
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    feat = FEATURE_REGISTRY["analyze_qualifying_battle"]

    result = {
        "available": True,
        "driver_a": "LEC", "driver_b": "NOR",
        "lap_time_a": "1:28.143", "lap_time_b": "1:28.183",
        "overall_gap_s": 0.040,
        "sector_comparison": {
            "sector1": {"gap_s": 0.05},
            "sector2": {"gap_s": 0.05},
            "sector3": {"gap_s": 0.04},
        },
        "decisive_sector": None,
        "decisive_sector_gap_s": None,
        "split_sector_lap": True,
    }
    widget = feat.make_widget(result)
    assert widget["type"] == "qualifying_battle"
    assert widget.get("decisive_sector") is None
    assert widget.get("split_sector_lap") is True
    assert widget.get("sector_comparison", {}).get("sector1", {}).get("gap_s") == 0.05


def test_qualifying_battle_widget_passes_through_decisive_sector_when_set():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    feat = FEATURE_REGISTRY["analyze_qualifying_battle"]

    result = {
        "available": True,
        "driver_a": "LEC", "driver_b": "NOR",
        "lap_time_a": "1:28.143", "lap_time_b": "1:28.183",
        "overall_gap_s": 0.040,
        "sector_comparison": {
            "sector1": {"gap_s": 0.131},
            "sector2": {"gap_s": -0.081},
            "sector3": {"gap_s": -0.010},
        },
        "decisive_sector": "Sector 1",
        "decisive_sector_gap_s": 0.131,
        "split_sector_lap": False,
    }
    widget = feat.make_widget(result)
    assert widget.get("decisive_sector") == "Sector 1"
    assert widget.get("split_sector_lap") is False
    assert widget.get("sector_comparison", {}).get("sector1", {}).get("gap_s") == 0.131


def test_qualifying_battle_widget_carries_time_gained_on_cause_explanations():
    """Each cause_explanations entry must carry time_gained_s, surfaced by
    the widget so the React component can render time as the headline."""
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    feat = FEATURE_REGISTRY["analyze_qualifying_battle"]

    result = {
        "available": True,
        "driver_a": "LEC", "driver_b": "NOR",
        "faster_driver": "LEC",
        "overall_gap_s": 0.040,
        "decisive_sector": "Sector 1",
        "decisive_sector_gap_s": 0.131,
        "split_sector_lap": False,
        "cause_explanations": [
            {
                "cause_type": "minimum_speed",
                "rank": 1,
                "distance_m": 1500,
                "delta_speed_kph": 13.0,
                "speed_a": 117.0,
                "speed_b": 104.0,
                "time_gained_s": 0.182,
                "gear_a": 3,
                "gear_b": 3,
                "sector": "sector1",
                "location_context": None,
                "explanation": "Mid-corner.",
            },
        ],
        "telemetry_summary": {
            "top_causes": [
                {
                    "cause_type": "minimum_speed",
                    "distance_m": 1500,
                    "speed_a": 117.0,
                    "speed_b": 104.0,
                    "delta_speed_kph": 13.0,
                    "time_gained_s": 0.182,
                },
            ],
        },
    }
    widget = feat.make_widget(result)
    causes = widget.get("cause_explanations") or []
    assert causes, "Expected cause_explanations to survive into the widget"
    assert causes[0].get("time_gained_s") == 0.182


def test_qualifying_battle_widget_passes_through_sector_reconciliation():
    """sector_reconciliation must survive into the widget so the JSX can
    render per-sector marker contribution vs sector gap with residuals."""
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    feat = FEATURE_REGISTRY["analyze_qualifying_battle"]

    result = {
        "available": True,
        "driver_a": "LEC", "driver_b": "NOR",
        "faster_driver": "LEC",
        "overall_gap_s": 0.040,
        "sector_reconciliation": {
            "Sector 1": {
                "sector_gap_s": 0.131,
                "marker_contribution_s": 0.105,
                "residual_s": 0.026,
                "markers": [{"distance_m": 1500, "time_gained_s": 0.105, "gainer_driver": "LEC"}],
            },
            "Sector 2": {
                "sector_gap_s": -0.081,
                "marker_contribution_s": -0.060,
                "residual_s": -0.021,
                "markers": [{"distance_m": 3200, "time_gained_s": -0.060, "gainer_driver": "NOR"}],
            },
            "Sector 3": {
                "sector_gap_s": -0.010,
                "marker_contribution_s": 0.0,
                "residual_s": -0.010,
                "markers": [],
            },
        },
    }
    widget = feat.make_widget(result)
    reconciliation = widget.get("sector_reconciliation") or {}
    assert "Sector 1" in reconciliation
    assert reconciliation["Sector 1"]["sector_gap_s"] == 0.131
    assert reconciliation["Sector 1"]["marker_contribution_s"] == 0.105
    assert reconciliation["Sector 2"]["markers"][0]["gainer_driver"] == "NOR"


def test_qualifying_battle_widget_carries_gainer_driver_on_each_marker():
    """When markers from BOTH drivers appear in cause_explanations, the
    gainer_driver field must propagate so the JSX can render each card
    with the correct attribution."""
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    feat = FEATURE_REGISTRY["analyze_qualifying_battle"]

    result = {
        "available": True,
        "driver_a": "LEC", "driver_b": "NOR",
        "faster_driver": "LEC",
        "overall_gap_s": 0.040,
        "cause_explanations": [
            {
                "cause_type": "minimum_speed",
                "rank": 1,
                "distance_m": 1500,
                "delta_speed_kph": 13.0,
                "time_gained_s": 0.105,
                "gainer_driver": "LEC",
                "sector": "Sector 1",
            },
            {
                "cause_type": "braking",
                "rank": 2,
                "distance_m": 3200,
                "delta_speed_kph": -10.0,
                "time_gained_s": -0.060,
                "gainer_driver": "NOR",
                "sector": "Sector 2",
            },
        ],
    }
    widget = feat.make_widget(result)
    causes = widget.get("cause_explanations") or []
    assert len(causes) == 2
    drivers = {c.get("gainer_driver") for c in causes}
    assert drivers == {"LEC", "NOR"}, (
        "Expected markers attributed to BOTH drivers (two-sided picker)"
    )
