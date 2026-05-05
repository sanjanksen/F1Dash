"""
Sourced editorial team/car profile notes.

These are not private setup facts. They are dated, human-curated context from
public reporting and should be treated as weaker evidence than telemetry.
"""

TEAM_CAR_PROFILES: dict[str, dict] = {
    "ferrari": {
        "team": "Ferrari",
        "profile_type": "curated_editorial",
        "last_reviewed": "2026-04-26",
        "confidence": "medium",
        "summary": "Recent public reporting has described Ferrari as having track-dependent limitations in high-speed corner confidence, while its slow-speed strength has varied by car generation.",
        "traits": [
            {
                "trait": "high_speed_confidence_limitation",
                "status": "reported_limitation",
                "note": "Autosport reported a 2025 Ferrari limitation that appeared in high-speed corners, linked to power-steering feel and driver confidence.",
                "source": "Autosport",
                "source_url": "https://www.autosport.com/f1/news/explained-the-problem-that-is-affecting-ferrari-at-high-speed-tracks-in-f1-2025/10740571/",
            },
            {
                "trait": "slow_speed_strength_not_stable",
                "status": "mixed",
                "note": "Autosport described slow-speed cornering as a prior SF-24 strength that looked weaker on the SF-25 early in 2025.",
                "source": "Autosport",
                "source_url": "https://www.autosport.com/f1/news/has-ferrari-turned-one-of-its-cars-key-strengths-into-a-weakness/10720130/",
            },
        ],
        "caveat": "Use this as dated reporting context only; verify against current telemetry and results before making a strong claim.",
    },
    "mercedes": {
        "team": "Mercedes",
        "profile_type": "curated_editorial",
        "last_reviewed": "2026-04-26",
        "confidence": "medium",
        "summary": "Public Mercedes commentary around the W15/W16 transition focused on improving slow-corner weakness, especially linked slow-corner sequences.",
        "traits": [
            {
                "trait": "slow_corner_sequence_weakness",
                "status": "reported_limitation",
                "note": "Mercedes trackside engineering comments identified slow-speed connected corners as a target area for the following car.",
                "source": "Crash.net",
                "source_url": "https://www.crash.net/f1/news/1059941/1/key-weakness-mercedes-are-focused-fixing-w16-f1-car",
            },
        ],
        "caveat": "This is public reporting around a previous car generation; current telemetry should override it.",
    },
    "aston martin": {
        "team": "Aston Martin",
        "profile_type": "curated_editorial",
        "last_reviewed": "2026-04-26",
        "confidence": "medium",
        "summary": "Recent reporting describes Aston Martin as oscillating between slow-corner recovery and fast-corner/straight-line weakness depending on package direction.",
        "traits": [
            {
                "trait": "high_downforce_slow_corner_bias",
                "status": "historical_tendency",
                "note": "Autosport described the AMR23 as high-downforce with low-speed strength but straight and fast-corner compromises.",
                "source": "Autosport",
                "source_url": "https://www.autosport.com/f1/news/what-is-behind-aston-martins-struggles-in-f1-2025/10717821/",
            },
        ],
        "caveat": "Treat as development-direction context, not a stable 2026 car identity.",
    },
    "red bull": {
        "team": "Red Bull Racing",
        "profile_type": "curated_editorial",
        "last_reviewed": "2026-04-26",
        "confidence": "medium",
        "summary": "Public analysis has often framed Red Bull's recent weakness as kerb/bump sensitivity rather than a simple high-speed or low-speed deficit.",
        "traits": [
            {
                "trait": "kerb_bump_sensitivity",
                "status": "reported_limitation",
                "note": "Autosport covered Verstappen describing a long-running Red Bull weakness on slower, bumpy circuits as the field caught up.",
                "source": "Autosport",
                "source_url": "https://www.autosport.com/f1/news/have-red-bulls-f1-weaknesses-really-been-found-out/10616918/",
            },
        ],
        "caveat": "This does not mean Red Bull is weak everywhere slow; it points specifically to kerbs, bumps, and platform sensitivity.",
    },
    "haas": {
        "team": "Haas F1 Team",
        "profile_type": "curated_editorial",
        "last_reviewed": "2026-04-26",
        "confidence": "low",
        "summary": "Public 2025 reporting described Haas as working through high-load, high-speed downforce limitations with floor development.",
        "traits": [
            {
                "trait": "high_speed_downforce_limitation",
                "status": "reported_limitation",
                "note": "Autosport reported Haas had struggled to maintain downforce through high-load, high-speed corners before development updates.",
                "source": "Autosport",
                "source_url": "https://www.autosport.com/f1/news/how-the-2025-f1-development-war-is-still-being-fought/10767590/",
            },
        ],
        "caveat": "Low confidence because this is package-specific and likely to change with development.",
    },
}


def get_team_car_profile(team_name: str) -> dict | None:
    needle = (team_name or "").strip().lower()
    if not needle:
        return None
    for key, profile in TEAM_CAR_PROFILES.items():
        team = profile.get("team", "").lower()
        if needle in key or key in needle or needle in team or team in needle:
            return dict(profile)
    return None
