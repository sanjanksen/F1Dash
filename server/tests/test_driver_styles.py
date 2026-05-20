from driver_styles import DRIVER_STYLES, get_comparison_framing


def test_2026_rookies_have_stub_entries():
    for code in ("BEA", "LAW", "HAD", "BOR", "DOO", "COL"):
        entry = DRIVER_STYLES.get(code)
        assert entry is not None, f"missing stub for {code}"
        assert entry.get("confidence") == "low"
        assert entry.get("editorial") == "draft"
        assert entry.get("last_reviewed") == "2026-05-19"


def test_get_comparison_framing_flags_low_confidence_for_stub_pair():
    framing = get_comparison_framing("HAM", "BEA")
    assert framing["style_confidence"] == "low"


def test_get_comparison_framing_high_confidence_for_full_profiled_pair():
    framing = get_comparison_framing("HAM", "VER")
    assert framing["style_confidence"] == "high"


def test_existing_driver_profiles_preserved():
    for code in ("VER", "NOR", "LEC"):
        entry = DRIVER_STYLES.get(code)
        assert entry is not None, f"existing profile {code} disappeared"
        assert entry.get("confidence") != "low"
        assert entry.get("corner_philosophy")
