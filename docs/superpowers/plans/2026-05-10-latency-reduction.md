# F1Dash Latency Reduction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut response latency by parallelising tool execution, adding session-cache TTL eviction, and streaming the final Claude text token-by-token via SSE so the user sees output within seconds instead of waiting 15–30 s for a complete JSON blob.

**Architecture:** There are two execution paths (deterministic analysis and agentic loop). Both currently execute tool calls serially even when Claude batches them. We add `ThreadPoolExecutor` parallelism to both, add TTL eviction to the existing in-memory FastF1 session cache, and convert the `/api/chat` endpoint to SSE so the final text can stream as soon as Claude starts generating. The frontend accumulates deltas and re-renders on each chunk; the final `done` event carries clean text (widgets stripped) and the widget list.

**Tech Stack:** Python `concurrent.futures.ThreadPoolExecutor`, FastAPI `StreamingResponse`, Anthropic SDK streaming (`client.messages.stream()`), `asyncio.Queue` for thread↔async bridge, browser Fetch `ReadableStream`

---

## File Map

| File | Change |
|---|---|
| `server/f1_data.py` | Add `SESSION_CACHE_TTL` + `time.monotonic()` to existing `_SESSION_CACHE` entries |
| `server/chat.py` | Parallel tool dispatch in `_retrieve_analysis_evidence()` and `_answer_anthropic()`; add streaming variants of answer-writer, agentic loop, deterministic path, and public entry point |
| `server/main.py` | Replace `answer_f1_payload` call with SSE `StreamingResponse` + thread/queue bridge |
| `server/tests/test_f1_data.py` | Add TTL eviction test |
| `server/tests/test_chat.py` | Add parallel-dispatch timing tests |
| `server/tests/test_main.py` | Update chat endpoint test for SSE; add streaming test |
| `client/src/api/f1api.js` | Replace `res.json()` with SSE `ReadableStream` reader + `onDelta` callback |
| `client/src/App.jsx` | Pass `onDelta` to `sendChatMessage`, update partial message on each delta, finalize on `done` |

---

## Task 1: Session cache TTL eviction

**Context:** `server/f1_data.py` already has `_SESSION_CACHE` (a dict keyed by `(CURRENT_YEAR, round_number, session_type)`) and `_SESSION_CACHE_LOCK`, but entries are never evicted. Stale data is not a safety problem (session data doesn't change mid-day) but old objects accumulate. More importantly, knowing TTL is in place means we can safely let multiple parallel tools share the cache with confidence.

The existing entry structure is:
```python
{
    "session": <FastF1 Session>,
    "laps": bool, "telemetry": bool, "weather": bool, "messages": bool,
    "lock": threading.Lock(),
}
```

We add `"created_at": time.monotonic()` and evict on the next access if older than 5 minutes.

**Files:**
- Modify: `server/f1_data.py`
- Test: `server/tests/test_f1_data.py`

- [ ] **Step 1: Write the failing test**

Add to `server/tests/test_f1_data.py`:

```python
def test_session_cache_evicts_stale_entry():
    """An entry older than SESSION_CACHE_TTL is evicted and reloaded on next access."""
    import time
    import f1_data

    mock_session = MagicMock()
    mock_session.load = MagicMock()

    with patch("f1_data.fastf1") as mock_ff1, \
         patch("f1_data._validate_session_availability", return_value=None):

        mock_ff1.get_session.return_value = mock_session

        # First call — populates cache
        f1_data._load_session(1, "Q", laps=True)
        assert mock_ff1.get_session.call_count == 1

        # Manually backdate the cache entry so it appears stale
        cache_key = (f1_data.CURRENT_YEAR, 1, "Q")
        f1_data._SESSION_CACHE[cache_key]["created_at"] = (
            time.monotonic() - f1_data.SESSION_CACHE_TTL - 1
        )

        # Second call — must evict stale entry and fetch again
        f1_data._load_session(1, "Q", laps=True)
        assert mock_ff1.get_session.call_count == 2
```

- [ ] **Step 2: Run it to confirm it fails**

```
cd server && python -m pytest tests/test_f1_data.py::test_session_cache_evicts_stale_entry -v
```
Expected: `FAILED — AttributeError: module 'f1_data' has no attribute 'SESSION_CACHE_TTL'`

- [ ] **Step 3: Add `import time` and `SESSION_CACHE_TTL` constant to `f1_data.py`**

After the existing imports at the top of `server/f1_data.py`, add:
```python
import time
```

After `_SESSION_CACHE_LOCK = threading.Lock()` (around line 27), add:
```python
SESSION_CACHE_TTL = 300  # seconds; session data does not change mid-day
```

- [ ] **Step 4: Add TTL eviction inside `_load_session()`**

The eviction must happen inside `_SESSION_CACHE_LOCK` before the `if entry is None:` branch. Replace the current `with _SESSION_CACHE_LOCK:` block (lines 47–58) with:

```python
    with _SESSION_CACHE_LOCK:
        entry = _SESSION_CACHE.get(cache_key)
        # Evict if stale — safe to do under the global lock
        if entry is not None and time.monotonic() - entry["created_at"] > SESSION_CACHE_TTL:
            logger.debug(
                "Evicting stale FastF1 session cache entry round=%s session=%s",
                round_number,
                normalized_session,
            )
            del _SESSION_CACHE[cache_key]
            entry = None

        if entry is None:
            entry = {
                "session": fastf1.get_session(CURRENT_YEAR, round_number, normalized_session),
                "laps": False,
                "telemetry": False,
                "weather": False,
                "messages": False,
                "lock": threading.Lock(),
                "created_at": time.monotonic(),
            }
            _SESSION_CACHE[cache_key] = entry
```

- [ ] **Step 5: Run the test to confirm it passes**

```
cd server && python -m pytest tests/test_f1_data.py::test_session_cache_evicts_stale_entry -v
```
Expected: `PASSED`

- [ ] **Step 6: Run full test suite to confirm no regressions**

```
cd server && python -m pytest tests/ -v
```
Expected: all tests that passed before still pass.

- [ ] **Step 7: Commit**

```bash
git add server/f1_data.py server/tests/test_f1_data.py
git commit -m "perf: add 5-minute TTL eviction to FastF1 in-memory session cache"
```

---

## Task 2: Parallel tool dispatch in `_retrieve_analysis_evidence()`

**Context:** `_retrieve_analysis_evidence()` (line 1468 in `server/chat.py`) iterates `plan["tool_calls"]` — a list of `(tool_name, args)` tuples — and calls `execute_tool()` serially. For a qualifying analysis the plan contains 6 calls (`analyze_qualifying_battle`, `compare_corner_profiles`, `analyze_cornering_loads`, `get_qualifying_results`, and 2× `get_team_radio`). All 6 are independent. The FastF1 session cache has per-entry locks so concurrent loads of the same session serialize safely at the session level.

We replace the serial loop with `ThreadPoolExecutor` + `executor.map()`. `map()` preserves submission order while running tasks concurrently, so the `evidence` list comes back in the same order as `plan["tool_calls"]`.

**Files:**
- Modify: `server/chat.py`
- Test: `server/tests/test_chat.py`

- [ ] **Step 1: Write the failing test**

Add to `server/tests/test_chat.py`:

```python
def test_retrieve_analysis_evidence_runs_tools_in_parallel():
    """All tools in a plan are dispatched concurrently, not serially."""
    import time
    import importlib
    import chat
    importlib.reload(chat)

    SLEEP = 0.15  # each tool sleeps this long

    def slow_tool(name, args):
        time.sleep(SLEEP)
        return {"tool": name, "data": "ok"}

    plan = {
        "tool_calls": [
            ("tool_a", {}),
            ("tool_b", {}),
            ("tool_c", {}),
        ],
    }

    with patch.object(chat, "execute_tool", side_effect=slow_tool):
        start = time.monotonic()
        evidence = chat._retrieve_analysis_evidence(plan)
        elapsed = time.monotonic() - start

    # Serial would take ≥3×SLEEP; parallel should finish in roughly 1×SLEEP + overhead
    assert elapsed < SLEEP * 2, f"Expected parallel execution, took {elapsed:.2f}s"
    assert len(evidence) == 3
    # Order must match plan order
    assert evidence[0]["tool"] == "tool_a"
    assert evidence[1]["tool"] == "tool_b"
    assert evidence[2]["tool"] == "tool_c"
```

- [ ] **Step 2: Run it to confirm it fails**

```
cd server && python -m pytest tests/test_chat.py::test_retrieve_analysis_evidence_runs_tools_in_parallel -v
```
Expected: `FAILED` (elapsed ≥ 0.30 s because current code is serial)

- [ ] **Step 3: Add the import at the top of `chat.py`**

Near the top of `server/chat.py`, after the existing `import` block, add:

```python
from concurrent.futures import ThreadPoolExecutor
```

- [ ] **Step 4: Replace the serial loop in `_retrieve_analysis_evidence()`**

Replace the entire `for tool_name, args in plan.get("tool_calls", []):` block (lines 1470–1492) with:

```python
    tool_calls = plan.get("tool_calls") or []

    def _run_one(call_pair):
        tool_name, args = call_pair
        try:
            logger.info("Deterministic analysis tool call: %s args=%s", tool_name, args)
            result = execute_tool(tool_name, args)
            if tool_name in ("analyze_cornering_loads", "analyze_race_cornering_profile"):
                result = {k: v for k, v in result.items() if k != "per_corner"}
            return {"tool": tool_name, "args": args, "result": result}
        except Exception as exc:
            return {"tool": tool_name, "args": args, "error": str(exc)}

    max_workers = min(len(tool_calls), 6) if tool_calls else 1
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # map() preserves submission order while running concurrently
        evidence = list(executor.map(_run_one, tool_calls))
```

The rest of the function (auto-inject driver style and circuit profile) remains unchanged.

- [ ] **Step 5: Run the new test to confirm it passes**

```
cd server && python -m pytest tests/test_chat.py::test_retrieve_analysis_evidence_runs_tools_in_parallel -v
```
Expected: `PASSED` (elapsed < 0.30 s)

- [ ] **Step 6: Run full suite**

```
cd server && python -m pytest tests/ -v
```
Expected: all existing tests pass.

- [ ] **Step 7: Commit**

```bash
git add server/chat.py server/tests/test_chat.py
git commit -m "perf: run deterministic analysis tool calls in parallel with ThreadPoolExecutor"
```

---

## Task 3: Parallel tool dispatch in `_answer_anthropic()`

**Context:** The agentic loop in `_answer_anthropic()` (line 1747) iterates Claude's `tool_use` blocks with a `for block in response.content:` loop and calls `execute_tool()` serially for each block. When Claude batches 3 tool calls in one round (which is common), each waits for the previous one. We replace this with `ThreadPoolExecutor` + `executor.map()`.

The `tool_results` list and `executed_evidence` list both need to preserve the order corresponding to the original tool_use blocks, so `map()` (order-preserving) is the right choice over `as_completed`.

**Files:**
- Modify: `server/chat.py`
- Test: `server/tests/test_chat.py`

- [ ] **Step 1: Write the failing test**

Add to `server/tests/test_chat.py`:

```python
def test_agentic_loop_dispatches_tools_in_parallel():
    """When Claude calls two tools in one round, they run concurrently."""
    import time

    SLEEP = 0.15

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [
        _two_tool_use_response(),
        _end_turn_response("Both done."),
    ]

    chat = _load_chat_with_client(mock_client)

    call_times = []

    def slow_tool(name, args):
        call_times.append(time.monotonic())
        time.sleep(SLEEP)
        return {"result": name}

    with patch.object(chat, "execute_tool", side_effect=slow_tool):
        start = time.monotonic()
        chat.answer_f1_question("parallel test")
        elapsed = time.monotonic() - start

    # Two tools called in one round — should be ≈ SLEEP, not ≈ 2×SLEEP
    assert elapsed < SLEEP * 2 + 0.3, f"Expected parallel, took {elapsed:.2f}s"
    # Both tool calls must have started at roughly the same time
    assert len(call_times) == 2
    assert abs(call_times[0] - call_times[1]) < SLEEP * 0.8, (
        f"Tools started {abs(call_times[0]-call_times[1]):.2f}s apart — likely serial"
    )
```

- [ ] **Step 2: Run it to confirm it fails**

```
cd server && python -m pytest tests/test_chat.py::test_agentic_loop_dispatches_tools_in_parallel -v
```
Expected: `FAILED` (elapsed ≥ 0.30 s or start-time delta ≥ SLEEP)

- [ ] **Step 3: Replace the serial tool loop inside `_answer_anthropic()`**

Replace the `if response.stop_reason == "tool_use":` block (lines 1747–1773) with:

```python
        if response.stop_reason == "tool_use":
            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

            def _dispatch_block(block):
                try:
                    logger.info("Anthropic tool call: %s args=%s", block.name, block.input)
                    result = execute_tool(block.name, block.input)
                    return block, result, None
                except Exception as exc:
                    return block, None, exc

            tool_results = []
            max_w = min(len(tool_use_blocks), 6) if tool_use_blocks else 1
            with ThreadPoolExecutor(max_workers=max_w) as executor:
                for block, result, exc in executor.map(_dispatch_block, tool_use_blocks):
                    if exc is None:
                        executed_evidence.append({
                            "tool": block.name,
                            "args": block.input,
                            "result": result,
                        })
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result, default=str),
                        })
                    else:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": str(exc),
                            "is_error": True,
                        })

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})
```

- [ ] **Step 4: Run new test + full suite**

```
cd server && python -m pytest tests/test_chat.py::test_agentic_loop_dispatches_tools_in_parallel tests/test_chat.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add server/chat.py server/tests/test_chat.py
git commit -m "perf: dispatch multiple tool calls in parallel inside the agentic loop"
```

---

## Task 4: SSE streaming — backend

**Context:** The client currently calls `POST /api/chat` and waits for a complete JSON response. We convert this to Server-Sent Events (SSE): the server streams `delta` events token-by-token as Claude generates the final text, then emits a `done` event carrying the clean text (with any `f1-widget` blocks stripped) and the widget list.

**SSE event protocol:**
```
data: {"type":"delta","text":"Norris "}\n\n
data: {"type":"delta","text":"was faster"}\n\n
data: {"type":"done","text":"Norris was faster…","widgets":[…]}\n\n
data: {"type":"error","detail":"something went wrong"}\n\n
```

The Anthropic Python SDK supports streaming via `client.messages.stream()`, a sync context manager. Its `.text_stream` property is an iterator of text-delta strings. We stay synchronous inside a thread and bridge to FastAPI's async world with `asyncio.Queue`.

**Files:**
- Modify: `server/chat.py`
- Modify: `server/main.py`
- Test: `server/tests/test_main.py`

- [ ] **Step 1: Write the failing test in `test_main.py`**

Replace the existing `test_chat_endpoint_returns_response` test and add a streaming test:

```python
import json
from unittest.mock import patch
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_cors_header_present():
    response = client.options(
        "/api/drivers",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


def _parse_sse_events(raw_bytes: bytes) -> list[dict]:
    text = raw_bytes.decode()
    events = []
    for part in text.split("\n\n"):
        part = part.strip()
        if part.startswith("data: "):
            events.append(json.loads(part[6:]))
    return events


def test_chat_endpoint_streams_sse():
    """The /api/chat endpoint emits SSE events: delta chunks then a done event."""

    def fake_streaming(message, history):
        yield 'data: {"type":"delta","text":"Verstappen"}\n\n'
        yield 'data: {"type":"delta","text":" leads."}\n\n'
        yield 'data: {"type":"done","text":"Verstappen leads.","widgets":[]}\n\n'

    with patch("main.answer_f1_payload_streaming", side_effect=fake_streaming):
        with client.stream("POST", "/api/chat", json={"message": "Who is leading?"}) as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            raw = b"".join(r.iter_bytes())

    events = _parse_sse_events(raw)
    assert events[0] == {"type": "delta", "text": "Verstappen"}
    assert events[1] == {"type": "delta", "text": " leads."}
    assert events[2]["type"] == "done"
    assert events[2]["text"] == "Verstappen leads."
    assert events[2]["widgets"] == []


def test_chat_endpoint_rejects_empty_message():
    response = client.post("/api/chat", json={"message": "   "})
    assert response.status_code == 400
```

- [ ] **Step 2: Run it to confirm it fails**

```
cd server && python -m pytest tests/test_main.py::test_chat_endpoint_streams_sse -v
```
Expected: `FAILED — ImportError: cannot import name 'answer_f1_payload_streaming' from 'main'`

- [ ] **Step 3: Add streaming answer-writer to `chat.py`**

Add this function directly after `_run_anthropic_answer_writer()` (around line 1712):

```python
def _run_anthropic_answer_writer_streaming(question: str, analysis: dict):
    """Generator — yields SSE delta strings for the answer writer response."""
    client = _get_anthropic_client()
    with client.messages.stream(
        model="claude-opus-4-7",
        max_tokens=1200,
        system=ANSWER_WRITER_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": _build_answer_writer_prompt(question, analysis),
        }],
    ) as stream:
        for text in stream.text_stream:
            yield f"data: {json.dumps({'type': 'delta', 'text': text})}\n\n"
```

- [ ] **Step 4: Add streaming agentic loop to `chat.py`**

Add this function directly after `_answer_anthropic()`:

```python
def _answer_anthropic_streaming(
    message: str,
    history: list[dict],
    resolved_context: dict | None = None,
    preloaded_context: dict | None = None,
):
    """Generator — SSE-streaming version of _answer_anthropic()."""
    client = _get_anthropic_client()
    if resolved_context is None:
        resolved, preloaded = _prepare_resolved_context(message, history)
    else:
        resolved = resolved_context
        preloaded = preloaded_context
    request_system_prompt = _build_request_system_prompt(resolved, preloaded)
    messages = [{"role": h["role"], "content": h["content"]} for h in history]
    messages.append({"role": "user", "content": message})
    executed_evidence: list[dict] = []

    for _ in range(MAX_TOOL_ROUNDS):
        with client.messages.stream(
            model="claude-opus-4-7",
            max_tokens=4096,
            system=request_system_prompt,
            tools=TOOL_DEFINITIONS,
            messages=messages,
        ) as stream:
            # Yield text deltas as they arrive; empty for tool_use responses
            for text in stream.text_stream:
                yield f"data: {json.dumps({'type': 'delta', 'text': text})}\n\n"
            final = stream.get_final_message()

        if final.stop_reason == "end_turn":
            full_text = "".join(b.text for b in final.content if hasattr(b, "text"))
            clean_text, inline_widgets = _extract_inline_widgets(full_text)
            widgets = _merge_widgets(
                _widgets_from_preloaded(preloaded),
                _widgets_from_analysis_evidence({}, executed_evidence),
                inline_widgets,
            )
            yield f"data: {json.dumps({'type': 'done', 'text': clean_text, 'widgets': widgets}, default=str)}\n\n"
            return

        if final.stop_reason == "tool_use":
            tool_use_blocks = [b for b in final.content if b.type == "tool_use"]

            def _dispatch_block(block):
                try:
                    result = execute_tool(block.name, block.input)
                    return block, result, None
                except Exception as exc:
                    return block, None, exc

            tool_results = []
            max_w = min(len(tool_use_blocks), 6) if tool_use_blocks else 1
            with ThreadPoolExecutor(max_workers=max_w) as executor:
                for block, result, exc in executor.map(_dispatch_block, tool_use_blocks):
                    if exc is None:
                        executed_evidence.append({
                            "tool": block.name,
                            "args": block.input,
                            "result": result,
                        })
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result, default=str),
                        })
                    else:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": str(exc),
                            "is_error": True,
                        })

            messages.append({"role": "assistant", "content": final.content})
            messages.append({"role": "user", "content": tool_results})
        else:
            raise ValueError(f"Unexpected stop_reason: {final.stop_reason!r}")

    raise ValueError(f"Exceeded {MAX_TOOL_ROUNDS} tool-call rounds without a final answer.")
```

- [ ] **Step 5: Add streaming deterministic path and public entry point to `chat.py`**

Add these two functions after `_try_deterministic_analysis()`:

```python
def _try_deterministic_analysis_streaming(
    question: str,
    history: list[dict],
    *,
    provider: str,
    resolved_context: dict | None = None,
) -> "Generator | None":
    """
    Returns a generator that yields SSE strings, or None if the question
    doesn't match a deterministic analysis mode.
    """
    resolved = resolved_context or resolve_query_context(
        question, resolve_context_from_history(history)
    )
    plan = _build_analysis_plan(question, resolved)
    if not plan:
        return None

    def _gen():
        evidence = _retrieve_analysis_evidence(plan, resolved)
        if not evidence:
            return

        try:
            if provider == "anthropic":
                analysis = _run_anthropic_analysis(question, resolved, plan, evidence)
                if plan.get("focus") == "qualifying":
                    analysis = _canonicalize_qualifying_analysis(analysis, evidence)
                elif plan.get("analysis_mode") == "race_pace_comparison":
                    analysis = _canonicalize_race_pace_analysis(analysis, evidence)

                # Stream the answer-writer response
                full_text_parts = []
                for chunk in _run_anthropic_answer_writer_streaming(question, analysis):
                    # Extract the text from the SSE delta event to reassemble
                    if chunk.startswith("data: "):
                        try:
                            ev = json.loads(chunk[6:])
                            if ev.get("type") == "delta":
                                full_text_parts.append(ev["text"])
                        except Exception:
                            pass
                    yield chunk

                full_text = "".join(full_text_parts)
                clean_text, inline_widgets = _extract_inline_widgets(full_text)
                widgets = _merge_widgets(
                    _widgets_from_analysis_evidence(plan, evidence),
                    inline_widgets,
                )
                yield f"data: {json.dumps({'type': 'done', 'text': clean_text, 'widgets': widgets}, default=str)}\n\n"

            # OpenAI provider falls through to None (no streaming support yet)
        except Exception as exc:
            logger.warning("Deterministic streaming analysis failed: %s", exc)
            raise

    return _gen()


def answer_f1_payload_streaming(message: str, history: list[dict] | None = None):
    """
    Public entry point. Synchronous generator — yields SSE event strings.
    Intended to be run in a thread; bridges to FastAPI via asyncio.Queue in main.py.
    """
    prior = history or []
    provider = os.environ.get("LLM_PROVIDER", "anthropic").lower()
    previous_context = resolve_context_from_history(prior)
    resolved = resolve_query_context(message, previous_context)

    deterministic_gen = _try_deterministic_analysis_streaming(
        message, prior, provider=provider, resolved_context=resolved
    )
    if deterministic_gen is not None:
        try:
            yield from deterministic_gen
            return
        except Exception:
            pass  # fall through to agentic path

    preloaded = _preload_resolved_context(resolved)
    if provider == "openai":
        # OpenAI streaming not yet implemented — use non-streaming and emit as single done
        result = _answer_openai(message, prior, resolved_context=resolved, preloaded_context=preloaded)
        yield f"data: {json.dumps({'type': 'done', 'text': result['response'], 'widgets': result.get('widgets', [])}, default=str)}\n\n"
    else:
        yield from _answer_anthropic_streaming(
            message, prior, resolved_context=resolved, preloaded_context=preloaded
        )
```

- [ ] **Step 6: Update `main.py` to use SSE `StreamingResponse`**

Replace the current `chat_endpoint` with:

```python
import asyncio
from fastapi.responses import StreamingResponse
from chat import answer_f1_payload_streaming

@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="message cannot be empty")

    async def event_generator():
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def producer():
            try:
                for chunk in answer_f1_payload_streaming(request.message, request.history):
                    loop.call_soon_threadsafe(queue.put_nowait, chunk)
            except ValueError as exc:
                err = json.dumps({"type": "error", "detail": str(exc)})
                loop.call_soon_threadsafe(queue.put_nowait, f"data: {err}\n\n")
            except Exception as exc:
                logger.exception("Error in POST /api/chat streaming")
                err = json.dumps({"type": "error", "detail": "Something went wrong processing your request."})
                loop.call_soon_threadsafe(queue.put_nowait, f"data: {err}\n\n")
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)  # sentinel

        loop.run_in_executor(None, producer)

        while True:
            item = await queue.get()
            if item is None:
                break
            yield item

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # prevents nginx from buffering SSE
        },
    )
```

Also add to the imports at the top of `main.py`:
```python
import asyncio
import json
from fastapi.responses import StreamingResponse
from chat import answer_f1_payload_streaming
```

Remove the old `from chat import answer_f1_payload, answer_f1_question` import line (or keep `answer_f1_question` if used elsewhere — it is not used in main.py currently).

- [ ] **Step 7: Run the new tests**

```
cd server && python -m pytest tests/test_main.py -v
```
Expected: all pass including `test_chat_endpoint_streams_sse`.

- [ ] **Step 8: Run full test suite**

```
cd server && python -m pytest tests/ -v
```
Expected: all pass.

- [ ] **Step 9: Commit backend SSE**

```bash
git add server/chat.py server/main.py server/tests/test_main.py
git commit -m "feat: stream /api/chat responses via SSE — delta events + done event with widgets"
```

---

## Task 5: SSE streaming — frontend

**Context:** The client calls `sendChatMessage()` in `f1api.js` which does `res.json()` — a blocking read of the complete response. We replace this with a `ReadableStream` reader that accumulates delta events and calls an `onDelta` callback for each chunk. `App.jsx` uses this to show a placeholder assistant message immediately and update it as chunks arrive; the final `done` event carries the clean text and widgets used to finalize the message.

**Files:**
- Modify: `client/src/api/f1api.js`
- Modify: `client/src/App.jsx`

There are no frontend tests. Verification is by running the dev server and manually testing.

- [ ] **Step 1: Rewrite `sendChatMessage` in `f1api.js`**

Replace the existing `sendChatMessage` export with:

```javascript
// client/src/api/f1api.js
const BASE = '/api'
let circuitsPromise = null

async function apiFetch(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

export const fetchDriverStats = (name) => apiFetch(`/driver/${encodeURIComponent(name)}/stats`)
export const fetchCircuits = () => {
  if (!circuitsPromise) {
    circuitsPromise = apiFetch('/circuits').catch((error) => {
      circuitsPromise = null
      throw error
    })
  }
  return circuitsPromise
}

/**
 * Send a chat message and consume the SSE stream.
 * onDelta(text: string) is called with each accumulated text string as it arrives.
 * Resolves with { response: string, widgets: array } when the done event arrives.
 */
export async function sendChatMessage(message, history = [], onDelta = null) {
  const res = await fetch(`${BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, history }),
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let accumulated = ''
  let finalResponse = ''
  let finalWidgets = []

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const parts = buffer.split('\n\n')
    buffer = parts.pop() ?? '' // keep the incomplete trailing fragment

    for (const part of parts) {
      const trimmed = part.trim()
      if (!trimmed.startsWith('data: ')) continue
      let event
      try {
        event = JSON.parse(trimmed.slice(6))
      } catch {
        continue
      }

      if (event.type === 'delta') {
        accumulated += event.text
        if (onDelta) onDelta(accumulated)
      } else if (event.type === 'done') {
        finalResponse = event.text
        finalWidgets = event.widgets ?? []
      } else if (event.type === 'error') {
        throw new Error(event.detail || 'Unknown server error')
      }
    }
  }

  return { response: finalResponse, widgets: finalWidgets }
}
```

- [ ] **Step 2: Update `handleSend` in `App.jsx`**

Replace the existing `handleSend` function (lines 39–68) with:

```javascript
  const handleSend = async (text) => {
    let sessionId = activeId
    if (!sessionId) sessionId = createSession()

    const current = activeSession?.messages || []
    const withUser = [...current, { id: crypto.randomUUID(), role: 'user', text }]
    updateMessages(sessionId, withUser)
    setLoading(true)

    const history = current.map((message) => ({ role: message.role, content: message.text }))
    const assistantId = crypto.randomUUID()

    // Add empty placeholder so the UI shows "typing" immediately
    updateMessages(sessionId, [
      ...withUser,
      { id: assistantId, role: 'assistant', text: '', widgets: [] },
    ])

    try {
      const { response, widgets = [] } = await sendChatMessage(
        text,
        history,
        (partial) => {
          // Update the placeholder with accumulated text as deltas arrive
          updateMessages(sessionId, [
            ...withUser,
            { id: assistantId, role: 'assistant', text: partial, widgets: [] },
          ])
        },
      )
      // Finalize: clean text + widgets from the done event
      updateMessages(sessionId, [
        ...withUser,
        { id: assistantId, role: 'assistant', text: response, widgets },
      ])
    } catch (error) {
      updateMessages(sessionId, [
        ...withUser,
        {
          id: assistantId,
          role: 'assistant',
          text: `Something went wrong: ${error.message}`,
          isError: true,
        },
      ])
    } finally {
      setLoading(false)
    }
  }
```

- [ ] **Step 3: Start the dev stack and test manually**

In one terminal:
```
cd server && uvicorn main:app --reload --port 8000
```
In another:
```
cd client && npm run dev
```

Open `http://localhost:5173` and ask: **"How did Russell do at the last race?"**

Verify:
- A typing indicator appears immediately (empty assistant message shows loading dots)
- Text starts appearing token-by-token within a second or two of tools completing
- The response text fills in progressively — not all at once
- Widgets appear at the end alongside the final clean text (no `f1-widget` JSON blocks visible)
- The sidebar session title updates as expected (first user message → title)

Also ask a simple question with no tool use: **"When did F1 start?"** — text should appear immediately.

- [ ] **Step 4: Test an error case**

Stop the backend. Ask a question in the UI. Verify the error message appears correctly (`Something went wrong: …`) and the UI is not stuck in loading state.

- [ ] **Step 5: Commit frontend SSE**

```bash
git add client/src/api/f1api.js client/src/App.jsx
git commit -m "feat: consume /api/chat SSE stream in client — progressive text rendering"
```

---

## Self-Review

**Spec coverage check:**

| Requirement | Task |
|---|---|
| Parallel tool calls in deterministic path | Task 2 |
| Parallel tool calls in agentic loop | Task 3 |
| Session cache TTL | Task 1 |
| SSE streaming backend | Task 4 |
| Thread pool for uvicorn (`run_in_executor`) | Task 4 — Step 6 (`loop.run_in_executor(None, producer)`) |
| Client reads SSE stream | Task 5 |
| No resolver changes | ✓ — resolver is untouched throughout |

**Placeholder scan:** No TBD, TODO, or "implement later" in the plan. All code blocks are complete.

**Type consistency:**
- `_run_anthropic_answer_writer_streaming` → used in `_try_deterministic_analysis_streaming` ✓
- `answer_f1_payload_streaming` → imported in `main.py` exactly as named ✓
- `_answer_anthropic_streaming` → called from `answer_f1_payload_streaming` ✓
- `_retrieve_analysis_evidence` signature unchanged — callers not broken ✓
- `_dispatch_block` is a local closure in both Task 3 and Task 4 — names don't conflict ✓
- SSE event shapes: `delta`/`done`/`error` — consistent between chat.py generators and f1api.js parser ✓

**Potential issues documented:**
- The `done` event carries `text` (clean, widget-stripped) in addition to `widgets`. This is why the client replaces the accumulated partial text with `response` from the `done` event rather than using the accumulated text directly — the accumulated text may include raw `f1-widget` JSON blocks.
- `_try_deterministic_analysis_streaming` falls through to the agentic path on exception, not on the `None` case. The `None` guard is on the return value of the function, not on the generator. This is handled correctly.
- OpenAI provider in `answer_f1_payload_streaming` emits a single `done` event (no deltas). This is acceptable — streaming is Anthropic-only for now.
