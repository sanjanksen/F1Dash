# Deterministic Parallel Tool Execution Plan

> Status: implemented.

## Goal

Reduce latency for deterministic analysis workflows by executing independent planned tool calls concurrently while preserving the exact evidence shape, ordering, error behavior, and widget behavior that the rest of `chat.py` expects.

This targets deterministic workflows only. LLM-directed Anthropic/OpenAI tool-call rounds remain sequential in this plan.

## Current Behavior

Deterministic analysis is built in `server/chat.py`:

- `_build_analysis_plan()` creates a `plan` with `tool_calls`.
- `_try_deterministic_analysis()` calls `_retrieve_analysis_evidence(plan, resolved)`.
- `_retrieve_analysis_evidence()` currently loops through `plan["tool_calls"]` and calls `execute_tool()` one at a time.

Current execution model:

```text
tool A starts -> tool A finishes -> tool B starts -> tool B finishes -> tool C starts -> tool C finishes
```

Target execution model:

```text
tool A starts
tool B starts
tool C starts
wait for all
return evidence in original plan order
```

## Scope

Parallelize planned deterministic tool calls for all workflows that use `_retrieve_analysis_evidence()`:

- `circuit_profile`
- `team_performance`
- `team_circuit_fit`
- `grip_comparison`
- `race_pace_comparison`
- `driver_comparison` qualifying
- `driver_comparison` race/session

Do not parallelize in this change:

- `_preload_resolved_context()`
- Anthropic `tool_use` rounds
- OpenAI `tool_calls` rounds
- Post-tool context injection for driver styles and circuit profiles

Those paths can reuse the same helper later if this proves stable.

## Design Choice

Use `concurrent.futures.ThreadPoolExecutor`.

Reasoning:

- The tool functions are synchronous today.
- Many tool calls are I/O-bound or session-load-bound, so threads are the lowest-friction fit.
- `ProcessPoolExecutor` would require pickling large objects and does not fit the shared FastF1/session/cache state well.
- `InterpreterPoolExecutor` exists in modern Python, but the isolation model is a poor fit for this codebase because tools rely on imported modules, caches, and shared process state.

Use a conservative cap:

```python
MAX_DETERMINISTIC_TOOL_WORKERS = 4
```

Then per batch:

```python
max_workers = min(MAX_DETERMINISTIC_TOOL_WORKERS, len(tool_calls))
```

## Implementation Plan

### Task 1: Add Imports And Worker Constant

File:

- `server/chat.py`

Add:

```python
from concurrent.futures import ThreadPoolExecutor
```

Near other module constants, add:

```python
MAX_DETERMINISTIC_TOOL_WORKERS = 4
```

Do not make this configurable yet unless tests or runtime use show a need.

### Task 2: Extract Single Tool Execution Helper

File:

- `server/chat.py`

Create:

```python
def _execute_analysis_tool_call(tool_name: str, args: dict) -> dict:
    try:
        logger.info("Deterministic analysis tool call: %s args=%s", tool_name, args)
        result = execute_tool(tool_name, args)
        if tool_name in ("analyze_cornering_loads", "analyze_race_cornering_profile"):
            result = {k: v for k, v in result.items() if k != "per_corner"}
        return {
            "tool": tool_name,
            "args": args,
            "result": result,
        }
    except Exception as exc:
        return {
            "tool": tool_name,
            "args": args,
            "error": str(exc),
        }
```

Acceptance:

- The returned dict shape exactly matches the current `_retrieve_analysis_evidence()` behavior.
- Cornering tools still strip `per_corner`.
- Errors remain per-tool evidence records, not fatal exceptions.

### Task 3: Add Ordered Parallel Batch Helper

File:

- `server/chat.py`

Create:

```python
def _execute_analysis_tool_calls(tool_calls: list[tuple[str, dict]]) -> list[dict]:
    if not tool_calls:
        return []
    if len(tool_calls) == 1:
        tool_name, args = tool_calls[0]
        return [_execute_analysis_tool_call(tool_name, args)]

    max_workers = min(MAX_DETERMINISTIC_TOOL_WORKERS, len(tool_calls))
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="f1dash-analysis-tool") as executor:
        futures = [
            executor.submit(_execute_analysis_tool_call, tool_name, args)
            for tool_name, args in tool_calls
        ]
        return [future.result() for future in futures]
```

Why collect with `[future.result() for future in futures]` instead of `as_completed()`:

- The returned evidence must preserve plan order.
- Individual helper catches exceptions, so `future.result()` should not raise for normal tool failures.
- The code stays simple and deterministic.

### Task 4: Replace The Sequential Loop

File:

- `server/chat.py`

Change `_retrieve_analysis_evidence()` from:

```python
evidence = []
for tool_name, args in plan.get("tool_calls", []):
    ...
```

To:

```python
evidence = _execute_analysis_tool_calls(plan.get("tool_calls", []))
```

Leave the existing driver-style and circuit-profile context injection after this unchanged.

### Task 5: Add Tests

File:

- `server/tests/test_chat.py`

Add tests for the helper behavior directly.

#### Test: Preserves Original Order

Patch `chat.execute_tool` so one fake call sleeps longer than another. The returned evidence should still match the original plan order.

Expected:

```python
assert [item["tool"] for item in evidence] == ["slow_tool", "fast_tool"]
```

#### Test: Runs Concurrently

Use a `threading.Barrier(2)` inside patched `execute_tool` for two calls.

If execution is sequential, the first call blocks forever waiting for the second. Use a short timeout in the barrier and fail if broken.

Expected:

- Both calls start before either completes.
- Evidence contains two successful results.

#### Test: Per-Tool Failure Does Not Cancel Batch

Patch one tool to raise and another to return normally.

Expected:

- Failed tool evidence has `"error"`.
- Successful tool evidence has `"result"`.
- Both evidence records are present in original order.

#### Test: Cornering Payload Still Strips `per_corner`

Patch `execute_tool` to return:

```python
{"summary": {"x": 1}, "per_corner": [{"corner": 1}]}
```

Call `_execute_analysis_tool_call("analyze_cornering_loads", args)`.

Expected:

```python
assert "per_corner" not in evidence["result"]
```

#### Test: Single Call Uses Same Shape

Call `_execute_analysis_tool_calls([("tool_a", {})])`.

Expected:

- One evidence record.
- Same shape as multi-call.

### Task 6: Verification

Run:

```bash
cd server
python -m pytest tests/test_chat.py -v
python -m pytest tests/ -v
```

## Behavioral Expectations By Workflow

### `circuit_profile`

Can run together:

- `get_circuit_profile`
- `get_circuit_track_map`
- `get_historical_circuit_performance`

Risk: low. These are independent evidence sources.

### `team_performance`

Only one planned tool today:

- `analyze_team_performance`

No parallel speedup, but behavior should remain unchanged.

### `team_circuit_fit`

Can run together:

- `analyze_team_circuit_fit`
- `get_team_car_profile`
- `analyze_team_telemetry_traits` when `round_number` exists

Risk: low to moderate. The telemetry tool may load session data while circuit-fit logic does other work. Keep worker cap conservative.

### `grip_comparison`

Only one planned tool today:

- `analyze_cornering_loads`

No speedup.

### `race_pace_comparison`

Can run together:

- `analyze_race_pace_battle`
- `get_safety_car_periods`
- `get_driver_strategy`

Risk: moderate. These may load overlapping race/session data. Shared session caching should help, but duplicate concurrent loads may briefly increase CPU/memory.

### `driver_comparison` Qualifying

Can run together:

- qualifying results
- `analyze_qualifying_battle`
- `compare_corner_profiles`
- `analyze_cornering_loads`
- team radio for driver A
- team radio for driver B

Risk: moderate. Several tools may touch the same FastF1 session. Cap workers at 4 to avoid starting all six at once.

### `driver_comparison` Race/Session

Can run together:

- race story for driver A
- race story for driver B
- `analyze_race_pace_battle`
- `get_safety_car_periods`

Risk: moderate. Race story and pace battle may overlap in session/result loading.

## Self-Critique

### What This Plan Gets Right

- It parallelizes at the narrowest useful point: `_retrieve_analysis_evidence()`.
- It benefits every deterministic workflow without rewriting each workflow.
- It preserves the existing evidence contract, so downstream analysis, answer writing, and widgets do not need to change.
- It keeps error behavior non-fatal per tool, matching current behavior.
- It keeps worker count conservative to avoid hammering FastF1/session loading.
- It deliberately avoids model-directed tool-call parallelism in the same patch, reducing blast radius.

### Risks And Weak Spots

- FastF1/session loading may not be perfectly thread-safe under simultaneous first loads of the same session. If this appears, the fix is likely to serialize session-load-heavy tools per `(round_number, session_type)` or add locking around `_load_session()`.
- Parallel duplicate session loads could use more memory briefly, especially in qualifying comparison workflows.
- The tests can prove concurrency at the helper level, but they cannot fully prove FastF1 thread safety without integration tests against real sessions.
- `future.result()` in original order means if the first tool is slow, evidence collection waits on it before reading later completed futures. That is acceptable because the deterministic workflow needs all evidence before analysis anyway.
- The worker cap is hard-coded. That is simpler, but if deployment resources vary, an environment variable may eventually be better.
- A shared global thread pool might be more efficient than creating one per deterministic request, but per-request pools are easier to reason about and clean up promptly.

### Deliberate Non-Goals

- No parallelism inside individual tools like `analyze_race_pace_battle`.
- No changes to FastF1 session cache locking unless tests or runtime behavior prove it necessary.
- No parallel execution for Anthropic/OpenAI model-chosen tool rounds in this plan.
- No cancellation/timeouts beyond existing request-level behavior.

### Possible Follow-Up

If deterministic parallel execution is stable, extract the batch helper into a generic tool-call executor and reuse it for Anthropic/OpenAI multi-tool rounds while preserving provider-specific response formatting.

## Implementation Notes

- Implemented in `server/chat.py` with `_execute_analysis_tool_call()` and `_execute_analysis_tool_calls()`.
- Deterministic planned tool calls now run with a capped `ThreadPoolExecutor`.
- Evidence order is preserved by collecting futures in submission order.
- Single-tool plans still run directly without thread-pool overhead.
- Per-tool errors remain non-fatal evidence records.
- Cornering payloads still strip `per_corner` before reaching the analysis LLM.

## Validation

- [x] `python -m pytest tests/test_chat.py -v`
- [x] `python -m pytest tests/ -v`
