"""Regulation-era registry.

Maps a season to its regulation era and the era-appropriate energy/rules
knowledge, and gates 2026-only tools out of earlier seasons. Lets the analysis
prompt and tool dispatch stay era-correct across the supported 2018–2026 range
without scattering year checks through the codebase.
"""

ERA_HIGH_RAKE = "high_rake_2014_2021"        # 2014-gen PU, pre-ground-effect aero
ERA_GROUND_EFFECT = "ground_effect_2022_2025"  # 2022 ground-effect aero, same PU
ERA_NEW_REGS_2026 = "new_regs_2026"           # 2026 PU + active aero + override

# Tools that only make sense under the 2026 regulations.
_ERA_2026_ONLY_TOOLS = frozenset({
    "analyze_active_aero_usage",
    "analyze_override_usage",
})


def era_for_year(year: int) -> str:
    if year >= 2026:
        return ERA_NEW_REGS_2026
    if year >= 2022:
        return ERA_GROUND_EFFECT
    return ERA_HIGH_RAKE


def era_knowledge(year: int) -> dict:
    """Energy/rules knowledge dict for the given season's era. 2026 → the
    2026 power-unit knowledge; 2018–2025 → the DRS/MGU-H/120 kW knowledge."""
    if era_for_year(year) == ERA_NEW_REGS_2026:
        from energy_2026 import get_energy_2026_knowledge
        return get_energy_2026_knowledge()
    from energy_ground_effect import get_energy_ground_effect_knowledge
    return get_energy_ground_effect_knowledge()


def tool_applies(tool: str, year: int) -> bool:
    """False when `tool` is a 2026-only mechanism asked about an earlier season."""
    if tool in _ERA_2026_ONLY_TOOLS:
        return year >= 2026
    return True
