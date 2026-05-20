from energy_2026 import ENERGY_2026_KNOWLEDGE, get_energy_2026_knowledge


def test_known_facts_no_8_5_mj():
    for fact in ENERGY_2026_KNOWLEDGE["known_facts"]:
        assert "8.5" not in fact


def test_known_facts_mentions_7_mj():
    assert any("7 MJ" in fact for fact in ENERGY_2026_KNOWLEDGE["known_facts"])


def test_deployment_curve_shape():
    standard = ENERGY_2026_KNOWLEDGE["deployment_curve"]["standard"]
    assert len(standard) == 3
    for anchor in standard:
        assert "speed_kph" in anchor
        assert "power_kw" in anchor
    assert standard[0]["speed_kph"] == 290
    assert standard[0]["power_kw"] == 350
    assert standard[-1]["speed_kph"] == 355
    assert standard[-1]["power_kw"] == 0


def test_override_mode_curve():
    override = ENERGY_2026_KNOWLEDGE["override_mode"]
    curve = override["curve"]
    assert curve[0]["speed_kph"] == 337
    assert curve[0]["power_kw"] == 350
    assert curve[-1]["speed_kph"] == 355
    assert curve[-1]["power_kw"] == 0
    assert "1-second" in override["trigger"]


def test_zone_caps_values():
    zones = ENERGY_2026_KNOWLEDGE["zone_caps"]
    assert zones["key_acceleration_zones_kw"] == 350
    assert zones["other_zones_kw"] == 250


def test_battery_storage_values():
    battery = ENERGY_2026_KNOWLEDGE["battery_storage"]
    assert battery["per_lap_recovery_mj"] == 7
    assert battery["stored_energy_cap_mj"] == 4


def test_get_energy_2026_knowledge_existing_keys_present():
    data = get_energy_2026_knowledge()
    assert isinstance(data, dict)
    for key in ("known_facts", "terms", "interpretation_rules", "limitations", "answer_rules"):
        assert key in data
