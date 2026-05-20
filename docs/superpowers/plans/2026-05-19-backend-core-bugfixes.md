# Backend Core Bug Fixes Implementation Plan

> Status: not started. Estimated effort: 3–4 days of focused work.

## Goal

Land the minimum fixes for seven backend reliability and clarity bugs surfaced by the 2026-05-19 audit. Each task is independent and shippable on its own. The plan deliberately scopes each fix narrowly so it does not block the wider "backend-resilience" feature plan, which will deliver broader hardening (retries, structured error responses, circuit breakers) on top of these foundations.

## Background

The audit identified seven concrete defects in `server/` that all share a common smell: bare-`except` handling, missing typed errors, and silent stub responses that let the LLM confabulate around missing data. None are pure feature work — each is a real bug with a one- or two-file fix. They should not be bundled into a larger refactor; each lands behind its own commit.

| # | Bug | Files | Severity |
|---|---|---|---|
| 1 | `_load_session()` has 25 unhandled call sites | `server/f1_data.py` | High — most-traveled code path |
| 2 | HTTP endpoints discard exception type | `server/main.py` | Medium — observability |
| 3 | Anthropic API errors mistyped as bugs | `server/chat.py` | High — user-visible |
| 4 | Tool args accessed by `KeyError`-prone subscript | `server/tools.py` | Medium — agentic loop self-correction blocked |
| 5 | Missing profile stubs are silent | `server/tools.py` | Medium — LLM confabulation source |
| 6 | Mixed speed units (kph vs m/s) | `server/f1_data.py` | Medium — subtle correctness bug |
| 7 | Duplicate evidence shaping across deterministic + agentic paths | `server/tools.py`, `server/chat.py` | Medium — divergence risk |

## Overlap With Future Feature Work

Several of these bugs touch surface area that the in-progress **backend-resilience** feature plan will harden further. The bug plan stays minimal; the feature plan layers retries, structured error envelopes, and per-tool circuit breakers on top.

| Bug task | Minimum fix here | Broader hardening deferred to backend-resilience |
|---|---|---|
| Task 1 (`_load_session`) | Wrap `fastf1.get_session()` once; raise typed error | Add bounded retry with jitter for FastF1 livetiming flakiness |
| Task 2 (HTTP endpoints) | Log exception type; sanitised detail | JSON error envelope schema across all endpoints |
| Task 3 (Anthropic errors) | Typed catches at three call sites | Token-bucket pre-rate-limit, fallback model routing |
| Task 4 (tool args) | `_require_args()` helper at one site | Pydantic-validated tool-call schemas across the registry |

Tasks 5, 6, 7 are bug-only — no overlap.

---

## Task 1: Wrap `_load_session()` And Audit Its 25 Call Sites

Files:

- Modify: `server/f1_data.py`
- Test: `server/tests/test_f1_data.py`

Current state: `_load_session()` at `server/f1_data.py:40` calls `fastf1.get_session()` (line 51) and `session.load()` (line 80) with no exception handling. The 25 call sites listed in the audit (lines 635, 665, 755, 801, 845, 1565, 1630, 1716, 1802, 1873, 2457, 3110, 3573, 3683, 3883, 3927, 4000, 4712, 4913, 4968, 5481, 5829, 6066, 6162, 6267, 6360) treat the returned `session` as always-valid. A FastF1 cache miss or livetiming outage produces an unhandled exception that bubbles up as a generic 500.

Change:

1. Define a narrow typed error near the top of `f1_data.py`:

```python
class FastF1Error(RuntimeError):
    """Raised when FastF1 cannot load the requested session."""

    def __init__(self, message: str, *, round_number: int, session_type: str, cause: Exception | None = None):
        super().__init__(message)
        self.round_number = round_number
        self.session_type = session_type
        self.__cause__ = cause
```

2. Wrap the two FastF1 calls inside `_load_session()` (lines 51 and 80) in a try/except that re-raises `FastF1Error`. Preserve the existing cache invariants — do not leave a half-loaded entry in `_SESSION_CACHE` if `session.load()` fails.

3. Audit the 25 call sites. For each, the wrapper function should catch `FastF1Error` and return a payload the caller (chat widget builder) can render as "data not yet available for round X session Y" rather than a 500. Concretely:
   - Wrapper functions that already return a dict (most of them) should return `{"available": False, "reason": "fastf1_unavailable", "round_number": ..., "session_type": ...}`.
   - Wrapper functions that raise `ValueError` for missing data should also raise `ValueError` here, with the FastF1Error chained.

4. Do not catch `FastF1Error` inside `_load_session()` itself — callers decide the recovery strategy.

Acceptance:

- `FastF1Error` is defined exactly once in `f1_data.py` and exported through the public API surface as needed.
- All 25 call sites compile and have an explicit recovery path documented by code (not a comment).
- A unit test patches `fastf1.get_session` to raise `RuntimeError`; `_load_session()` surfaces `FastF1Error` with the round number and session type attached.
- A unit test patches `_load_session` to raise `FastF1Error`; at least three representative wrappers return `{"available": False, ...}` rather than propagating.
- Existing tests pass unchanged.

Tests to add (`server/tests/test_f1_data.py`):

- `test_load_session_wraps_get_session_failure`
- `test_load_session_wraps_load_failure_clears_cache_entry`
- `test_get_race_results_returns_unavailable_on_fastf1_error`
- `test_analyze_stint_degradation_returns_unavailable_on_fastf1_error`
- `test_get_lap_telemetry_returns_unavailable_on_fastf1_error`

Risk note: this is the riskiest task in the plan because 25 call sites change shape. Land it behind a feature commit and run the full suite before moving on.

---

## Task 2: Log Exception Type In Every HTTP Endpoint

Files:

- Modify: `server/main.py`
- Test: `server/tests/test_main.py` (create if missing)

Current state: `server/main.py:45`, `:61`, `:70`, `:83` all catch bare `Exception`, call `logger.exception(...)`, and raise `HTTPException(500)` with a generic detail string. The exception **type** never reaches the log line in a structured form, so triaging from logs requires grepping the stack trace.

Change:

1. Replace each `except Exception as e:` block with the following pattern (example for `/api/drivers`):

```python
except Exception as e:
    logger.warning(
        "Error in GET /api/drivers: %s",
        type(e).__name__,
        exc_info=True,
    )
    raise HTTPException(
        status_code=500,
        detail=f"Failed to fetch drivers ({type(e).__name__}).",
    )
```

2. Use `logger.warning` with `exc_info=True` rather than `logger.exception` so the level is correct (these are not always errors — FastF1 outages are operational) and the stack trace still lands.

3. **Never** include `str(e)` in the HTTPException detail. Only the type name. Some exceptions stringify to filesystem paths, internal URLs, or credentials.

4. Add the same treatment to the `/api/chat` endpoint at `:83`.

Acceptance:

- All four endpoints log `type(e).__name__` as a structured field (`%s` argument).
- All four endpoints include the type name (not message) in the `detail`.
- A test patches `get_drivers` to raise `FileNotFoundError`; the response body's `detail` contains `"FileNotFoundError"` and does not contain the file path.
- A test patches `get_circuits` to raise `ConnectionError`; the warning log contains `"ConnectionError"`.

Tests to add (`server/tests/test_main.py`):

- `test_drivers_endpoint_returns_type_in_detail`
- `test_circuits_endpoint_does_not_leak_exception_message`
- `test_chat_endpoint_returns_type_in_detail`

---

## Task 3: Typed Handlers For Anthropic API Errors

Files:

- Modify: `server/chat.py`
- Test: `server/tests/test_chat.py`

Current state: three Anthropic `client.messages.create()` call sites at `server/chat.py:1711`, `:1726`, `:1751` and three OpenAI `client.chat.completions.create()` call sites at `:1822`, `:1835`, `:1859` have no typed exception handling. A `RateLimitError` currently looks like a code bug in logs and surfaces to the user as the same generic 500 as any other crash.

Change:

1. Import the typed errors at module top:

```python
import anthropic
# anthropic.RateLimitError, anthropic.APIError, anthropic.APIConnectionError, anthropic.APIStatusError
```

For OpenAI:

```python
import openai
# openai.RateLimitError, openai.APIError, openai.APIConnectionError
```

2. Wrap each of the six call sites with a small helper that returns a tagged result rather than re-raising. Suggested signature near the top of `chat.py`:

```python
class LLMTransientError(RuntimeError):
    """Raised when a model-provider call should be surfaced as 'retry later'."""

    def __init__(self, message: str, *, provider: str, kind: str):
        super().__init__(message)
        self.provider = provider
        self.kind = kind  # "rate_limit" | "connection" | "api"


def _call_anthropic(client, **kwargs):
    try:
        return client.messages.create(**kwargs)
    except anthropic.RateLimitError as e:
        logger.warning("Anthropic rate-limited: %s", type(e).__name__)
        raise LLMTransientError("Anthropic rate-limited", provider="anthropic", kind="rate_limit") from e
    except anthropic.APIConnectionError as e:
        logger.warning("Anthropic connection error: %s", type(e).__name__)
        raise LLMTransientError("Anthropic connection error", provider="anthropic", kind="connection") from e
    except anthropic.APIError as e:
        logger.error("Anthropic API error: %s", type(e).__name__, exc_info=True)
        raise LLMTransientError("Anthropic API error", provider="anthropic", kind="api") from e


def _call_openai(client, **kwargs):
    # symmetric wrapper for openai.RateLimitError / APIConnectionError / APIError
    ...
```

3. Replace each call site with `_call_anthropic(client, ...)` / `_call_openai(client, ...)`.

4. In `answer_f1_payload()` / `answer_f1_question()`, catch `LLMTransientError` at the outermost level and return a user-visible message:

> *"The model is throttling right now — please retry in a moment."* (`rate_limit`)
> *"I lost the connection to the model — please retry."* (`connection`)
> *"The model API returned an error — please retry."* (`api`)

These should come back as a normal chat payload (`{"text": ..., "widgets": []}`), not as an HTTP 500. The HTTP layer stays clean.

Acceptance:

- All six call sites go through `_call_anthropic` / `_call_openai`.
- A test patches `client.messages.create` to raise `anthropic.RateLimitError`; `answer_f1_payload` returns a payload whose text contains "throttling" and whose widgets list is empty.
- A test patches `client.messages.create` to raise `anthropic.APIConnectionError`; same shape, message contains "lost the connection".
- Log lines for rate limits use level `warning`, not `error`.

Tests to add (`server/tests/test_chat.py`):

- `test_answer_f1_payload_returns_throttle_message_on_rate_limit`
- `test_answer_f1_payload_returns_connection_message_on_connection_error`
- `test_answer_f1_payload_logs_warning_not_error_on_rate_limit`
- Symmetric tests for OpenAI provider.

---

## Task 4: Add `_require_args()` For Tool Arg Validation

Files:

- Modify: `server/tools.py`
- Test: `server/tests/test_tools.py`

Current state: `server/tools.py` accesses required args via `args["driver_name"]`, `args["round_number"]`, `args["driver_a"]`, etc. at dozens of branches inside `execute_tool()` (representative lines: 712, 718, 725, 729, 731, 733, 739, 741, 743, 751, 761, 778, 790, 815, 843, 851, 857, 869). When the LLM emits a malformed tool call (missing arg), a `KeyError` becomes an unhandled 500 in the agentic loop rather than being fed back to Claude as a tool-error result it can self-correct from.

Change:

1. Add a small helper at the top of `execute_tool()`:

```python
def _require_args(args: dict, required: list[str], tool_name: str) -> None:
    missing = [k for k in required if k not in args or args[k] in (None, "")]
    if missing:
        raise ValueError(
            f"Tool {tool_name!r} called without required arg(s): {', '.join(missing)}. "
            f"Please retry with the missing field(s) populated."
        )
```

2. At the top of each branch that uses `args["..."]` for a required key, call `_require_args(args, [...], name)` first. Example for the `get_driver_season_stats` branch at line 717:

```python
if name == "get_driver_season_stats":
    _require_args(args, ["driver_name"], name)
    stats = get_driver_stats(args["driver_name"])
    ...
```

3. The agentic loop in `chat.py` already catches `ValueError` from `execute_tool()` and feeds it back to the model as a tool-error result block. Confirm this still happens — do not change the loop. If the loop currently swallows `ValueError`, add a small inline assertion ("feed `str(e)` back into the next tool-result message") rather than re-architecting.

4. Branches with mixed required + optional args (e.g. `analyze_cornering_loads` at line 774) require only the required ones in the helper call. Do not validate optional args.

5. Apply this to all branches in `execute_tool()` that use the subscript form on a required key. Estimated coverage: ~40 branches.

Acceptance:

- `_require_args()` is defined once and used at every branch that requires a key.
- A test calls `execute_tool("get_driver_season_stats", {})` and gets a `ValueError` whose message contains `"driver_name"`.
- A test confirms the agentic loop in `chat.py` translates that `ValueError` into a tool-result message visible to the next model turn (mock the LLM client; assert the tool-result content includes `"required arg"`).
- Existing happy-path tests pass unchanged.

Tests to add (`server/tests/test_tools.py`):

- `test_require_args_raises_value_error_listing_missing_keys`
- `test_execute_tool_missing_driver_name_raises_value_error`
- `test_execute_tool_missing_round_number_raises_value_error`
- `test_execute_tool_missing_driver_a_and_b_raises_value_error_listing_both`

Tests to add (`server/tests/test_chat.py`):

- `test_agentic_loop_feeds_value_error_back_as_tool_result`

---

## Task 5: WARN-Log And Surface Missing Profile Stubs

Files:

- Modify: `server/tools.py`
- Test: `server/tests/test_tools.py`

Current state: `server/tools.py:873–901` covers `get_team_car_profile` and `get_driver_style_profile`. When the lookup misses, the branch silently returns `{"available": False, ...}` stubs. There is no log entry, so the curated knowledge base never gets corrected. Worse, the LLM may not key on the `available` flag and confabulates around the gap.

Change:

1. In the `get_team_car_profile` branch (line 873), when `profile is None`:

```python
logger.warning(
    "Missing team_car_profile for query=%r — add an entry to team_car_profiles.py",
    args["team_name"],
)
return {
    "team_query": args["team_name"],
    "profile_type": "curated_editorial",
    "available": False,
    "caveat": "No sourced public-reporting profile is currently curated for this team.",
    "guidance_for_model": (
        "I do not have a curated car-character profile for this team. "
        "Do not invent traits — say the profile is unavailable."
    ),
}
```

2. In the `get_driver_style_profile` branch (line 888), when both single-driver and comparison lookups miss, log a WARN naming the missing driver code(s) and return a stub with the same `guidance_for_model` field.

3. Update the relevant system prompts in `chat.py` to instruct: *"If a tool result contains `available: False` and `guidance_for_model`, follow that guidance verbatim. Never paper over the gap with invented characteristics."*

4. Do not throttle the WARN log — a missing profile is a one-time concern; the audit trail across deploys is the value.

Acceptance:

- A test calls `execute_tool("get_team_car_profile", {"team_name": "NonexistentTeam"})` and asserts (a) the result has `"available": False`, (b) `caplog` captures a WARNING containing the team name and the file name `team_car_profiles.py`.
- A test calls `execute_tool("get_driver_style_profile", {"driver_a": "ZZZ"})` and asserts a WARNING containing `"ZZZ"`.
- System prompt change is visible in `SYSTEM_PROMPT` (or both system prompts if deterministic + agentic each have their own).

Tests to add (`server/tests/test_tools.py`):

- `test_get_team_car_profile_logs_warning_on_missing_team`
- `test_get_driver_style_profile_logs_warning_on_missing_driver`
- `test_get_driver_style_profile_logs_warning_on_missing_comparison_pair`

---

## Task 6: Add A `units.py` Conversion Module

Files:

- Add: `server/units.py`
- Modify: `server/f1_data.py` (worst-offender functions first)
- Test: `server/tests/test_units.py`

Current state: `server/f1_data.py` mixes `speed_kph` and raw FastF1 `m/s` across telemetry helpers. Conversion is inlined ad-hoc (`* 3.6`, `/ 3.6`, sometimes neither). This is a subtle source of off-by-3.6x bugs.

Change:

1. Create `server/units.py`:

```python
"""Unit conversion helpers. Convert at boundaries; keep kph internally."""

KPH_PER_MS = 3.6

def ms_to_kph(value: float | None) -> float | None:
    if value is None:
        return None
    return value * KPH_PER_MS

def kph_to_ms(value: float | None) -> float | None:
    if value is None:
        return None
    return value / KPH_PER_MS

def ms_to_kph_series(values):
    return [ms_to_kph(v) for v in values]
```

2. Audit telemetry-emitting functions in `f1_data.py` for `m/s` vs `kph`. Convert at the boundary where FastF1 returns telemetry. Pick the worst offenders first:
   - `get_lap_telemetry()` and helpers feeding `SpeedTrace` widget
   - `get_telemetry_comparison()`
   - `analyze_cornering_loads()`
   - `extract_corner_profiles()`

3. Standardise on **kph** in all outward-facing widget payloads. Internally, the moment FastF1 hands over telemetry, convert via `ms_to_kph_series()` once. No downstream code should call `* 3.6` or `/ 3.6` inline.

4. Refactor incrementally — do not attempt all callers in one commit. The acceptance is "the worst-offender three functions exclusively use the helpers"; leftover ones land in a follow-up.

Acceptance:

- `server/units.py` exists with `ms_to_kph`, `kph_to_ms`, `ms_to_kph_series`.
- A unit test covers None-passthrough, 0.0 round-trip, and a 100 m/s → 360 kph conversion.
- At least three of the worst-offender functions in `f1_data.py` route every m/s→kph conversion through the helpers.
- A targeted test asserts that `get_lap_telemetry()` emits kph values (max speed in a realistic range, e.g. 300–360 kph) and no longer emits raw m/s.
- A grep for `\* 3\.6` and `/ 3\.6` inside the refactored functions returns zero matches.

Tests to add (`server/tests/test_units.py`):

- `test_ms_to_kph_handles_none`
- `test_ms_to_kph_zero_round_trips`
- `test_ms_to_kph_canonical_value` (100 → 360)
- `test_kph_to_ms_canonical_value` (360 → 100)
- `test_ms_to_kph_series_preserves_length_and_nones`

Tests to add or extend (`server/tests/test_f1_data.py`):

- `test_get_lap_telemetry_emits_kph_not_ms`
- `test_telemetry_comparison_speed_units_are_kph`

Note: this is the only task that touches widget payload shape. The widgets already expect kph for the most part; double-check `client/src/components/chat-widgets/SpeedTrace.jsx` to confirm the axis label and that no client-side `* 3.6` exists. If found, remove in the same commit.

---

## Task 7: Extract Shared Evidence-Shaping Helpers

Files:

- Add: `server/evidence_shaping.py`
- Modify: `server/chat.py`, `server/tools.py`
- Test: `server/tests/test_evidence_shaping.py`

Current state: there are two analysis paths — deterministic (`_retrieve_analysis_evidence`/`_execute_analysis_tool_call` in `chat.py`) and agentic (the LLM tool-use loop in `chat.py` that calls into `tools.py`). Both perform evidence shaping and driver-style injection, but only one consistently strips `per_corner` from cornering payloads. The deterministic path strips correctly; the agentic path does not. The system prompt forbids `data_table` widgets for cornering data, but nothing enforces it.

Change:

1. Create `server/evidence_shaping.py` with shared functions:

```python
"""Shared evidence shaping for deterministic + agentic analysis paths.

Both paths must apply identical post-tool transformations so behavior does not
diverge. The system prompt's 'no data_table for cornering' rule is enforced
here, not by the LLM.
"""

CORNERING_TOOL_NAMES = frozenset({
    "analyze_cornering_loads",
    "analyze_race_cornering_profile",
    "compare_corner_profiles",
    "extract_corner_profiles",
})


def strip_heavy_payload_fields(tool_name: str, result: dict) -> dict:
    """Drop per_corner from cornering payloads. Apply uniformly to both paths."""
    if tool_name in CORNERING_TOOL_NAMES and isinstance(result, dict):
        return {k: v for k, v in result.items() if k != "per_corner"}
    return result


def is_cornering_evidence(tool_name: str) -> bool:
    return tool_name in CORNERING_TOOL_NAMES


def reject_data_table_for_cornering(widget_type: str, source_tool: str | None) -> bool:
    """Returns True if this widget should be suppressed. Use at widget-builder boundary."""
    return widget_type == "data_table" and source_tool in CORNERING_TOOL_NAMES
```

2. In `chat.py`:
   - Replace the inline `per_corner` strip inside `_execute_analysis_tool_call` (deterministic path) with `strip_heavy_payload_fields(tool_name, result)`.
   - Add a `strip_heavy_payload_fields(...)` call in the agentic loop right after `execute_tool(...)` returns, before the result is appended to the tool-result message.
   - At every `_make_data_table_widget(...)` call site (or equivalent), pass through `reject_data_table_for_cornering()`. If it returns True, skip the widget and emit a `corner_analysis` widget instead, or fall back to the cornering-specific widget the system prompt already prefers.

3. In `tools.py`: no logic change required. Optionally import `CORNERING_TOOL_NAMES` to keep names in one place rather than duplicating string literals.

4. Update both system prompts (deterministic + agentic) to remove or de-emphasise the `data_table`-cornering instruction now that it is enforced in code. Keep one short sentence acknowledging the constraint.

Acceptance:

- `evidence_shaping.py` exists with the three functions.
- Deterministic path's `_execute_analysis_tool_call` imports from `evidence_shaping` rather than inlining `{k: v for k, v in result.items() if k != "per_corner"}`.
- Agentic path also strips `per_corner` (new behavior).
- A test calls the agentic loop with a fake `analyze_cornering_loads` tool result containing `per_corner: [...]`; asserts the message sent to the next LLM turn does not include `per_corner`.
- A test calls the widget builder for a cornering tool with `widget_type="data_table"`; asserts the resulting widget is not a `data_table`.
- Both system prompts still pass their snapshot tests (update snapshots if the wording changed).

Tests to add (`server/tests/test_evidence_shaping.py`):

- `test_strip_heavy_payload_fields_drops_per_corner_for_cornering_tools`
- `test_strip_heavy_payload_fields_passthrough_for_other_tools`
- `test_is_cornering_evidence_recognises_all_four_tools`
- `test_reject_data_table_for_cornering_blocks_cornering_data_table`
- `test_reject_data_table_for_cornering_allows_non_cornering_data_table`

Tests to add (`server/tests/test_chat.py`):

- `test_agentic_loop_strips_per_corner_from_cornering_tool_result`
- `test_widget_builder_suppresses_data_table_for_cornering_tool`

---

## Validation Checklist

Cross-cutting. Run after each task lands; run all of these at the end of the slice.

- [ ] `cd server; python -m pytest tests/ -v` — full suite green.
- [ ] `cd client; npm run build` — frontend still compiles (only Task 6 / Task 7 could touch widget contracts).
- [ ] No bare `except Exception:` without a typed log of `type(e).__name__` remains in `server/main.py`, `server/chat.py`, `server/f1_data.py`.
- [ ] No HTTP response body contains a raw exception message string. Only the type name.
- [ ] `grep -n "args\[" server/tools.py` shows every branch guarded by a `_require_args(...)` call above it (or accesses are `args.get(...)` for optional args).
- [ ] `grep -rn "\* 3\.6\b" server/f1_data.py` returns zero matches inside the refactored worst-offender functions.
- [ ] `grep -n "per_corner" server/chat.py` shows the strip happens only through `strip_heavy_payload_fields()`.
- [ ] Manual smoke: open `:5173`, ask a cornering question; confirm widget is `corner_analysis` / `corner_comparison`, never `data_table`.
- [ ] Manual smoke: temporarily block egress to `api.anthropic.com`; submit a chat message; confirm a user-visible "throttling" / "connection" message rather than a 500.
- [ ] Manual smoke: submit a chat message for a season-old, uncurated team (e.g. an HRT/Caterham era query); confirm both the WARN log entry and the model declining to invent a profile.

---

## Risks and Open Questions

| Risk | When it triggers | Proposed resolution | Decision needed by |
|---|---|---|---|
| Task 1's audit of 25 call sites is mechanical; missing one leaves a 500 in production | Always | Land Task 1 behind a feature flag for one deploy, then remove flag. Or: keep a fallback `try/except FastF1Error` at the chat-payload assembly boundary. Recommend the latter — simpler. | Task 1 start |
| Task 3's user-visible "throttling" message races with the agentic loop's retry behavior (if it has one) | Phase rollout | Currently the loop does not retry on rate limit. Confirm; if it does, place the throttling message only at the final outermost catch so it does not surface on first-attempt retries. | Task 3 start |
| Task 4 catches `KeyError` indirectly by replacing subscript with explicit validation, but if a wrapper function (`get_race_results`, etc.) itself uses `args[...]`-style internal lookups, the fix is incomplete | Task 4 testing | Grep for `KeyError` traces in production logs (if any) before committing. Otherwise scope to the `execute_tool()` dispatch layer and document the boundary. | Task 4 start |
| Task 6's incremental refactor leaves some functions still using inline `* 3.6` — risk of half-converted state | Always | The acceptance criterion explicitly accepts incremental conversion (worst-offender three functions). Track the rest in a follow-up. Do not block the slice on full coverage. | Task 6 close-out |
| Task 7's data_table-for-cornering suppression could silently drop widgets the LLM legitimately wants | After Task 7 ships | Log at INFO when suppression fires, so we can audit how often it happens. If frequent, the system prompt or the widget builder is wrong, not the suppression. | Post-Task 7 |
| Snapshot tests for the system prompts (Task 7) may need updates | Task 7 testing | Acceptable. Update snapshots, eyeball the diff, commit. | Task 7 |

## Commit Plan

Each task lands as its own commit, in order:

1. `feat: typed FastF1Error wrapper around _load_session()`
2. `fix: 25 call sites recover from FastF1Error rather than 500`
3. `fix: log exception type and sanitise HTTP error details`
4. `fix: typed Anthropic/OpenAI error handling with user-visible throttling message`
5. `fix: validate required tool args at execute_tool() dispatch`
6. `fix: WARN-log missing curated profile stubs and surface guidance to model`
7. `refactor: centralise speed-unit conversion in server/units.py`
8. `refactor: shared evidence shaping for deterministic + agentic paths`

Commits 1 and 2 are split because the wrapper change (1) is isolated and reviewable independently from the 25-site audit (2). The remaining tasks are single commits.

## Non-Goals

- No retries, no jitter, no circuit breakers — those belong to the backend-resilience feature plan.
- No JSON error envelope schema across endpoints — same.
- No Pydantic validation of tool-call schemas — same. Task 4's helper is the minimum.
- No full m/s→kph conversion across every telemetry function — Task 6 is incremental by design.
- No frontend changes beyond removing a stale `* 3.6` if found.
- No system-prompt re-architecture — only the minimum wording changes Task 7 needs.

## References

- Companion plan: `2026-05-15-deterministic-parallel-tool-execution.md` — defines `_execute_analysis_tool_call` which Task 7 modifies.
- Companion plan: `2026-05-15-tire-cliff-detection.md` — uses `_load_session()` indirectly via `_fit_stint_degradation`; Task 1's wrapper must not break it.
- Companion plan: `2026-05-19-counterfactual-race-simulation.md` — depends on a stable `_load_session()` contract; Task 1 lands before any counterfactual work begins.
- Audit log: 2026-05-19, items #1–7.
