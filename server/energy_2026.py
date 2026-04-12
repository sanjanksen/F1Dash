ENERGY_2026_KNOWLEDGE = {
    "known_facts": [
        "The 2026 power-unit rules materially increase electrical contribution relative to the previous generation.",
        "The MGU-K output rises to roughly 350 kW, up from the previous 120 kW era.",
        "The 2026 rules target about 8.5 MJ per lap of energy recuperation under braking.",
        "The 2026 rules remove the MGU-H, so the core visible recovery story is much more braking-centric than heat-energy-centric.",
        "At high speed, deployment can taper away, so a car can stay at full throttle while no longer gaining speed at the same rate late on a straight.",
        "FastF1 does not expose direct ERS state of charge, deployment maps, or harvest mode selectors.",
    ],
    "terms": {
        "lift_and_coast": (
            "A driver lifts off the throttle before the braking point. In 2026 this can reduce energy demand, "
            "support braking recovery, and help keep the battery state healthier for later deployment."
        ),
        "clipping": (
            "A deployment taper where electric assistance stops adding the same acceleration late on a straight, "
            "so the car remains at full throttle but the speed trace flattens relative to a rival."
        ),
        "super_clipping": (
            "A stronger form of clipping expected to be more visible under the 2026 rules because the cars rely much more heavily "
            "on electrical deployment and that contribution can run out earlier on long full-throttle sections."
        ),
        "energy_harvesting": (
            "Recovering electrical energy, mainly through braking via the MGU-K in the 2026 era. A telemetry trace can suggest "
            "lift-and-coast-assisted recovery, but it cannot directly reveal the exact harvest strategy."
        ),
    },
    "interpretation_rules": [
        "If a driver is still at or near full throttle but loses speed relative to a rival late on a straight, that is consistent with clipping or earlier deployment taper.",
        "If a driver lifts earlier than the braking point without immediately applying the brake, that is consistent with lift-and-coast-assisted energy management.",
        "If the telemetry only shows a late-straight speed fade, you can explain clipping but you should not claim the exact harvest mode that caused it.",
        "If telemetry shows repeated early lifts before major braking zones, it is reasonable to say lift-and-coast-assisted harvesting is likely.",
        "If telemetry and speed-trap data disagree or are incomplete, keep the energy conclusion tentative.",
    ],
    "limitations": [
        "ERS deployment state, battery state of charge, and control maps are not directly available in FastF1 telemetry.",
        "Any statement about clipping, harvesting, or deployment is an inference from speed, throttle, brake, gear, RPM, and DRS patterns.",
        "FastF1 can show a pattern that is consistent with clipping, but it cannot prove whether the root cause was state of charge, calibration, or a chosen deployment map.",
        "FastF1 can suggest lift-and-coast-assisted harvesting, but it cannot tell you the exact harvest mode or control logic in use.",
    ],
    "answer_rules": [
        "Explain the mechanism once, then move on to the specific evidence. Do not repeat the same energy point in multiple sentences.",
        "Prefer concrete language such as sector, corner, distance marker, and speed differential.",
        "If energy is relevant, explain why clipping matters in 2026: higher electrical reliance means a car that runs out of deployment earlier will stop accelerating as hard late on the straight.",
        "Do not claim setup, battery state, or exact harvest type unless the evidence clearly supports that narrower claim.",
    ],
}


def get_energy_2026_knowledge() -> dict:
    return ENERGY_2026_KNOWLEDGE
