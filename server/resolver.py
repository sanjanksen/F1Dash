import re

from f1_data import get_circuits, get_drivers


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9\s]", " ", text.lower()).strip()


def _has_reference_language(normalized: str) -> bool:
    reference_terms = (
        "here", "there", "that race", "that weekend", "that session",
        "he", "him", "his", "they", "them", "their", "teammate"
    )
    return any(re.search(rf"\b{re.escape(term)}\b", normalized) for term in reference_terms)


def _detect_session_scope(normalized: str) -> tuple[str | None, str | None]:
    session_type = None
    if (
        "qualifying" in normalized
        or re.search(r"\bq\d\b", normalized)
        or re.search(r"\bquali\b", normalized)
        or "pole lap" in normalized
        or "pole run" in normalized
    ):
        session_type = "Q"
    elif "sprint qualifying" in normalized or "sprint shootout" in normalized:
        session_type = "SQ"
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
    if any(term in normalized for term in ("lift and coast", "lift-and-coast", "lico", "clipping", "super clipping", "super-clipping", "energy recovery", "deployment")):
        scope = "energy"
    if "qualifying" in normalized or re.search(r"\bquali\b", normalized) or "pole lap" in normalized or "pole run" in normalized:
        scope = scope or "qualifying"
    if re.search(r"\bradio\b", normalized) or "team radio" in normalized or "on the radio" in normalized:
        scope = "radio"
    if any(phrase in normalized for phrase in (
        "standings", "championship", "who leads", "points table",
        "leaderboard", "points leader", "championship leader",
    )):
        scope = "standings"

    return session_type, scope


def _match_drivers(normalized: str) -> list[dict]:
    matches = []
    seen = set()
    for driver in get_drivers():
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
    teams = sorted({driver.get("team", "") for driver in get_drivers() if driver.get("team")}, key=len, reverse=True)
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

    circuits = get_circuits()
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
    if scope == "radio":
        return "get_team_radio"
    if scope == "energy":
        return "analyze_energy_management"
    # Note: scope == "standings" is handled inline in _base_context because
    # it needs the raw normalized message to distinguish driver vs constructor.
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


def _detect_analysis_mode(normalized: str, matched_drivers: list[dict], session_type: str | None) -> tuple[str | None, str | None]:
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

    if session_type == "Q" or "qualifying" in normalized or re.search(r"\bquali\b", normalized) or "pole lap" in normalized or "outqualif" in normalized:
        return "driver_comparison", "qualifying"
    if session_type == "R" or "race" in normalized or "grand prix" in normalized:
        return "driver_comparison", "race"
    return "driver_comparison", "session"


def _base_context(message: str) -> dict:
    normalized = _normalize(message)
    session_type, scope = _detect_session_scope(normalized)
    matched_drivers = _match_drivers(normalized)
    driver = matched_drivers[0] if len(matched_drivers) == 1 else None
    team = None if driver else _match_team(normalized)
    event = _match_event(normalized)
    analysis_mode, analysis_focus = _detect_analysis_mode(normalized, matched_drivers, session_type)

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

    fallback_fields = (
        "event_name", "round_number", "country", "session_type",
        "entity_type", "entity_name", "entity_code", "scope",
        "entity_names", "entity_codes", "analysis_mode", "analysis_focus"
    )

    for field in fallback_fields:
        current_value = merged.get(field)
        is_missing = current_value is None or current_value == []
        if is_missing and previous.get(field) is not None:
            if field in ("entity_type", "entity_name", "entity_code") and not merged.get("has_reference_language"):
                continue
            merged[field] = previous[field]
            used_previous = True

    if merged.get("suggested_tool") is None:
        if merged.get("scope") == "standings":
            _is_constructor = any(w in (merged.get("normalized_message") or "") for w in ("constructor", "team standings", "constructors"))
            merged["suggested_tool"] = "get_constructor_standings" if _is_constructor else "get_driver_standings"
        else:
            merged["suggested_tool"] = _suggest_tool(merged.get("entity_type"), merged.get("scope"), merged.get("session_type"))

    if current.get("analysis_mode") is None and previous.get("analysis_mode") is not None and merged.get("has_reference_language"):
        used_previous = True

    explicit_parts = sum(1 for field in ("entity_name", "event_name", "session_type", "scope") if current.get(field) is not None)
    if explicit_parts >= 2:
        resolution_confidence = "high"
    elif explicit_parts == 1 or used_previous:
        resolution_confidence = "medium"
    else:
        resolution_confidence = "low"

    single_entity = merged.get("entity_type") in ("driver", "team")
    if merged.get("suggested_tool") and merged.get("round_number") and single_entity and not merged.get("has_reference_language"):
        routing_confidence = "high"
    elif merged.get("suggested_tool") and merged.get("round_number"):
        routing_confidence = "medium"
    else:
        routing_confidence = "low"

    merged["resolution_confidence"] = resolution_confidence
    merged["routing_confidence"] = routing_confidence
    merged["used_previous_context"] = used_previous
    return merged


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
