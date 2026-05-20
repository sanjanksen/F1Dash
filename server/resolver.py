import re
import os
import json
import logging
import time

import anthropic

from f1_data import get_circuits, get_drivers

logger = logging.getLogger(__name__)

# ── Canonical data cache ──────────────────────────────────────────────────────
_drivers_cache: list[dict] = []
_drivers_cache_time: float = 0.0
_circuits_cache: list[dict] = []
_circuits_cache_time: float = 0.0
_DRIVER_CACHE_TTL = 300  # 5 minutes
_CIRCUITS_CACHE_TTL = 3600  # 1 hour


def _cached_drivers() -> list[dict]:
    global _drivers_cache, _drivers_cache_time
    if not _drivers_cache or time.time() - _drivers_cache_time > _DRIVER_CACHE_TTL:
        try:
            _drivers_cache = get_drivers()
            _drivers_cache_time = time.time()
        except Exception:
            pass
    return _drivers_cache


def _cached_circuits() -> list[dict]:
    global _circuits_cache, _circuits_cache_time
    if not _circuits_cache or time.time() - _circuits_cache_time > _CIRCUITS_CACHE_TTL:
        try:
            _circuits_cache = get_circuits()
            _circuits_cache_time = time.time()
        except Exception:
            pass
    return _circuits_cache


# ── Haiku entity extractor ────────────────────────────────────────────────────
_haiku_client: anthropic.Anthropic | None = None


def _get_haiku_client() -> anthropic.Anthropic:
    global _haiku_client
    if _haiku_client is None:
        _haiku_client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    return _haiku_client


def _extract_entities_llm(message: str) -> dict:
    """
    Use Claude Haiku to extract canonical F1 entities from a free-text message.
    Handles nicknames, aliases, and paraphrasing that regex can't catch.
    Returns: {drivers: [3-letter codes], team: str|None, event_country: str|None, round: int|None}
    Falls back to empty dict on any error so regex path kicks in.
    """
    try:
        drivers = _cached_drivers()
        circuits = _cached_circuits()

        driver_lines = "\n".join(
            f"  {d.get('code', '')} | {d.get('full_name', '')} | {d.get('team', '')}"
            for d in drivers
        )
        circuit_lines = "\n".join(
            f"  {c.get('country', '')} | {c.get('event_name', '')} | {c.get('circuit_name', '')} | round {c.get('round', '')}"
            for c in circuits
        )

        system = f"""You extract F1 entities from user messages. Return ONLY a JSON object, no prose.

Current F1 drivers (code | full name | team):
{driver_lines}

Current circuits (country | event name | circuit name | round):
{circuit_lines}

From the user message extract:
- "drivers": list of 3-letter driver codes for any drivers mentioned (by full name, surname, first name, nickname, pronoun, or possessive like "his"). Empty list if none clearly mentioned.
- "team": exact team name from the driver list above if any team is mentioned by any name/nickname. null if none.
- "event_country": exact country name from the circuit list if any event, circuit, or location is mentioned. null if none.
- "round": round number as integer if explicitly mentioned. null if not.

Common aliases to resolve:
- Prancing Horse / Scuderia / SF-xx → Ferrari
- Silver Arrows / the stars / Brackley → Mercedes
- Milton Keynes / RB20 → Red Bull
- Woking / papaya → McLaren
- Max / Mad Max → VER  |  Lando → NOR  |  Checo / Sergio → PER
- Carlos → SAI  |  George → RUS  |  Lewis → HAM  |  Charles → LEC
- Oscar → PIA  |  Fernando / Alonso → ALO  |  Lance → STR
- Kimi / Antonelli → ANT | Ollie / Oliver / Bearman → BEA | Liam / Lawson → LAW | Isack / Hadjar → HAD
- Gabriel / Bortoleto → BOR | Jack / Doohan → DOO | Yuki / Tsunoda → TSU | Franco / Colapinto → COL

Return JSON only: {{"drivers": [], "team": null, "event_country": null, "round": null}}"""

        response = _get_haiku_client().messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            system=system,
            messages=[{"role": "user", "content": message}],
        )
        text = "".join(b.text for b in response.content if hasattr(b, "text")).strip()
        # Strip markdown fences if model wraps output
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text).strip()
        result = json.loads(text)
        logger.debug("LLM entity extraction for %r: %s", message[:60], result)
        return result
    except Exception:
        logger.warning("LLM entity extraction failed, falling back to regex", exc_info=True)
        return {}


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9\s]", " ", text.lower()).strip()


def _has_reference_language(normalized: str) -> bool:
    strong_phrases = (
        "that race", "that weekend", "that session", "that gp", "that grand prix",
        "this race", "this weekend", "this session", "this gp",
        "the same driver", "the same race", "same weekend",
        "last race", "last weekend",
        "teammate",
    )
    if any(re.search(rf"\b{re.escape(p)}\b", normalized) for p in strong_phrases):
        return True

    weak_tokens = (
        "he", "him", "his", "she", "her",
        "they", "them", "their",
        "it", "its",
        "the",
        "here", "there", "both",
    )
    hits = sum(
        1 for t in weak_tokens
        if re.search(rf"\b{re.escape(t)}\b", normalized)
    )
    return hits >= 2


def _detect_fp_number(normalized: str) -> int | None:
    """Return 1, 2, or 3 if the message mentions a specific FP session."""
    if re.search(r"\bfp\s*1\b|\bfree\s+practice\s+1\b|\bpractice\s+1\b", normalized):
        return 1
    if re.search(r"\bfp\s*2\b|\bfree\s+practice\s+2\b|\bpractice\s+2\b", normalized):
        return 2
    if re.search(r"\bfp\s*3\b|\bfree\s+practice\s+3\b|\bpractice\s+3\b", normalized):
        return 3
    return None


def _detect_session_scope(normalized: str) -> tuple[str | None, str | None]:
    session_type = None
    fp_number = _detect_fp_number(normalized)
    if fp_number is not None:
        session_type = f"FP{fp_number}"
    elif (
        "sprint qualifying" in normalized
        or "sprint quali" in normalized
        or "sprint shootout" in normalized
        or re.search(r"\bsq\b", normalized)
    ):
        session_type = "SQ"
    elif (
        "qualifying" in normalized
        or re.search(r"\bq\d\b", normalized)
        or re.search(r"\bquali\b", normalized)
        or "pole lap" in normalized
        or "pole run" in normalized
    ):
        session_type = "Q"
    elif re.search(r"\bsprint\b", normalized):
        session_type = "S"
    elif "race" in normalized or "grand prix" in normalized:
        session_type = "R"

    scope = None
    if any(phrase in normalized for phrase in (
        "how did", "what happened to", "talk me through", "race story", "weekend", "weekend recap"
    )):
        scope = "overview"
    if any(phrase in normalized for phrase in ("race report", "race recap", "whole race", "full race")):
        scope = "race_report"
    if "safety car" in normalized or "vsc" in normalized:
        scope = "safety_car"
    if "strategy" in normalized or "pit" in normalized:
        scope = "strategy"
    if any(term in normalized for term in (
        "pit stop", "pit stops", "fastest stop", "fastest pit", "pit timing",
        "pit duration", "undercut", "overcut", "pit window",
    )):
        scope = "pit_strategy"
    if any(term in normalized for term in ("lift and coast", "lift-and-coast", "lico", "clipping", "super clipping", "super-clipping", "energy recovery", "deployment")):
        scope = "energy"
    if "qualifying" in normalized or re.search(r"\bquali\b", normalized) or "pole lap" in normalized or "pole run" in normalized:
        scope = scope or "qualifying"
    if re.search(r"\bradio\b", normalized) or "team radio" in normalized or "on the radio" in normalized:
        scope = "radio"
    if any(term in normalized for term in (
        "track temperature", "track temp", "air temperature", "air temp",
        "track condition", "temperature affect", "temperature effect",
        "rainfall affect", "weather affect", "rain affect", "rain effect",
        "temperature drop", "temperature change",
    )):
        scope = "weather_pace"
    if any(term in normalized for term in (
        "corner profile", "braking point", "apex speed", "traction point",
        "gear at", "corner analysis", "corner comparison", "setup direction",
        "corner heavy", "straight heavy", "race pace",
    )):
        scope = "corner_analysis"
    if any(term in normalized for term in (
        "degradation", "tyre wear", "tire wear", "deg rate", "stint pace",
        "tyre deg", "tire deg", "tyre management", "tire management",
        "tyre performance", "tire performance",
    )):
        scope = "degradation"
    if any(phrase in normalized for phrase in (
        "standings", "championship", "who leads", "points table",
        "leaderboard", "points leader", "championship leader",
    )):
        scope = "standings"

    if any(phrase in normalized for phrase in (
        "circuit profile", "circuit guide", "track guide", "track profile",
        "about the circuit", "about this circuit", "circuit breakdown",
        "about the track",
    )) or re.search(r"\bcircuit info\b", normalized) or re.search(r"\btrack info\b", normalized) \
            or (re.search(r"\btell me about\b", normalized) and ("circuit" in normalized or "track" in normalized)):
        scope = "circuit"

    if fp_number is not None or any(term in normalized for term in (
        "free practice", "fp1", "fp2", "fp3", "practice session",
        "practice programme", "practice running",
    )):
        scope = "fp"

    if any(term in normalized for term in (
        "top speed", "speed trap", "fastest straight", "straight-line speed",
        "speed down the straight", "highest speed", "trap speed",
        "maximum speed", "top speeds", "down the straight",
        "fastest on the straight", "speed on the straight",
    )) or re.search(r"\bdrag\b", normalized):
        scope = "speed_trap"

    if any(term in normalized for term in (
        "brave", "bravery", "braver", "courageous",
        "grip style", "tyre confidence", "grip confidence",
        "who pushes harder", "pushes harder",
        "who extracts", "extracts more", "extract grip",
        "how committed", "more committed",
        "confidence through corners", "confidence in corners",
        "who is braver", "braver driver", "braver through",
        "on the limit", "at the limit", "reaches the limit",
        "limit of the car", "limit of their car",
        "who uses more grip", "grip usage",
    )):
        scope = "grip_style"

    return session_type, scope


def _match_drivers(normalized: str) -> list[dict]:
    matches = []
    seen = set()
    for driver in _cached_drivers():
        names = {
            _normalize(driver.get("full_name", "")),
            _normalize(driver.get("driver_id", "")),
            _normalize(driver.get("code", "")),
        }
        family = _normalize(driver.get("full_name", "").split()[-1] if driver.get("full_name") else "")
        given = _normalize(driver.get("full_name", "").split()[0] if driver.get("full_name") else "")
        names.update({family, given})
        positions = [
            match.start()
            for name in names if name
            for match in [re.search(rf"\b{re.escape(name)}\b", normalized)]
            if match
        ]
        if positions:
            code = (driver.get("code") or driver.get("driver_id") or driver.get("full_name") or "").upper()
            if code and code not in seen:
                seen.add(code)
                matches.append((min(positions), driver))
    matches.sort(key=lambda item: item[0])
    return [driver for _, driver in matches]


def _match_driver(normalized: str) -> dict | None:
    matches = _match_drivers(normalized)
    return matches[0] if matches else None


def _match_team(normalized: str) -> str | None:
    teams = sorted({driver.get("team", "") for driver in _cached_drivers() if driver.get("team")}, key=len, reverse=True)
    aliases = {
        "merc": "Mercedes",
        "mercedes": "Mercedes",
        "ferrari": "Ferrari",
        "mclaren": "McLaren",
        "red bull": "Red Bull",
        "rb": "RB",
        "aston": "Aston Martin",
        "alpine": "Alpine",
        "haas": "Haas F1 Team",
        "sauber": "Kick Sauber",
        "williams": "Williams",
        "audi": "Audi",           # 2026 rebrand
        "kick sauber": "Kick Sauber",
    }

    for alias, canonical in aliases.items():
        if re.search(rf"\b{re.escape(alias)}\b", normalized):
            for team in teams:
                if canonical.lower() in team.lower() or team.lower() in canonical.lower():
                    return team

    for team in teams:
        if re.search(rf"\b{re.escape(_normalize(team))}\b", normalized):
            return team
    return None


def _match_event(normalized: str) -> dict | None:
    alias_map = {
        "suzuka": "japan",
        "japanese gp": "japan",
        "japanese grand prix": "japan",
        "monza": "italy",
        "spa": "belgium",
        "silverstone": "britain",
        "interlagos": "brazil",
        "yas marina": "abu dhabi",
        "cota": "united states",
        "imola": "emilia romagna",
        "montreal": "canada",
        "villeneuve": "canada",
        "sakhir": "bahrain",
        "albert park": "australia",
        "budapest": "hungary",
        "spielberg": "austria",
        "red bull ring": "austria",
        "marina bay": "singapore",
        "lusail": "qatar",
        "baku": "azerbaijan",
        "jeddah": "saudi arabia",
        "las vegas": "las vegas",
        "mexico city": "mexico",
        "autodromo hermanos rodriguez": "mexico",
        "circuit de barcelona": "spain",
        "barcelona": "spain",
        "catalunya": "spain",
        "zandvoort": "netherlands",
    }
    search_terms = set()
    for alias, mapped in alias_map.items():
        if alias in normalized:
            search_terms.add(alias)
            search_terms.add(mapped)

    token_terms = set()
    for token in normalized.split():
        if len(token) >= 4:
            token_terms.add(token)
    search_terms.update(token_terms)

    circuits = _cached_circuits()
    best_match = None
    best_score = 0
    for circuit in circuits:
        haystacks = [
            _normalize(circuit.get("event_name", "")),
            _normalize(circuit.get("circuit_name", "")),
            _normalize(circuit.get("country", "")),
        ]
        gpless = haystacks[0].replace("grand prix", "").strip()
        if gpless:
            haystacks.append(gpless)
        country = haystacks[2]
        if country:
            haystacks.append(f"{country} grand prix")
            if country.endswith("n"):
                haystacks.append(country[:-1])
        score = 0
        for hay in [hay for hay in haystacks if hay]:
            if hay and re.search(rf"\b{re.escape(hay)}\b", normalized):
                score = max(score, len(hay) + 10)

        for term in list(search_terms):
            normalized_term = term.replace("gp", "grand prix").strip()
            if not normalized_term:
                continue
            for hay in [hay for hay in haystacks if hay]:
                if re.search(rf"\b{re.escape(normalized_term)}\b", hay):
                    score = max(score, len(normalized_term))

        if score > best_score:
            best_score = score
            best_match = circuit

    return best_match if best_score > 0 else None


def _suggest_tool(entity_type: str | None, scope: str | None, session_type: str | None = None) -> str | None:
    if scope == "fp":
        return "get_fp_summary"
    if scope == "speed_trap":
        return "get_speed_trap_leaderboard"
    if scope == "radio":
        return "get_team_radio"
    if scope == "energy":
        return "analyze_energy_management"
    if scope == "pit_strategy":
        return "get_pit_stop_analysis"
    if scope == "weather_pace":
        return "analyze_weather_pace_correlation"
    if scope == "degradation" and entity_type == "driver":
        return "analyze_stint_degradation"
    if scope == "grip_style":
        if session_type in ("Q", "SQ"):
            return "analyze_cornering_loads"
        return "analyze_race_cornering_profile"
    # Note: scope == "standings" is handled inline in _base_context because
    # it needs the raw normalized message to distinguish driver vs constructor.
    if session_type == "SQ" and entity_type in (None, "driver"):
        return "get_sprint_qualifying_results"
    if entity_type == "driver":
        # Qualifying questions must not route to race-only tools
        if session_type == "Q":
            return "get_driver_weekend_overview"
        if scope in ("overview", "strategy", "safety_car"):
            return "get_driver_race_story"
        return "get_driver_weekend_overview"
    if entity_type == "team":
        return "get_team_weekend_overview"
    if scope == "race_report":
        return "get_race_report"
    if scope == "safety_car":
        return "get_safety_car_periods"
    return None


def _detect_analysis_mode(normalized: str, matched_drivers: list[dict], session_type: str | None, matched_team: str | None = None) -> tuple[str | None, str | None]:
    # Team performance mode (single team, no two-driver comparison)
    if matched_team and len(matched_drivers) < 2:
        team_fit_terms = any(phrase in normalized for phrase in (
            "suited", "suit", "fits", "fit", "car fit", "team fit",
            "car characteristic", "car characteristics", "strength", "weakness", "strengths", "weaknesses",
            "what tracks", "what circuits", "kind of tracks", "kind of circuits",
            "high speed", "low speed", "slow speed", "stop and go",
            "late braking", "late braker", "u line", "v line",
            "downforce", "power circuit", "street circuit",
        ))
        if team_fit_terms:
            return "team_circuit_fit", None

        team_perf_terms = any(phrase in normalized for phrase in (
            "team performance", "as a team", "team analysis", "setup direction",
            "corner heavy", "straight heavy", "which teammate", "teammate comparison",
            "better through the corners", "better on the straights",
        ))
        if team_perf_terms:
            return "team_performance", None

    if len(matched_drivers) < 2:
        return None, None

    comparison_language = any(phrase in normalized for phrase in (
        "compare", "compared", "comparison", "vs", "versus", "faster than", "slower than",
        "beat", "ahead of", "edge", "advantage", "where did", "how did", "why did",
        "gain time", "lose time", "quicker than", "better than",
        "outqualif", "outperform", "outpace", "outrun",
        "gap between", "difference between", "time difference", "delta between",
        "how much did", "which driver", "who was quicker", "who was faster",
    ))
    if not comparison_language:
        return None, None

    # Grip / cornering analysis: explicit grip or cornering vocabulary routes to dedicated
    # grip_comparison mode which calls only analyze_cornering_loads (no qualifying battle needed)
    grip_terms = any(phrase in normalized for phrase in (
        "grip", "cornering loads", "corner analysis", "cornering analysis", "cornering style",
        "tyre confidence", "grip style", "grip confidence", "extract grip",
        "who pushes harder", "pushes harder", "how committed", "more committed",
        "on the limit", "at the limit", "limit of the car",
        "brave", "bravery", "load variance",
    ))
    if grip_terms:
        return "grip_comparison", session_type

    # Race pace comparison: explicit race pace / degradation language
    race_pace_terms = any(phrase in normalized for phrase in (
        "race pace", "pace battle", "deg", "degradation", "tyre wear", "tire wear",
        "stint", "fuel corrected", "pull away", "pulled away", "gap in the race",
    ))
    if race_pace_terms and session_type != "Q":
        return "race_pace_comparison", "race"

    if session_type == "Q" or "qualifying" in normalized or re.search(r"\bquali\b", normalized) or "pole lap" in normalized or "outqualif" in normalized:
        return "driver_comparison", "qualifying"
    if session_type == "R" or "race" in normalized or "grand prix" in normalized:
        return "driver_comparison", "race"
    return "driver_comparison", "session"


def _base_context(message: str) -> dict:
    normalized = _normalize(message)
    fp_number = _detect_fp_number(normalized)
    session_type, scope = _detect_session_scope(normalized)

    # ── LLM extraction — handles nicknames, aliases, and paraphrasing ─────────
    llm = _extract_entities_llm(message)

    # Resolve driver codes → driver dicts; fall back to regex if LLM found none
    driver_by_code = {d.get("code", "").upper(): d for d in _cached_drivers() if d.get("code")}
    matched_drivers: list[dict] = [
        driver_by_code[code.upper()]
        for code in (llm.get("drivers") or [])
        if code.upper() in driver_by_code
    ]
    if not matched_drivers:
        matched_drivers = _match_drivers(normalized)

    # Team is only relevant when no single driver is identified
    driver = matched_drivers[0] if len(matched_drivers) == 1 else None
    if driver:
        team = None
    else:
        team = llm.get("team") or _match_team(normalized)

    # Resolve event: prefer LLM country/round match, fall back to regex
    event: dict | None = None
    llm_country = (llm.get("event_country") or "").strip()
    llm_round = llm.get("round")
    if llm_country or llm_round:
        for c in _cached_circuits():
            if llm_country and _normalize(c.get("country", "")) == _normalize(llm_country):
                event = c
                break
            if llm_round and c.get("round") == llm_round:
                event = c
                break
    if not event:
        event = _match_event(normalized)

    if scope == "circuit":
        analysis_mode, analysis_focus = "circuit_profile", None
    else:
        analysis_mode, analysis_focus = _detect_analysis_mode(normalized, matched_drivers, session_type, team)

    entity_type = None
    entity_name = None
    entity_code = None
    if len(matched_drivers) >= 2:
        entity_type = "multi_driver"
    elif driver:
        entity_type = "driver"
        entity_name = driver.get("full_name")
        entity_code = driver.get("code")
    elif team:
        entity_type = "team"
        entity_name = team

    if scope == "standings":
        _is_constructor = any(w in normalized for w in ("constructor", "team standings", "constructors"))
        _suggested_tool = "get_constructor_standings" if _is_constructor else "get_driver_standings"
    else:
        _suggested_tool = _suggest_tool(entity_type, scope, session_type)

    return {
        "raw_message": message,
        "normalized_message": normalized,
        "entity_type": entity_type,
        "entity_name": entity_name,
        "entity_code": entity_code,
        "entity_names": [driver.get("full_name") for driver in matched_drivers],
        "entity_codes": [driver.get("code") or driver.get("driver_id", "").upper() for driver in matched_drivers],
        "event_name": event.get("event_name") if event else None,
        "round_number": event.get("round") if event else None,
        "country": event.get("country") if event else None,
        "session_type": session_type,
        "fp_number": fp_number,
        "scope": scope,
        "analysis_mode": analysis_mode,
        "analysis_focus": analysis_focus,
        "suggested_tool": _suggested_tool,
        "has_reference_language": _has_reference_language(normalized),
        "has_explicit_context": any([
            entity_type is not None,
            event is not None,
            session_type is not None,
            scope is not None,
            analysis_mode is not None,
        ]),
    }


def _merge_with_previous_context(current: dict, previous: dict | None) -> dict:
    if not previous:
        current["resolution_confidence"] = "high" if current.get("has_explicit_context") else "low"
        current["routing_confidence"] = "high" if current.get("suggested_tool") and current.get("round_number") else "low"
        current["used_previous_context"] = False
        return current

    merged = dict(current)
    used_previous = False

    # Fields that always carry forward (event/round/location context)
    unconditional_fields = ("event_name", "round_number", "country", "session_type", "scope")
    # Fields that only carry forward when the message contains reference language
    # (pronouns, "that race", "it", etc.) — prevents topic bleeding
    reference_gated_fields = (
        "entity_type", "entity_name", "entity_code",
        "entity_names", "entity_codes",
        "analysis_mode", "analysis_focus",
    )

    has_ref = merged.get("has_reference_language", False)

    for field in unconditional_fields + reference_gated_fields:
        current_value = merged.get(field)
        is_missing = current_value is None or current_value == []
        if not is_missing:
            continue
        if previous.get(field) is None:
            continue
        if field in reference_gated_fields and not has_ref:
            continue
        merged[field] = previous[field]
        used_previous = True

    if merged.get("suggested_tool") is None:
        if merged.get("scope") == "standings":
            _is_constructor = any(w in (merged.get("normalized_message") or "") for w in ("constructor", "team standings", "constructors"))
            merged["suggested_tool"] = "get_constructor_standings" if _is_constructor else "get_driver_standings"
        else:
            merged["suggested_tool"] = _suggest_tool(merged.get("entity_type"), merged.get("scope"), merged.get("session_type"))

    explicit_parts = sum(1 for field in ("entity_name", "event_name", "session_type", "scope") if current.get(field) is not None)
    if explicit_parts >= 2:
        resolution_confidence = "high"
    elif explicit_parts == 1 or used_previous:
        resolution_confidence = "medium"
    else:
        resolution_confidence = "low"

    single_entity = merged.get("entity_type") in ("driver", "team")
    if merged.get("suggested_tool") and merged.get("round_number") and single_entity and not has_ref:
        routing_confidence = "high"
    elif merged.get("suggested_tool") and merged.get("round_number"):
        routing_confidence = "medium"
    else:
        routing_confidence = "low"

    # Detect when we should prompt the model to ask a clarifying question
    needs_clarification = _detect_clarification_needed(merged)

    merged["resolution_confidence"] = resolution_confidence
    merged["routing_confidence"] = routing_confidence
    merged["used_previous_context"] = used_previous
    merged["needs_clarification"] = needs_clarification
    return merged


def _detect_clarification_needed(resolved: dict) -> str | None:
    """
    Returns a short description of what's missing, or None if context is clear enough.
    Called after merging, so 'resolved' already has previous context applied.
    """
    scope = resolved.get("scope")
    round_number = resolved.get("round_number")
    entity_name = resolved.get("entity_name")
    entity_names = resolved.get("entity_names") or []
    has_any_entity = bool(entity_name or entity_names)

    # Scopes that never need a specific round
    general_scopes = {"standings", "schedule", "general", "drivers", "circuits"}
    if scope in general_scopes:
        return None

    # We have a driver/team but absolutely no race context anywhere
    if has_any_entity and round_number is None and not resolved.get("used_previous_context"):
        # Only flag if the question seems race-specific (has a session/scope that implies event data)
        if resolved.get("session_type") or scope in ("race", "qualifying", "overview", "pace", "telemetry"):
            return "which_race"

    # Extremely vague — no entity, no round, no scope, nothing to work with
    if (not has_any_entity and round_number is None and scope is None
            and resolved.get("resolution_confidence") == "low"
            and not resolved.get("has_explicit_context")):
        return "general_ambiguity"

    return None


def resolve_query_context(message: str, previous_context: dict | None = None) -> dict:
    return _merge_with_previous_context(_base_context(message), previous_context)


def resolve_context_from_history(history: list[dict]) -> dict | None:
    context = None
    for item in history:
        if item.get("role") != "user":
            continue
        content = item.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        context = resolve_query_context(content, context)
    return context
