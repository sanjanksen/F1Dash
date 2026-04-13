# server/chat.py
"""
Agentic chat loop supporting both Anthropic (Claude) and OpenAI (GPT).

Set LLM_PROVIDER=anthropic (default) or LLM_PROVIDER=openai in your .env.
The corresponding API key (ANTHROPIC_API_KEY / OPENAI_API_KEY) must also be set.
"""
import json
import os
import logging
import re
import anthropic
import openai as openai_sdk
from tools import TOOL_DEFINITIONS, OPENAI_TOOL_DEFINITIONS, execute_tool
from resolver import resolve_query_context, resolve_context_from_history

MAX_TOOL_ROUNDS = 8
logger = logging.getLogger(__name__)

import datetime

CURRENT_YEAR = datetime.date.today().year


def _make_qualifying_battle_widget(result: dict) -> dict:
    return {
        "type": "qualifying_battle",
        "title": f"{result.get('driver_a')} vs {result.get('driver_b')}",
        "event": result.get("event"),
        "session": result.get("compared_segment") or result.get("session"),
        "driver_a": result.get("driver_a"),
        "driver_b": result.get("driver_b"),
        "faster_driver": result.get("faster_driver"),
        "overall_gap_s": result.get("overall_gap_s"),
        "decisive_sector": result.get("decisive_sector"),
        "decisive_sector_gap_s": result.get("decisive_sector_gap_s"),
        "decisive_corner": result.get("decisive_corner"),
        "cause_type": result.get("cause_type"),
        "cause_explanation": result.get("cause_explanation"),
        "zone_summary": result.get("zone_summary"),
        "energy_relevant": result.get("energy_relevant"),
        "energy_reason": result.get("energy_reason"),
        "speed_trace": result.get("speed_trace") or [],
        "focus_window_trace": result.get("focus_window_trace") or [],
    }


def _make_race_story_widget(result: dict) -> dict:
    race = result.get("race") or {}
    qualifying = result.get("qualifying") or {}
    radio = result.get("radio_highlights") or []
    return {
        "type": "race_story",
        "title": result.get("driver"),
        "subtitle": result.get("event"),
        "driver_code": result.get("code"),
        "team": result.get("team"),
        "grid_position": race.get("grid_position") or qualifying.get("position"),
        "finish_position": race.get("finish_position"),
        "points": race.get("points"),
        "status": race.get("status"),
        "pit_stops": result.get("pit_stops") or [],
        "story_points": result.get("story_points") or [],
        "interval_summary": result.get("interval_summary"),
        "position_timeline_summary": result.get("position_timeline_summary"),
        "radio_highlights": radio[:3],
        "rivalry_story": result.get("rivalry_story") or [],
    }


def _widgets_from_preloaded(preloaded: dict | None) -> list[dict]:
    if not preloaded or "result" not in preloaded:
        return []
    tool = preloaded.get("tool")
    result = preloaded.get("result") or {}
    if tool == "get_driver_race_story":
        return [_make_race_story_widget(result)]
    if tool == "analyze_qualifying_battle":
        return [_make_qualifying_battle_widget(result)]
    return []


def _widgets_from_analysis_evidence(plan: dict, evidence: list[dict]) -> list[dict]:
    widgets = []
    for item in evidence:
        if "result" not in item:
            continue
        if item.get("tool") == "analyze_qualifying_battle":
            widgets.append(_make_qualifying_battle_widget(item["result"]))
        elif item.get("tool") == "get_driver_race_story":
            widgets.append(_make_race_story_widget(item["result"]))
    if plan.get("focus") == "race":
        deduped = []
        seen = set()
        for widget in widgets:
            key = (widget.get("type"), widget.get("title"), widget.get("subtitle"))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(widget)
        return deduped
    return widgets

SYSTEM_PROMPT = f"""You are an expert Formula 1 analyst with access to real-time {CURRENT_YEAR} season data through tools.

Your job is to answer questions about the {CURRENT_YEAR} F1 season accurately, using the tools provided to fetch up-to-date data. Do not rely on your training knowledge for current standings, results, or points — always fetch the relevant data first.

Today's date is {datetime.date.today().isoformat()}.

Guidelines:
- If the user's latest message explicitly names a Grand Prix, circuit, round, year, or session, that explicit reference OVERRIDES prior conversation context.
- When the latest message explicitly names an event like "Japanese GP" or "Suzuka", resolve the event from get_season_schedule first before calling any race/session-specific tool.
- Do not let follow-up context about a previous race override a newly named event in the latest user message.
- For broad recap questions, prefer COMPOSITE RECAP TOOLS first. Use PRIMITIVE TOOLS only for narrower follow-up questions or when the user explicitly asks for one slice of information.
- For championship standings: use get_driver_standings or get_constructor_standings
- For a specific driver's season: use get_driver_season_stats
- For a broad question about a driver's race or weekend, start with get_driver_race_story or get_driver_weekend_overview before using any narrower tool
- For a broad question about a team's race or weekend, start with get_team_weekend_overview before using narrower team or driver tools
- For a broad question about the whole race, use get_race_report
- For rich classification, penalties, grid vs finish, or team-color/headshot metadata: use get_session_results
- For comparing two drivers: use get_head_to_head
- For race results: use get_race_results with the round number
- For qualifying: use get_qualifying_results
- For calendar/schedule questions OR when asked about "the most recent race" / "latest race": call get_season_schedule first to find which rounds have already occurred based on today's date, then fetch that round's results
- For stint/tyre strategy, pit timing, or undercut/overcut questions: use get_driver_strategy
- For qualifying storylines like who improved through Q1/Q2/Q3: use get_qualifying_progression
- For trustworthy pace rankings, especially when traffic, deleted laps, or yellows matter: use get_clean_pace_summary
- For sector-by-sector pace: use get_sector_comparison
- For causal qualifying battle questions like "why was Leclerc faster than Norris in quali?" use analyze_qualifying_battle
- For lap-by-lap pace: use get_driver_lap_times
- For corner-level analysis (braking points, gear shifts, throttle application): use get_lap_telemetry or get_telemetry_comparison. These include gear, RPM, throttle, and brake at every 100m — use them to make specific claims like "Norris was still in 4th gear at 1400m while Leclerc had already dropped to 3rd, braking 20m earlier"
- For 2026-style energy questions like lift-and-coast, clipping, super-clipping, deployment taper, or energy recovery behavior: use analyze_energy_management
- For racing-line or on-track position comparisons, track maps, or where a gain happened physically on the lap: use get_track_position_comparison
- For team radio or in-car context, use get_team_radio
- For live-style gap-to-leader / interval questions in a race, use get_intervals
- For cleaner position change timelines in a session, use get_live_position_timeline
- For richer circuit-map context like marshal sectors/lights or rotation for track-map overlays: use get_circuit_details or get_circuit_corners
- For safety car / VSC questions, strategy impact, who got screwed by the SC: use get_safety_car_periods
- For deleted laps, race control decisions, incidents, or steward-style explanations: use get_race_control_messages
- For weather conditions, rain timing, temperature impact on tyres/pace: use get_session_weather
- FastF1 does not provide direct ERS state of charge, harvest maps, or deployment maps. For energy questions, clearly distinguish measured telemetry from inference.

Answer quality rules:
- Lead with the number or the fact. "Russell finished P3, 8 seconds off the lead" beats "Russell had a solid race finishing in the top 3".
- Sound like a knowledgeable person explaining to someone who follows F1 — not an analyst filing a report. After the first mention, use "he" and "his", not the driver code or full name every sentence.
- Keep the driver as the active subject. "Norris was clipping at 600m" beats "the speed delta at 600m was indicative of clipping for Norris".
- No filler phrases: no "it's worth noting", no "interestingly", no "this suggests that", no "it appears", no "Additional factors included", no "reflecting his", no "consistent with", no "in line with". State things directly.
- Never say the same fact twice in different words across consecutive sentences.
- If data is missing, acknowledge it in a short embedded clause — not a standalone disclaimer sentence at the end. "without radio context, the deployment target is unclear" is fine. "The precise team strategies are unknown due to unavailable team radio footage." is not.
- Stay focused on exactly what was asked. If asked about one driver, lead with that driver.
- Use the conversation history for follow-up questions.
- 3-5 sentences for most answers. Use bullets only when listing genuinely separate items."""

ANALYSIS_SYSTEM_PROMPT = """You are the analysis stage for an F1 product.

You do not answer like a chatbot. You read retrieved evidence and produce a JSON analysis object.

Rules:
- Focus on causal explanation, not data recap.
- direct_answer must state WHERE the gap came from (sector, corner, distance) and HOW MUCH (seconds, kph). Never just "Driver A was faster due to X" — always "Driver A took Xs in SectorN" or "gap opened at Xm where A carried Y kph more".
- Identify the single biggest factor first. One cause, stated precisely.
- Use only the strongest evidence from the supplied tool results.
- If the evidence includes a zone summary, decisive corner, decisive distance, or speed differential, those numbers must appear in direct_answer or primary_reason.
- Do not restate every statistic you see.
- Keep reasons non-overlapping. Do not repeat the same straight-line or energy point in different wording.
- Do not claim setup, tyre condition, balance, confidence, or car behavior unless that is explicitly present in the supplied evidence.
- If telemetry or energy evidence is unavailable, say that clearly and do not invent a braking/traction/setup explanation.
- If the evidence is mixed or weak, say so in uncertainties.
- Output valid JSON only.

Required JSON keys:
- direct_answer: string — must include the WHERE and HOW MUCH
- primary_reason: string
- secondary_reasons: array of strings
- strongest_evidence: array of strings
- caveats: array of strings
- confidence: one of high, medium, low
"""

ANSWER_WRITER_SYSTEM_PROMPT = """You are the final answer writer for an F1 analysis product.

You will receive a structured analysis JSON object. Write the final user-facing answer.

Voice: Write like a knowledgeable person talking through what they saw — not an analyst filing a report, not a commentator reading stats off a sheet. Think of how an F1 engineer would explain a lap to a driver after qualifying. Direct, specific, human.

Rules:
- Open with the WHERE and HOW MUCH. Name the sector or distance and the actual gap or speed delta in the first sentence. "Leclerc took 0.3s out of Norris in Sector 2" or "The gap opened at 800m — Leclerc was carrying 21 kph more speed at the top of the straight."
- Keep the driver as the subject of sentences. "Norris was already clipping at 600m and losing speed" beats "a late-straight speed fade of 21 kph was observed for Norris." Use "he" and "his" freely after the first mention.
- Explain the cause in plain language. "He ran out of deployment earlier down the straight" not "Norris experienced an earlier deployment taper reducing acceleration at full throttle."
- Never say the same thing twice. If you explained the 600m speed gap in sentence 1, don't restate it as "this clipping-induced speed reduction" in sentence 3.
- No filler or analytical hedges: no "this advantage allowed", no "Additional factors included", no "reflecting his", no "consistent with", no "pointing to", no "it appears", no "high-confidence".
- No energy rule primer. If energy is relevant, say what the data showed — one clause — and move on.
- No standalone disclaimer sentence at the end. If data is missing, embed a short qualifier mid-sentence ("without radio context, the exact target is unclear") and keep going. Never end with "The precise team strategies are unknown due to..."
- 3-5 sentences total. Add a bullet only when there are genuinely separate contributing factors.
"""


# ── Anthropic ────────────────────────────────────────────────────────────────

_anthropic_client: anthropic.Anthropic | None = None


def _suggested_tool_args(resolved: dict) -> dict | None:
    tool = resolved.get("suggested_tool")
    round_number = resolved.get("round_number")
    if not tool or round_number is None:
        return None

    if tool in ("get_driver_race_story", "get_driver_weekend_overview"):
        if not resolved.get("entity_name"):
            return None
        return {"round_number": round_number, "driver_name": resolved["entity_name"]}

    if tool == "get_team_weekend_overview":
        if not resolved.get("entity_name"):
            return None
        return {"round_number": round_number, "team_name": resolved["entity_name"]}

    if tool == "get_race_report":
        return {"round_number": round_number}

    if tool == "get_safety_car_periods":
        session_type = resolved.get("session_type") or "R"
        return {"round_number": round_number, "session_type": session_type}

    if tool == "get_team_radio":
        session_type = resolved.get("session_type") or "R"
        args = {"round_number": round_number, "session_type": session_type}
        if resolved.get("entity_code"):
            args["driver_ref"] = resolved["entity_code"]
        return args

    if tool == "analyze_energy_management":
        session_type = resolved.get("session_type") or "Q"
        if resolved.get("entity_type") == "driver" and resolved.get("entity_code"):
            return {
                "round_number": round_number,
                "session_type": session_type,
                "driver_a": resolved["entity_code"],
            }
        if resolved.get("entity_type") == "multi_driver" and len(resolved.get("entity_codes") or []) >= 2:
            codes = resolved["entity_codes"]
            return {
                "round_number": round_number,
                "session_type": session_type,
                "driver_a": codes[0],
                "driver_b": codes[1],
            }

    return None


def _extract_json_object(text: str) -> dict:
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _build_analysis_plan(message: str, resolved: dict) -> dict | None:
    if resolved.get("analysis_mode") != "driver_comparison":
        return None

    round_number = resolved.get("round_number")
    codes = resolved.get("entity_codes") or []
    names = resolved.get("entity_names") or []
    if round_number is None or len(codes) < 2 or len(names) < 2:
        return None

    focus = resolved.get("analysis_focus") or ("qualifying" if resolved.get("session_type") == "Q" else "race")
    session_type = "Q" if focus == "qualifying" else (resolved.get("session_type") or "R")

    plan = {
        "analysis_mode": "driver_comparison",
        "focus": focus,
        "question": message,
        "round_number": round_number,
        "drivers": [
            {"name": names[0], "code": codes[0]},
            {"name": names[1], "code": codes[1]},
        ],
        "tool_calls": [],
    }

    if focus == "qualifying":
        plan["tool_calls"] = [
            ("get_qualifying_results", {"round_number": round_number}),
            ("analyze_qualifying_battle", {
                "round_number": round_number,
                "driver_a": codes[0],
                "driver_b": codes[1],
            }),
            ("get_team_radio", {
                "round_number": round_number,
                "session_type": "Q",
                "driver_ref": codes[0],
                "limit": 6,
            }),
            ("get_team_radio", {
                "round_number": round_number,
                "session_type": "Q",
                "driver_ref": codes[1],
                "limit": 6,
            }),
        ]
        return plan

    if focus in ("race", "session"):
        plan["tool_calls"] = [
            ("get_driver_race_story", {"round_number": round_number, "driver_name": names[0]}),
            ("get_driver_race_story", {"round_number": round_number, "driver_name": names[1]}),
            ("get_safety_car_periods", {"round_number": round_number, "session_type": "R"}),
            ("analyze_energy_management", {
                "round_number": round_number,
                "session_type": resolved.get("session_type") or "R",
                "driver_a": codes[0],
                "driver_b": codes[1],
            }),
        ]
        return plan

    return None


def _retrieve_analysis_evidence(plan: dict) -> list[dict]:
    evidence = []
    for tool_name, args in plan.get("tool_calls", []):
        try:
            logger.info("Deterministic analysis tool call: %s args=%s", tool_name, args)
            evidence.append({
                "tool": tool_name,
                "args": args,
                "result": execute_tool(tool_name, args),
            })
        except Exception as exc:
            evidence.append({
                "tool": tool_name,
                "args": args,
                "error": str(exc),
            })
    return evidence


def _prepare_resolved_context(message: str, history: list[dict]) -> tuple[dict, dict | None]:
    previous_context = resolve_context_from_history(history)
    return _prepare_resolved_context_from_previous(message, previous_context)


def _prepare_resolved_context_from_previous(message: str, previous_context: dict | None) -> tuple[dict, dict | None]:
    resolved = resolve_query_context(message, previous_context)

    preloaded = None
    if resolved.get("routing_confidence") == "high":
        args = _suggested_tool_args(resolved)
        tool = resolved.get("suggested_tool")
        if tool and args:
            try:
                logger.info("Preloading suggested tool: %s args=%s", tool, args)
                preloaded = {
                    "tool": tool,
                    "args": args,
                    "result": execute_tool(tool, args),
                }
            except Exception as exc:
                logger.warning("Preload failed for tool %s args=%s error=%s", tool, args, exc)
                preloaded = {
                    "tool": tool,
                    "args": args,
                    "error": str(exc),
                }

    return resolved, preloaded


def _build_request_system_prompt(resolved: dict, preloaded: dict | None) -> str:
    if not resolved.get("has_explicit_context") and not resolved.get("used_previous_context"):
        return SYSTEM_PROMPT

    lines = [
        "Deterministic backend-resolved context for the latest user message:",
        f"- entity_type: {resolved.get('entity_type')}",
        f"- entity_name: {resolved.get('entity_name')}",
        f"- entity_code: {resolved.get('entity_code')}",
        f"- event_name: {resolved.get('event_name')}",
        f"- round_number: {resolved.get('round_number')}",
        f"- session_type: {resolved.get('session_type')}",
        f"- scope: {resolved.get('scope')}",
        f"- suggested_tool: {resolved.get('suggested_tool')}",
        f"- resolution_confidence: {resolved.get('resolution_confidence')}",
        f"- routing_confidence: {resolved.get('routing_confidence')}",
        f"- used_previous_context: {resolved.get('used_previous_context')}",
        "Treat this resolved context as higher priority than ambiguous prior chat history.",
    ]

    if resolved.get("routing_confidence") == "medium" and resolved.get("suggested_tool"):
        lines.append(
            f"Routing directive: start with {resolved.get('suggested_tool')} unless the latest message explicitly requires a narrower tool."
        )

    if preloaded:
        lines.append("High-confidence backend preloaded tool result:")
        lines.append(f"- preloaded_tool: {preloaded.get('tool')}")
        lines.append(f"- preloaded_args: {preloaded.get('args')}")
        if "result" in preloaded:
            lines.append(f"- preloaded_result_json: {json.dumps(preloaded['result'], default=str)}")
        if "error" in preloaded:
            lines.append(f"- preloaded_error: {preloaded['error']}")

    return SYSTEM_PROMPT + "\n\n" + "\n".join(lines)


def _build_analysis_user_prompt(question: str, resolved: dict, plan: dict, evidence: list[dict]) -> str:
    payload = {
        "question": question,
        "resolved_context": {
            "event_name": resolved.get("event_name"),
            "round_number": resolved.get("round_number"),
            "session_type": resolved.get("session_type"),
            "analysis_mode": resolved.get("analysis_mode"),
            "analysis_focus": resolved.get("analysis_focus"),
            "entity_names": resolved.get("entity_names"),
            "entity_codes": resolved.get("entity_codes"),
        },
        "plan": plan,
        "evidence": evidence,
    }
    return json.dumps(payload, default=str)


def _build_answer_writer_prompt(question: str, analysis: dict) -> str:
    return json.dumps({
        "question": question,
        "analysis": analysis,
    }, default=str)


def _try_deterministic_analysis(question: str, history: list[dict], *, provider: str) -> dict | None:
    previous_context = resolve_context_from_history(history)
    resolved = resolve_query_context(question, previous_context)
    plan = _build_analysis_plan(question, resolved)
    if not plan:
        return None

    evidence = _retrieve_analysis_evidence(plan)
    if not evidence:
        return None

    try:
        if provider == "openai":
            analysis = _run_openai_analysis(question, resolved, plan, evidence)
            return {
                "response": _run_openai_answer_writer(question, analysis),
                "widgets": _widgets_from_analysis_evidence(plan, evidence),
            }

        analysis = _run_anthropic_analysis(question, resolved, plan, evidence)
        return {
            "response": _run_anthropic_answer_writer(question, analysis),
            "widgets": _widgets_from_analysis_evidence(plan, evidence),
        }
    except Exception as exc:
        logger.warning("Deterministic analysis failed; falling back to normal tool loop. error=%s", exc)
        return None

def _get_anthropic_client() -> anthropic.Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.Anthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY")
        )
    return _anthropic_client


def _run_anthropic_analysis(question: str, resolved: dict, plan: dict, evidence: list[dict]) -> dict:
    client = _get_anthropic_client()
    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1200,
        system=ANALYSIS_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": _build_analysis_user_prompt(question, resolved, plan, evidence),
        }],
    )
    text = "".join(block.text for block in response.content if hasattr(block, "text"))
    return _extract_json_object(text)


def _run_anthropic_answer_writer(question: str, analysis: dict) -> str:
    client = _get_anthropic_client()
    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1200,
        system=ANSWER_WRITER_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": _build_answer_writer_prompt(question, analysis),
        }],
    )
    return "".join(block.text for block in response.content if hasattr(block, "text")).strip()


def _answer_anthropic(message: str, history: list[dict]) -> dict:
    client = _get_anthropic_client()
    resolved, preloaded = _prepare_resolved_context(message, history)
    request_system_prompt = _build_request_system_prompt(resolved, preloaded)
    messages = [{"role": h["role"], "content": h["content"]} for h in history]
    messages.append({"role": "user", "content": message})

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=4096,
            system=request_system_prompt,
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    return {
                        "response": block.text,
                        "widgets": _widgets_from_preloaded(preloaded),
                    }
            raise ValueError("Claude returned end_turn but no text content block")

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                try:
                    logger.info("Anthropic tool call: %s args=%s", block.name, block.input)
                    result = execute_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, default=str),
                    })
                except Exception as exc:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(exc),
                        "is_error": True,
                    })
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

        else:
            raise ValueError(f"Unexpected stop_reason from Claude: {response.stop_reason!r}")

    raise ValueError(f"Exceeded {MAX_TOOL_ROUNDS} tool-call rounds without a final answer.")


# ── OpenAI ───────────────────────────────────────────────────────────────────

_openai_client: openai_sdk.OpenAI | None = None

def _get_openai_client() -> openai_sdk.OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = openai_sdk.OpenAI(
            api_key=os.environ.get("OPENAI_API_KEY")
        )
    return _openai_client


def _run_openai_analysis(question: str, resolved: dict, plan: dict, evidence: list[dict]) -> dict:
    client = _get_openai_client()
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
            {"role": "user", "content": _build_analysis_user_prompt(question, resolved, plan, evidence)},
        ],
        response_format={"type": "json_object"},
    )
    return _extract_json_object(response.choices[0].message.content)


def _run_openai_answer_writer(question: str, analysis: dict) -> str:
    client = _get_openai_client()
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": ANSWER_WRITER_SYSTEM_PROMPT},
            {"role": "user", "content": _build_answer_writer_prompt(question, analysis)},
        ],
    )
    return response.choices[0].message.content.strip()


def _answer_openai(message: str, history: list[dict]) -> dict:
    client = _get_openai_client()
    resolved, preloaded = _prepare_resolved_context(message, history)
    request_system_prompt = _build_request_system_prompt(resolved, preloaded)
    messages = [{"role": "system", "content": request_system_prompt}]
    messages += [{"role": h["role"], "content": h["content"]} for h in history]
    messages.append({"role": "user", "content": message})

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            tools=OPENAI_TOOL_DEFINITIONS,
            tool_choice="auto",
        )

        choice = response.choices[0]

        if choice.finish_reason == "stop":
            return {
                "response": choice.message.content,
                "widgets": _widgets_from_preloaded(preloaded),
            }

        if choice.finish_reason == "tool_calls":
            # Append the assistant turn (contains the tool_calls)
            messages.append(choice.message)

            # Execute each tool call and append results
            for tool_call in choice.message.tool_calls:
                try:
                    args = json.loads(tool_call.function.arguments)
                    logger.info("OpenAI tool call: %s args=%s", tool_call.function.name, args)
                    result = execute_tool(tool_call.function.name, args)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, default=str),
                    })
                except Exception as exc:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": f"Error: {exc}",
                    })

        else:
            raise ValueError(f"Unexpected finish_reason from OpenAI: {choice.finish_reason!r}")

    raise ValueError(f"Exceeded {MAX_TOOL_ROUNDS} tool-call rounds without a final answer.")


# ── Public interface ─────────────────────────────────────────────────────────

def answer_f1_payload(message: str, history: list[dict] | None = None) -> dict:
    """
    Answer an F1 question using the configured LLM provider.

    history: list of prior {role, content} dicts from the conversation.
    Reads LLM_PROVIDER from the environment (default: 'anthropic').
    """
    prior = history or []
    provider = os.environ.get("LLM_PROVIDER", "anthropic").lower()
    deterministic = _try_deterministic_analysis(message, prior, provider=provider)
    if deterministic:
        return deterministic
    if provider == "openai":
        return _answer_openai(message, prior)
    return _answer_anthropic(message, prior)


def answer_f1_question(message: str, history: list[dict] | None = None) -> str:
    return answer_f1_payload(message, history)["response"]
