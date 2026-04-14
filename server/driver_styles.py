# server/driver_styles.py
"""
Curated driving style profiles for current F1 drivers.

Each profile describes how a driver approaches corners — turn-in commitment,
V-line vs U-line philosophy, braking technique, apex style, throttle application,
and what their telemetry typically looks like relative to a reference lap.

Sources: technical analyses, published telemetry comparisons, team/driver interviews.
Used to contextualise qualifying battle and teammate comparisons so the LLM can frame
speed differences in terms of technique and style rather than pure numbers.
"""

# ── Classification constants ──────────────────────────────────────────────────
# steering_style:    "smooth" | "measured" | "aggressive"
# corner_approach:   "v_line" | "u_line" | "balanced"
#   V-line: hard late braking, sharp apex, early throttle — trades mid-corner speed
#           for late braking and early power; works well in slow/medium corners.
#   U-line: earlier braking, rounder arc, higher minimum speed — exploits high-
#           downforce cars' exponential grip-speed relationship.
# braking_style:     "late_aggressive" | "early_settle" | "balanced"
# apex_style:        "late" | "standard" | "early"
# throttle_style:    "early_explosive" | "gradual" | "measured"
# car_preference:    "oversteer" | "understeer" | "balanced"
#   oversteer: pointy/responsive front end, tolerates/uses rear sliding
#   understeer: stable rear, front hesitates on turn-in — easier to manage

DRIVER_STYLES: dict[str, dict] = {

    "VER": {
        "full_name": "Max Verstappen",
        "steering_style": "smooth",
        "corner_approach": "balanced",   # late-apex discipline but not pure V
        "braking_style": "early_settle",
        # Verstappen touches the brake early to settle weight transfer, then ramps up hard —
        # this is counterintuitive but it allows him to stabilise the car and then commit deeply.
        "apex_style": "late",
        "throttle_style": "early_explosive",
        "car_preference": "oversteer",   # pointy front, loose rear
        "setup_preference": "pointy_oversteer",
        "corner_philosophy": (
            "Thinks about the straight when approaching the corner — makes the corner as short "
            "as possible to maximise straight length. Late apex enables earlier, harder power "
            "application. Exceptional grip sensing: one of the best at feeling the limit and "
            "responding before the car breaks away."
        ),
        "key_traits": [
            "Touches brakes early to initiate weight transfer, then dives deep",
            "Late apex — gets to power earlier and harder than almost anyone",
            "Smooth through fast corner sequences; appears almost effortless",
            "Prefers pointy front end with a loose rear he can control",
            "Makes tiny incremental steering corrections rather than big reactive ones",
        ],
        "telemetry_signature": (
            "Slightly earlier initial brake touch followed by deeper commitment; "
            "late steering turn-in; higher minimum speed in fast corners; "
            "early, decisive throttle application post-apex."
        ),
        "weakness": "Late-apex philosophy loads rear tyres more — higher degradation in long stints.",
        "wet_weather": "Exceptional — feel-based advantage translates directly in low-grip conditions.",
    },

    "HAM": {
        "full_name": "Lewis Hamilton",
        "steering_style": "smooth",
        "corner_approach": "balanced",
        "braking_style": "late_aggressive",
        "apex_style": "standard",
        "throttle_style": "gradual",
        "car_preference": "understeer",  # stable rear, front hesitates but planted
        "setup_preference": "stable_understeer",
        "corner_philosophy": (
            "Precision and stability — wants a car he can commit to with confidence. "
            "Makes time predominantly on braking phases; smooth, deliberate steering; "
            "gradual throttle preserves tyre temperature. Cannot straighten the car as quickly "
            "as Verstappen post-apex but extracts maximum from a stable platform."
        ),
        "key_traits": [
            "One of the deepest brakers on the grid — large time gains in braking zones",
            "Smooth, deliberate steering with minimal mid-corner correction",
            "Gradual, measured throttle — prioritises traction over explosive exit speed",
            "Prefers rear stability over pointy front end",
            "Best-in-class tyre preservation — softer entry/exit life extends stints",
        ],
        "telemetry_signature": (
            "Very late, decisive brake point; smooth speed entry arc; "
            "measured throttle ramp; clean steering trace with no spike corrections."
        ),
        "weakness": "Struggles more than Verstappen to maximise exit speed from slow corners on fresh tyres.",
        "wet_weather": "Excellent — smooth inputs and car feel transfer well to wet conditions.",
    },

    "LEC": {
        "full_name": "Charles Leclerc",
        "steering_style": "smooth",
        "corner_approach": "balanced",
        "braking_style": "late_aggressive",
        "apex_style": "late",
        "throttle_style": "early_explosive",
        "car_preference": "oversteer",   # pointy front, similar to Verstappen
        "setup_preference": "pointy_oversteer",
        "corner_philosophy": (
            "Heavily loads the front of the car during braking to generate rotation, "
            "then carries maximum speed to a late apex. Uses a 'little turn, big turn' "
            "two-stage technique in medium/low-speed corners to reduce understeer — initial "
            "gentle steering input to settle the car, then a more committed second turn "
            "at the apex. Smooth despite aggressive philosophy."
        ),
        "key_traits": [
            "'Little turn, big turn' two-stage apex technique in medium/low-speed corners",
            "Heavy front loading under braking to induce rotation",
            "Releases throttle slightly earlier than Verstappen on entry to aid rotation",
            "Smoother mid-corner steering than Hamilton despite similar aggression philosophy",
            "Relies on absolute confidence that the rear stays planted",
        ],
        "telemetry_signature": (
            "Early throttle lift on corner entry to help car rotation; "
            "late, heavy braking; two-stage steering input visible in medium-speed corners; "
            "early, committed throttle post-apex."
        ),
        "weakness": "Two-stage turn technique costs marginal time in corners where it isn't perfectly executed.",
        "wet_weather": "Strong — front-loading technique helps with rotation in low grip.",
    },

    "NOR": {
        "full_name": "Lando Norris",
        "steering_style": "aggressive",
        "corner_approach": "v_line",
        "braking_style": "late_aggressive",
        "apex_style": "standard",
        "throttle_style": "early_explosive",
        "car_preference": "oversteer",
        "setup_preference": "responsive_front",
        "corner_philosophy": (
            "Aggressive V-line approach — brakes hard and late, induces oversteer on entry, "
            "then must correct multiple times mid-corner ('correct, correct, correct'). "
            "Gains significant time on entry but the correction phase costs time and tyre energy "
            "in the middle of the corner. Car rotates more aggressively at turn-in than teammates."
        ),
        "key_traits": [
            "V-shaped racing line — aggressive entry, sharp apex, early exit",
            "Brakes hard and late, inducing deliberate oversteer rotation",
            "Multiple mid-corner steering corrections after aggressive turn-in",
            "Gains time on entry; trades mid-corner smoothness for late braking",
            "Car turns significantly more aggressively at corner entry than peers",
        ],
        "telemetry_signature": (
            "Very late brake point; sharp turn-in steering spike; "
            "multiple small steering correction inputs mid-corner; "
            "aggressive early throttle; higher entry speed, lower minimum speed vs Piastri."
        ),
        "weakness": "Mid-corner corrections cost tyre temperature and time; worse in high-speed corners where corrections are dangerous.",
        "wet_weather": "Risky — aggressive entry oversteer is hard to manage in low grip.",
    },

    "PIA": {
        "full_name": "Oscar Piastri",
        "steering_style": "smooth",     # decisive single input rather than corrections
        "corner_approach": "u_line",
        "braking_style": "early_settle",
        "apex_style": "standard",
        "throttle_style": "measured",
        "car_preference": "understeer",
        "setup_preference": "stable_understeer",
        "corner_philosophy": (
            "U-line approach — earlier braking to settle the car, rounder arc maintaining "
            "higher minimum corner speed. 'Turns and waits' rather than correcting. "
            "Single decisive steering input that works through to the apex. "
            "Appears smooth but inputs are described as 'incredibly aggressive' in their "
            "decisiveness — one clean, committed movement rather than multiple adjustments. "
            "Particularly strong through fast corners where mid-corner speed is decisive."
        ),
        "key_traits": [
            "U-shaped line — higher minimum speed, smoother arc, less peak entry speed",
            "Early braker — loads tyres over a longer period, induces less snap oversteer",
            "Single decisive steering input rather than entry-to-mid-corner corrections",
            "'Turns and waits' — patience through the apex rather than reactive adjustments",
            "Particularly quick in fast corners due to high minimum speed",
        ],
        "telemetry_signature": (
            "Earlier brake point vs Norris; smoother entry speed arc; "
            "single clean steering input peak; higher minimum corner speed; "
            "later throttle application but from a higher base speed."
        ),
        "weakness": "Earlier braking can cost time in pure braking zones; entry speed lower than late-brakers.",
        "wet_weather": "Strong — smooth, patient inputs handle low-grip conditions well.",
    },

    "SAI": {
        "full_name": "Carlos Sainz",
        "steering_style": "smooth",
        "corner_approach": "balanced",
        "braking_style": "late_aggressive",
        "apex_style": "standard",
        "throttle_style": "early_explosive",
        "car_preference": "understeer",
        "setup_preference": "stable_understeer",
        "corner_philosophy": (
            "Self-described as aggressive but telemetry shows controlled smoothness. "
            "Brakes deeper into corners than teammates; gets back to throttle earlier using "
            "the pedals to manipulate weight transfer rather than steering. "
            "Always searching for tiny corrections — loves when the car 'lives underneath him'. "
            "Best-in-class tyre management; strong at traction-demanding corners."
        ),
        "key_traits": [
            "Brakes deeper into corners than teammates",
            "Early throttle application — uses pedals to control weight transfer on exit",
            "Smooth overall but always making tiny corrective steering inputs",
            "Excellent tyre preservation — manages degradation better than most",
            "Particularly strong at traction corners (e.g. Monza, chicane exits)",
        ],
        "telemetry_signature": (
            "Late, aggressive braking; early throttle application on exit; "
            "smooth steering trace with small micro-corrections visible; "
            "lower tyre temperature spikes than more aggressive entry drivers."
        ),
        "weakness": "Micro-correction hunting can add marginal steering noise in high-speed corners.",
        "wet_weather": "Good — smooth inputs and tyre management transfer well.",
    },

    "RUS": {
        "full_name": "George Russell",
        "steering_style": "measured",
        "corner_approach": "v_line",
        "braking_style": "late_aggressive",
        "apex_style": "late",
        "throttle_style": "early_explosive",
        "car_preference": "balanced",
        "setup_preference": "balanced",
        "corner_philosophy": (
            "Measured aggression — brakes slightly later but holds a single decisive steering "
            "input rather than correcting. Takes straighter line trajectories, turns later, "
            "and carries more corner speed as a result. Avoids aggressive kerb strikes. "
            "Very tidy, precise flow that reduces energy spikes into the tyres. "
            "V-shaped approach draws comparisons to Mika Häkkinen."
        ),
        "key_traits": [
            "Brakes later and holds a single decisive steering input — no corrections",
            "Straighter line trajectory — turns later than Hamilton, carries more exit speed",
            "Very tidy and precise — avoids aggressive kerbs",
            "Measured rather than raw aggressive — calculated V-line execution",
            "Reduces tyre temperature spikes through energy-efficient technique",
        ],
        "telemetry_signature": (
            "Late, hard braking; later turn-in point vs Hamilton; "
            "single clean steering input; high exit speed from corners; "
            "minimal correction spikes in mid-corner steering trace."
        ),
        "weakness": "Measured approach can cost time in slow corners where raw aggression and rotation pay off.",
        "wet_weather": "Good — precise, low-energy inputs suit low-grip conditions.",
    },

    "ALO": {
        "full_name": "Fernando Alonso",
        "steering_style": "aggressive",
        "corner_approach": "variable",   # adapts circuit by circuit
        "braking_style": "balanced",
        "apex_style": "variable",
        "throttle_style": "measured",
        "car_preference": "responsive",  # needs the car to talk to him
        "setup_preference": "high_feedback_front",
        "corner_philosophy": (
            "Reactive feel-based driving that becomes proactive through extreme speed of "
            "interpretation. Turns in harder and sharper than any other current driver. "
            "Aggressive steering wheel movement in the middle of corners. "
            "Front tyre feel is non-negotiable — needs the car to communicate through the "
            "steering. Interprets grip feedback so quickly that reactive corrections appear "
            "seamless. Mastery of understeer management through aggressive technique."
        ),
        "key_traits": [
            "Sharpest, most aggressive turn-in on the grid",
            "Aggressive steering wheel movement through the middle of corners",
            "Heavily dependent on front tyre feel and steering feedback",
            "Reactive style that appears proactive due to extreme interpretation speed",
            "Exceptional in wet conditions — feel-based advantage amplified by low grip",
        ],
        "telemetry_signature": (
            "Sharp turn-in steering spikes; distinct mid-corner steering activity; "
            "variable braking patterns circuit-to-circuit; "
            "strong feedback-reading visible as small rapid corrections that smooth out at pace."
        ),
        "weakness": "Highly car-sensitive — underperforms when the car doesn't communicate well through the steering.",
        "wet_weather": "Outstanding — arguably the best wet-weather driver of his era.",
    },

    "ANT": {
        "full_name": "Kimi Antonelli",
        "steering_style": "smooth",
        "corner_approach": "balanced",
        "braking_style": "balanced",
        "apex_style": "standard",
        "throttle_style": "measured",
        "car_preference": "understeer",  # Mercedes developmental lineage
        "setup_preference": "stable",
        "corner_philosophy": (
            "Mercedes academy driver — trained on smooth, precise inputs in the Hamilton "
            "tradition. Still adapting to F1 machinery in debut season; base style is "
            "smooth and disciplined but raw pace extrapolation is ongoing."
        ),
        "key_traits": [
            "Smooth, precise inputs — Mercedes academy training",
            "Disciplined corner approach, minimal corrections",
            "Still building confidence and aggression for F1 pace",
        ],
        "telemetry_signature": "Smooth traces; early career data — profile will develop through 2025/2026.",
        "weakness": "Rookie adaptation — not yet extracting maximum from aggressive situations.",
        "wet_weather": "Unknown — limited data.",
    },

    "STR": {
        "full_name": "Lance Stroll",
        "steering_style": "measured",
        "corner_approach": "balanced",
        "braking_style": "balanced",
        "apex_style": "standard",
        "throttle_style": "gradual",
        "car_preference": "understeer",
        "setup_preference": "stable_understeer",
        "corner_philosophy": (
            "Measured, stability-focused approach. Strong in wet conditions. "
            "Prefers a stable, predictable car that he can lean on consistently."
        ),
        "key_traits": [
            "Measured, consistent inputs",
            "Prefers stable understeer platform",
            "Strong in wet and damp conditions",
        ],
        "telemetry_signature": "Consistent, measured throttle and steering traces.",
        "weakness": "Less aggressive extraction on entry — loses time vs teammates in pure dry-weather braking zones.",
        "wet_weather": "Strong — one of the better wet-weather drivers on the grid.",
    },

    "GAS": {
        "full_name": "Pierre Gasly",
        "steering_style": "aggressive",
        "corner_approach": "v_line",
        "braking_style": "late_aggressive",
        "apex_style": "standard",
        "throttle_style": "early_explosive",
        "car_preference": "oversteer",
        "setup_preference": "responsive_front",
        "corner_philosophy": (
            "Aggressive, committed driver. Brakes late, prefers a responsive front end. "
            "V-line tendency — extracts time from aggressive entries."
        ),
        "key_traits": [
            "Aggressive, late-braking style",
            "Prefers responsive, front-end-loaded setup",
            "Extracts time from corner entry",
        ],
        "telemetry_signature": "Late brake points; aggressive turn-in; early throttle application.",
        "weakness": "Aggressive style can be inconsistent under pressure or in lower-grip conditions.",
        "wet_weather": "Capable — aggressive instincts balanced by reasonable feel.",
    },

    "HUL": {
        "full_name": "Nico Hülkenberg",
        "steering_style": "measured",
        "corner_approach": "balanced",
        "braking_style": "late_aggressive",
        "apex_style": "standard",
        "throttle_style": "measured",
        "car_preference": "balanced",
        "setup_preference": "balanced",
        "corner_philosophy": (
            "Experienced, versatile driver. Measured approach that extracts consistent "
            "performance. Strong in qualifying trim — known as a good one-lap driver."
        ),
        "key_traits": [
            "Consistent, measured technique",
            "Strong one-lap pace in qualifying",
            "Versatile — adapts well to different car characteristics",
        ],
        "telemetry_signature": "Clean, consistent traces; strong braking zone execution.",
        "weakness": "Less explosive natural pace than top-tier drivers in pure performance scenarios.",
        "wet_weather": "Competent — measured style transfers adequately.",
    },

    "TSU": {
        "full_name": "Yuki Tsunoda",
        "steering_style": "aggressive",
        "corner_approach": "v_line",
        "braking_style": "late_aggressive",
        "apex_style": "standard",
        "throttle_style": "early_explosive",
        "car_preference": "oversteer",
        "setup_preference": "responsive_front",
        "corner_philosophy": (
            "Aggressive, raw natural speed. Late braker with v-line tendencies. "
            "Can be inconsistent — occasionally over-aggressive in high-pressure situations "
            "but capable of very fast single laps when fully committed."
        ),
        "key_traits": [
            "Aggressive, late braking with responsive front end preference",
            "V-line tendency — trades mid-corner smoothness for entry speed",
            "Raw natural pace but inconsistency under pressure",
        ],
        "telemetry_signature": "Late, aggressive braking; sharp turn-in; early throttle.",
        "weakness": "Inconsistency — over-aggression occasionally leads to mistakes or tyre abuse.",
        "wet_weather": "Mixed — aggressive instincts need managing in low grip.",
    },

    "LAW": {
        "full_name": "Liam Lawson",
        "steering_style": "aggressive",
        "corner_approach": "v_line",
        "braking_style": "late_aggressive",
        "apex_style": "standard",
        "throttle_style": "early_explosive",
        "car_preference": "oversteer",
        "setup_preference": "responsive_front",
        "corner_philosophy": (
            "Aggressive natural racer — similar aggressive tendencies to the Red Bull academy "
            "mould. Late braker, committed entries. Still building F1 experience."
        ),
        "key_traits": [
            "Aggressive, late-braking style",
            "Red Bull academy-style committed corner entries",
            "Building F1 consistency",
        ],
        "telemetry_signature": "Aggressive entry; late brake points; sharp turn-in.",
        "weakness": "Experience — still learning tyre and race management at the highest level.",
        "wet_weather": "Limited data.",
    },

    "BEA": {
        "full_name": "Oliver Bearman",
        "steering_style": "measured",
        "corner_approach": "balanced",
        "braking_style": "balanced",
        "apex_style": "standard",
        "throttle_style": "measured",
        "car_preference": "balanced",
        "setup_preference": "balanced",
        "corner_philosophy": (
            "Ferrari academy driver — smooth, disciplined inputs reflecting elite single-seater "
            "training. Showed strong composure in limited F1 appearances. Profile developing."
        ),
        "key_traits": [
            "Ferrari academy smoothness — disciplined, precise inputs",
            "Composed under pressure for a rookie",
            "Style developing with F1 experience",
        ],
        "telemetry_signature": "Clean, controlled traces — early career profile.",
        "weakness": "Limited F1 data — style profile still emerging.",
        "wet_weather": "Unknown — limited data.",
    },
}


def get_driver_style(driver_code: str) -> dict | None:
    """Return the style profile for a driver by their 3-letter code. Case-insensitive."""
    return DRIVER_STYLES.get(driver_code.upper())


def get_comparison_framing(code_a: str, code_b: str) -> dict:
    """
    Return style profiles for both drivers plus a framing note about
    what to watch for when comparing them — what their style differences
    predict about where one should be faster.
    """
    a = get_driver_style(code_a)
    b = get_driver_style(code_b)

    if not a or not b:
        return {"driver_a_style": a, "driver_b_style": b, "style_prediction": None}

    predictions = []

    # Corner approach clash
    if a.get("corner_approach") == "v_line" and b.get("corner_approach") == "u_line":
        predictions.append(
            f"{code_a.upper()} (V-line) should gain on corner entry and in braking zones; "
            f"{code_b.upper()} (U-line) should carry more mid-corner speed through fast corners."
        )
    elif a.get("corner_approach") == "u_line" and b.get("corner_approach") == "v_line":
        predictions.append(
            f"{code_b.upper()} (V-line) should gain on corner entry and in braking zones; "
            f"{code_a.upper()} (U-line) should carry more mid-corner speed through fast corners."
        )

    # Braking style
    if a.get("braking_style") == "late_aggressive" and b.get("braking_style") == "early_settle":
        predictions.append(
            f"{code_a.upper()} brakes later and more aggressively — expect a braking zone advantage for them."
        )
    elif b.get("braking_style") == "late_aggressive" and a.get("braking_style") == "early_settle":
        predictions.append(
            f"{code_b.upper()} brakes later and more aggressively — expect a braking zone advantage for them."
        )

    # Car preference clash
    if a.get("car_preference") == "oversteer" and b.get("car_preference") == "understeer":
        predictions.append(
            f"{code_a.upper()} prefers an oversteer/pointy setup while {code_b.upper()} prefers a stable/understeer "
            f"platform — the car's natural balance will favour one of them."
        )
    elif b.get("car_preference") == "oversteer" and a.get("car_preference") == "understeer":
        predictions.append(
            f"{code_b.upper()} prefers an oversteer/pointy setup while {code_a.upper()} prefers a stable/understeer "
            f"platform — the car's natural balance will favour one of them."
        )

    return {
        "driver_a_style": a,
        "driver_b_style": b,
        "style_prediction": " ".join(predictions) if predictions else None,
    }
