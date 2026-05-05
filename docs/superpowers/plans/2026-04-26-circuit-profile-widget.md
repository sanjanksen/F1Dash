# Circuit Profile Deterministic Route & Widget Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic routing path for circuit-info questions and a `CircuitProfileWidget` that shows sector breakdown, style advantages, energy profile, and tyre challenge.

**Architecture:** The resolver detects circuit-info intent (e.g. "tell me about the Miami circuit") and sets `analysis_mode = "circuit_profile"`. `_build_analysis_plan` in `chat.py` handles that mode by calling `get_circuit_profile`, then `_make_circuit_profile_widget` maps the result to a typed widget dict. The React widget renders the structured profile data visually.

**Tech Stack:** Python/FastAPI backend, React/Vite frontend, Tailwind CSS, existing `Badge` component from `client/src/components/ui/badge.jsx`.

---

## File Map

**Modified:**
- `server/resolver.py` — `_detect_session_scope` (add circuit scope), `_base_context` (set analysis_mode for circuit scope)
- `server/chat.py` — add `_make_circuit_profile_widget`, circuit branch in `_build_analysis_plan`, wire into `_widgets_from_analysis_evidence`
- `client/src/components/AnswerRenderer.jsx` — import and register `circuit_profile` widget type
- `server/tests/test_resolver.py` — 2 new tests for circuit scope detection
- `server/tests/test_chat.py` — 2 new tests for circuit plan building and widget builder

**Created:**
- `client/src/components/chat-widgets/CircuitProfileWidget.jsx` — new widget component

---

### Task 1: Resolver — detect circuit scope and set analysis_mode

**Files:**
- Modify: `server/resolver.py`
- Test: `server/tests/test_resolver.py`

- [ ] **Step 1: Write the failing tests**

Add to the end of `server/tests/test_resolver.py`:

```python
@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_resolve_query_context_circuit_scope_tell_me_about(mock_circuits, mock_drivers):
    """'tell me about the X circuit' sets scope=circuit and analysis_mode=circuit_profile."""
    mock_drivers.return_value = []
    mock_circuits.return_value = [
        {"round": 6, "event_name": "Miami Grand Prix", "circuit_name": "Miami International Autodrome", "country": "United States"},
    ]

    result = resolver.resolve_query_context("tell me about the miami circuit")

    assert result["scope"] == "circuit"
    assert result["analysis_mode"] == "circuit_profile"
    assert result["country"] == "United States"
    assert result["event_name"] == "Miami Grand Prix"


@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_resolve_query_context_circuit_scope_circuit_guide(mock_circuits, mock_drivers):
    """'circuit guide' phrasing also triggers circuit scope."""
    mock_drivers.return_value = []
    mock_circuits.return_value = [
        {"round": 3, "event_name": "Japanese Grand Prix", "circuit_name": "Suzuka Circuit", "country": "Japan"},
    ]

    result = resolver.resolve_query_context("circuit guide for suzuka")

    assert result["scope"] == "circuit"
    assert result["analysis_mode"] == "circuit_profile"
    assert result["country"] == "Japan"
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd server && python -m pytest tests/test_resolver.py::test_resolve_query_context_circuit_scope_tell_me_about tests/test_resolver.py::test_resolve_query_context_circuit_scope_circuit_guide -v
```

Expected: FAIL (scope/analysis_mode not set)

- [ ] **Step 3: Add circuit scope detection to `_detect_session_scope`**

In `server/resolver.py`, find `_detect_session_scope`. It returns `session_type, scope` at the bottom. Add the circuit detection block just before the final `return` statement:

```python
    if any(phrase in normalized for phrase in (
        "circuit profile", "circuit guide", "track guide", "track profile",
        "about the circuit", "about this circuit", "circuit breakdown",
        "about the track", "circuit info", "track info",
    )) or (re.search(r"\btell me about\b", normalized) and ("circuit" in normalized or "track" in normalized)):
        scope = "circuit"

    return session_type, scope
```

The existing `return session_type, scope` is already there — insert the block immediately before it.

- [ ] **Step 4: Set `analysis_mode = "circuit_profile"` in `_base_context`**

In `server/resolver.py`, find this line in `_base_context`:

```python
    analysis_mode, analysis_focus = _detect_analysis_mode(normalized, matched_drivers, session_type, team)
```

Replace it with:

```python
    if scope == "circuit" and event:
        analysis_mode, analysis_focus = "circuit_profile", None
    else:
        analysis_mode, analysis_focus = _detect_analysis_mode(normalized, matched_drivers, session_type, team)
```

- [ ] **Step 5: Run tests to verify they pass**

```
cd server && python -m pytest tests/test_resolver.py::test_resolve_query_context_circuit_scope_tell_me_about tests/test_resolver.py::test_resolve_query_context_circuit_scope_circuit_guide -v
```

Expected: PASS

- [ ] **Step 6: Run the full resolver + chat test suite**

```
cd server && python -m pytest tests/test_resolver.py tests/test_chat.py -v 2>&1 | tail -15
```

Expected: same pass count as before (no regressions in existing tests)

- [ ] **Step 7: Commit**

```bash
git add server/resolver.py server/tests/test_resolver.py
git commit -m "feat: detect circuit-info scope and set circuit_profile analysis_mode in resolver"
```

---

### Task 2: chat.py — circuit deterministic route and widget builder

**Files:**
- Modify: `server/chat.py`
- Test: `server/tests/test_chat.py`

- [ ] **Step 1: Write the failing tests**

Add to the end of `server/tests/test_chat.py`:

```python
def test_build_analysis_plan_circuit_profile_without_round():
    """Circuit profile plan is built from country alone — round_number is not required."""
    import chat as chat_module
    resolved = {
        "analysis_mode": "circuit_profile",
        "country": "United States",
        "event_name": "Miami Grand Prix",
        "round_number": None,
    }
    plan = chat_module._build_analysis_plan("tell me about the miami circuit", resolved)
    assert plan is not None
    assert plan["analysis_mode"] == "circuit_profile"
    tool_names = [name for name, _ in plan["tool_calls"]]
    assert "get_circuit_profile" in tool_names
    profile_args = next(args for name, args in plan["tool_calls"] if name == "get_circuit_profile")
    assert profile_args["country"] == "United States"
    assert profile_args["event_name"] == "Miami Grand Prix"


def test_make_circuit_profile_widget_maps_all_fields():
    """_make_circuit_profile_widget passes through all profile fields with type=circuit_profile."""
    import chat as chat_module
    profile = {
        "circuit_key": "miami",
        "circuit_name": "Miami International Autodrome",
        "character": "street_like_mixed",
        "downforce_level": "medium_high",
        "sector_1": {
            "type": "medium_speed_hairpin",
            "description": "T1-T6: hard braking into T1",
            "style_advantage": "late_braker",
            "energy_demand": "medium",
        },
        "sector_2": {
            "type": "high_speed_straight_into_heavy_braking",
            "description": "T7-T11: long back straight",
            "style_advantage": "late_braker",
            "energy_demand": "very_high",
        },
        "sector_3": {
            "type": "stop_and_go",
            "description": "T12-T19: marina hairpins",
            "style_advantage": "v_line",
            "energy_demand": "medium",
        },
        "energy_profile": {
            "deployment_demand": "high",
            "clipping_risk": "medium",
            "harvesting_opportunity": "medium",
            "key_straights": ["back_straight"],
            "notes": "Good harvesting at marina hairpins.",
        },
        "style_verdict": {
            "qualifier": "v_line_late_braker",
            "explanation": "V-line late-brakers have the structural edge.",
        },
        "tyre_challenge": "Heavy rear wear from aggressive traction zones.",
        "narrative": "Miami is a stop-and-go street-like circuit.",
    }
    widget = chat_module._make_circuit_profile_widget(profile)

    assert widget["type"] == "circuit_profile"
    assert widget["circuit_name"] == "Miami International Autodrome"
    assert widget["circuit_key"] == "miami"
    assert widget["character"] == "street_like_mixed"
    assert widget["sector_1"]["style_advantage"] == "late_braker"
    assert widget["sector_3"]["style_advantage"] == "v_line"
    assert widget["energy_profile"]["deployment_demand"] == "high"
    assert widget["style_verdict"]["qualifier"] == "v_line_late_braker"
    assert widget["tyre_challenge"] == "Heavy rear wear from aggressive traction zones."
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd server && python -m pytest tests/test_chat.py::test_build_analysis_plan_circuit_profile_without_round tests/test_chat.py::test_make_circuit_profile_widget_maps_all_fields -v
```

Expected: FAIL (functions don't exist yet)

- [ ] **Step 3: Add `_make_circuit_profile_widget` to `chat.py`**

In `server/chat.py`, after the `_make_corner_comparison_widget` function (around line 135), add:

```python
def _make_circuit_profile_widget(result: dict) -> dict:
    return {
        "type": "circuit_profile",
        "circuit_name": result.get("circuit_name"),
        "circuit_key": result.get("circuit_key"),
        "character": result.get("character"),
        "downforce_level": result.get("downforce_level"),
        "sector_1": result.get("sector_1"),
        "sector_2": result.get("sector_2"),
        "sector_3": result.get("sector_3"),
        "energy_profile": result.get("energy_profile"),
        "style_verdict": result.get("style_verdict"),
        "tyre_challenge": result.get("tyre_challenge"),
        "narrative": result.get("narrative"),
    }
```

- [ ] **Step 4: Add the `circuit_profile` branch to `_build_analysis_plan`**

In `server/chat.py`, find `_build_analysis_plan`. It starts with:

```python
def _build_analysis_plan(message: str, resolved: dict) -> dict | None:
    analysis_mode = resolved.get("analysis_mode")
    round_number = resolved.get("round_number")

    # ── team_performance mode ────────────────────────────────────────────────
    if analysis_mode == "team_performance":
```

Add a new block at the very top, immediately after `round_number = resolved.get("round_number")`:

```python
    # ── circuit_profile mode ─────────────────────────────────────────────────
    if analysis_mode == "circuit_profile":
        country = resolved.get("country")
        event_name = resolved.get("event_name")
        if not country:
            return None
        tool_calls = [
            ("get_circuit_profile", {"country": country, "event_name": event_name or ""}),
        ]
        if round_number:
            tool_calls.append(("get_historical_circuit_performance", {"round_number": round_number}))
        return {
            "analysis_mode": "circuit_profile",
            "focus": "circuit",
            "question": message,
            "round_number": round_number,
            "event_name": event_name,
            "country": country,
            "tool_calls": tool_calls,
        }

```

- [ ] **Step 5: Wire `get_circuit_profile` into `_widgets_from_analysis_evidence`**

In `server/chat.py`, find `_widgets_from_analysis_evidence`. It has a series of `elif tool == ...` checks. Add a new branch at the end of the for-loop body (before the closing of the loop):

```python
        elif tool == "get_circuit_profile":
            widgets.append(_make_circuit_profile_widget(item["result"]))
```

The full elif chain should look like:

```python
        if tool == "analyze_qualifying_battle":
            widgets.append(_make_qualifying_battle_widget(item["result"]))
        elif tool == "get_driver_race_story":
            widgets.append(_make_race_story_widget(item["result"]))
        elif tool == "analyze_race_pace_battle":
            widgets.append(_make_race_pace_battle_widget(item["result"]))
        elif tool == "compare_corner_profiles":
            if plan.get("focus") == "qualifying" and has_primary_qualifying_widget:
                continue
            widgets.append(_make_corner_comparison_widget(item["result"]))
        elif tool == "analyze_team_performance" and isinstance(item["result"].get("corner_comparison"), dict):
            widgets.append(_make_corner_comparison_widget(item["result"]["corner_comparison"]))
        elif tool == "get_circuit_profile":
            widgets.append(_make_circuit_profile_widget(item["result"]))
```

- [ ] **Step 6: Run tests to verify they pass**

```
cd server && python -m pytest tests/test_chat.py::test_build_analysis_plan_circuit_profile_without_round tests/test_chat.py::test_make_circuit_profile_widget_maps_all_fields -v
```

Expected: PASS

- [ ] **Step 7: Run full test suite**

```
cd server && python -m pytest tests/test_chat.py tests/test_f1_data.py tests/test_resolver.py -v 2>&1 | tail -10
```

Expected: all existing tests still pass

- [ ] **Step 8: Commit**

```bash
git add server/chat.py server/tests/test_chat.py
git commit -m "feat: add circuit_profile deterministic route and widget builder to chat.py"
```

---

### Task 3: CircuitProfileWidget.jsx — new frontend widget

**Files:**
- Create: `client/src/components/chat-widgets/CircuitProfileWidget.jsx`

- [ ] **Step 1: Create the file**

Create `client/src/components/chat-widgets/CircuitProfileWidget.jsx` with the following content:

```jsx
import { Badge } from '../ui/badge.jsx'

const CHARACTER_LABELS = {
  street_like_mixed: 'Street-Like Mixed',
  high_speed_street: 'High-Speed Street',
  medium_speed_technical: 'Technical',
  high_speed_power: 'Power Circuit',
  slow_technical: 'Slow-Technical',
  high_speed_flowing: 'High-Speed Flowing',
  mixed: 'Mixed',
}

const STYLE_LABELS = {
  late_braker: 'Late-braker',
  v_line: 'V-line',
  u_line: 'U-line',
  balanced: 'Balanced',
}

const ENERGY_LABELS = {
  low: 'Low',
  medium: 'Medium',
  high: 'High',
  very_high: 'Very High',
}

const DOWNFORCE_LABELS = {
  low: 'Low Downforce',
  medium_low: 'Medium-Low Downforce',
  medium: 'Medium Downforce',
  medium_high: 'Medium-High Downforce',
  high: 'High Downforce',
}

const VERDICT_LABELS = {
  v_line: 'V-line',
  u_line: 'U-line',
  late_braker: 'Late-braker',
  v_line_late_braker: 'V-line / Late-braker',
  u_line_late_braker: 'U-line / Late-braker',
  balanced: 'Balanced',
}

function SectorColumn({ label, sector }) {
  if (!sector) return null
  const styleLabel = STYLE_LABELS[sector.style_advantage] ?? sector.style_advantage ?? '—'
  const energyLabel = ENERGY_LABELS[sector.energy_demand] ?? sector.energy_demand ?? '—'

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border/60 p-3">
      <div className="text-xs font-semibold text-primary">{label}</div>
      <div className="flex flex-wrap gap-1.5">
        <Badge variant="muted" className="text-[11px]">{styleLabel}</Badge>
        <Badge variant="outline" className="text-[11px]">Energy: {energyLabel}</Badge>
      </div>
      <div className="text-xs leading-5 text-muted-foreground">{sector.description}</div>
    </div>
  )
}

function EnergyRow({ label, value }) {
  if (!value) return null
  const displayValue = ENERGY_LABELS[value] ?? value
  return (
    <div className="flex items-center justify-between py-1.5 text-sm border-b border-border/50 last:border-b-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium text-foreground">{displayValue}</span>
    </div>
  )
}

export default function CircuitProfileWidget({ widget }) {
  if (!widget) return null

  const {
    circuit_name,
    character,
    downforce_level,
    sector_1,
    sector_2,
    sector_3,
    energy_profile,
    style_verdict,
    tyre_challenge,
  } = widget

  const characterLabel = CHARACTER_LABELS[character] ?? character ?? '—'
  const downforceLabel = DOWNFORCE_LABELS[downforce_level] ?? downforce_level ?? null
  const verdictLabel = VERDICT_LABELS[style_verdict?.qualifier] ?? style_verdict?.qualifier ?? '—'

  return (
    <div className="rounded-xl border border-border bg-card text-card-foreground shadow-sm">
      {/* Header */}
      <div className="border-b border-border/70 px-5 py-4">
        <div className="text-base font-semibold text-foreground">{circuit_name ?? 'Circuit Profile'}</div>
        <div className="mt-1.5 flex flex-wrap gap-2">
          <Badge variant="default">{characterLabel}</Badge>
          {downforceLabel ? <Badge variant="outline">{downforceLabel}</Badge> : null}
        </div>
      </div>

      <div className="divide-y divide-border/60">
        {/* Sector breakdown */}
        {(sector_1 || sector_2 || sector_3) && (
          <div className="px-5 py-4">
            <div className="mb-3 text-sm font-medium text-foreground">Sector breakdown</div>
            <div className="grid gap-3 sm:grid-cols-3">
              <SectorColumn label="S1" sector={sector_1} />
              <SectorColumn label="S2" sector={sector_2} />
              <SectorColumn label="S3" sector={sector_3} />
            </div>
          </div>
        )}

        {/* Energy profile */}
        {energy_profile && (
          <div className="px-5 py-4">
            <div className="mb-3 text-sm font-medium text-foreground">Energy profile</div>
            <div className="rounded-lg border border-border/60 px-3 py-1">
              <EnergyRow label="Deployment demand" value={energy_profile.deployment_demand} />
              <EnergyRow label="Clipping risk" value={energy_profile.clipping_risk} />
              <EnergyRow label="Harvesting opportunity" value={energy_profile.harvesting_opportunity} />
            </div>
            {energy_profile.notes ? (
              <div className="mt-2 text-xs leading-5 text-muted-foreground">{energy_profile.notes}</div>
            ) : null}
          </div>
        )}

        {/* Style verdict */}
        {style_verdict && (
          <div className="px-5 py-4">
            <div className="mb-2 text-sm font-medium text-foreground">Style verdict</div>
            <div className="flex items-start gap-3">
              <Badge variant="muted" className="mt-0.5 shrink-0">{verdictLabel}</Badge>
              <p className="text-sm leading-6 text-muted-foreground">{style_verdict.explanation}</p>
            </div>
          </div>
        )}

        {/* Tyre challenge */}
        {tyre_challenge && (
          <div className="px-5 py-4">
            <div className="mb-1 text-sm font-medium text-foreground">Tyre challenge</div>
            <p className="text-sm leading-6 text-muted-foreground">{tyre_challenge}</p>
          </div>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify the file was created**

```
ls client/src/components/chat-widgets/CircuitProfileWidget.jsx
```

Expected: file exists

- [ ] **Step 3: Commit**

```bash
git add client/src/components/chat-widgets/CircuitProfileWidget.jsx
git commit -m "feat: add CircuitProfileWidget with sector breakdown, energy profile, and style verdict"
```

---

### Task 4: Wire CircuitProfileWidget into AnswerRenderer

**Files:**
- Modify: `client/src/components/AnswerRenderer.jsx`

- [ ] **Step 1: Add import at the top of AnswerRenderer.jsx**

Find the existing imports at the top of `client/src/components/AnswerRenderer.jsx`:

```js
import { Badge } from './ui/badge.jsx'
import QualifyingBattleWidget from './chat-widgets/QualifyingBattleWidget.jsx'
import RaceStoryWidget from './chat-widgets/RaceStoryWidget.jsx'
import RacePaceBattleWidget from './chat-widgets/RacePaceBattleWidget.jsx'
import CornerComparisonWidget from './chat-widgets/CornerComparisonWidget.jsx'
```

Add one line:

```js
import { Badge } from './ui/badge.jsx'
import QualifyingBattleWidget from './chat-widgets/QualifyingBattleWidget.jsx'
import RaceStoryWidget from './chat-widgets/RaceStoryWidget.jsx'
import RacePaceBattleWidget from './chat-widgets/RacePaceBattleWidget.jsx'
import CornerComparisonWidget from './chat-widgets/CornerComparisonWidget.jsx'
import CircuitProfileWidget from './chat-widgets/CircuitProfileWidget.jsx'
```

- [ ] **Step 2: Register `circuit_profile` in `WidgetRenderer`**

Find the `WidgetRenderer` function:

```jsx
function WidgetRenderer({ widget }) {
  if (!widget?.type) return null
  if (widget.type === 'qualifying_battle') {
    return <QualifyingBattleWidget widget={widget} />
  }
  if (widget.type === 'race_story') {
    return <RaceStoryWidget widget={widget} />
  }
  if (widget.type === 'race_pace_battle') {
    return <RacePaceBattleWidget widget={widget} />
  }
  if (widget.type === 'corner_comparison') {
    return <CornerComparisonWidget widget={widget} />
  }
  return null
}
```

Replace with:

```jsx
function WidgetRenderer({ widget }) {
  if (!widget?.type) return null
  if (widget.type === 'qualifying_battle') {
    return <QualifyingBattleWidget widget={widget} />
  }
  if (widget.type === 'race_story') {
    return <RaceStoryWidget widget={widget} />
  }
  if (widget.type === 'race_pace_battle') {
    return <RacePaceBattleWidget widget={widget} />
  }
  if (widget.type === 'corner_comparison') {
    return <CornerComparisonWidget widget={widget} />
  }
  if (widget.type === 'circuit_profile') {
    return <CircuitProfileWidget widget={widget} />
  }
  return null
}
```

- [ ] **Step 3: Run the backend test suite one final time**

```
cd server && python -m pytest tests/test_chat.py tests/test_f1_data.py tests/test_resolver.py -v 2>&1 | tail -5
```

Expected: all passing

- [ ] **Step 4: Commit**

```bash
git add client/src/components/AnswerRenderer.jsx
git commit -m "feat: register circuit_profile widget type in AnswerRenderer"
```
