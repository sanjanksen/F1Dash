# Frontend Bug Fixes Implementation Plan

> Status: not started. Estimated effort: 2–3 days of focused work.

## Goal

Land the minimum fixes for eight frontend reliability and UX bugs surfaced by the 2026-05-19 audit (items #18–25). Each task is independent and shippable on its own. The plan deliberately scopes each fix narrowly so it does not block the wider frontend-resilience and design-quality feature work, which will deliver broader hardening (typed payload schemas, telemetry-size budgets, a curated driver-code registry shared with the backend) on top of these foundations.

## Background

The audit identified eight concrete defects in `client/` that all share a common smell: optimistic payload destructuring, silent failures, missing keys, and brittle string parsing. None are pure feature work — each is a real bug with a one- or two-file fix. They should not be bundled into a larger refactor; each lands behind its own commit.

| # | Bug | Files | Severity |
|---|---|---|---|
| 18 | `sendChatMessage` response shape not validated | `client/src/App.jsx` | High — user sees blank assistant reply on shape error |
| 19 | `localStorage` growth unbounded | `client/src/hooks/useChatSessions.js` | High — silent persistence corruption |
| 20 | Widget React keys collide for two same-type widgets | `client/src/components/AnswerRenderer.jsx` | Medium — incorrect DOM reuse on re-render |
| 21 | Qualifying widget falls back to splitting the title | `client/src/components/chat-widgets/QualifyingBattleWidget.jsx`, `server/chat.py` | Medium — brittle if title format changes |
| 22 | Data-table cells render `""` for missing keys | `client/src/components/chat-widgets/DataTableWidget.jsx` | Medium — backend gaps look like real data |
| 23 | Race-story points hard-capped at 4 | `client/src/components/chat-widgets/RaceStoryWidget.jsx` | Low — UX, but user-visible truncation |
| 24 | Badge regex `\b[A-Z]{3}\b` over-matches acronyms | `client/src/components/AnswerRenderer.jsx` | Medium — visual bug, drifts as vocab grows |
| 25 | `fetchCircuits` failure is silently swallowed | `client/src/components/ChatView.jsx` | Low — degraded suggestion strip with no telemetry |

## Overlap With Future Feature Work

Several of these bugs touch surface area that in-progress feature plans will harden further. The bug plan stays minimal; future feature plans layer typed payload schemas, telemetry-size budgets, and a curated driver-code registry on top.

| Bug task | Minimum fix here | Broader hardening deferred to feature plan |
|---|---|---|
| Task 18 | `validateChatResponse(body)` helper at one call site; user-facing fallback message | Full Zod/TypeScript-style shape validation across `f1api.js` (F38) |
| Task 19 | try/catch + LRU pruning at `persist()` | Widget-payload-size budget; per-session compaction; IndexedDB migration (F37) |
| Task 20 | Stable per-widget id at message creation | Typed widget envelope with `id` field on the backend (F39) |
| Task 24 | Pull driver-code allowlist from a per-message field or resolver export | Shared driver-code registry on both ends; system-wide token vocabulary |

Tasks 21, 22, 23, 25 are bug-only — no overlap.

---

## Task 18: Validate Chat Response Shape Before Destructuring

Files:

- Modify: `client/src/App.jsx`
- Test: none (component test infrastructure does not exist yet; this is a UI-visible smoke check)

Current state: `client/src/App.jsx:51` runs:

```js
const { response, widgets = [] } = await sendChatMessage(text, history)
```

`sendChatMessage` in `client/src/lib/f1api.js` returns whatever `await res.json()` produced. A 500 returning HTML, a streaming abort, or a proxy hiccup destructures to `response: undefined`, which `AnswerRenderer` then renders as nothing. The `catch` block at line 56 only surfaces `"Something went wrong: ${error.message}"`, so a malformed-but-non-throwing body slips silently into the chat as a blank assistant turn.

Change:

1. Add a small helper at the top of `App.jsx` (or beside `sendChatMessage` in `client/src/lib/f1api.js` if it fits cleanly there):

```js
function validateChatResponse(body) {
  if (!body || typeof body !== 'object') {
    return { ok: false, reason: 'not-an-object' }
  }
  if (typeof body.response !== 'string' || body.response.length === 0) {
    return { ok: false, reason: 'missing-or-empty-response' }
  }
  if (body.widgets != null && !Array.isArray(body.widgets)) {
    return { ok: false, reason: 'widgets-not-array' }
  }
  return { ok: true, response: body.response, widgets: body.widgets ?? [] }
}
```

2. Replace the destructuring block in the try at `App.jsx:51`:

```js
const body = await sendChatMessage(text, history)
const validated = validateChatResponse(body)
if (!validated.ok) {
  console.error('Chat response shape invalid:', validated.reason, body)
  updateMessages(sessionId, [
    ...withUser,
    {
      id: crypto.randomUUID(),
      role: 'assistant',
      text: 'The server returned an unexpected response. Please try again.',
      isError: true,
    },
  ])
  return
}

const { response, widgets } = validated
updateMessages(sessionId, [
  ...withUser,
  { id: crypto.randomUUID(), role: 'assistant', text: response, widgets },
])
```

3. Leave the existing `catch (error)` block alone — it still handles network-level throws.

4. Do not add a UI toast. The error message in the assistant turn is enough; the console log is for the developer.

Acceptance:

- A manual test: temporarily edit `sendChatMessage` to return `{}` → the assistant turn renders the user-visible "unexpected response" text and the console contains the body.
- A manual test: temporarily edit `sendChatMessage` to return `{ response: '' }` → same fallback.
- A manual test: temporarily edit `sendChatMessage` to return `{ response: 'ok', widgets: 'broken' }` → same fallback; widgets is not coerced.
- A real happy-path response still renders normally with no warnings.
- No widget renders for a malformed response (the assistant turn carries `widgets: undefined`, and `AnswerRenderer` already handles that).

Risks:

- The validator is permissive on extra fields by design — adding a strict schema is the feature-plan task (F38). Do not block this fix on it.

---

## Task 19: Bound `localStorage` Growth With Quota Handling And LRU Pruning

Files:

- Modify: `client/src/hooks/useChatSessions.js`
- Test: none (no client test harness); manual quota-fill check below

Current state: `client/src/hooks/useChatSessions.js:13` does:

```js
function persist(sessions) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions))
}
```

No size check, no try/catch. Telemetry-heavy widgets (`speed_trace`, `qualifying_battle`, `race_story`) carry ~30 KB of point arrays each. 50 sessions × 10 messages × 30 KB ≈ 15 MB, well past the ~5 MB browser quota. When `setItem` throws `QuotaExceededError`, the next `load()` happens against a stale or partially-written value, and the next user message corrupts the chat list.

Change:

1. Add a constants block near the top of the file:

```js
const STORAGE_KEY = 'f1dash_sessions'
const TARGET_BYTES = 4 * 1024 * 1024     // 4 MB — soft target, below ~5 MB browser quota
const MIN_SESSIONS_TO_KEEP = 5            // never prune below this even if oversized
```

2. Replace `persist()` with a version that catches the quota error and falls back to LRU pruning:

```js
function approxBytes(value) {
  // JSON string length is a close-enough proxy for UTF-16-encoded localStorage cost
  return value.length * 2
}

function trimSessions(sessions) {
  // Keep newest-first ordering (the rest of the code already enforces it).
  // Drop the oldest until under target or down to MIN_SESSIONS_TO_KEEP.
  let trimmed = sessions
  while (trimmed.length > MIN_SESSIONS_TO_KEEP) {
    const serialized = JSON.stringify(trimmed)
    if (approxBytes(serialized) <= TARGET_BYTES) return trimmed
    trimmed = trimmed.slice(0, trimmed.length - 1)
  }
  return trimmed
}

function persist(sessions) {
  let toWrite = sessions
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(toWrite))
    return toWrite
  } catch (err) {
    if (err?.name !== 'QuotaExceededError' && err?.code !== 22) {
      console.warn('Failed to persist sessions:', err)
      return toWrite
    }
    console.warn('localStorage quota exceeded; pruning oldest sessions.')
    toWrite = trimSessions(toWrite)
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(toWrite))
      return toWrite
    } catch (innerErr) {
      console.warn('Still over quota after pruning; clearing sessions.', innerErr)
      try {
        localStorage.removeItem(STORAGE_KEY)
      } catch {}
      return []
    }
  }
}
```

3. The two existing call sites that invoke `persist(next)` (inside `createSession` and `updateMessages` at lines around 36 and 57) need to use the return value so React state stays in sync with what actually got written:

```js
setSessions((prev) => {
  const next = [session, ...prev]
  const persisted = persist(next)
  return persisted
})
```

If pruning fires, the returned `persisted` array is shorter than `next`, and the React state updates to match — keeping UI and storage consistent.

4. Optional widget-payload trimming (only land if Task 19 leaves headroom feeling thin in manual testing): before persisting, walk the oldest N sessions and strip large arrays from their widgets — keep `summary`, drop fields like `points`, `corners`, `laps`. Implementation sketch (do not land unless quota issues persist):

```js
function stripHeavyArrays(widget) {
  if (!widget || typeof widget !== 'object') return widget
  const HEAVY = ['points', 'laps', 'corners', 'samples']
  const out = { ...widget }
  for (const k of HEAVY) delete out[k]
  return out
}
```

Recommend deferring this branch to the feature plan (F37) and shipping only the quota-catch + LRU pruning here.

Acceptance:

- A manual test: in DevTools, run `for (let i = 0; i < 200; i++) localStorage.setItem('junk-' + i, 'x'.repeat(50000))` to fill the quota, then trigger a chat — `persist` should log a warning, prune to fit, and the chat list should remain coherent (newest sessions kept).
- A manual test: with a normal-size chat list, persist still works without warnings.
- The returned `persist()` value is reflected in the React state (no drift between memory and storage).
- The `MIN_SESSIONS_TO_KEEP` invariant holds: at least the most recent 5 sessions survive even under quota pressure.

Risks:

- Pruning the oldest session silently loses user-visible history. A future feature plan (F37) should add a UI cue ("3 older sessions were archived to free space") — out of scope here. Acceptable for now: the alternative is a hard-broken chat list.
- `approxBytes` is approximate. If a session is itself >4 MB, the loop trims down to `MIN_SESSIONS_TO_KEEP` and then `setItem` may still throw — handled by the inner `removeItem` fallback.

---

## Task 20: Generate Stable Per-Widget IDs At Message Creation

Files:

- Modify: `client/src/App.jsx`, `client/src/components/AnswerRenderer.jsx`
- Test: none (visual-only; React DevTools key inspection is enough)

Current state: `client/src/components/AnswerRenderer.jsx:196` builds widget React keys as:

```jsx
key={`${widget.type}-${index}`}
```

When an answer contains two `data_table` widgets (or two `corner_comparison`, etc.) and the message re-renders for any reason — typing animation, theme change, container resize — React reuses DOM subtrees by index, but the type-prefix gives the illusion of identity. Internal state (open accordions, hover, scroll positions) gets cross-wired.

Change:

1. At message-creation time in `App.jsx:54`, stamp each widget with a stable id before storing it on the message:

```js
const stampedWidgets = (widgets ?? []).map((w) => ({
  ...w,
  _id: w?._id ?? (typeof crypto?.randomUUID === 'function' ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`),
}))
updateMessages(sessionId, [
  ...withUser,
  { id: crypto.randomUUID(), role: 'assistant', text: response, widgets: stampedWidgets },
])
```

2. In `AnswerRenderer.jsx:196`, replace the key:

```jsx
key={widget._id ?? `${widget.type}-${index}`}
```

Fallback to the index-based key keeps backward compatibility with sessions already in `localStorage` that lack `_id`.

3. Optional follow-up (do not block this task): the backend's widget builders in `server/chat.py` could populate a server-side `widget.id`. That belongs to the typed-widget-envelope feature plan (F39) — not this task.

Acceptance:

- A manual test: trigger an answer with two `data_table` widgets (e.g. one for race results, one for season standings). Open React DevTools → each widget has a distinct `key` prop derived from `_id`.
- A manual test: re-render the message (toggle dark mode) — internal widget state (open rows, selected drivers) does not cross-wire between the two tables.
- A session reloaded from `localStorage` written before this change still renders without crashing (the fallback `${widget.type}-${index}` triggers).

Risks:

- `_id` is a client-side concept and is not echoed back to the server. That's fine — it only needs to be stable within the lifetime of the message in the browser. If a session is exported/imported across browsers later, the ids regenerate; that's also fine.

---

## Task 21: Stop Falling Back To `title.split(' vs ')` In Qualifying Widget

Files:

- Verify: `server/chat.py` (widget builder `_make_qualifying_battle_widget`)
- Modify: `client/src/components/chat-widgets/QualifyingBattleWidget.jsx`
- Test: `server/tests/test_chat.py` (one assertion); manual frontend check

Current state: `client/src/components/chat-widgets/QualifyingBattleWidget.jsx:222–223`:

```jsx
const driverA = widget.driver_a ?? widget.title?.split(' vs ')[0]
const driverB = widget.driver_b ?? widget.title?.split(' vs ')[1]
```

If `widget.title` is `"Norris vs Leclerc — Qualifying Battle (R5)"`, the split yields `"Norris"` and `"Leclerc — Qualifying Battle (R5)"`. Brittle.

Change:

1. In `server/chat.py`, verify `_make_qualifying_battle_widget()` always populates `driver_a` and `driver_b` as top-level fields on the widget dict. If it currently relies on `title`, fix it to set both fields from the resolved driver names. Add a one-line assertion in `server/tests/test_chat.py` that the builder output contains both keys for a representative input.

2. In `QualifyingBattleWidget.jsx`, remove the split-title fallback. If either field is missing, render a placeholder block and short-circuit the rest of the widget:

```jsx
const driverA = widget.driver_a
const driverB = widget.driver_b

if (!driverA || !driverB) {
  return (
    <section className="rounded-lg border border-border bg-muted/40 p-4 text-sm text-muted-foreground">
      Driver information for this qualifying battle is missing. Please try again or rephrase the question.
    </section>
  )
}

const fasterIsA = widget.faster_driver === driverA
// ... rest of widget unchanged
```

Acceptance:

- `server/tests/test_chat.py` has an assertion that `_make_qualifying_battle_widget(...)` returns a dict with `driver_a` and `driver_b` as non-empty strings for a representative input.
- A manual test: artificially null both fields in the assistant message in DevTools → widget renders the placeholder, not a malformed comparison.
- Happy-path qualifying battles render exactly as before.

Risks:

- Sessions loaded from `localStorage` before backend builder fix may still have widgets missing `driver_a`/`driver_b`. The placeholder is the correct UX for those — degrades gracefully.

---

## Task 22: Distinguish Missing-Key From Empty-Value In Data Table Cells

Files:

- Modify: `client/src/components/chat-widgets/DataTableWidget.jsx`

Current state: `client/src/components/chat-widgets/DataTableWidget.jsx:53`:

```jsx
<td key={column.key} className={cellClass(column.align)}>
  {row?.[column.key] ?? ''}
</td>
```

`""` is rendered whether the backend explicitly returned `""`/`null` (real "no data") or omitted the key entirely (a backend bug). Both look like real empty cells.

Change:

1. Render three distinct states:

```jsx
{columns.map((column) => {
  const present = row != null && Object.prototype.hasOwnProperty.call(row, column.key)
  const value = present ? row[column.key] : undefined

  let display
  let title
  if (!present) {
    display = '?'
    title = 'value not provided by backend'
  } else if (value === null || value === '') {
    display = '—' // em-dash
  } else {
    display = value
  }

  return (
    <td
      key={column.key}
      className={cellClass(column.align)}
      title={title}
      aria-label={title}
    >
      {display}
    </td>
  )
})}
```

2. The em-dash `—` ("—") is the standard "no data" glyph; the `?` is the operator-visible "backend didn't even send this key" signal. The native `title` tooltip is enough — no custom popover.

Acceptance:

- A manual test: synthesize a row missing one column key → that cell renders `?` with a hover tooltip "value not provided by backend".
- A manual test: synthesize a row with `key: null` → that cell renders an em-dash, no tooltip.
- A manual test: synthesize a row with `key: ""` → same em-dash.
- Normal cells with non-empty data render unchanged.

Risks:

- `?` glyph could distract from real data on dense tables. Acceptable trade-off; if it visually overwhelms, downgrade to a smaller `?` styled with `text-muted-foreground` — leave styling decisions to the implementer.

---

## Task 23: Add "Show More" To Race Story Points

Files:

- Modify: `client/src/components/chat-widgets/RaceStoryWidget.jsx`

Current state: `client/src/components/chat-widgets/RaceStoryWidget.jsx:69`:

```jsx
{widget.story_points.slice(0, 4).map((point, index) => (
```

User cannot see points 5+ even when they exist. A race story can carry up to ~10 points in practice.

Change:

1. Add expansion state at the top of the component body:

```jsx
const [storyExpanded, setStoryExpanded] = useState(false)
```

2. Replace the `.slice(0, 4)` block with a conditional render that toggles on the new state:

```jsx
{widget.story_points?.length ? (
  <section className="py-4">
    <h4 className="text-sm font-medium text-foreground">Race story</h4>
    <ol className="mt-3 space-y-2 text-sm leading-6 text-foreground">
      {(storyExpanded ? widget.story_points : widget.story_points.slice(0, 4)).map((point, index) => (
        <li key={index} className="grid grid-cols-[1.5rem_minmax(0,1fr)] gap-2">
          <span className="font-mono-data text-xs text-muted-foreground">{index + 1}</span>
          <span>{point}</span>
        </li>
      ))}
    </ol>
    {widget.story_points.length > 4 ? (
      <button
        type="button"
        onClick={() => setStoryExpanded((v) => !v)}
        className="mt-3 text-xs text-muted-foreground underline-offset-2 hover:underline"
      >
        {storyExpanded
          ? 'Show fewer'
          : `Show ${widget.story_points.length - 4} more`}
      </button>
    ) : null}
  </section>
) : null}
```

3. Default collapsed. State is local to this widget instance; it does not persist across reloads, and that's fine.

Acceptance:

- A manual test: widget with 4 or fewer points has no button.
- A manual test: widget with 7 points renders 4 + a "Show 3 more" button; clicking expands to all 7 and the button reads "Show fewer".
- The button styling matches the muted-foreground utility class used elsewhere in the widget (no new visual tokens).

Risks:

- None significant. State resets on remount, which is acceptable for an in-message control.

---

## Task 24: Restrict Driver-Code Badge Matching To A Known Allowlist

Files:

- Modify: `client/src/components/AnswerRenderer.jsx`
- Optional: `server/chat.py` to populate a per-message `valid_driver_codes` field

Current state: `client/src/components/AnswerRenderer.jsx:84` uses:

```js
const parts = text.split(
  /(\*\*\*[^*]+\*\*\*|\*\*[^*]+\*\*|`[^`]+`|\bP\d+\b|\bQ[123]\b|\bSC\b|\bVSC\b|\bFP[123]\b|\b[A-Z]{3}\b|\b\d+\.\d+s\b)/g,
)
```

and at line 115:

```js
if (/^[A-Z]{3}$/.test(part) && !BADGE_BLOCKLIST.has(part)) {
  return <Badge key={index} variant="muted" ...>{part}</Badge>
}
```

The blocklist at lines 75–81 is a growing reactive list of acronyms ("LAP", "WET", "FIA", etc.). Every new 3-letter acronym that appears in a model answer renders as a driver-code badge — wrong by default.

Change:

1. Prefer the allowlist path. Two options, pick (a):

   **(a) Per-message allowlist passed from the backend (recommended)**

   - In `server/chat.py`, augment the chat response with `valid_driver_codes: list[str]` derived from the resolver's curated driver code set used in the request. This is one line in the response builder.
   - In `App.jsx`, store that field on the assistant message: `{ ..., valid_driver_codes }`.
   - Pass it through to `AnswerRenderer` as a prop.
   - The badge regex still matches `\b[A-Z]{3}\b`; the render check at line 115 becomes:

     ```js
     if (/^[A-Z]{3}$/.test(part) && validDriverCodes.has(part)) {
       return <Badge key={index} variant="muted" ...>{part}</Badge>
     }
     ```

   - Drop the `BADGE_BLOCKLIST`. Plain spans render for unmatched 3-letter tokens.

   **(b) Static client allowlist (fallback if the backend change is rejected)**

   - Import a hard-coded set of current-season driver codes from `client/src/lib/driverCodes.js` (new file).
   - Same render-check pattern, gated on `STATIC_DRIVER_CODES.has(part)`.
   - Trade-off: stale across season changes; the file must be edited when the grid changes.

2. Recommend (a). It is two lines of backend code and produces a per-request truth source. The driver-code-registry feature plan can later promote this into a typed schema and a shared module on both ends.

Acceptance:

- A manual test: an assistant answer containing "the FIA stewards reviewed" — "FIA" renders as plain text, not a badge.
- A manual test: an assistant answer containing "NOR vs LEC" — both render as muted badges.
- A manual test: a season query for an older era where "VET" is valid — "VET" renders as a badge; "VTR" (not on the grid) does not.
- `BADGE_BLOCKLIST` is removed from `AnswerRenderer.jsx` (option a) or replaced by `driverCodes.js` import (option b).

Risks:

- Option (a) couples a UI-rendering decision to a per-message backend field. Acceptable: the backend already drives the answer; adding one allowlist field is consistent.
- If the backend forgets to populate `valid_driver_codes`, no driver codes render as badges (graceful degradation, not crash). Acceptable.

---

## Task 25: Log And Surface `fetchCircuits` Failure In ChatView

Files:

- Modify: `client/src/components/ChatView.jsx`

Current state: `client/src/components/ChatView.jsx:17–23`:

```jsx
useEffect(() => {
  fetchCircuits()
    .then((circuits) => {
      const today = new Date().toISOString().slice(0, 10)
      const completed = circuits.filter((c) => c.date < today)
      if (completed.length > 0) setLastRound(completed[completed.length - 1])
    })
    .catch(() => {})
}, [])
```

The empty `.catch(() => {})` silently swallows backend failure. The suggestion strip degrades to "the latest race" and no one notices.

Change:

1. Replace the empty catch with a logger and a UI-visible hint:

```jsx
const [suggestionsLoadError, setSuggestionsLoadError] = useState(false)

useEffect(() => {
  fetchCircuits()
    .then((circuits) => {
      const today = new Date().toISOString().slice(0, 10)
      const completed = circuits.filter((c) => c.date < today)
      if (completed.length > 0) setLastRound(completed[completed.length - 1])
    })
    .catch((err) => {
      console.warn('Failed to fetch circuits for suggestion strip:', err)
      setSuggestionsLoadError(true)
    })
}, [])
```

2. In the rendered suggestion strip, append a small muted hint when the load failed (do not block the rest of the UI):

```jsx
{suggestionsLoadError ? (
  <p className="text-xs text-muted-foreground">
    Couldn't load suggestions — try a question anyway.
  </p>
) : null}
```

3. Do not retry. A second-try-on-failure adds flakiness without value; the user can refresh or just type a question.

Acceptance:

- A manual test: block `/api/circuits` in DevTools → console contains a WARN with the error; the suggestion strip falls back to "the latest race" + the muted hint.
- A manual test: normal `/api/circuits` response works as before; no console warning, no hint.
- The rest of the chat input/send flow is unaffected by the failure.

Risks:

- None significant.

---

## Validation Checklist

Cross-cutting. Run after each task lands; run all of these at the end of the slice.

- [ ] `cd client; npm run build` — frontend compiles after every task.
- [ ] `cd server; python -m pytest tests/ -v` — backend suite green (only Task 21 touches a backend test; Task 24 option (a) touches `chat.py`).
- [ ] Manual smoke: open `:5173`, submit "How did Russell do at Imola?" — happy path renders normally; widgets all have distinct keys (React DevTools).
- [ ] Manual smoke: force a 500 in `sendChatMessage` (DevTools throttle to offline, or temporarily edit the helper) — assistant turn shows "unexpected response" message, console has the body.
- [ ] Manual smoke: fill `localStorage` with junk (`for (let i = 0; i < 200; i++) localStorage.setItem('j' + i, 'x'.repeat(50000))`) and send a chat — console warns about quota; pruning fires; chat list remains coherent and matches storage.
- [ ] Manual smoke: trigger an answer with two `data_table` widgets — both render independently; toggling theme does not cross-wire state.
- [ ] Manual smoke: ask a question that produces a qualifying battle — `driver_a`/`driver_b` come from backend fields, not title splits.
- [ ] Manual smoke: confirm a data-table row with a known-missing key renders `?` with the "value not provided by backend" tooltip; a row with `null` renders `—`.
- [ ] Manual smoke: race story with >4 points shows "Show N more"; clicking expands.
- [ ] Manual smoke: an assistant turn containing "FIA stewards" does not render "FIA" as a badge; "NOR" still does.
- [ ] Manual smoke: block `/api/circuits` → console warns; muted hint visible; rest of UI works.
- [ ] `grep -n "split(' vs ')" client/src/components/chat-widgets/QualifyingBattleWidget.jsx` returns zero matches.
- [ ] `grep -n "BADGE_BLOCKLIST" client/src/components/AnswerRenderer.jsx` returns zero matches (if option (a) landed).
- [ ] `grep -n "catch(() => {})" client/src/` returns zero matches.

---

## Risks and Open Questions

| Risk | When it triggers | Proposed resolution | Decision needed by |
|---|---|---|---|
| Task 18's validator is permissive on extra fields | Always | Acceptable. Strict schema validation is feature-plan F38; the bug here is the absence of *any* validation. | Task 18 start |
| Task 19's LRU pruning silently deletes user history | Quota pressure | Log a WARN on the deletion, expose a "sessions archived" hint in a follow-up. The alternative — keep all sessions and break persistence — is worse. Acceptable for the bug fix. | Task 19 close-out |
| Task 19's `MIN_SESSIONS_TO_KEEP=5` cap could itself fail to fit (single huge session) | Edge case: one ~5 MB session | The inner `removeItem` fallback clears the lot. Painful but bounded; surfaces the underlying widget-payload-size bug visibly rather than silently. Acceptable. | Task 19 start |
| Task 20's `_id` is not persisted server-side | Always | Client-only stamping at message creation is enough for stable React keys within a session. The typed-widget-envelope feature plan (F39) can later promote `_id` into a server-issued field. | Task 20 close-out |
| Task 21's placeholder for missing `driver_a`/`driver_b` could hide a server bug | If backend regresses on the builder | The backend test added in Task 21 catches the regression directly. The placeholder is the right UX even when the bug is real. Acceptable. | Task 21 start |
| Task 22's `?` glyph could clutter dense tables | High-density tables with many gaps | Style with `text-muted-foreground` + reduced opacity; if still distracting, replace with a small caret icon in the design pass. Out of scope here. | Task 22 close-out |
| Task 23's expansion state resets on remount | Theme toggle, navigation away | Acceptable — the control is intentionally per-message and per-render. Persisting would require lifting state to the message store, which is feature work, not a bug fix. | Task 23 start |
| Task 24's per-message allowlist couples backend to a UI rendering decision | Always | The backend already controls the answer text; adding one allowlist field is consistent and one-line. The driver-code-registry feature plan can later promote this to a shared schema. | Task 24 start |
| Task 24 option (b) (static client list) goes stale across season changes | When grid changes mid-season | Recommend option (a). If we land (b), add a `TODO: regenerate when grid changes` and a season-change checklist item. | Task 24 start |
| Task 25's hint text could distract from happy-path UX | Always | Only render when `suggestionsLoadError === true`. Muted styling. Acceptable. | Task 25 start |

## Commit Plan

Each task lands as its own commit, in order:

1. `fix: validate chat response shape before destructuring`
2. `fix: bound localStorage growth with quota handling and LRU pruning`
3. `fix: stable per-widget IDs at message creation`
4. `fix: stop falling back to title.split for qualifying widget drivers`
5. `fix: distinguish missing-key from empty-value in data table cells`
6. `feat: show-more toggle for race story points`
7. `fix: restrict driver-code badges to a per-message allowlist`
8. `fix: log and surface fetchCircuits failure in ChatView`

Each is small enough to review in one pass. Tasks 18, 19, 20 are foundational and should land first; the remaining five are independent and can land in any order after.

## Non-Goals

- No typed payload schema across `f1api.js` — that's feature plan F38.
- No IndexedDB migration or per-session compaction — that's feature plan F37.
- No typed widget envelope with server-issued `id` — that's feature plan F39.
- No shared driver-code registry module spanning client + server — future feature work.
- No component-level test harness setup — explicitly out of scope for this bug slice.
- No design-system pass on the new placeholders / hints / em-dashes — restrained inline styling only.
- No accessibility audit beyond the `title`/`aria-label` already added in Task 22 — broader a11y is feature work.

## References

- Companion plan: `2026-05-19-backend-core-bugfixes.md` — sibling bug plan from the same audit batch (items #1–7).
- Companion plan: `2026-05-15-tire-cliff-detection.md` — touches `DegTrendChart.jsx`; this plan does not.
- Companion plan: `2026-05-15-deterministic-parallel-tool-execution.md` — backend evidence shaping; relevant to Task 21's verification of `_make_qualifying_battle_widget`.
- Companion plan: `2026-05-19-counterfactual-race-simulation.md` — adds widgets that will benefit from Task 20's stable IDs.
- Audit log: 2026-05-19, items #18–25.
