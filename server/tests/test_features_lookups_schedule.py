import pytest

pytestmark = pytest.mark.usefixtures("reset_feature_registry")


def test_season_schedule_registered():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    assert "get_season_schedule" in FEATURE_REGISTRY


def test_season_schedule_passes_year_to_get_circuits():
    from unittest.mock import patch
    from features.lookups.schedule import SeasonScheduleFeature
    with patch("f1_data.get_circuits") as m:
        SeasonScheduleFeature().execute(year=2024)
    assert m.call_args.args == (2024,) or m.call_args.kwargs.get("year") == 2024


def test_season_schedule_year_in_schema():
    from features.lookups.schedule import SeasonScheduleFeature
    assert "year" in SeasonScheduleFeature.tool_schema["properties"]
