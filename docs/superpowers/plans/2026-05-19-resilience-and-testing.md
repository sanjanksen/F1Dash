# Backend Resilience and UX Hardening Implementation Plan

> Status: not started. Estimated effort: ~2.5 weeks (Phase 1 ~1 week, Phase 2 ~3 days, Phase 3 ~1 week).

## Goal

Lift F1Dash from "happy-path works" to "fails loudly, recovers cleanly, surfaces honestly." Seven features (F34–F40) harden backend external boundaries, validate the frontend's contract with the backend, and lock behaviour in via a thin e2e test that exercises HTTP → resolver → agentic loop → widget assembly.

This is the systematic version of `2026-05-19-backend-core-bugfixes.md`. Where that plan lands minimum patches, this one introduces a typed exception hierarchy, retry/timeout policy, frontend response validation, error boundaries, and a regression net for future resilience work.

## Background

The 2026-05-19 audit surfaced 23 issues. The bug-fix plan handles the seven most acute; this one picks up the systematic concerns.

| Bug-plan ref | This plan | Scope difference |
|---|---|---|
| Bugs #1–3 | F34 | Bug plan adds `FastF1Error` + `LLMTransientError` at narrow sites. This plan promotes them into a four-class hierarchy with central HTTP status mapping. |
| Bug #4 | F35 | Bug plan: helper. This plan: schema-driven validation generated from `input_schema.required`. |
| Bug #13 | F36 | Bug plan: nothing. This plan: bounded exponential backoff on connection errors + 5xx. |
| Bug #19 | F37 | LRU prune + quota recovery. |
| Bug #18 | F38 | Response-shape validator + ErrorBoundary. |
| Bugs #20, #23 | F39 | Stable widget UUIDs + "show all" toggles. |
| — | F40 | E2E regression net. |

## Phase Overview

| Phase | Features | Effort | Theme |
|---|---|---|---|
| 1 | F34, F35, F36 | ~1 week | Backend correctness |
| 2 | F37, F38, F39 | ~3 days | Frontend UX |
| 3 | F40 | ~1 week | E2E regression suite |

Phase 2 depends on Phase 1's typed errors for the user-visible throttling shape. Phase 3 exercises both.

---

## Typed Exception Hierarchy (used by F34, F35, F36)

New `server/errors.py`:

```python
class F1DashError(RuntimeError):
    """Root of the typed hierarchy. Catch at the HTTP layer."""
    def __init__(self, message, *, context=None, cause=None):
        super().__init__(message)
        self.context = context or {}
        if cause is not None:
            self.__cause__ = cause

class FastF1Error(F1DashError):     # context: round_number, session_type, phase
    """FastF1 cannot load/serve the requested session."""

class OpenF1Error(F1DashError):     # context: endpoint, status_code, attempts
    """OpenF1 cannot serve the requested endpoint."""

class JolpicaError(F1DashError):    # context: url, status_code
    """Jolpica-Ergast API failed or returned unexpected shape."""

class AnthropicError(F1DashError):  # context: provider, kind
    """LLM provider call failed. kind in {rate_limit, connection, api, timeout}.
    Name reflects primary provider; context['provider'] disambiguates Anthropic vs OpenAI."""
```

Central HTTP mapping (lives in `main.py`):

| Exception | Status | Detail (type name only) |
|---|---|---|
| `FastF1Error` / `OpenF1Error` / `JolpicaError` | 503 | `"Data temporarily unavailable ({type_name})."` |
| `AnthropicError` kind=`rate_limit` | 429 | `"Model is throttling. Retry in a moment."` |
| `AnthropicError` kind=`connection` / `timeout` | 503 | `"Lost connection to model provider."` |
| `AnthropicError` kind=`api` | 502 | `"Model API returned an error."` |
| `ValueError` (resolver / required-args) | 422 | `str(e)` — user-correctable. |
| Anything else | 500 | `"Unexpected backend error ({type_name})."` |

All branches log `type(e).__name__`, the `context` dict, and `exc_info=True` at WARN (INFO for rate-limit). Never include `str(e)` in 5xx detail — exception messages may leak filesystem paths or credentials.

---

## Phase 1 — Backend Correctness (~1 week)

### F34 — Typed Exception Handling At Every External Boundary

Files: add `server/errors.py`; modify `server/f1_data.py`, `server/openf1.py`, `server/chat.py`, `server/main.py`. Tests: `server/tests/test_errors.py` plus extensions to `test_f1_data.py`, `test_chat.py`, `test_main.py`.

Current state:
- `_load_session()` (`f1_data.py:40`) calls `fastf1.get_session()` and `session.load()` unprotected; ~25 wrappers consume the result.
- `_openf1_get()` raises raw `requests` exceptions.
- `chat.py` calls `client.messages.create()` / `client.chat.completions.create()` at six known sites (lines 1711, 1726, 1751, 1822, 1835, 1859) — `RateLimitError` indistinguishable from bugs in logs.
- `main.py:45,61,70,83` catch bare `Exception`, return generic 500s; exception type never reaches the log structurally.

Change:

1. Create `errors.py` with the hierarchy above.
2. Wrap both FastF1 calls in `_load_session()` in try/except → `FastF1Error` with `phase='get_session'` or `phase='load'`. On `load` failure, pop the half-loaded cache entry. Do not catch `FastF1Error` inside `_load_session()` — callers decide recovery. Coordinate with bug-fix Task 1: import from `errors.py` so there's only one definition.
3. Wrap `_openf1_get()` exceptions as `OpenF1Error` after retry (see F36). Preserve the existing 404 special-case in `get_team_radio()` by checking `exc.context.get("status_code") == 404` instead of `requests.HTTPError`.
4. Add `_call_anthropic()` and `_call_openai()` wrappers in `chat.py`. Each catches provider-specific typed errors (`anthropic.RateLimitError`, `APIConnectionError`, `APIError`; same for `openai`) and re-raises `AnthropicError(kind=...)`. Replace all six call sites with the wrappers.
5. Wrap Jolpica HTTP calls in `f1_data.py`. Grep for `JOLPICA_BASE` / `ergast`; each site needs try/except around `.raise_for_status()` and `.json()` → `JolpicaError`.
6. Central FastAPI exception handlers in `main.py`:
   ```python
   @app.exception_handler(F1DashError)
   async def f1dash_error_handler(request, exc):
       status, detail, level = _map_typed_error(exc)
       getattr(logger, level)("%s on %s: %s context=%s",
           type(exc).__name__, request.url.path, str(exc), exc.context, exc_info=True)
       return JSONResponse(status, {"detail": detail, "error_type": type(exc).__name__})

   @app.exception_handler(Exception)
   async def unhandled_error_handler(request, exc):
       logger.warning("Unhandled %s on %s", type(exc).__name__, request.url.path, exc_info=True)
       return JSONResponse(500, {"detail": f"Unexpected backend error ({type(exc).__name__}).",
                                  "error_type": type(exc).__name__})
   ```
   With handlers in place, per-endpoint `try/except Exception` blocks reduce to just `HTTPException` / `ValueError` branches needing distinct codes.

Acceptance:
- `errors.py` defines the four typed classes plus root.
- `_load_session()` raises `FastF1Error` on both phases with `context` populated.
- All six LLM call sites route through wrappers.
- HTTP responses: `FastF1Error` → 503, `AnthropicError(kind=rate_limit)` → 429; `error_type` appears in JSON body.
- Rate-limit logs at `info`/`warning`, never `error`.

Observable-behaviour tests:
- `test_load_session_get_session_failure_raises_fastf1_error_with_context`
- `test_load_session_load_failure_clears_cache_entry`
- `test_openf1_get_raises_openf1error_after_retry_exhaustion`
- `test_jolpica_failure_raises_jolpica_error_with_url_in_context`
- `test_fastf1_failure_in_endpoint_returns_503`
- `test_anthropic_rate_limit_returns_429`
- `test_anthropic_connection_error_returns_503`
- `test_unhandled_typeerror_returns_500_with_type_in_body`
- `test_rate_limit_log_level_is_warning_not_error`

---

### F35 — Required-arg Validation At `execute_tool()` Entry

Files: modify `server/tools.py`. Tests: `server/tests/test_tools.py`, `test_chat.py`.

Current state: `execute_tool()` branches access `args["driver_name"]`, `args["round_number"]`, etc. directly. A malformed LLM tool call produces a `KeyError` that becomes a 500 in the agentic loop instead of a `tool_result` the model can self-correct from. ~40 affected branches.

Change:

1. Add `_require_args(args, required, tool_name)`:
   ```python
   def _require_args(args, required, tool_name):
       missing = [k for k in required if k not in args or args[k] in (None, "")]
       if missing:
           raise ValueError(
               f"Tool {tool_name!r} called without required arg(s): {', '.join(missing)}. "
               "Retry with the missing field(s) populated.")
   ```
2. Build the required list **from the tool definition** at import time:
   ```python
   _REQUIRED_ARGS = {t["name"]: list(t.get("input_schema", {}).get("required", []))
                     for t in TOOL_DEFINITIONS}
   ```
   Then `_require_args(args, _REQUIRED_ARGS.get(name, []), name)` once at the top of `execute_tool()`. Single source of truth; new tools auto-covered.
3. Confirm the agentic loop in `chat.py` catches `ValueError` from `execute_tool()` and feeds it back as `{"type": "tool_result", "tool_use_id": ..., "content": str(e), "is_error": True}`. If not, add the wrap inline.
4. Optional args aren't validated (they aren't in `input_schema.required`). Internal invariant checks inside individual tool branches (e.g. corner indices in `analyze_cornering_loads`) stay as-is — F35 is only about the dispatch boundary.

Acceptance:
- `_REQUIRED_ARGS` built once from `TOOL_DEFINITIONS`; used at every branch via a single dispatch-top call.
- `execute_tool("get_driver_season_stats", {})` raises `ValueError` mentioning `"driver_name"`.
- Agentic loop translates that into a `tool_result` with `is_error: True`.
- Adding a new tool with `"required": ["foo"]` validates `foo` without further edits.

Observable-behaviour tests:
- `test_require_args_lists_missing_keys_in_error_message`
- `test_require_args_treats_none_and_empty_string_as_missing`
- `test_execute_tool_missing_driver_name_raises_value_error`
- `test_execute_tool_missing_round_number_raises_value_error`
- `test_execute_tool_missing_driver_a_and_b_lists_both`
- `test_execute_tool_optional_args_not_validated`
- `test_required_args_table_built_from_tool_definitions`
- `test_agentic_loop_feeds_value_error_back_as_tool_result_is_error_true`

---

### F36 — Retry + Timeout On `_openf1_get()`

Files: modify `server/openf1.py`. Tests: `server/tests/test_openf1.py` (create if missing).

Current state: `openf1.py:26–29` has `timeout=20` (audit's "no timeout" is stale) but no retry. One transient blip cascades into a chat-payload failure.

Change:

1. Reduce `timeout` to 10s. OpenF1's p99 is well under that.
2. Bounded exponential backoff with jitter — 3 retries (4 total attempts), delays `[0.5, 1.5, 4.5]`, +/-20% jitter:
   ```python
   _OPENF1_RETRY_DELAYS = [0.5, 1.5, 4.5]
   def _openf1_get(endpoint, **params):
       last_exc = None
       for attempt, base_delay in enumerate([0.0] + _OPENF1_RETRY_DELAYS):
           if base_delay > 0:
               time.sleep(base_delay * random.uniform(0.8, 1.2))
           try:
               response = requests.get(url, params=params, timeout=10)
           except (requests.ConnectionError, requests.Timeout) as exc:
               last_exc = exc
               continue  # retry connection-level
           if response.status_code >= 500:
               last_exc = requests.HTTPError(...)
               continue  # retry 5xx
           try:
               response.raise_for_status()
           except requests.HTTPError as exc:
               # 4xx: do not retry. Caller may special-case (e.g. 404).
               raise OpenF1Error(..., context={"endpoint": endpoint,
                   "status_code": response.status_code, "attempts": attempt + 1}, cause=exc)
           return response.json()
       raise OpenF1Error(..., context={"endpoint": endpoint, "attempts": 4}, cause=last_exc)
   ```
3. Preserve the 404 special-case in `get_team_radio()` (`openf1.py:92–97`). Update the caller to catch `OpenF1Error` and check `exc.context.get("status_code") == 404`.
4. Do not retry 401, 403, 404. Connection errors and 5xx only.

Risk: `time.sleep` blocks the event-loop thread. Tolerable because chat calls go through `run_in_threadpool` (`main.py:80`) and worst-case retry budget is ~6.5s. Revisit if we add async-first streaming endpoints.

Acceptance:
- Retries up to 3 times on `ConnectionError`/`Timeout`/5xx; raises `OpenF1Error` with `attempts: 4` after exhaustion.
- 4xx raises immediately with `status_code` in context.
- `get_team_radio()` 404 fallback still works via context check.
- `timeout=10`, not 20.

Observable-behaviour tests:
- `test_openf1_get_succeeds_on_first_attempt_no_sleep`
- `test_openf1_get_retries_three_times_on_connection_error`
- `test_openf1_get_retries_on_5xx` (parameterised over 500/502/503/504)
- `test_openf1_get_does_not_retry_on_401_403_404`
- `test_openf1_get_404_raises_openf1error_with_status_code_in_context`
- `test_get_team_radio_handles_404_via_openf1_error_context`
- `test_openf1_get_total_retry_budget_under_seven_seconds` (mocked sleep)

---

## Phase 2 — Frontend UX (~3 days)

### F37 — localStorage Bounds (LRU Prune)

Files: add `client/src/lib/storage.js`; modify `client/src/hooks/useChatSessions.js`. Test: manual.

Current state: `useChatSessions.js` persists all sessions to localStorage on every change. Widget payloads run tens of KB; ~50 sessions hits Chrome's ~5MB quota and `setItem` throws `QuotaExceededError`, breaking persistence silently.

Change:

1. New `storage.js` with `persistSessions(key, sessions)`:
   - Hard cap `MAX_SESSIONS = 50`; slice to `.slice(-MAX_SESSIONS)` first.
   - On `QuotaExceededError`: first attempt strips `widgets: []` from messages in sessions whose `updatedAt` is older than 7 days. Subsequent attempts drop the oldest session, looping until `setItem` succeeds or only one session remains.
   - `console.warn` on prune events with new count.
   - Quota-error detection covers `e.code === 22`, `e.code === 1014`, `e.name === 'QuotaExceededError'`, `e.name === 'NS_ERROR_DOM_QUOTA_REACHED'` (Firefox).
2. `useChatSessions.js` calls `persistSessions(...)` instead of `localStorage.setItem` directly.
3. No remote telemetry. `console.warn` is enough for v1.

Acceptance:
- 51st session triggers oldest-drop; 50 remain on reload.
- `QuotaExceededError` triggers stale-widget strip, then iterative drop, then `console.warn`.
- Happy path (< 50 sessions, < 1MB) unchanged.

Observable-behaviour tests (manual; document in `client/MANUAL_TESTS.md`):
- Create 51 sessions; reload; 50 remain.
- Inject 8MB synthetic session via DevTools; next chat triggers `[storage] quota exceeded; pruned to N sessions`.
- Active session + 6 most-recent remain intact after prune.

---

### F38 — Frontend Response Shape Validation + Better Error UI

Files: modify `client/src/api/f1api.js`, `client/src/App.jsx`; add `client/src/components/ErrorBoundary.jsx`. Test: manual.

Current state: `App.jsx:51` destructures `{response, widgets}` without checking shape. Malformed payloads silently destructure to `undefined, undefined`; widget render errors crash the entire chat pane.

Change:

1. `validateChatResponse(body)` in `f1api.js` returns `{ok: true, body}` or `{ok: false, reason, body}`. Checks: body is object, `response` is string, `widgets` is array, every widget has string `type`.
2. `sendChat(message, history)` returns a discriminated union. Non-200 returns `{ok: false, reason, status, error_type}` reading `error_type` from F34's typed JSON body. Non-JSON response logs the parse error and returns `{ok: false, reason: 'response was not JSON'}`.
3. `App.jsx` switches on `.ok`. On `false`, append an assistant message keyed off `error_type`:
   - `AnthropicError` (429): "The model is throttling right now — please retry in a moment."
   - `FastF1Error` / `OpenF1Error` / `JolpicaError`: "Race data temporarily unavailable. Try again in a minute."
   - generic: "The server returned unexpected data — try rephrasing or retry."
   - Full body logged to `console.error` for triage.
4. `WidgetErrorBoundary` (class component, `getDerivedStateFromError` + `componentDidCatch`) wraps each widget **individually** inside `AnswerRenderer.jsx`'s `widgets.map`. Fallback: small red-bordered card "A widget failed to render. The text answer is still shown above." `componentDidCatch` logs via `console.error`.

Acceptance:
- `validateChatResponse` rejects non-JSON, missing fields, malformed widgets.
- App switches on `.ok`; non-200 surfaces typed message.
- A throwing widget shows ErrorBoundary fallback; siblings still render.
- 429 from F34 shows throttling message, not generic crash.

Observable-behaviour tests (manual):
- Backend returns `{"response": "hi"}`: error message shown; body in console.
- Backend returns HTML (proxy 502): "unexpected data" message; parse error in console.
- Inject malformed widget (e.g. `story_points: null`); ErrorBoundary fallback shown for that widget only.
- Trigger 429: throttling message appears.

---

### F39 — Unique Widget Keys + "Show More"

Files: modify `client/src/components/AnswerRenderer.jsx`, `client/src/hooks/useChatSessions.js`, `client/src/components/chat-widgets/RaceStoryWidget.jsx`, audit other widgets. Test: manual.

Current state:
- `AnswerRenderer.jsx:196` uses `key={`${widget.type}-${index}`}` — collides for two widgets of the same type in one message.
- `RaceStoryWidget.jsx:69` `story_points.slice(0, 4)` silently hides everything past the 4th point.

Change:

1. At message creation in `useChatSessions.js`, attach `_key: crypto.randomUUID()` to each widget. Backfill on load for pre-existing sessions: any widget missing `_key` gets one. (Use `crypto.randomUUID()` not `uuid` package — available in all targeted browsers, no new dep.)
2. `AnswerRenderer.jsx:196` → `key={widget._key ?? `${widget.type}-${index}`}` (fallback handles pre-upgrade persisted sessions in the same browser session).
3. `RaceStoryWidget.jsx`: `useState(false)` for `expanded`; render `expanded ? story_points : story_points.slice(0, 4)`; show toggle button "Show all N points" / "Show fewer" only if `story_points.length > 4`.
4. Grep `client/src/components/chat-widgets/` for `.slice(0, ` and apply the same pattern to any user-facing list with hard truncation. Known candidates: `QualifyingBattle`, `PitStopStrategyWidget`, `RacePaceBattle`. `DataTableWidget` has scroll; skip.

Acceptance:
- Every widget has stable `_key`; no duplicate-key warnings in React DevTools.
- Pre-upgrade sessions still render via fallback key.
- `RaceStoryWidget` shows 4 + toggle when story has more than 4 points.
- At least two other hard-sliced widgets get the same toggle.

Observable-behaviour tests (manual):
- Ask a race-story question with 8 beats; widget shows 4 + "Show all 8 points"; expanding reveals all 8.
- Reload from pre-upgrade session; widgets still render; toggles work.
- DevTools console clear of duplicate-key warnings.

---

## Phase 3 — End-to-End Testing (~1 week)

### F40 — End-to-end Test (HTTP → Resolver → Agentic Loop → Widget)

Files: add `server/tests/test_e2e.py`; modify `server/tests/conftest.py`. Tests itself.

Current state: unit tests mock the LLM and FastF1 in isolation. Nothing exercises the full request lifecycle.

Change:

1. **`ScriptedAnthropicClient` in `conftest.py`** keyed by user-message substring. Each script entry is a list of turns; consecutive `messages.create` calls within one agentic loop pull successive turns. A turn is either a `tool_use` block or a final text block. Stub `chat._anthropic_client` via `monkeypatch.setattr`. Mirror surface for the OpenAI provider via the same script format so a single fixture covers both.
2. **FastF1 stub** keyed by `(round_number, session_type)`. `_build_fake_session(data)` is a duck-typed object exposing only the attributes the wrappers read (`.load()`, `.laps`, `.results`, `.session_info`). `monkeypatch.setattr("fastf1.get_session", ...)`. Reset between tests via `function`-scoped fixture. Also `monkeypatch.setenv("FASTF1_CACHE_DIR", tmp_path)` so the real disk cache is untouched.
3. **Jolpica stub** via `monkeypatch.setattr("requests.get", ...)` returning canned JSON for standings/results.
4. **Three scenarios:**

   **A — "Who won the 2025 Hungarian GP?"** Agentic path. Resolver returns `round=13`, `session_type="R"`. LLM script: `tool_use(get_race_results, {round_number: 13})` → tool_result → text "Lando Norris won...". FastF1 stub: round 13 R has Norris first. Assert 200; widget with type `data_table` or `race_results`; text mentions Norris; no ERROR-level logs.

   **B — "Compare Norris and Piastri's qualifying at Spa"** Deterministic path. Resolver returns drivers + round 14. Hits `_execute_analysis_tool_call` → `analyze_qualifying_battle`. FastF1 stub: round 14 Q with Q3 times for both. Assert widget type `qualifying_battle`; narrative mentions both names.

   **C — "Tyre degradation for Russell at Singapore"** FastF1 stub: synthetic stint with clear cliff at tyre age 14 (pre slope 0.05, post slope 0.25 s/lap, 20 laps). LLM script: `tool_use(analyze_stint_degradation)` → text mentions "cliff". Assert widget type `deg_trend_chart`; `stints[0].cliff_detected == true`; `cliff_tyre_age == 14`; text contains "cliff".

5. **Cross-cutting assertion helper**:
   ```python
   def assert_clean_e2e(response, caplog):
       assert response.status_code == 200
       body = response.json()
       assert isinstance(body["response"], str) and body["response"]
       assert isinstance(body["widgets"], list)
       for w in body["widgets"]:
           assert isinstance(w.get("type"), str)
       errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
       assert errors == [], f"Unexpected errors: {[r.message for r in errors]}"
   ```
6. **No-network sanity test**: `monkeypatch.setattr("socket.socket.connect", raise_runtimeerror)`; suite still passes.

Acceptance:
- Three scenarios pass against current implementation. If any fail because of a real bug surfaced by writing the test, file a follow-up rather than papering over.
- `ScriptedAnthropicClient` handles multi-turn tool-use loops.
- No real HTTP leaves the test process.
- `python -m pytest tests/test_e2e.py -v` runs in < 5s.

Observable-behaviour tests:
- `test_scenario_a_who_won_hungarian_2025`
- `test_scenario_b_compare_norris_piastri_qualifying_spa`
- `test_scenario_c_tyre_degradation_russell_singapore_cliff_detected`
- `test_chat_endpoint_400_on_empty_message`
- `test_chat_endpoint_returns_429_on_anthropic_rate_limit_e2e` (depends on F34)
- `test_chat_endpoint_returns_503_on_fastf1_error_e2e` (depends on F34)
- `test_no_real_network_calls_during_e2e_suite`

---

## Validation Checklist

Run after each phase; rerun all at the end.

- [ ] `cd server; python -m pytest tests/ -v` — full suite green.
- [ ] `cd client; npm run build` — frontend compiles.
- [ ] **Phase 1**: `grep -rn "except Exception" server/` shows only the central handler in `main.py` and the wrappers in `chat.py`/`f1_data.py`/`openf1.py`.
- [ ] **Phase 1**: `grep -rn "raise HTTPException(status_code=500" server/main.py` — no per-endpoint hand-rolled 500s.
- [ ] **Phase 1**: `grep -n "args\[" server/tools.py` — access only after the dispatch-top `_require_args` call (optional args use `args.get`).
- [ ] **Phase 1**: `_OPENF1_RETRY_DELAYS` defined; `_openf1_get` retries on `ConnectionError`/`Timeout`/5xx; `timeout=10`.
- [ ] **Phase 2**: `client/src/lib/storage.js` exists; `useChatSessions.js` no longer calls `localStorage.setItem` directly.
- [ ] **Phase 2**: `validateChatResponse` covers all observed shapes; `WidgetErrorBoundary` wraps every widget.
- [ ] **Phase 2**: every widget has `_key`; no duplicate-key warnings in React DevTools.
- [ ] **Phase 3**: `test_e2e.py` runs < 5s; three scenarios pass; no real network calls.
- [ ] Manual: block egress to `api.anthropic.com`; chat returns 429 with `error_type: AnthropicError`; UI shows throttling.
- [ ] Manual: DevTools → Application → Local Storage — session count <= 50 after creating 51.
- [ ] Manual: race-story question with 8 beats — "Show all" toggle works.

---

## Risks and Open Questions

| Risk | When it triggers | Proposed resolution | Decision needed by |
|---|---|---|---|
| F34 changes status codes from "always 500" to mixed 4xx/5xx; FE retry/error logic may behave differently in the deploy window | Phase 1 deploy | Sequence Phase 1 + Phase 2 deploys as a pair so FE knows how to read `error_type`. Or: behind config flag `ERROR_HANDLING_V2` for one cycle. Recommend the flag — single deploy with reversible switch. | F34 start |
| F35's schema-driven validation breaks if `TOOL_DEFINITIONS` lists a required key the branch doesn't actually use | F35 testing | Startup assertion: for every entry in `_REQUIRED_ARGS`, the matching `execute_tool` branch references each key. Fail loud on `import tools`. | F35 start |
| F36's `time.sleep` blocks the event-loop thread | Prod load | Chat calls go through `run_in_threadpool` (`main.py:80`); worst-case ~6.5s budget. Revisit if we add async streaming endpoints. Acknowledge and defer. | F36 start |
| FastF1 filesystem cache state leaks between F40 test runs | Always | `conftest.py` monkeypatches `FASTF1_CACHE_DIR` to `tmp_path` for e2e tests; verify the FastF1 stub doesn't touch the real cache. | F40 start |
| F40's FastF1 stub is duck-typed; FastF1 minor-version bump could silently diverge | After any FastF1 upgrade | Pin FastF1 in `requirements.txt`; on upgrade, regenerate stub-shape fixtures from a real session capture. CI check that imports `fastf1` and asserts the attributes the stub fakes still exist. | F40 start |
| F40's LLM mocking must fake both Anthropic and OpenAI surfaces — drift is easy | Adding new scenarios | Single `ScriptedLLMClient` used for both providers via the `LLM_PROVIDER` env switch; `messages.create` and `chat.completions.create` surfaces share a script format. | F40 start |
| F37's LRU prune drops user data without confirmation | First quota event | `console.warn` for v1; revisit a toast/settings page in a follow-up. | F37 close-out |
| F38's ErrorBoundary swallows widget bugs and we stop noticing | After F38 deploy | `componentDidCatch` logs via `console.error`; pipe to Sentry in a follow-up. Manual triage via DevTools in v1. | F38 close-out |

## Commit Plan

**Phase 1:**
1. `feat: typed F1DashError hierarchy in server/errors.py`
2. `feat: wrap FastF1 calls in _load_session() with FastF1Error`
3. `feat: wrap Jolpica calls with JolpicaError`
4. `feat: typed Anthropic/OpenAI wrappers raising AnthropicError`
5. `feat: central FastAPI exception handler maps F1DashError to typed HTTP status`
6. `feat: schema-driven required-arg validation in execute_tool()`
7. `feat: bounded exponential backoff and 10s timeout in _openf1_get()`

**Phase 2:**

8. `feat: LRU prune and quota recovery in client storage layer`
9. `feat: validate chat response shape; typed error messages in UI`
10. `feat: WidgetErrorBoundary isolates widget render failures`
11. `feat: stable widget UUIDs and "show all N points" toggle`

**Phase 3:**

12. `test: scripted LLM and FastF1 stubs for e2e suite`
13. `test: end-to-end scenarios — race winner, quali compare, cliff detection`

## Non-Goals

- No circuit breakers, no token-bucket pre-rate-limiting. (Future plan.)
- No retry on Anthropic — provider retries on its side; UX is the "retry" message.
- No Pydantic models for widget payloads — JSON-schema validation is the FE's job until contracts stabilise.
- No Vitest/RTL setup. Manual FE smoke only for now.
- No structured-JSON logging. Logger format stays; only level and content change.
- No `tenacity` or other retry libraries — three-attempt explicit loop is clearer at this scope.
- No backend tests for FE-only features (F37, F38, F39).

## References

- `2026-05-19-backend-core-bugfixes.md` — minimum patches this plan systematises. Per-feature cross-refs in the Background table.
- `2026-05-15-tire-cliff-detection.md` — F40 scenario C verifies cliff fields flow end-to-end.
- `2026-05-15-deterministic-parallel-tool-execution.md` — F40 scenario B exercises the deterministic path.
- `2026-05-19-counterfactual-race-simulation.md` — depends on a stable typed-error surface; F34 lands first.
- Audit log: 2026-05-19, items F34–F40 and bugs #1–4, #13, #18, #19, #20, #23.
