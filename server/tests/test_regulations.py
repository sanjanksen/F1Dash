import json


# ── B1: era registry ────────────────────────────────────────────────────────

def test_era_for_year_boundaries():
    from regulations import era_for_year, ERA_NEW_REGS_2026, ERA_GROUND_EFFECT
    assert era_for_year(2026) == ERA_NEW_REGS_2026
    assert era_for_year(2025) == ERA_GROUND_EFFECT
    assert era_for_year(2022) == ERA_GROUND_EFFECT
    # 2021 and earlier is a different era from the 2022-2025 ground-effect rules
    assert era_for_year(2021) != ERA_GROUND_EFFECT
    assert era_for_year(2021) != ERA_NEW_REGS_2026


def test_tool_applies_gates_2026_only_tools():
    from regulations import tool_applies
    assert tool_applies("analyze_active_aero_usage", 2026) is True
    assert tool_applies("analyze_active_aero_usage", 2024) is False
    assert tool_applies("analyze_override_usage", 2025) is False
    assert tool_applies("analyze_override_usage", 2026) is True
    # Non-era-gated tools always apply
    assert tool_applies("get_race_results", 2024) is True
    assert tool_applies("get_driver_race_story", 2019) is True


def test_era_knowledge_returns_era_specific_dict():
    from regulations import era_knowledge
    k2026 = era_knowledge(2026)
    k2024 = era_knowledge(2024)
    assert isinstance(k2026, dict) and isinstance(k2024, dict)
    assert k2026 != k2024, "2026 and 2024 must yield different rule knowledge"


# ── B2: ground-effect (2022-2025) energy knowledge ──────────────────────────

_NARRATIVE_KEYS = {"known_facts", "terms", "interpretation_rules", "limitations", "answer_rules"}


def test_energy_ground_effect_mirrors_narrative_shape():
    from energy_ground_effect import get_energy_ground_effect_knowledge
    g = get_energy_ground_effect_knowledge()
    assert _NARRATIVE_KEYS.issubset(set(g.keys()))


def test_energy_ground_effect_describes_pre_2026_power_unit():
    from energy_ground_effect import get_energy_ground_effect_knowledge
    blob = json.dumps(get_energy_ground_effect_knowledge()).lower()
    assert "mgu-h" in blob
    assert "drs" in blob
    assert "120" in blob  # 120 kW MGU-K limit


def test_energy_ground_effect_does_not_claim_2026_concepts():
    from energy_ground_effect import get_energy_ground_effect_knowledge
    blob = json.dumps(get_energy_ground_effect_knowledge()).lower()
    assert "override" not in blob, "override mode is a 2026 concept"
    assert "active aero" not in blob and "active-aero" not in blob
