"""
Curated circuit knowledge for F1 analysis.

Each profile captures:
- character: broad circuit type
- sector_1/2/3: corner types, which driving style wins, energy demand
- energy_profile: deployment demand, harvesting opportunity, clipping risk
- style_verdict: V-line vs U-line vs late-braker advantage and why
- tyre_challenge: what the circuit asks of tyres
- narrative: 2-3 sentence human-readable summary for LLM grounding

Used by the deterministic analysis pipeline and the agentic tool loop to
give the LLM contextual grounding before it interprets telemetry evidence.
"""

CALENDAR_YEAR = 2026


CIRCUIT_PROFILES: dict[str, dict] = {

    "bahrain": {
        "circuit_name": "Bahrain International Circuit",
        "character": "medium_speed_technical",
        "sector_1": {
            "type": "medium_speed_corners",
            "description": "T1-T6: medium-speed sequence, heavy braking at T1 and T4",
            "style_advantage": "late_braker",
            "energy_demand": "medium",
        },
        "sector_2": {
            "type": "slow_technical",
            "description": "T7-T10: slowest part of the lap — hairpins and chicanes favour rotation",
            "style_advantage": "v_line",
            "energy_demand": "low",
        },
        "sector_3": {
            "type": "high_speed_into_straight",
            "description": "T11-T15: flowing corners into main straight with DRS",
            "style_advantage": "u_line",
            "energy_demand": "high",
        },
        "energy_profile": {
            "deployment_demand": "high",
            "harvesting_opportunity": "medium",
            "clipping_risk": "medium",
            "key_straights": ["main_straight", "back_straight"],
            "notes": "Good harvesting at T1, T4, T10 braking zones. Both straights demand full deployment.",
        },
        "style_verdict": {
            "qualifier": "balanced",
            "explanation": "S1 and S2 hairpins favour late-aggressive brakers (V-line benefit); S3 flowing section slightly favours U-line minimum speed. Neither style dominant overall.",
        },
        "tyre_challenge": "High traction demand out of slow hairpin exits. Rear compound vulnerable over race distance.",
        "downforce_level": "high",
        "narrative": "Bahrain is balanced across corner types but punishes aggressive rear usage through its slow hairpins. The main and back straights both demand full deployment, making clipping a moderate risk. S2 hairpins favour late-brakers; the S3 flowing section rewards minimum speed.",
    },

    "saudi_arabia": {
        "circuit_name": "Jeddah Corniche Circuit",
        "character": "high_speed_street",
        "sector_1": {
            "type": "high_speed_walls",
            "description": "T1-T4: fast sweepers near the walls requiring confidence and commitment",
            "style_advantage": "u_line",
            "energy_demand": "medium",
        },
        "sector_2": {
            "type": "high_speed_sequence",
            "description": "T5-T17: relentless high-speed sequence, minimal braking, walls close — minimum speed dominant",
            "style_advantage": "u_line",
            "energy_demand": "high",
        },
        "sector_3": {
            "type": "stop_and_go_into_main",
            "description": "T18-T27: chicanes and slow corners leading to very long main straight",
            "style_advantage": "late_braker",
            "energy_demand": "very_high",
        },
        "energy_profile": {
            "deployment_demand": "very_high",
            "harvesting_opportunity": "low",
            "clipping_risk": "high",
            "key_straights": ["main_straight_approx_1km"],
            "notes": "Few slow corners means limited harvesting. Super-clipping risk is high on the main straight under 2026 rules.",
        },
        "style_verdict": {
            "qualifier": "u_line_favored",
            "explanation": "The sustained S2 high-speed sequence heavily favours minimum-speed U-line drivers. Carrying even 2 kph more through 12 consecutive corners compounds a decisive sector advantage.",
        },
        "tyre_challenge": "Low degradation but sustained lateral load through S2. Walls prevent track-limit extensions.",
        "downforce_level": "medium",
        "narrative": "Jeddah is among the fastest circuits on the calendar. S2 is where laps are made — U-line drivers carrying more minimum speed through the sweepers compound a large advantage. Limited braking zones mean poor harvesting; the long main straight makes super-clipping under 2026 rules a genuine risk.",
    },

    "australia": {
        "circuit_name": "Albert Park Circuit",
        "character": "medium_speed_technical",
        "sector_1": {
            "type": "medium_speed_flowing",
            "description": "T1-T6: medium-speed corners with multiple braking opportunities",
            "style_advantage": "balanced",
            "energy_demand": "medium",
        },
        "sector_2": {
            "type": "high_speed_sweepers",
            "description": "T7-T10: fastest part of the lap, minimum speed critical at T9/T10",
            "style_advantage": "u_line",
            "energy_demand": "high",
        },
        "sector_3": {
            "type": "stop_and_go",
            "description": "T11-T16: stop-and-go T13 and T15 chicanes into main straight",
            "style_advantage": "late_braker",
            "energy_demand": "high",
        },
        "energy_profile": {
            "deployment_demand": "medium_high",
            "harvesting_opportunity": "medium",
            "clipping_risk": "low",
            "key_straights": ["main_straight"],
        },
        "style_verdict": {
            "qualifier": "balanced",
            "explanation": "S2 high-speed section favours U-line; S3 chicane complex gives late-brakers a recovery. Broadly balanced — no single style dominant.",
        },
        "tyre_challenge": "Smooth surface means moderate degradation. Bumps at certain corners unsettle aggressive setups.",
        "downforce_level": "medium_high",
        "narrative": "Albert Park rewards an all-round setup. S2 high-speed flow is where U-line drivers gain; the S3 chicane complex is the late-brakers' recovery zone. Bumps at certain corners mean car stability matters alongside outright pace.",
    },

    "japan": {
        "circuit_name": "Suzuka International Racing Course",
        "character": "high_speed_technical",
        "sector_1": {
            "type": "high_speed_sweepers",
            "description": "T1-T9: S-curves, Dunlop, Degner — continuous medium-to-high-speed corners, 8 consecutive apexes",
            "style_advantage": "u_line",
            "energy_demand": "medium",
        },
        "sector_2": {
            "type": "mixed_casino_spoon",
            "description": "T10-T17: Casino triangle (slow), 130R (ultra-fast, near-flat), chicane — wide variety",
            "style_advantage": "balanced",
            "energy_demand": "medium",
        },
        "sector_3": {
            "type": "final_hairpin_into_main",
            "description": "T18-end: hairpin into the main straight — long full deployment zone",
            "style_advantage": "late_braker",
            "energy_demand": "very_high",
        },
        "energy_profile": {
            "deployment_demand": "high",
            "harvesting_opportunity": "medium",
            "clipping_risk": "medium_high",
            "key_straights": ["main_straight_approx_1100m"],
            "notes": "130R is near-flat, creating sustained deployment through S2. Main straight is one of the longest. Clipping is a real risk.",
        },
        "style_verdict": {
            "qualifier": "u_line_favored",
            "explanation": "S1 is the defining zone. Carrying 2-3 kph more minimum speed through 8 consecutive S-curve apexes compounds a massive sector advantage — the U-line structural benefit is nowhere stronger than here.",
        },
        "tyre_challenge": "Sustained high-speed load degrades rear tyres faster than most circuits, especially the right-rear through the clockwise S-curves.",
        "downforce_level": "high",
        "narrative": "Suzuka is the ultimate high-speed commitment test. The S1 S-curves are defining — a driver carrying even 2-3 kph more minimum speed through 8 consecutive corners compounds a decisive sector advantage. U-line drivers have a structural benefit here. The main straight creates a real clipping risk under 2026 rules, and 130R means deployment is active through most of S2.",
    },

    "china": {
        "circuit_name": "Shanghai International Circuit",
        "character": "mixed",
        "sector_1": {
            "type": "ultra_long_radius_curve",
            "description": "T1-T6: the unique ultra-long-radius T1-T2 entry sweeper, then back straight — minimum speed through T1-T2 arc is decisive",
            "style_advantage": "u_line",
            "energy_demand": "high",
        },
        "sector_2": {
            "type": "slow_technical",
            "description": "T7-T11: hairpin and slow chicane complex, traction-limited",
            "style_advantage": "v_line",
            "energy_demand": "low",
        },
        "sector_3": {
            "type": "flowing_into_main",
            "description": "T12-T16: medium-speed flowing section into main straight",
            "style_advantage": "u_line",
            "energy_demand": "high",
        },
        "energy_profile": {
            "deployment_demand": "high",
            "harvesting_opportunity": "medium",
            "clipping_risk": "medium",
            "key_straights": ["back_straight", "main_straight"],
        },
        "style_verdict": {
            "qualifier": "balanced",
            "explanation": "T1-T2 ultra-long-radius and S3 flow favour U-line; the S2 hairpin complex gives late-brakers a clear advantage back. Net result is balanced.",
        },
        "tyre_challenge": "High rear wear through the long T1-T2 radius. Front wear in S2 heavy braking zones.",
        "downforce_level": "medium_high",
        "narrative": "Shanghai's T1-T2 ultra-radius entry defines the lap — carrying speed through this arc rewards smooth high-minimum-speed drivers massively. The S2 hairpin is the main recovery zone for aggressive late-brakers. Both the back and main straight demand full deployment.",
    },

    "miami": {
        "circuit_name": "Miami International Autodrome",
        "character": "street_like_mixed",
        "sector_1": {
            "type": "medium_speed_hairpin",
            "description": "T1-T6: medium-speed section, T1 hard braking, T6 slow hairpin",
            "style_advantage": "v_line",
            "energy_demand": "medium",
        },
        "sector_2": {
            "type": "back_straight_heavy_braking",
            "description": "T7-T11: long back straight into heavy braking zone, then medium-speed flow",
            "style_advantage": "late_braker",
            "energy_demand": "very_high",
        },
        "sector_3": {
            "type": "marina_stop_and_go",
            "description": "T12-T19: marina section with multiple slow corners and traction zones",
            "style_advantage": "v_line",
            "energy_demand": "medium",
        },
        "energy_profile": {
            "deployment_demand": "high",
            "harvesting_opportunity": "medium",
            "clipping_risk": "medium",
            "key_straights": ["back_straight"],
        },
        "style_verdict": {
            "qualifier": "v_line_slight_advantage",
            "explanation": "Multiple slow corners in S1 and the marina section reward late brakers and rotation. The back straight is the only major deployment zone.",
        },
        "tyre_challenge": "High abrasion from repeated aggressive traction zones. Rear wear heavy.",
        "downforce_level": "medium_high",
        "narrative": "Miami has a stop-and-go character. V-line late-brakers find multiple gain opportunities in S1 and the marina section. The back straight is the key deployment zone — drivers who nail the T11 hairpin exit get maximum DRS range. Marina section slow corners provide good battery harvesting.",
    },

    "emilia_romagna": {
        "circuit_name": "Autodromo Enzo e Dino Ferrari",
        "character": "technical_narrow",
        "sector_1": {
            "type": "braking_heavy",
            "description": "T1-T6: Tamburello chicane, Villeneuve, Tosa hairpin — braking-heavy sequence",
            "style_advantage": "late_braker",
            "energy_demand": "medium",
        },
        "sector_2": {
            "type": "high_speed_flowing",
            "description": "T7-T12: Piratella, Acque Minerali — flowing medium-high-speed section",
            "style_advantage": "u_line",
            "energy_demand": "medium",
        },
        "sector_3": {
            "type": "chicane_into_main",
            "description": "T13-T19: Variante Alta, Rivazza, into main straight",
            "style_advantage": "balanced",
            "energy_demand": "high",
        },
        "energy_profile": {
            "deployment_demand": "medium",
            "harvesting_opportunity": "high",
            "clipping_risk": "low",
            "key_straights": ["main_straight"],
            "notes": "Multiple heavy braking zones generate excellent harvesting. Battery stays healthy — clipping unlikely.",
        },
        "style_verdict": {
            "qualifier": "balanced",
            "explanation": "S1 braking-heavy zones favour late-brakers; S2 high-speed flow favours U-line. Good harvesting from multiple braking zones keeps battery healthy throughout.",
        },
        "tyre_challenge": "Narrow circuit limits overtaking — qualifying lap is critical. Mixed surface abrasion.",
        "downforce_level": "high",
        "narrative": "Imola rewards precision over aggression. S1 braking sequences favour late commitment; S2 rewards smooth high-speed discipline. Multiple heavy braking zones enable excellent energy harvesting — clipping is essentially off the table here. The narrow circuit makes track position critical.",
    },

    "monaco": {
        "circuit_name": "Circuit de Monaco",
        "character": "slow_street",
        "sector_1": {
            "type": "slow_technical",
            "description": "T1-T6: Casino square, Mirabeau, Grand Hotel hairpin — very low speed, walls everywhere",
            "style_advantage": "late_braker",
            "energy_demand": "low",
        },
        "sector_2": {
            "type": "tunnel_and_chicane",
            "description": "T7-T11: tunnel (only significant speed zone), chicane, Tabac",
            "style_advantage": "u_line",
            "energy_demand": "medium",
        },
        "sector_3": {
            "type": "slow_technical",
            "description": "T12-T19: Swimming pool complex, Rascasse, Anthony Noghes — all slow",
            "style_advantage": "v_line",
            "energy_demand": "low",
        },
        "energy_profile": {
            "deployment_demand": "low",
            "harvesting_opportunity": "very_high",
            "clipping_risk": "none",
            "key_straights": ["tunnel_only"],
            "notes": "Battery perpetually full due to extreme braking frequency. Under 2026 rules this means maximum deployment available on every brief acceleration zone — a unique advantage over previous-gen cars.",
        },
        "style_verdict": {
            "qualifier": "late_braker_advantage",
            "explanation": "Monaco is dominated by braking zones and slow-corner traction. U-line minimum speed is irrelevant at 50-70 kph. Car rotation and precision in braking zones determine everything.",
        },
        "tyre_challenge": "No thermal degradation — mechanical wear from constant low-speed scrubbing. Strategy driven by safety car probability.",
        "downforce_level": "very_high",
        "narrative": "Monaco is the outlier. Energy is never a constraint — the battery stays full, giving maximum deployment on every brief acceleration zone. Late brakers dominate every sector. The race is almost entirely determined by track position, safety car timing, and the absence of mistakes.",
    },

    "canada": {
        "circuit_name": "Circuit Gilles Villeneuve",
        "character": "stop_and_go",
        "sector_1": {
            "type": "medium_into_hairpin",
            "description": "T1-T6: medium-speed opening, first hairpin — significant braking opportunity",
            "style_advantage": "late_braker",
            "energy_demand": "medium",
        },
        "sector_2": {
            "type": "island_hairpins",
            "description": "T7-T13: back straight, hairpin, casino section — classic stop-and-go",
            "style_advantage": "v_line",
            "energy_demand": "very_high",
        },
        "sector_3": {
            "type": "wall_of_champions_into_main",
            "description": "T13-T14: wall of champions chicane into main straight — very heavy braking, defining lap moment",
            "style_advantage": "late_braker",
            "energy_demand": "very_high",
        },
        "energy_profile": {
            "deployment_demand": "very_high",
            "harvesting_opportunity": "very_high",
            "clipping_risk": "high",
            "key_straights": ["back_straight", "main_straight"],
            "notes": "Two very long straights with multiple hard braking zones. Plenty of harvesting but also very high deployment demand. Super-clipping is a genuine risk on both straights under 2026 rules.",
        },
        "style_verdict": {
            "qualifier": "v_line_late_braker_favored",
            "explanation": "Montreal is pure stop-and-go. Late-brakers and V-line drivers gain at every hairpin and chicane. Minimum speed in corners is irrelevant — it's all about braking depth and traction.",
        },
        "tyre_challenge": "High brake energy loads. Front tyres exposed to heavy braking loads repeatedly.",
        "downforce_level": "low",
        "narrative": "Canada is one of the few circuits where V-line late-brakers have an unambiguous structural advantage — every sector rewards hard braking. Both back and main straights are among the calendar's longest, creating high super-clipping risk under 2026 rules. Drivers with better deployment management or lower drag will be fastest on the straights.",
    },

    "spain": {
        "circuit_name": "Circuit de Barcelona-Catalunya",
        "character": "mixed_high_downforce",
        "sector_1": {
            "type": "medium_speed_technical",
            "description": "T1-T5: T1 hard braking, T3 long-radius right — diverse demands, balanced",
            "style_advantage": "balanced",
            "energy_demand": "medium",
        },
        "sector_2": {
            "type": "high_speed_into_heavy_braking",
            "description": "T6-T10: Campsa corner, back straight, heavy braking at T10",
            "style_advantage": "u_line",
            "energy_demand": "high",
        },
        "sector_3": {
            "type": "slow_into_main",
            "description": "T11-T16: slow chicane, hairpin, into main straight",
            "style_advantage": "v_line",
            "energy_demand": "high",
        },
        "energy_profile": {
            "deployment_demand": "high",
            "harvesting_opportunity": "medium",
            "clipping_risk": "medium",
            "key_straights": ["back_straight", "main_straight"],
        },
        "style_verdict": {
            "qualifier": "balanced",
            "explanation": "S2 high-speed flowing favours U-line; S3 slow corners give V-line a chance. Barcelona is the FIA reference circuit precisely because it is perfectly balanced.",
        },
        "tyre_challenge": "Historically the hardest circuit on rear tyres due to sustained lateral load through T3 and S2. Heat cycle management is critical over race distance.",
        "downforce_level": "high",
        "narrative": "Barcelona is the definitive balanced reference circuit. S2 flowing section rewards U-line minimum speed; S3 slow technical section rewards late-brakers. Rear tyre degradation is historically severe — driver style through T3 and S2 is a key differentiator over race distance.",
    },

    "austria": {
        "circuit_name": "Red Bull Ring",
        "character": "power_short",
        "sector_1": {
            "type": "uphill_into_hairpin",
            "description": "T1-T3: uphill run, T1 hard braking hairpin, T2 fast right, T3 left",
            "style_advantage": "late_braker",
            "energy_demand": "medium",
        },
        "sector_2": {
            "type": "fast_downhill",
            "description": "T4-T6: fast downhill flow, T4 left-hander, T5 flat, T6 fast right",
            "style_advantage": "u_line",
            "energy_demand": "high",
        },
        "sector_3": {
            "type": "final_chicane_into_main",
            "description": "T7-T10: final chicane into very long main straight — heavy braking at T9",
            "style_advantage": "late_braker",
            "energy_demand": "very_high",
        },
        "energy_profile": {
            "deployment_demand": "very_high",
            "harvesting_opportunity": "high",
            "clipping_risk": "high",
            "key_straights": ["main_straight_over_1km"],
            "notes": "Very long main straight plus altitude effect. Super-clipping is among the highest-probability scenarios on the calendar under 2026 rules.",
        },
        "style_verdict": {
            "qualifier": "late_braker_slight_advantage",
            "explanation": "T1 and T9 are the two defining braking zones. S2 downhill section gives U-line a brief advantage but the hairpins dominate lap time.",
        },
        "tyre_challenge": "Low abrasion but very high energy input at T1. Front-left particularly exposed under repeated hard braking.",
        "downforce_level": "medium_low",
        "narrative": "Austria is deceptively demanding for a short circuit. The main straight is very long — super-clipping under 2026 rules is among the highest-probability scenarios on the calendar. T1 and T9 are the decisive braking zones. The short lap means small sector gaps accumulate rapidly over race distance.",
    },

    "britain": {
        "circuit_name": "Silverstone Circuit",
        "character": "high_speed",
        "sector_1": {
            "type": "high_speed_sweepers",
            "description": "T1-T7: Copse, Maggotts, Becketts, Chapel — continuous high-speed commitment, 5 apex sequence",
            "style_advantage": "u_line",
            "energy_demand": "medium",
        },
        "sector_2": {
            "type": "medium_speed_technical",
            "description": "T8-T14: Stowe, Vale, Club — medium-speed braking zones",
            "style_advantage": "late_braker",
            "energy_demand": "medium",
        },
        "sector_3": {
            "type": "high_speed_into_straight",
            "description": "T15-T18: Abbey, Farm, Village — fast sequence into the Hangar straight",
            "style_advantage": "u_line",
            "energy_demand": "high",
        },
        "energy_profile": {
            "deployment_demand": "high",
            "harvesting_opportunity": "medium",
            "clipping_risk": "medium",
            "key_straights": ["hangar_straight", "wellington_straight"],
        },
        "style_verdict": {
            "qualifier": "u_line_favored",
            "explanation": "Maggotts-Becketts-Chapel is one of the most demanding high-speed sequences on the calendar. A driver carrying more minimum speed through all five apexes gains massively — U-line wins S1 definitively, and S3 reinforces that.",
        },
        "tyre_challenge": "Rear-heavy wear from sustained lateral load through S1 high-speed sweepers. Historically very rear-demanding — particularly right-rear.",
        "downforce_level": "high",
        "narrative": "Silverstone is defined by Maggotts-Becketts-Chapel. It is the ultimate test of high-speed minimum speed — U-line drivers who carry more cornering speed through all five apexes compound a sector-defining advantage. A driver who loses in S1 has no comparable zone to fully recover. The Hangar straight provides a moderate deployment zone.",
    },

    "belgium": {
        "circuit_name": "Circuit de Spa-Francorchamps",
        "character": "power_high_speed",
        "sector_1": {
            "type": "high_speed_commitment",
            "description": "T1-T8: Eau Rouge/Raidillon flat-out, into Kemmel straight — commitment defines S1",
            "style_advantage": "u_line",
            "energy_demand": "high",
        },
        "sector_2": {
            "type": "medium_speed_technical",
            "description": "T9-T15: Pouhon (decisive fast corner), Fagnes — minimum speed at Pouhon is critical",
            "style_advantage": "u_line",
            "energy_demand": "medium",
        },
        "sector_3": {
            "type": "bus_stop_into_main",
            "description": "T16-T19: Bus Stop chicane into main straight — heavy braking",
            "style_advantage": "late_braker",
            "energy_demand": "very_high",
        },
        "energy_profile": {
            "deployment_demand": "very_high",
            "harvesting_opportunity": "medium",
            "clipping_risk": "very_high",
            "key_straights": ["kemmel_straight_over_700m", "main_straight"],
            "notes": "Kemmel is one of the longest full-throttle straights in F1. Super-clipping is almost certain here for higher-drag setups under 2026 rules.",
        },
        "style_verdict": {
            "qualifier": "u_line_favored",
            "explanation": "Eau Rouge commitment and Pouhon high-speed corner both reward minimum speed. The Bus Stop gives late-brakers a small recovery but U-line dominates two of the three sectors.",
        },
        "tyre_challenge": "Rear wear from Eau Rouge/Raidillon high-speed loading. Front wear from Bus Stop heavy braking.",
        "downforce_level": "low_medium",
        "narrative": "Spa demands high-speed commitment through Eau Rouge and Pouhon, rewarding U-line drivers throughout S1 and S2. Kemmel straight is near-certain super-clipping territory under 2026 rules — cars will have exhausted deployment before the Bus Stop. Drivers with better energy management will gain significant straight-line distance on Kemmel.",
    },

    "hungary": {
        "circuit_name": "Hungaroring",
        "character": "slow_technical",
        "sector_1": {
            "type": "slow_medium_braking",
            "description": "T1-T4: T1 heavy braking, T2 long-radius curve, T3/T4 sequence",
            "style_advantage": "late_braker",
            "energy_demand": "medium",
        },
        "sector_2": {
            "type": "slow_hairpins",
            "description": "T5-T9: multiple slow turns, T5-T6 hairpin complex — maximum rotation demand",
            "style_advantage": "v_line",
            "energy_demand": "low",
        },
        "sector_3": {
            "type": "medium_into_main",
            "description": "T10-T14: medium-speed flow into main straight",
            "style_advantage": "balanced",
            "energy_demand": "high",
        },
        "energy_profile": {
            "deployment_demand": "medium",
            "harvesting_opportunity": "very_high",
            "clipping_risk": "none",
            "key_straights": ["main_straight"],
            "notes": "Extensive slow-corner braking keeps the battery perpetually well-charged. No clipping risk at all.",
        },
        "style_verdict": {
            "qualifier": "v_line_late_braker_favored",
            "explanation": "Hungaroring is dominated by slow corners and hairpins. V-line late-brakers gain on every significant corner. High-speed minimum speed is irrelevant — there are no sustained fast sections.",
        },
        "tyre_challenge": "High rear wear from constant slow-corner traction demands. Very physically demanding on tyres despite the smooth surface.",
        "downforce_level": "very_high",
        "narrative": "Hungary is the anti-Silverstone — every significant gain comes from braking zones and slow-corner rotation. V-line late-brakers dominate. Extensive slow-corner braking keeps the battery full, so energy management is a non-factor. The circuit is particularly demanding on rear tyres through repeated traction zones.",
    },

    "netherlands": {
        "circuit_name": "Circuit Zandvoort",
        "character": "technical_banked",
        "sector_1": {
            "type": "high_speed_banked",
            "description": "T1-T5: T1 hard braking, banked T3 Hugenholtz — banking amplifies minimum-speed advantage",
            "style_advantage": "u_line",
            "energy_demand": "medium",
        },
        "sector_2": {
            "type": "high_speed_dunes",
            "description": "T6-T11: Scheivlak, Hunzerug — fast flowing section through the dunes",
            "style_advantage": "u_line",
            "energy_demand": "medium",
        },
        "sector_3": {
            "type": "banked_final_into_straight",
            "description": "T12-T14: banked Arie Luyendijk corner into main straight — unique banking",
            "style_advantage": "u_line",
            "energy_demand": "high",
        },
        "energy_profile": {
            "deployment_demand": "medium_high",
            "harvesting_opportunity": "medium",
            "clipping_risk": "low",
            "key_straights": ["main_straight_short"],
            "notes": "No long straights — clipping risk is minimal. Banked corners allow more speed with less lateral force, compounding minimum-speed advantage.",
        },
        "style_verdict": {
            "qualifier": "u_line_strongly_favored",
            "explanation": "Banking amplifies the minimum-speed advantage at T3 and T14 — these unique banked corners allow cars to carry substantially more speed with less risk. U-line drivers benefit structurally throughout all three sectors.",
        },
        "tyre_challenge": "Unique banking creates unusual load patterns. High sustained lateral acceleration throughout. Rear tyres particularly loaded.",
        "downforce_level": "high",
        "narrative": "Zandvoort's banked corners are unique on the F1 calendar. Banking increases corner speed while reducing slip angle, making U-line minimum-speed driving particularly dominant. No long straights means energy management is benign. One of the circuits where U-line driving philosophy most clearly and comprehensively wins.",
    },

    "italy": {
        "circuit_name": "Autodromo Nazionale Monza",
        "character": "power_low_downforce",
        "sector_1": {
            "type": "chicane_into_back_straight",
            "description": "T1-T6: Variante del Rettifilo chicane, Curva Grande, Variante della Roggia — all about straight-line exit speed",
            "style_advantage": "late_braker",
            "energy_demand": "very_high",
        },
        "sector_2": {
            "type": "lesmo_into_main_back_section",
            "description": "T7-T9: Lesmo 1 and 2, Serraglio — two medium-speed corners, minimum exit speed feeds long straight",
            "style_advantage": "u_line",
            "energy_demand": "very_high",
        },
        "sector_3": {
            "type": "parabolica_into_main",
            "description": "T10-T11: Ascari chicane, Parabolica — Parabolica minimum speed feeds directly onto 1.3km main straight",
            "style_advantage": "u_line",
            "energy_demand": "very_high",
        },
        "energy_profile": {
            "deployment_demand": "maximum",
            "harvesting_opportunity": "medium",
            "clipping_risk": "maximum",
            "key_straights": ["main_straight_1300m", "back_straight"],
            "notes": "Monza has the longest straights in F1 (~1.3km main straight). Super-clipping is essentially certain under 2026 rules. Parabolica minimum speed is the single most consequential corner on the calendar.",
        },
        "style_verdict": {
            "qualifier": "power_and_minimum_speed",
            "explanation": "Parabolica defines the lap — minimum speed through T11 feeds directly onto the longest straight in F1. U-line high minimum speed advantage is maximally amplified here. Carry 2 kph more and it pays over 1300m.",
        },
        "tyre_challenge": "Extremely low mechanical wear due to very few corners. Thermal loads from high-speed running but minimal degradation.",
        "downforce_level": "very_low",
        "narrative": "Monza is the pure power circuit. The main straight at ~1300m is the longest in F1 — super-clipping under 2026 rules is essentially certain. Parabolica minimum speed is the most consequential corner on the calendar: carry 2 kph more out of T11 and it pays over the full straight length. Energy management is the primary performance differentiator here.",
    },

    "azerbaijan": {
        "circuit_name": "Baku City Circuit",
        "character": "stop_and_go_street",
        "sector_1": {
            "type": "castle_section_slow",
            "description": "T1-T8: old city section — extremely tight, narrow, slowest street section in F1",
            "style_advantage": "v_line",
            "energy_demand": "low",
        },
        "sector_2": {
            "type": "medium_speed_seafront",
            "description": "T9-T16: flowing medium-speed seafront section",
            "style_advantage": "balanced",
            "energy_demand": "medium",
        },
        "sector_3": {
            "type": "final_corner_into_2200m_straight",
            "description": "T17-T20: final tight corners onto the Turn 16 to Turn 1 start/finish main straight (~2.2 km) — T20 exit speed is the single most consequential moment of the lap",
            "style_advantage": "u_line",
            "energy_demand": "maximum",
        },
        "energy_profile": {
            "deployment_demand": "maximum",
            "harvesting_opportunity": "high",
            "clipping_risk": "maximum",
            "key_straights": ["main_straight_2200m"],
            "notes": "The Turn 16 to Turn 1 start/finish main straight at ~2.2 km is the longest single straight in F1 (not the total circuit length). Under 2026 rules cars will almost certainly exhaust deployment hundreds of meters before the braking zone — creating the most visible super-clipping on the calendar.",
        },
        "style_verdict": {
            "qualifier": "circuit_specific_by_sector",
            "explanation": "S1 castle section rewards V-line rotation in ultra-tight corners; T20 exit speed onto the straight rewards U-line minimum speed for maximum velocity down the ~2.2 km Turn 16 to Turn 1 main straight. Dramatically different demands by sector.",
        },
        "tyre_challenge": "Very low degradation on smooth tarmac. Strategy heavily influenced by safety car probability.",
        "downforce_level": "low",
        "narrative": "Baku is the super-clipping circuit par excellence. The main straight — the Turn 16 to Turn 1 start/finish straight running roughly 2.2 km — is the longest single straight in F1 (this figure refers to the straight, not total circuit length). Under 2026 rules cars will almost certainly exhaust deployment before the braking zone. T20 exit speed is the most consequential moment on the lap: a driver carrying 3 kph more out of Turn 20 has a structural straight-line advantage all the way to the Turn 1 braking zone.",
    },

    "singapore": {
        "circuit_name": "Marina Bay Street Circuit",
        "character": "slow_technical_street",
        "sector_1": {
            "type": "slow_narrow_street",
            "description": "T1-T9: slow narrow sections, multiple tight corners — very similar to Monaco",
            "style_advantage": "v_line",
            "energy_demand": "low",
        },
        "sector_2": {
            "type": "medium_slow_mixed",
            "description": "T10-T19: marina section, slightly faster but still bumpy and narrow",
            "style_advantage": "balanced",
            "energy_demand": "medium",
        },
        "sector_3": {
            "type": "slow_final_into_short_straight",
            "description": "T20-T23: final section with heavy braking at T20, into main straight",
            "style_advantage": "late_braker",
            "energy_demand": "medium",
        },
        "energy_profile": {
            "deployment_demand": "medium",
            "harvesting_opportunity": "very_high",
            "clipping_risk": "none",
            "key_straights": ["main_straight_short"],
            "notes": "Many slow corners mean exceptional harvesting — battery is always full. Identical energy profile to Monaco.",
        },
        "style_verdict": {
            "qualifier": "v_line_late_braker_favored",
            "explanation": "Singapore is Monaco-adjacent. Slow corners everywhere, no sustained high-speed sections. V-line late-brakers gain on every significant corner. Track position and safety car timing dominate outcomes.",
        },
        "tyre_challenge": "High rear wear from repeated traction zones. Bumpy surface creates additional suspension and tyre load. Night race heat is unique.",
        "downforce_level": "very_high",
        "narrative": "Singapore is the other pole of the calendar from Monza — slow, bumpy, track-position dominant. V-line late-brakers find gains everywhere. Energy management is irrelevant; the battery stays full. Safety car probability is very high, making strategy luck a significant factor alongside pure pace.",
    },

    "united_states": {
        "circuit_name": "Circuit of the Americas",
        "character": "mixed_high_downforce",
        "sector_1": {
            "type": "high_speed_technical_complex",
            "description": "T1-T11: T1 hard braking, then T2-T9 high-speed S-curve sequence, T11 hairpin — the S-curves are the defining zone",
            "style_advantage": "u_line",
            "energy_demand": "medium",
        },
        "sector_2": {
            "type": "medium_speed_undulating",
            "description": "T12-T15: back section with medium-speed undulating turns",
            "style_advantage": "balanced",
            "energy_demand": "medium",
        },
        "sector_3": {
            "type": "stadium_into_main",
            "description": "T16-T20: stadium section T16-T18 complex, into main straight",
            "style_advantage": "v_line",
            "energy_demand": "high",
        },
        "energy_profile": {
            "deployment_demand": "high",
            "harvesting_opportunity": "medium",
            "clipping_risk": "medium",
            "key_straights": ["main_straight"],
        },
        "style_verdict": {
            "qualifier": "u_line_slight_advantage",
            "explanation": "T2-T9 S-curve sequence is comparable to Silverstone's Maggotts-Becketts — U-line minimum speed through 8 consecutive corners compounds a major S1 advantage. Stadium section gives V-line some recovery in S3.",
        },
        "tyre_challenge": "Bumpy surface particularly at the S-curves creates additional tyre stress. Rear degradation is high.",
        "downforce_level": "high",
        "narrative": "COTA's T2-T9 sequence is the circuit's defining zone — a mini-Maggotts-Becketts where U-line drivers carrying minimum speed through 8 consecutive corners gain heavily. The bumpy surface stresses tyres more than the pure lap time suggests. Stadium section in S3 gives some recovery for late-brakers.",
    },

    "mexico": {
        "circuit_name": "Autodromo Hermanos Rodriguez",
        "character": "altitude_power",
        "sector_1": {
            "type": "stadium_hairpin",
            "description": "T1-T5: stadium hairpin complex, T1-T2 first corner — hard braking at altitude",
            "style_advantage": "late_braker",
            "energy_demand": "very_high",
        },
        "sector_2": {
            "type": "very_long_curved_straight",
            "description": "T6-T12: Recta Principal — very long curved back straight at altitude, sustained full deployment",
            "style_advantage": "u_line",
            "energy_demand": "maximum",
        },
        "sector_3": {
            "type": "esses_into_main",
            "description": "T13-T17: Esses section, slow hairpin, into main straight",
            "style_advantage": "v_line",
            "energy_demand": "high",
        },
        "energy_profile": {
            "deployment_demand": "maximum",
            "harvesting_opportunity": "medium",
            "clipping_risk": "maximum",
            "key_straights": ["recta_principal_very_long", "main_straight"],
            "notes": "Altitude of 2200m reduces air density — ICE produces less power but MGU-K contribution is relatively MORE significant. Super-clipping is essentially certain. The altitude-electrical interaction makes this the most energy-analytical circuit on the calendar.",
        },
        "style_verdict": {
            "qualifier": "energy_management_dominant",
            "explanation": "Altitude makes the electric component relatively more powerful than the ICE. The Recta Principal is so long that deployment depletes early — managing when and how hard you deploy defines straight-line pace more here than anywhere else.",
        },
        "tyre_challenge": "Rear blistering common from high-speed cornering at altitude. Lower air density reduces cooling.",
        "downforce_level": "low",
        "narrative": "Mexico City is the 2026 energy management circuit. Altitude reduces ICE power but amplifies the relative importance of the MGU-K — and makes it more likely to deplete. The Recta Principal is very long and curved; super-clipping happens earlier and more dramatically than at any other circuit. A driver who manages deployment to still have power near the braking zone has a decisive straight-line weapon.",
    },

    "brazil": {
        "circuit_name": "Autodromo Jose Carlos Pace",
        "character": "mixed_undulating",
        "sector_1": {
            "type": "downhill_senna_s",
            "description": "T1-T4: Senna S high-speed chicane entered downhill at very high speed, T3 heavy braking",
            "style_advantage": "u_line",
            "energy_demand": "medium",
        },
        "sector_2": {
            "type": "technical_undulating",
            "description": "T5-T11: Descida do Lago, Ferradura hairpin — uphill and downhill technical",
            "style_advantage": "balanced",
            "energy_demand": "medium",
        },
        "sector_3": {
            "type": "juncao_into_main",
            "description": "T12-T15: Junção, fast final sector into main straight",
            "style_advantage": "u_line",
            "energy_demand": "high",
        },
        "energy_profile": {
            "deployment_demand": "high",
            "harvesting_opportunity": "medium",
            "clipping_risk": "medium",
            "key_straights": ["main_straight"],
        },
        "style_verdict": {
            "qualifier": "balanced",
            "explanation": "Senna S high-speed chicane rewards minimum speed approach; Ferradura hairpin rewards late braking. Brazil is balanced but favours complete car balance over single-technique dominance.",
        },
        "tyre_challenge": "Bumpy surface and undulations increase mechanical tyre wear. Weather variability frequently complicates compound choice.",
        "downforce_level": "medium_high",
        "narrative": "Interlagos is short but intense. The Senna S at T1-T2 is a high-speed chicane entered at very high speed downhill — minimum speed defines S1. Undulations throughout stress the car differently from most circuits. Weather variability is high and damp patches are common even without full rain.",
    },

    "las_vegas": {
        "circuit_name": "Las Vegas Street Circuit",
        "character": "street_power",
        "sector_1": {
            "type": "strip_straight_into_chicanes",
            "description": "T1-T8: Strip section, T1 very heavy braking, chicane sequence into hotels area",
            "style_advantage": "late_braker",
            "energy_demand": "maximum",
        },
        "sector_2": {
            "type": "medium_speed_hotel",
            "description": "T9-T14: hotel section, medium-speed corners",
            "style_advantage": "balanced",
            "energy_demand": "medium",
        },
        "sector_3": {
            "type": "final_hairpin_into_return_strip",
            "description": "T15-T17: final hairpin into the return along the Strip — very long straight",
            "style_advantage": "late_braker",
            "energy_demand": "maximum",
        },
        "energy_profile": {
            "deployment_demand": "maximum",
            "harvesting_opportunity": "medium",
            "clipping_risk": "maximum",
            "key_straights": ["strip_straight_very_long", "return_strip_straight"],
            "notes": "Two very long straights along the Las Vegas Strip. Super-clipping almost certain on both under 2026 rules.",
        },
        "style_verdict": {
            "qualifier": "power_and_late_braker",
            "explanation": "Two long straights followed by hard braking zones reward late-brakers at T1 and T15. Energy management on the straights is the primary performance differentiator.",
        },
        "tyre_challenge": "Cold track surface in the night race affects tyre temperature management. Graining is a significant risk.",
        "downforce_level": "low",
        "narrative": "Las Vegas is one of the most power-dependent circuits on the calendar, with two very long Strip straights. Super-clipping is essentially certain under 2026 rules. Cold night temperatures create unique tyre warm-up challenges — graining is common on the first flying lap. Qualifying and race pace can diverge significantly based on tyre temperature management.",
    },

    "qatar": {
        "circuit_name": "Lusail International Circuit",
        "character": "high_speed_flowing",
        "sector_1": {
            "type": "high_speed_sweepers",
            "description": "T1-T8: continuous high-speed sequence requiring sustained minimum-speed commitment",
            "style_advantage": "u_line",
            "energy_demand": "high",
        },
        "sector_2": {
            "type": "medium_high_speed",
            "description": "T9-T14: medium-to-high-speed flowing section — still very demanding",
            "style_advantage": "u_line",
            "energy_demand": "high",
        },
        "sector_3": {
            "type": "final_into_main",
            "description": "T15-T16: final corner complex into main straight",
            "style_advantage": "late_braker",
            "energy_demand": "very_high",
        },
        "energy_profile": {
            "deployment_demand": "high",
            "harvesting_opportunity": "medium",
            "clipping_risk": "medium_high",
            "key_straights": ["main_straight"],
        },
        "style_verdict": {
            "qualifier": "u_line_strongly_favored",
            "explanation": "Lusail is the closest calendar analogue to Jeddah. Sustained high-speed sections through S1 and S2 heavily reward minimum-speed drivers. V-line drivers find very few braking zones to recover.",
        },
        "tyre_challenge": "Extreme rear wear — one of the most degradation-intensive circuits. Sprint format often held here amplifies tyre management importance.",
        "downforce_level": "high",
        "narrative": "Qatar punishes tyres harder than almost any other circuit — extreme rear degradation from sustained high-speed loading. U-line drivers who carry more minimum speed and load the rear less aggressively have a structural race pace advantage. Managing rear tyre temperature through the high-speed sweepers is the primary race challenge.",
    },

    "abu_dhabi": {
        "circuit_name": "Yas Marina Circuit",
        "character": "mixed_flowing",
        "sector_1": {
            "type": "medium_speed_flowing",
            "description": "T1-T9: flowing medium-speed section, varied corner types — broadly balanced",
            "style_advantage": "balanced",
            "energy_demand": "medium",
        },
        "sector_2": {
            "type": "high_speed_after_back_straight",
            "description": "T10-T14: high-speed flowing section after back straight",
            "style_advantage": "u_line",
            "energy_demand": "high",
        },
        "sector_3": {
            "type": "hotel_into_main",
            "description": "T15-T21: hotel section, final hairpin, into main straight",
            "style_advantage": "late_braker",
            "energy_demand": "high",
        },
        "energy_profile": {
            "deployment_demand": "high",
            "harvesting_opportunity": "medium",
            "clipping_risk": "medium",
            "key_straights": ["back_straight", "main_straight"],
        },
        "style_verdict": {
            "qualifier": "balanced",
            "explanation": "S2 high-speed section after the back straight favours U-line; the final hairpin complex gives late-brakers a recovery. Broadly balanced but cooler November conditions make tyres last longer.",
        },
        "tyre_challenge": "Moderate degradation. Cool evening conditions in the November season finale help tyre longevity — one-stop strategies are viable.",
        "downforce_level": "medium_high",
        "narrative": "Abu Dhabi is a comprehensive test without a dominant characteristic. S2 high-speed section rewards U-line minimum speed; the final hairpin complex gives late-brakers a chance. Cool conditions in the season finale mean tyres last longer than most circuits.",
    },
}


# ── Country/event → profile key lookup ───────────────────────────────────────

# Canonical mapping: casefolded country name (and common variants) → profile key.
# Matched by exact equality first; substring scan is the fallback.
_COUNTRY_ALIASES: dict[str, str] = {
    "bahrain": "bahrain",
    "saudi arabia": "saudi_arabia",
    "saudi": "saudi_arabia",
    "australia": "australia",
    "japan": "japan",
    "china": "china",
    "united states": "united_states",
    "united states of america": "united_states",
    "usa": "united_states",
    "us": "united_states",
    "america": "united_states",
    "emilia romagna": "emilia_romagna",
    "emilia-romagna": "emilia_romagna",
    "italy emilia romagna": "emilia_romagna",
    "monaco": "monaco",
    "canada": "canada",
    "spain": "spain",
    "austria": "austria",
    "great britain": "britain",
    "united kingdom": "britain",
    "britain": "britain",
    "uk": "britain",
    "england": "britain",
    "belgium": "belgium",
    "hungary": "hungary",
    "netherlands": "netherlands",
    "holland": "netherlands",
    "the netherlands": "netherlands",
    "italy": "italy",
    "azerbaijan": "azerbaijan",
    "singapore": "singapore",
    "mexico": "mexico",
    "brazil": "brazil",
    "las vegas": "las_vegas",
    "qatar": "qatar",
    "abu dhabi": "abu_dhabi",
    "united arab emirates": "abu_dhabi",
    "uae": "abu_dhabi",
}


# Fallback substring fragments — only consulted when the exact alias lookup
# fails. Order matters: earlier entries win on ambiguous matches.
_LOOKUP_FALLBACK: list[tuple[str, str]] = [
    ("bahrain", "bahrain"),
    ("saudi", "saudi_arabia"),
    ("australia", "australia"),
    ("japan", "japan"),
    ("china", "china"),
    ("emilia", "emilia_romagna"),
    ("monaco", "monaco"),
    ("canada", "canada"),
    ("spain", "spain"),
    ("austria", "austria"),
    ("brit", "britain"),
    ("kingdom", "britain"),
    ("england", "britain"),
    ("belgi", "belgium"),
    ("hungar", "hungary"),
    ("netherlands", "netherlands"),
    ("holland", "netherlands"),
    ("ital", "italy"),
    ("azerbai", "azerbaijan"),
    ("singapore", "singapore"),
    ("mexico", "mexico"),
    ("brazil", "brazil"),
    ("las vegas", "las_vegas"),
    ("qatar", "qatar"),
    ("abu dhabi", "abu_dhabi"),
    ("emirates", "abu_dhabi"),
    # COTA fallback is the very last US match; Miami is handled by the
    # event-name disambiguation in get_circuit_profile.
    ("united states", "united_states"),
    ("america", "united_states"),
]


def get_circuit_profile(country: str, event_name: str = "") -> dict | None:
    """
    Return the circuit profile for a given country + optional event name.
    Country is matched against an explicit canonical alias table first
    (casefolded, whitespace-stripped); only if that misses do we fall back
    to a substring scan. event_name is only consulted for the Miami vs
    COTA disambiguation on US rounds.
    """
    c = " ".join((country or "").casefold().split())
    e = (event_name or "").casefold()

    best_key: str | None = _COUNTRY_ALIASES.get(c)

    if best_key is None:
        for frag, key in _LOOKUP_FALLBACK:
            if frag in c:
                best_key = key
                break

    # Miami vs COTA: both report country "united states" / "United States".
    # Miami wins when the event name says so; otherwise COTA is the default.
    if best_key == "united_states" and "miami" in e:
        best_key = "miami"

    if best_key is None:
        return None
    profile = CIRCUIT_PROFILES.get(best_key)
    if profile is None:
        return None
    return {"circuit_key": best_key, **profile}
