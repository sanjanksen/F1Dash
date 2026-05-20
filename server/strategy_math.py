"""
Pure-math layer for race-strategy decisions.

No FastF1 imports, no I/O. Inputs are plain dicts/numbers from a strategy
snapshot built in f1_data.py. Tests run in <50ms with no fixtures.

Main entry points:
  - compute_undercut_window(driver_code, current_lap, target_driver_code,
                             snapshot, max_rejoin_laps) -> dict
  - compute_pit_loss_variants(green_pit_loss_s) -> dict  (F19 helper)

Equation (per F16 plan):
  Undercut_advantage(L) =
      [Δfresh_tyre_pace(L_decision) × N_laps_to_rejoin_ahead]
      -  Pit_loss
      -  Out_lap_warmup_penalty
      -  Traffic_cost
      -  Δfuel_pace_correction
"""

OUT_LAP_COMPOUND_OFFSET = {
    "SOFT": 0.6,
    "MEDIUM": 1.0,
    "HARD": 1.6,
    "INTERMEDIATE": 0.5,
    "WET": 0.5,
}

OUT_LAP_WARMUP = {
    "SOFT":         {"warm_track": 0.5, "cool_track": 1.0},
    "MEDIUM":       {"warm_track": 0.8, "cool_track": 1.3},
    "HARD":         {"warm_track": 1.2, "cool_track": 2.0},
    "INTERMEDIATE": {"warm_track": 0.0, "cool_track": 0.0},
    "WET":          {"warm_track": 0.0, "cool_track": 0.0},
}

TRAFFIC_PACE_THRESHOLD_S_PER_LAP = 0.3
CLEAN_AIR_GAP_S = 1.5
COOL_TRACK_TEMP_C = 30.0
VSC_PIT_LOSS_FRACTION = 0.55  # F19
SC_PIT_LOSS_FRACTION = 0.35   # F19
COMPOUND_TYPICAL_DEG_SLOPE = {"SOFT": 0.10, "MEDIUM": 0.07, "HARD": 0.05}
MIN_STINT_LAPS_FOR_SLOPE_USE = 6
FUEL_COEFF_S_PER_KG = 0.03
FUEL_BURN_KG_PER_LAP = 1.8


def _norm_compound(c) -> str:
    return str(c or "").strip().upper()


def _pick_deg_slope(driver: dict) -> tuple[float, str]:
    """Returns (slope_s_per_lap, source) where source is one of:
    'post_cliff', 'pre_cliff', 'fitted', 'compound_typical_fallback'.
    """
    has_cliff = bool(driver.get("has_cliff"))
    age = float(driver.get("tyre_age") or 0)
    cliff_age = driver.get("cliff_age")
    pre = driver.get("pre_cliff_slope")
    post = driver.get("post_cliff_slope")
    fitted = driver.get("deg_slope")
    stint_laps = driver.get("stint_laps_used")

    if has_cliff and cliff_age is not None and age >= float(cliff_age) and post is not None:
        return (float(post), "post_cliff")
    if has_cliff and pre is not None:
        return (float(pre), "pre_cliff")
    if stint_laps is not None and stint_laps < MIN_STINT_LAPS_FOR_SLOPE_USE:
        comp = _norm_compound(driver.get("compound"))
        return (COMPOUND_TYPICAL_DEG_SLOPE.get(comp, 0.07), "compound_typical_fallback")
    if fitted is not None:
        return (float(fitted), "fitted")
    comp = _norm_compound(driver.get("compound"))
    return (COMPOUND_TYPICAL_DEG_SLOPE.get(comp, 0.07), "compound_typical_fallback")


def _out_lap_warmup(new_compound: str, track_temp_c: float | None) -> float:
    comp = _norm_compound(new_compound)
    table = OUT_LAP_WARMUP.get(comp, OUT_LAP_WARMUP["MEDIUM"])
    if track_temp_c is None:
        return table["warm_track"]
    if float(track_temp_c) < COOL_TRACK_TEMP_C:
        return table["cool_track"]
    return table["warm_track"]


def _apply_sc_state(green_pit_loss_s: float, active_sc_state: str | None) -> tuple[float, str]:
    state = (active_sc_state or "green").lower()
    if state == "vsc":
        return (green_pit_loss_s * VSC_PIT_LOSS_FRACTION, "vsc")
    if state == "sc":
        return (green_pit_loss_s * SC_PIT_LOSS_FRACTION, "sc")
    return (green_pit_loss_s, "green")


def _traffic_cost(snapshot: dict, fresh_pace_s_per_lap: float, n: int) -> tuple[float, int]:
    """Sum per-lap deficits to slower cars in the rejoin window over N laps.

    Returns (traffic_cost_s, cars_counted).
    """
    cars = snapshot.get("cars_in_rejoin_window") or []
    if not cars:
        return (0.0, 0)
    total = 0.0
    counted = 0
    for car in cars:
        predicted_pace = car.get("predicted_pace")
        if predicted_pace is None:
            continue
        deficit_per_lap = float(predicted_pace) - float(fresh_pace_s_per_lap)
        if deficit_per_lap <= TRAFFIC_PACE_THRESHOLD_S_PER_LAP:
            continue
        # Approximate exposure: deficit accumulates over N rejoin laps but
        # diminishes as the focal driver clears each car. Use first-lap deficit
        # for one car as the dominant term; cap to N.
        total += deficit_per_lap * min(n, 1)
        counted += 1
    return (round(total, 3), counted)


def _delta_fresh_pace(driver: dict, target: dict | None) -> tuple[float, dict]:
    """Δfresh_tyre_pace at decision lap.

    Compares worn-tyre projected pace vs. fresh-tyre projected pace, where the
    fresh compound is either the explicit 'next_compound' field or assumed to
    be the next-step harder compound. If a target is supplied and the target's
    fresh compound info is more precise, use that. Returns (delta, details).
    """
    slope_old, source_old = _pick_deg_slope(driver)
    base_old = float(driver.get("base_pace") or 0)
    age = float(driver.get("tyre_age") or 0)
    worn_pace = base_old + slope_old * age

    next_compound = _norm_compound(driver.get("next_compound") or _next_compound_guess(driver))
    base_new = driver.get("base_pace_new") or driver.get("base_pace") or 0
    base_new = float(base_new)
    out_offset = OUT_LAP_COMPOUND_OFFSET.get(next_compound, 1.0)
    fresh_pace_full_lap = base_new + out_offset

    delta = worn_pace - fresh_pace_full_lap
    return delta, {
        "worn_pace_s": round(worn_pace, 3),
        "fresh_pace_s": round(fresh_pace_full_lap, 3),
        "deg_slope_used_s_per_lap": round(slope_old, 4),
        "deg_slope_source": source_old,
        "new_compound": next_compound,
        "out_lap_compound_offset_s": out_offset,
    }


def _next_compound_guess(driver: dict) -> str:
    """If no explicit next compound provided, guess the typical undercut switch:
    SOFT -> MEDIUM, MEDIUM -> HARD, HARD -> MEDIUM."""
    current = _norm_compound(driver.get("compound"))
    return {
        "SOFT": "MEDIUM",
        "MEDIUM": "HARD",
        "HARD": "MEDIUM",
        "INTERMEDIATE": "INTERMEDIATE",
        "WET": "INTERMEDIATE",
    }.get(current, "MEDIUM")


def _build_rationale(*, delta_fresh: float, n_to_crossover: int | None,
                     pit_loss_s: float, out_warmup_s: float, traffic_cost_s: float,
                     advantage_s: float, sc_state: str, sc_state_orig: str,
                     deg_source: str, cars_in_window: int) -> list[str]:
    bullets: list[str] = []
    bullets.append(
        f"Fresh-tyre gain of {delta_fresh:+.2f} s/lap over 1 lap can't recover "
        f"{pit_loss_s:.1f}s pit-loss within this cycle." if advantage_s < 0
        else f"Fresh-tyre gain of {delta_fresh:+.2f} s/lap clears the {pit_loss_s:.1f}s pit-loss within {n_to_crossover or 1} lap(s)."
    )
    if sc_state_orig != "green":
        bullets.append(
            f"Pit-loss reduced by {sc_state_orig.upper()}: "
            f"effective {pit_loss_s:.1f}s vs green-flag baseline."
        )
    if out_warmup_s >= 1.5:
        bullets.append(f"Cold out-lap warm-up costs an extra {out_warmup_s:.1f}s on the new compound.")
    elif out_warmup_s >= 1.0:
        bullets.append(f"Out-lap warm-up of {out_warmup_s:.1f}s on a warm track.")
    if traffic_cost_s > 0 and cars_in_window > 0:
        bullets.append(
            f"Rejoin window holds {cars_in_window} slower car(s); traffic cost ≈ {traffic_cost_s:.1f}s."
        )
    elif cars_in_window == 0:
        bullets.append("Clean-air rejoin — no traffic cost projected.")
    if deg_source == "compound_typical_fallback":
        bullets.append("Stint too short to fit a deg slope; using compound-typical fallback (lower confidence).")
    elif deg_source == "post_cliff":
        bullets.append("Current tyre is past the detected cliff — using post-cliff deg slope.")
    if n_to_crossover is None and advantage_s < 0:
        bullets.append("Advantage never turns positive within the modelled rejoin window.")
    return bullets[:5]


def _recommendation(advantage_s: float, crossover_lap: int | None) -> str:
    if advantage_s >= 1.0 and crossover_lap is not None and crossover_lap <= 2:
        return "pit_now"
    if advantage_s <= -3.0:
        return "stay_out"
    return "marginal"


def _confidence(snapshot: dict, deg_source: str, traffic_was_computed: bool) -> str:
    driver = snapshot.get("driver") or {}
    stint_laps = driver.get("stint_laps_used") or 0
    weather_known = snapshot.get("track_temp_c") is not None

    if not weather_known:
        return "low"
    if stint_laps < MIN_STINT_LAPS_FOR_SLOPE_USE or deg_source == "compound_typical_fallback":
        return "low"
    if stint_laps < 8 or deg_source == "pre_cliff":
        return "moderate"
    if not traffic_was_computed:
        return "moderate"
    return "high"


def compute_undercut_window(
    driver_code: str,
    current_lap: int,
    target_driver_code: str | None,
    snapshot: dict,
    max_rejoin_laps: int = 5,
) -> dict:
    """Compute undercut/overcut viability from a strategy snapshot.

    See module docstring for the equation. Returns the canonical dict shape
    documented in the F16 plan.
    """
    driver = snapshot.get("driver") or {}
    target = snapshot.get("target")
    green_pit_loss = float(snapshot.get("pit_loss_s") or 0.0)
    sc_state_orig = (snapshot.get("active_sc_state") or "green").lower()
    pit_loss_effective, sc_state = _apply_sc_state(green_pit_loss, sc_state_orig)

    delta_fresh, fresh_details = _delta_fresh_pace(driver, target)
    new_compound = fresh_details["new_compound"]
    out_warmup = _out_lap_warmup(new_compound, snapshot.get("track_temp_c"))

    advantage_at_n: list[tuple[int, float, float]] = []
    crossover_lap: int | None = None
    cars_counted = 0
    traffic_cost_at_n1 = 0.0

    for n in range(1, max(1, int(max_rejoin_laps)) + 1):
        traffic, counted = _traffic_cost(snapshot, fresh_details["fresh_pace_s"], n)
        if n == 1:
            traffic_cost_at_n1 = traffic
            cars_counted = counted
        delta_fuel = 0.0
        if n >= 3:
            delta_fuel = FUEL_COEFF_S_PER_KG * FUEL_BURN_KG_PER_LAP * n
        adv = (delta_fresh * n) - pit_loss_effective - out_warmup - traffic - delta_fuel
        advantage_at_n.append((n, round(adv, 3), round(traffic, 3)))
        if crossover_lap is None and adv >= 0:
            crossover_lap = n

    advantage_s = advantage_at_n[0][1]
    deg_source = fresh_details["deg_slope_source"]
    traffic_was_computed = bool(snapshot.get("cars_in_rejoin_window"))

    rec = _recommendation(advantage_s, crossover_lap)
    conf = _confidence(snapshot, deg_source, traffic_was_computed)

    rationale = _build_rationale(
        delta_fresh=delta_fresh,
        n_to_crossover=crossover_lap,
        pit_loss_s=pit_loss_effective,
        out_warmup_s=out_warmup,
        traffic_cost_s=traffic_cost_at_n1,
        advantage_s=advantage_s,
        sc_state=sc_state,
        sc_state_orig=sc_state_orig,
        deg_source=deg_source,
        cars_in_window=cars_counted,
    )

    return {
        "driver_code": driver_code,
        "current_lap": current_lap,
        "target_driver_code": target_driver_code,
        "undercut_available": advantage_s > 0,
        "overcut_available": advantage_s < 0 and rec != "stay_out",
        "advantage_s": round(advantage_s, 2),
        "crossover_lap": crossover_lap,
        "pit_loss_s": round(pit_loss_effective, 2),
        "pit_loss_green_s": round(green_pit_loss, 2),
        "delta_fresh_pace_s_per_lap": round(delta_fresh, 3),
        "out_lap_warmup_s": round(out_warmup, 2),
        "traffic_cost_s": round(traffic_cost_at_n1, 2),
        "advantage_by_rejoin_lap": [
            {"n": n, "advantage_s": adv, "traffic_cost_s": tc}
            for n, adv, tc in advantage_at_n
        ],
        "recommendation": rec,
        "confidence": conf,
        "active_sc_state": sc_state,
        "rationale": rationale,
        "inputs_summary": {
            "track_temp_c": snapshot.get("track_temp_c"),
            "new_compound": new_compound,
            "current_compound": _norm_compound(driver.get("compound")),
            "current_tyre_age": driver.get("tyre_age"),
            "deg_slope_used_s_per_lap": fresh_details["deg_slope_used_s_per_lap"],
            "deg_slope_source": deg_source,
            "worn_pace_s": fresh_details["worn_pace_s"],
            "fresh_pace_s": fresh_details["fresh_pace_s"],
            "cars_in_rejoin_window": cars_counted,
            "gap_to_target_s": snapshot.get("gap_to_target_s"),
        },
    }


def compute_pit_loss_variants(green_pit_loss_s: float) -> dict:
    """F19 helper. Returns green/VSC/SC pit-loss in seconds."""
    g = float(green_pit_loss_s)
    return {
        "green": round(g, 2),
        "vsc": round(g * VSC_PIT_LOSS_FRACTION, 2),
        "sc": round(g * SC_PIT_LOSS_FRACTION, 2),
    }
