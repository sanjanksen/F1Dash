"""Static energy-management knowledge for the 2022–2025 ground-effect era.

Mirrors the narrative shape of energy_2026 (known_facts / terms /
interpretation_rules / limitations / answer_rules) so the analysis prompt
builder can consume either era uniformly. This era's power unit is the
2014-generation V6 turbo-hybrid: MGU-K capped at 120 kW, MGU-H present, and DRS
(not active aero) as the straight-line overtaking aid. None of the 2026-only
concepts (override mode, active aero / Z-mode, ~350 kW deployment) apply here.
"""

ENERGY_GROUND_EFFECT_KNOWLEDGE = {
    "known_facts": [
        "The 2022–2025 cars use the 2014-generation V6 turbo-hybrid power unit: the MGU-K deployment is capped at 120 kW (about 161 hp) for roughly 33 seconds per lap.",
        "The MGU-H recovers energy from turbo heat and can redeploy it or feed the battery, so recovery is split between braking (MGU-K) and exhaust heat (MGU-H).",
        "Overtaking assistance comes from DRS (a stalled rear wing in designated zones), not from any driver-activated power boost.",
        "These are ground-effect cars (2022 aero rules): downforce is generated largely by the floor and venturi tunnels rather than by a high-rake philosophy.",
        "Electrical deployment is a smaller fraction of total power than under the 2026 rules, so a flat speed trace late on a straight is more often aero/drag-limited than deployment-limited.",
        "FastF1 does not expose direct ERS state of charge, deployment maps, or harvest mode selectors.",
    ],
    "terms": {
        "lift_and_coast": (
            "A driver lifts off the throttle before the braking point to save fuel, manage brake and tyre "
            "temperature, and support MGU-K harvesting in this era."
        ),
        "drs": (
            "Drag Reduction System — a driver-opened rear-wing flap, allowed only in designated DRS zones when "
            "within one second of the car ahead, giving a fixed straight-line speed advantage."
        ),
        "harvesting": (
            "Recovering electrical energy through the MGU-K under braking and the MGU-H from turbo heat. A "
            "telemetry trace can hint at lift-and-coast-assisted recovery but cannot reveal the exact strategy."
        ),
        "deployment": (
            "Releasing stored electrical energy via the MGU-K, capped at 120 kW. Because the cap is comparatively "
            "low, deployment tapers are less dramatic on the speed trace than in the 2026 era."
        ),
    },
    "interpretation_rules": [
        "If a driver gains a large chunk of straight-line speed only in a marked zone while close behind another car, that is consistent with DRS, not a power-unit boost.",
        "If a driver lifts earlier than the braking point without immediately braking, that is consistent with lift-and-coast fuel/energy management.",
        "A late-straight speed fade in this era is more often drag- or tow-related than deployment 'clipping'; keep deployment claims cautious because the 120 kW contribution is modest.",
        "Attribute straight-line and braking-zone behaviour only to mechanisms that exist in this era (DRS, the tow, MGU-K/MGU-H harvesting, fuel/tyre management); do not import later-generation power-unit concepts.",
        "If telemetry and speed-trap data disagree or are incomplete, keep the energy conclusion tentative.",
    ],
    "limitations": [
        "ERS deployment state, battery state of charge, MGU-H behaviour, and control maps are not directly available in FastF1 telemetry.",
        "Any statement about harvesting or deployment is an inference from speed, throttle, brake, gear, RPM, and DRS patterns.",
        "FastF1 cannot prove whether a straight-line gain came from DRS, the tow, or deployment without corroborating DRS-state data.",
    ],
    "answer_rules": [
        "When energy is relevant for 2022–2025, frame the overtaking aid as DRS and the deployment limit as 120 kW MGU-K; keep the explanation within this era's mechanisms.",
        "Prefer DRS, tow, and tyre/brake management explanations for straight-line and braking-zone differences before invoking deployment clipping.",
    ],
}


def get_energy_ground_effect_knowledge() -> dict:
    return ENERGY_GROUND_EFFECT_KNOWLEDGE
