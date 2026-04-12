ENERGY_2026_KNOWLEDGE = {
    "known_facts": [
        "The 2026 regulations materially increase electric power contribution relative to previous power units.",
        "FastF1 does not expose direct ERS state of charge, harvest mode, or deployment maps.",
        "Lift-and-coast can sometimes be inferred from early throttle lift before a braking zone.",
        "Super-clipping can sometimes be inferred when a car loses end-of-straight acceleration while still at high throttle.",
    ],
    "terms": {
        "lift_and_coast": "A driver lifts off the throttle earlier than the braking point to save fuel, tyres, temperatures, or electrical energy.",
        "super_clipping": "A likely high-speed deployment taper where electrical assistance no longer sustains the same acceleration late on a straight.",
        "energy_harvesting": "Recovering electrical energy primarily under braking rather than measuring deployment directly from telemetry.",
    },
    "limitations": [
        "ERS deployment state, battery state of charge, and control maps are not directly available in FastF1 telemetry.",
        "Any statement about clipping, harvesting, or deployment is an inference from speed, throttle, brake, gear, RPM, and DRS patterns.",
        "These inferences are stronger in qualifying laps and cleaner telemetry windows than in traffic-heavy race laps.",
    ],
}


def get_energy_2026_knowledge() -> dict:
    return ENERGY_2026_KNOWLEDGE
