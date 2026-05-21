from editorial.relevance import (
    EDITORIAL_RELEVANT_MODES,
    should_retrieve_editorial,
)


def test_interpretive_modes_retrieve():
    """Interpretive modes ('why' questions) should retrieve editorial."""
    for mode in ("qualifying_battle", "race_pace_comparison",
                 "driver_comparison", "team_performance",
                 "team_circuit_fit"):
        assert should_retrieve_editorial(mode), f"{mode} should retrieve"


def test_descriptive_modes_skip():
    """Descriptive modes (telemetric / structural) should skip retrieval."""
    for mode in ("circuit_profile", "grip_comparison",
                 "sector_comparison", "corner_comparison"):
        assert not should_retrieve_editorial(mode), f"{mode} should skip"


def test_unknown_mode_skips():
    """Unknown modes default to skip — fail safe."""
    assert not should_retrieve_editorial("unknown_mode")
    assert not should_retrieve_editorial(None)
    assert not should_retrieve_editorial("")
