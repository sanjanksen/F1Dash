# F1Dash Frontend Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix nine frontend issues: Sidebar session grouping bug, AnswerRenderer badge false positives and widget ordering, SpeedTraceChart line differentiation, RaceStoryWidget radio timestamp display, DriverCard nationality codes, CSS accent/destructive color clash, stale ChatView suggestion prompts, and a loading timeout message for slow responses.

**Architecture:** All changes are targeted edits to React JSX components and one CSS file. No new components. No new dependencies. Verification is done by running the Vite dev server (`npm run dev`) and visually inspecting the affected UI.

**Tech Stack:** React 19, Tailwind CSS v4, Vite 8, shadcn/ui components

---

## File Map

| File | Changes |
|------|---------|
| `client/src/components/Sidebar.jsx` | Fix grouping bug in `else` branch |
| `client/src/components/AnswerRenderer.jsx` | Blocklist 3-letter badge false positives; move widgets below lead text |
| `client/src/components/chat-widgets/SpeedTraceChart.jsx` | Add `strokeDasharray` to driver B line and legend dot |
| `client/src/components/chat-widgets/RaceStoryWidget.jsx` | Format radio timestamp to HH:MM local time |
| `client/src/components/ChatView.jsx` | Dynamic suggestions from last round; show timeout message after 15s |
| `client/src/components/DriverCard.jsx` | Add nationality → ISO3 code mapping |
| `client/src/index.css` | Make `--accent` purple (fastest-lap color); keep `--destructive` distinct red |
| `client/src/components/ChatView.jsx` | Fetch last completed round from `/api/circuits` for dynamic suggestions |
| `client/src/api/f1api.js` | Re-export `fetchCircuits` (already exists) |

---

### Task 1: Fix Sidebar session grouping bug

When multiple chat sessions share the same date label (e.g., three "Today" sessions), the `else` branch always appends to `groups[groups.length - 1]` — the most recently created group — instead of finding the matching group. Sessions from two days ago get appended to yesterday's group.

**Files:**
- Modify: `client/src/components/Sidebar.jsx`

- [ ] **Step 1: Locate the bug**

Open `client/src/components/Sidebar.jsx`. The grouping logic is:

```javascript
for (const session of sessions) {
    const label = formatDate(session.createdAt)
    if (!seen.has(label)) {
        seen.add(label)
        groups.push({ label, items: [session] })
    } else {
        groups[groups.length - 1].items.push(session)  // BUG: always last group
    }
}
```

- [ ] **Step 2: Fix the `else` branch**

Replace the `else` branch so it finds the matching group:

```javascript
for (const session of sessions) {
    const label = formatDate(session.createdAt)
    if (!seen.has(label)) {
        seen.add(label)
        groups.push({ label, items: [session] })
    } else {
        groups.find((g) => g.label === label).items.push(session)
    }
}
```

- [ ] **Step 3: Verify manually**

Start the dev server:
```bash
cd client && npm run dev
```

In the app, create 3 or more chat sessions. Navigate away and back. Confirm all sessions with the same date label appear in the correct group.

- [ ] **Step 4: Commit**

```bash
git add client/src/components/Sidebar.jsx
git commit -m "fix: sidebar grouping now finds matching date group instead of always appending to last"
```

---

### Task 2: Fix AnswerRenderer badge false positives

The `renderInline` regex `\b[A-Z]{3}\b` badges every 3-letter uppercase word including common prose words like LAP, WET, DRY, ERS, FIA. Add a blocklist of words that should never become badges.

**Files:**
- Modify: `client/src/components/AnswerRenderer.jsx`

- [ ] **Step 1: Locate the 3-letter badge handler in `renderInline`**

In `AnswerRenderer.jsx`, the relevant block is:

```javascript
if (/^[A-Z]{3}$/.test(part)) {
    return <Badge key={index} variant="muted" className="mx-0.5 tracking-[0.08em]">{part}</Badge>
}
```

- [ ] **Step 2: Add a blocklist constant above `renderInline`**

Before the `renderInline` function definition, add:

```javascript
// Words that look like 3-letter F1 codes but are common prose words
const BADGE_BLOCKLIST = new Set([
    'LAP', 'WET', 'DRY', 'FIA', 'ERS', 'PIT', 'CAR', 'RUN', 'END',
    'ALL', 'THE', 'AND', 'FOR', 'BUT', 'NOT', 'NEW', 'OLD', 'TOP',
    'ONE', 'TWO', 'SET', 'BOX', 'OFF', 'OWN', 'WAY', 'PUT', 'GET',
    'GOT', 'HAD', 'HAS', 'WAS', 'CAN', 'DID', 'NOW', 'ITS', 'OUT',
    'WIN', 'LED', 'GAP', 'AIR', 'KPH', 'MPH', 'KMH', 'TYR', 'AGO',
])
```

- [ ] **Step 3: Update the badge render condition**

Replace:

```javascript
if (/^[A-Z]{3}$/.test(part)) {
    return <Badge key={index} variant="muted" className="mx-0.5 tracking-[0.08em]">{part}</Badge>
}
```

with:

```javascript
if (/^[A-Z]{3}$/.test(part) && !BADGE_BLOCKLIST.has(part)) {
    return <Badge key={index} variant="muted" className="mx-0.5 tracking-[0.08em]">{part}</Badge>
}
```

- [ ] **Step 4: Verify manually**

Run the dev server and ask a question. Confirm that:
- Driver codes like VER, NOR, RUS still render as badges
- "He set the fastest LAP with an ERS issue" — "LAP" and "ERS" appear as plain text, not badges

- [ ] **Step 5: Commit**

```bash
git add client/src/components/AnswerRenderer.jsx
git commit -m "fix: blocklist common prose words from 3-letter badge rendering in AnswerRenderer"
```

---

### Task 3: Fix AnswerRenderer widget/text order

Currently, `AnswerRenderer` renders widgets **before** the lead text paragraph. This means a race story widget appears above the answer text, but the text provides the context for the widget. Render the lead text first, then widgets.

**Files:**
- Modify: `client/src/components/AnswerRenderer.jsx`

- [ ] **Step 1: Find the render order**

In `AnswerRenderer`, the return block currently is:

```jsx
return (
    <div className="max-w-3xl space-y-3.5">
        {widgets.map((widget, index) => (
            <WidgetRenderer key={`${widget.type}-${index}`} widget={widget} />
        ))}

        {hasLead ? (
            <div className="text-[15px] leading-7 text-foreground">
                {renderInline(first.text)}
            </div>
        ) : null}

        {bodyBlocks.map((block, index) => { ... })}
    </div>
)
```

- [ ] **Step 2: Move widgets below the lead paragraph**

Replace the return block with:

```jsx
return (
    <div className="max-w-3xl space-y-3.5">
        {hasLead ? (
            <div className="text-[15px] leading-7 text-foreground">
                {renderInline(first.text)}
            </div>
        ) : null}

        {widgets.map((widget, index) => (
            <WidgetRenderer key={`${widget.type}-${index}`} widget={widget} />
        ))}

        {bodyBlocks.map((block, index) => {
            if (block.type === 'paragraph') {
                return (
                    <Card key={index}>
                        <CardContent className="p-4 text-sm leading-7 text-foreground">
                            {renderInline(block.text)}
                        </CardContent>
                    </Card>
                )
            }

            if (block.type === 'bullet-list') {
                return (
                    <Card key={index}>
                        <CardContent className="p-4">
                            <List items={block.items} />
                        </CardContent>
                    </Card>
                )
            }

            if (block.type === 'number-list') {
                return (
                    <Card key={index}>
                        <CardContent className="p-4">
                            <List items={block.items} ordered />
                        </CardContent>
                    </Card>
                )
            }

            if (block.type === 'kv-grid') {
                return (
                    <Card key={index}>
                        <CardContent className="grid gap-3 p-4">
                            {block.rows.map((row, rowIndex) => (
                                <div
                                    key={rowIndex}
                                    className="grid gap-1 border-b border-border/80 pb-3 last:border-b-0 last:pb-0 sm:grid-cols-[9rem_minmax(0,1fr)] sm:gap-4"
                                >
                                    <div className="text-[10px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
                                        {row.label}
                                    </div>
                                    <div className="text-sm leading-7 text-foreground">{renderInline(row.value)}</div>
                                </div>
                            ))}
                        </CardContent>
                    </Card>
                )
            }

            if (block.type === 'section-list') {
                return (
                    <Card key={index}>
                        <CardContent className="p-4">
                            <div className="mb-3 text-[10px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
                                {block.title}
                            </div>
                            <List items={block.items} />
                        </CardContent>
                    </Card>
                )
            }

            return null
        })}
    </div>
)
```

- [ ] **Step 3: Verify manually**

Ask a race question that triggers a `race_story` widget. The answer text should appear first, followed by the structured widget card.

- [ ] **Step 4: Commit**

```bash
git add client/src/components/AnswerRenderer.jsx
git commit -m "fix: render lead text before widgets in AnswerRenderer so text provides context for widget"
```

---

### Task 4: Fix SpeedTraceChart line differentiation

Driver A and Driver B paths use different colors (white vs red), which is distinguishable but fails for colorblind users. Add `strokeDasharray="6 3"` to the driver B path and a dashed legend indicator.

**Files:**
- Modify: `client/src/components/chat-widgets/SpeedTraceChart.jsx`

- [ ] **Step 1: Add `strokeDasharray` to the driver B path**

In `SpeedTraceChart.jsx`, find:

```jsx
<path d={pathB} fill="none" stroke="currentColor" strokeWidth="2.2" className="text-primary/85" />
```

Replace with:

```jsx
<path d={pathB} fill="none" stroke="currentColor" strokeWidth="2.2" className="text-primary/85" strokeDasharray="6 3" />
```

- [ ] **Step 2: Update the driver B legend indicator**

In the legend section, find the driver B indicator:

```jsx
<span className="inline-flex items-center gap-1.5">
    <span className="h-2 w-2 rounded-full bg-primary/80" />
    {driverB}
</span>
```

Replace the dot with a short dashed line to match:

```jsx
<span className="inline-flex items-center gap-1.5">
    <svg width="16" height="8" className="shrink-0">
        <line x1="0" y1="4" x2="16" y2="4" stroke="currentColor" strokeWidth="2" strokeDasharray="4 2" className="text-primary/80" />
    </svg>
    {driverB}
</span>
```

- [ ] **Step 3: Verify manually**

Run the dev server and trigger a qualifying battle question that returns a SpeedTrace widget. Confirm driver B's line is dashed and the legend shows the matching dashed indicator.

- [ ] **Step 4: Commit**

```bash
git add client/src/components/chat-widgets/SpeedTraceChart.jsx
git commit -m "fix: add dashed strokeDasharray to SpeedTraceChart driver B line for colorblind accessibility"
```

---

### Task 5: Fix RaceStoryWidget radio timestamp display

The radio section shows a raw ISO 8601 timestamp string (e.g., `2026-03-23T14:37:22.000Z`) as the label. Format it to a readable `HH:MM` local time instead.

**Files:**
- Modify: `client/src/components/chat-widgets/RaceStoryWidget.jsx`

- [ ] **Step 1: Add a `formatRadioTime` helper**

At the top of `RaceStoryWidget.jsx`, before the `formatPitStop` function, add:

```javascript
function formatRadioTime(dateStr) {
    if (!dateStr) return 'Radio'
    try {
        return new Date(dateStr).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
    } catch {
        return 'Radio'
    }
}
```

- [ ] **Step 2: Use `formatRadioTime` in the radio section**

Find the radio highlights render block:

```jsx
{widget.radio_highlights.map((message, index) => (
    <li key={index} className="border-t border-border/80 pt-2 first:border-t-0 first:pt-0">
        <div className="text-xs text-muted-foreground">{message.date ?? 'Radio'}</div>
        {message.recording_url ? (
```

Replace `{message.date ?? 'Radio'}` with `{formatRadioTime(message.date)}`:

```jsx
{widget.radio_highlights.map((message, index) => (
    <li key={index} className="border-t border-border/80 pt-2 first:border-t-0 first:pt-0">
        <div className="text-xs text-muted-foreground">{formatRadioTime(message.date)}</div>
        {message.recording_url ? (
```

- [ ] **Step 3: Verify manually**

Trigger a race story widget that has radio data. Confirm the timestamp shows as `14:37` instead of `2026-03-23T14:37:22.000Z`.

- [ ] **Step 4: Commit**

```bash
git add client/src/components/chat-widgets/RaceStoryWidget.jsx
git commit -m "fix: format radio timestamps to HH:MM in RaceStoryWidget instead of raw ISO string"
```

---

### Task 6: Fix DriverCard nationality display

`stats.nationality?.slice(0, 3).toUpperCase()` produces `"BRI"` for `"British"`, `"DUT"` for `"Dutch"`, etc. These are meaningless. Map Jolpica/Ergast nationality strings to proper ISO 3166-1 alpha-3 codes (GBR, NLD, etc.).

**Files:**
- Modify: `client/src/components/DriverCard.jsx`

- [ ] **Step 1: Add the nationality map constant**

Before the `podiumTone` constant in `DriverCard.jsx`, add:

```javascript
const NATIONALITY_ISO3 = {
    'British': 'GBR',
    'Dutch': 'NLD',
    'Spanish': 'ESP',
    'Monegasque': 'MCO',
    'Australian': 'AUS',
    'Mexican': 'MEX',
    'Finnish': 'FIN',
    'French': 'FRA',
    'German': 'DEU',
    'Canadian': 'CAN',
    'Thai': 'THA',
    'Japanese': 'JPN',
    'Chinese': 'CHN',
    'Italian': 'ITA',
    'Danish': 'DNK',
    'American': 'USA',
    'New Zealander': 'NZL',
    'Austrian': 'AUT',
    'Argentinian': 'ARG',
    'Brazilian': 'BRA',
    'Belgian': 'BEL',
    'Swiss': 'CHE',
    'South African': 'ZAF',
    'Venezuelan': 'VEN',
    'Colombian': 'COL',
    'Czech': 'CZE',
    'Hungarian': 'HUN',
    'Polish': 'POL',
    'Indonesian': 'IDN',
    'Uruguayan': 'URY',
}
```

- [ ] **Step 2: Use the map in the Origin stat box**

Find:

```jsx
{stats.nationality?.slice(0, 3).toUpperCase() || '---'}
```

Replace with:

```jsx
{(stats.nationality && NATIONALITY_ISO3[stats.nationality]) || stats.nationality?.slice(0, 3).toUpperCase() || '---'}
```

- [ ] **Step 3: Verify manually**

Open the Stats tab. For George Russell ("British"), the Origin box should now show `GBR` instead of `BRI`. For Lando Norris ("British") same result.

- [ ] **Step 4: Commit**

```bash
git add client/src/components/DriverCard.jsx
git commit -m "fix: use ISO 3166-1 alpha-3 nationality codes in DriverCard instead of slice(0,3)"
```

---

### Task 7: Fix index.css accent color clash

`--accent` and `--primary` are both `0 72% 50%` (identical red). The `--destructive` is also the same value. `--accent` is used for the "FL" (Fastest Lap) badge in DriverCard — which in official F1 styling is **purple/violet**, not red. Give accent a distinct purple hue and leave destructive as a slightly darker red to differentiate error states from interactive elements.

**Files:**
- Modify: `client/src/index.css`

- [ ] **Step 1: Update `:root` color values**

In `client/src/index.css`, find the `:root` block and update three values:

```css
:root {
  /* ... keep existing values, change only these three: */
  --accent: 285 60% 52%;          /* purple — F1 fastest-lap official color */
  --accent-foreground: 0 0% 98%;
  --destructive: 0 65% 42%;       /* slightly darker/muted red, distinct from primary */
  --destructive-foreground: 0 0% 98%;
}
```

- [ ] **Step 2: Update `.dark` block with the same values**

In the `.dark` block, apply the same two overrides:

```css
.dark {
  /* ... keep existing values, change only these: */
  --accent: 285 60% 52%;
  --accent-foreground: 0 0% 98%;
  --destructive: 0 65% 42%;
  --destructive-foreground: 0 0% 98%;
}
```

- [ ] **Step 3: Verify manually**

Open the Stats tab. The "FL" badge on race results should now be purple/violet. Error states (if triggered) should show a slightly different red than interactive buttons.

- [ ] **Step 4: Commit**

```bash
git add client/src/index.css
git commit -m "fix: accent color is now purple (F1 fastest-lap) instead of duplicate primary red"
```

---

### Task 8: Dynamic ChatView suggestions from last completed round

The suggestion prompts in `ChatView.jsx` are hardcoded to reference old races ("Suzuka", "Japanese GP"). Replace with dynamic prompts that fetch the last completed round from `/api/circuits` and build suggestions from it.

**Files:**
- Modify: `client/src/components/ChatView.jsx`

- [ ] **Step 1: Add the `useEffect` and state for the last round**

At the top of `ChatView.jsx`, add `useEffect` to the existing import:

```javascript
import { useEffect, useRef, useState } from 'react'
```

(It's already imported — confirm it includes `useEffect`.)

Add `fetchCircuits` to the f1api import. Currently there is no f1api import in ChatView. Add:

```javascript
import { fetchCircuits } from '../api/f1api.js'
```

Inside the `ChatView` component function, after the existing state declarations, add:

```javascript
const [lastRound, setLastRound] = useState(null)

useEffect(() => {
    fetchCircuits()
        .then((circuits) => {
            const today = new Date().toISOString().slice(0, 10)
            const completed = circuits.filter((c) => c.date < today)
            if (completed.length > 0) {
                setLastRound(completed[completed.length - 1])
            }
        })
        .catch(() => {
            // Silently fall back to static suggestions
        })
}, [])
```

- [ ] **Step 2: Build dynamic suggestions from `lastRound`**

Replace the static `suggestions` constant:

```javascript
const suggestions = [
    { label: 'Race story', text: 'How did Russell do at Suzuka?' },
    { label: 'Team weekend', text: 'How did Ferrari do this weekend?' },
    { label: 'Race report', text: 'Give me the Japanese GP race recap' },
    { label: 'Qualifying', text: 'Why was Norris faster than Leclerc in qualifying?' },
]
```

with a `useMemo`-style computed value (no import needed, just a variable that reads `lastRound`):

```javascript
const eventName = lastRound?.event_name ?? 'the latest race'
const shortName = lastRound
    ? lastRound.event_name.replace(' Grand Prix', ' GP')
    : 'the latest race'

const suggestions = [
    { label: 'Race story', text: `How did Russell do at ${shortName}?` },
    { label: 'Team weekend', text: `How did Ferrari do at ${shortName}?` },
    { label: 'Race report', text: `Give me the ${shortName} race recap` },
    { label: 'Qualifying', text: `Why was Norris faster than Leclerc in qualifying at ${shortName}?` },
]
```

- [ ] **Step 3: Verify manually**

Run the dev server. The intro screen should show suggestions with the name of the last completed race. If the API request fails (e.g., server not running), it falls back to "the latest race" in each prompt.

- [ ] **Step 4: Commit**

```bash
git add client/src/components/ChatView.jsx
git commit -m "feat: ChatView suggestions now reference last completed round fetched from /api/circuits"
```

---

### Task 9: Add loading timeout message to ChatView

When the backend takes more than 15 seconds to respond, show a secondary message below the typing indicator so users know the request is still in progress (not stalled).

**Files:**
- Modify: `client/src/components/ChatView.jsx`

- [ ] **Step 1: Add a `loadingTooLong` state that fires after 15 seconds**

In `ChatView.jsx`, after the existing state declarations, add:

```javascript
const [loadingTooLong, setLoadingTooLong] = useState(false)
```

Add a `useEffect` that starts and clears a 15-second timer whenever `loading` changes:

```javascript
useEffect(() => {
    if (!loading) {
        setLoadingTooLong(false)
        return
    }
    const timer = setTimeout(() => setLoadingTooLong(true), 15000)
    return () => clearTimeout(timer)
}, [loading])
```

- [ ] **Step 2: Show the timeout message below the typing indicator**

Find the loading indicator block in the message list:

```jsx
{loading && (
    <div className="flex flex-col gap-2">
        <div className="flex items-center gap-3">
            <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                F1 Dash
            </div>
            <div className="h-px flex-1 bg-border/80" />
        </div>
        <div className="inline-flex w-fit items-center gap-2 rounded-md border border-border/90 bg-card px-4 py-3 text-sm text-muted-foreground">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-foreground/60" />
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-foreground/60 [animation-delay:120ms]" />
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-foreground/60 [animation-delay:240ms]" />
        </div>
    </div>
)}
```

Replace with:

```jsx
{loading && (
    <div className="flex flex-col gap-2">
        <div className="flex items-center gap-3">
            <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                F1 Dash
            </div>
            <div className="h-px flex-1 bg-border/80" />
        </div>
        <div className="inline-flex w-fit items-center gap-2 rounded-md border border-border/90 bg-card px-4 py-3 text-sm text-muted-foreground">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-foreground/60" />
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-foreground/60 [animation-delay:120ms]" />
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-foreground/60 [animation-delay:240ms]" />
        </div>
        {loadingTooLong && (
            <div className="text-xs text-muted-foreground">
                Fetching telemetry and session data — this may take a moment.
            </div>
        )}
    </div>
)}
```

- [ ] **Step 3: Verify manually**

In the dev server, send a complex question. Within ~15 seconds you should see the timeout message appear below the typing dots. Once the response arrives, it disappears.

- [ ] **Step 4: Commit**

```bash
git add client/src/components/ChatView.jsx
git commit -m "feat: show 'may take a moment' message after 15s of loading in ChatView"
```
