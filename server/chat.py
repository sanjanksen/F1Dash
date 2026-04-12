# server/chat.py
"""
Agentic chat loop supporting both Anthropic (Claude) and OpenAI (GPT).

Set LLM_PROVIDER=anthropic (default) or LLM_PROVIDER=openai in your .env.
The corresponding API key (ANTHROPIC_API_KEY / OPENAI_API_KEY) must also be set.
"""
import json
import os
import logging
import anthropic
import openai as openai_sdk
from tools import TOOL_DEFINITIONS, OPENAI_TOOL_DEFINITIONS, execute_tool
from resolver import resolve_query_context, resolve_context_from_history

MAX_TOOL_ROUNDS = 5
logger = logging.getLogger(__name__)

import datetime

CURRENT_YEAR = datetime.date.today().year

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
- For lap-by-lap pace: use get_driver_lap_times
- For corner-level analysis (braking points, gear shifts, throttle application): use get_lap_telemetry or get_telemetry_comparison. These include gear, RPM, throttle, and brake at every 100m — use them to make specific claims like "Norris was still in 4th gear at 1400m while Leclerc had already dropped to 3rd, braking 20m earlier"
- For racing-line or on-track position comparisons, track maps, or where a gain happened physically on the lap: use get_track_position_comparison
- For richer circuit-map context like marshal sectors/lights or rotation for track-map overlays: use get_circuit_details or get_circuit_corners
- For safety car / VSC questions, strategy impact, who got screwed by the SC: use get_safety_car_periods
- For deleted laps, race control decisions, incidents, or steward-style explanations: use get_race_control_messages
- For weather conditions, rain timing, temperature impact on tyres/pace: use get_session_weather

Answer quality rules:
- Stay focused on exactly what was asked. If asked about one driver, lead with that driver — don't pad the answer with other drivers' results unless directly relevant.
- Use the conversation history to understand follow-up questions. "where did he finish" or "what about Lando" refers to the race or context already discussed.
- Be concise. Lead with the key fact, then support with numbers."""


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

    return None


def _prepare_resolved_context(message: str, history: list[dict]) -> tuple[dict, dict | None]:
    previous_context = resolve_context_from_history(history)
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

def _get_anthropic_client() -> anthropic.Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.Anthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY")
        )
    return _anthropic_client


def _answer_anthropic(message: str, history: list[dict]) -> str:
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
                    return block.text
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


def _answer_openai(message: str, history: list[dict]) -> str:
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
            return choice.message.content

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

def answer_f1_question(message: str, history: list[dict] | None = None) -> str:
    """
    Answer an F1 question using the configured LLM provider.

    history: list of prior {role, content} dicts from the conversation.
    Reads LLM_PROVIDER from the environment (default: 'anthropic').
    """
    prior = history or []
    provider = os.environ.get("LLM_PROVIDER", "anthropic").lower()
    if provider == "openai":
        return _answer_openai(message, prior)
    return _answer_anthropic(message, prior)
