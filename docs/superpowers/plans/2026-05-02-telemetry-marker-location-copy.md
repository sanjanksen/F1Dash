# Telemetry Marker Location Copy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace raw telemetry marker distances in qualifying battle explanations with readable track-context labels such as "exit of Turn 2" and "braking zone into Turn 11".

**Architecture:** Add a backend helper in `server/f1_data.py` that derives authoritative `location_context` from `get_circuit_corners()` and each telemetry cause type. The helper uses previous/next corner context, not nearest-corner-only logic, and supports lap wraparound. Pass the new object through existing widget payloads, then update `QualifyingBattleWidget.jsx` to prefer readable labels and backend-authored phrases while preserving `distance_m` for charts/maps and old-payload fallback.

**Tech Stack:** Python 3.11+/FastAPI backend, pytest backend tests, React/Vite frontend.

---

## File Structure

- Modify `server/f1_data.py`: add location context helper, use it in backend explanation copy, and attach context to `cause_explanations`.
- Modify `server/chat.py`: verify/pass through `location_context` only if the mapper drops it.
- Modify `client/src/components/chat-widgets/QualifyingBattleWidget.jsx`: display readable location labels and use location-aware fallback copy.
- Modify `server/tests/test_f1_data.py`: backend regression tests for location context and qualifying payloads.
- Modify `server/tests/test_chat.py`: widget mapper pass-through test if needed.

---

### Task 1: Backend Location Context Helper

**Files:**
- Modify: `server/f1_data.py`
- Test: `server/tests/test_f1_data.py`

- [ ] **Step 1: Write failing tests for location phases**

Add tests near the existing qualifying battle tests:

```python
def test_telemetry_location_context_traction_uses_previous_corner_exit():
    import f1_data
    corners = [
        {"number": 1, "label": None, "distance_m": 300},
        {"number": 2, "label": None, "distance_m": 650},
    ]
    with patch("f1_data.get_circuit_corners", return_value=corners):
        result = f1_data._telemetry_location_context(6, 520, "traction")

    assert result["label"] == "Exit of Turn 1"
    assert result["plain"] == "on the run out of Turn 1"
    assert result["phase"] == "corner_exit"
    assert result["corner"] == "Turn 1"
    assert result["next_corner"] == "Turn 2"
    assert result["distance_m"] == 520


def test_telemetry_location_context_braking_uses_next_corner_entry():
    import f1_data
    corners = [
        {"number": 10, "label": None, "distance_m": 3000},
        {"number": 11, "label": None, "distance_m": 3280},
    ]
    with patch("f1_data.get_circuit_corners", return_value=corners):
        result = f1_data._telemetry_location_context(6, 3200, "braking")

    assert result["label"] == "Braking zone into Turn 11"
    assert result["plain"] == "in the braking zone into Turn 11"
    assert result["phase"] == "braking_zone"
    assert result["corner"] == "Turn 11"


def test_telemetry_location_context_minimum_speed_uses_nearest_corner():
    import f1_data
    corners = [
        {"number": 10, "label": None, "distance_m": 3000},
        {"number": 11, "label": None, "distance_m": 3220},
        {"number": 12, "label": None, "distance_m": 3500},
    ]
    with patch("f1_data.get_circuit_corners", return_value=corners):
        result = f1_data._telemetry_location_context(6, 3200, "minimum_speed")

    assert result["label"] == "Mid-corner at Turn 11"
    assert result["plain"] == "through Turn 11"
    assert result["phase"] == "mid_corner"


def test_telemetry_location_context_straight_between_corners():
    import f1_data
    corners = [
        {"number": 13, "label": None, "distance_m": 3600},
        {"number": 14, "label": None, "distance_m": 4100},
    ]
    with patch("f1_data.get_circuit_corners", return_value=corners):
        result = f1_data._telemetry_location_context(6, 3800, "straight_line_speed")

    assert result["label"] == "Straight between Turn 13 and Turn 14"
    assert result["plain"] == "on the straight between Turn 13 and Turn 14"
    assert result["phase"] == "straight"


def test_telemetry_location_context_wraps_after_final_corner_to_turn_1():
    import f1_data
    corners = [
        {"number": 1, "label": None, "distance_m": 250},
        {"number": 19, "label": None, "distance_m": 5200},
    ]
    with patch("f1_data.get_circuit_corners", return_value=corners):
        result = f1_data._telemetry_location_context(6, 5350, "straight_line_speed")

    assert result["label"] == "Straight between Turn 19 and Turn 1"
    assert result["plain"] == "on the straight between Turn 19 and Turn 1"
    assert result["previous_corner"]["number"] == 19
    assert result["next_corner"]["number"] == 1


def test_telemetry_location_context_fallback_avoids_bare_distance():
    import f1_data
    with patch("f1_data.get_circuit_corners", side_effect=Exception("no circuit info")):
        result = f1_data._telemetry_location_context(6, 500, "traction")

    assert result["label"] == "Early in the lap"
    assert result["plain"] == "early in the lap"
    assert result["phase"] == "lap_region"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
& 'C:\Users\sanja\AppData\Local\Python\bin\python.exe' -m pytest server\tests\test_f1_data.py -q
```

Expected: the new tests fail because `_telemetry_location_context` does not exist.

- [ ] **Step 3: Implement helper**

Add below `_nearest_corner_label`:

```python
def _corner_label(corner: dict | None) -> str | None:
    if not corner:
        return None
    label = f"Turn {corner.get('number')}"
    if corner.get("label"):
        label += str(corner["label"])
    return label


def _lap_region(distance_m: int | None) -> str:
    if distance_m is None:
        return "Key part of the lap"
    if distance_m < 1800:
        return "Early in the lap"
    if distance_m < 3800:
        return "Middle of the lap"
    return "Late in the lap"


def _base_location_context(distance_m: int | None) -> dict:
    label = _lap_region(distance_m)
    plain = label[:1].lower() + label[1:]
    return {
        "label": label,
        "plain": plain,
        "technical": plain,
        "phase": "lap_region",
        "distance_m": distance_m,
        "corner": None,
        "previous_corner": None,
        "next_corner": None,
    }


def _telemetry_location_context(round_number: int, distance_m: int | None, cause_type: str | None) -> dict:
    base = _base_location_context(distance_m)
    if distance_m is None:
        return base

    try:
        corners = get_circuit_corners(round_number)
    except Exception:
        return base

    valid = sorted(
        [corner for corner in corners if corner.get("distance_m") is not None],
        key=lambda corner: corner["distance_m"],
    )
    if not valid:
        return base

    previous_corner = max(
        (corner for corner in valid if corner["distance_m"] <= distance_m),
        key=lambda corner: corner["distance_m"],
        default=None,
    ) or valid[-1]
    next_corner = min(
        (corner for corner in valid if corner["distance_m"] >= distance_m),
        key=lambda corner: corner["distance_m"],
        default=None,
    ) or valid[0]
    nearest_corner = min(valid, key=lambda corner: abs(corner["distance_m"] - distance_m))

    prev_label = _corner_label(previous_corner)
    next_label = _corner_label(next_corner)
    nearest_label = _corner_label(nearest_corner)
    cause = cause_type or "mixed"

    if cause == "braking" and next_label:
        return {
            **base,
            "label": f"Braking zone into {next_label}",
            "plain": f"in the braking zone into {next_label}",
            "technical": f"corner entry into {next_label}",
            "phase": "braking_zone",
            "corner": next_label,
            "previous_corner": previous_corner,
            "next_corner": next_corner,
        }

    if cause == "minimum_speed" and nearest_label:
        return {
            **base,
            "label": f"Mid-corner at {nearest_label}",
            "plain": f"through {nearest_label}",
            "technical": f"apex/minimum-speed phase at {nearest_label}",
            "phase": "mid_corner",
            "corner": nearest_label,
            "previous_corner": previous_corner,
            "next_corner": next_corner,
        }

    if cause == "traction" and prev_label:
        return {
            **base,
            "label": f"Exit of {prev_label}",
            "plain": f"on the run out of {prev_label}",
            "technical": f"corner exit from {prev_label}",
            "phase": "corner_exit",
            "corner": prev_label,
            "previous_corner": previous_corner,
            "next_corner": next_corner,
        }

    if cause in ("straight_line_speed", "straight_line_speed_energy_limited"):
        if prev_label and next_label and prev_label != next_label:
            return {
                **base,
                "label": f"Straight between {prev_label} and {next_label}",
                "plain": f"on the straight between {prev_label} and {next_label}",
                "technical": f"full-throttle section before {next_label}",
                "phase": "straight",
                "corner": prev_label,
                "previous_corner": previous_corner,
                "next_corner": next_corner,
            }
        if next_label:
            return {
                **base,
                "label": f"Straight before {next_label}",
                "plain": f"on the straight before {next_label}",
                "technical": f"full-throttle section before {next_label}",
                "phase": "straight",
                "corner": prev_label,
                "previous_corner": previous_corner,
                "next_corner": next_corner,
            }

    return base
```

- [ ] **Step 4: Run tests to verify helper passes**

Run the same command. Expected: new helper tests pass.

---

### Task 2: Attach Location Context To Qualifying Causes And Backend Copy

**Files:**
- Modify: `server/f1_data.py`
- Test: `server/tests/test_f1_data.py`

- [ ] **Step 1: Write failing payload test**

Add a test using the existing `analyze_qualifying_battle` setup pattern, or patch `_telemetry_location_context` if setup is too bulky:

```python
def test_analyze_qualifying_battle_includes_location_context():
    import f1_data
    context = {
        "label": "Exit of Turn 1",
        "plain": "on the run out of Turn 1",
        "technical": "corner exit from Turn 1",
        "phase": "corner_exit",
        "distance_m": 500,
        "corner": "Turn 1",
        "previous_corner": {"number": 1, "label": None, "distance_m": 300},
        "next_corner": {"number": 2, "label": None, "distance_m": 650},
    }

    with patch("f1_data._telemetry_location_context", return_value=context):
        result = f1_data.analyze_qualifying_battle(8, "NOR", "PIA")

    primary = result["cause_explanations"][0]
    assert primary["location_context"]["label"] == "Exit of Turn 1"
    assert "500m" not in primary["explanation"]
```

- [ ] **Step 2: Run test to verify it fails**

Expected: failure because `location_context` is missing and backend explanations still use meter text.

- [ ] **Step 3: Attach context and use it in backend explanation copy**

Inside `analyze_qualifying_battle`, build context before each explanation:

```python
def _cause_explanation(ct: str, dist: int | None, location_context: dict | None = None) -> str:
    loc = (
        f" {location_context['plain']}"
        if location_context and location_context.get("plain")
        else (f" around {dist}m" if dist is not None else "")
    )
    ...
```

Then build `cause_explanations` imperatively so the same context is used for both fields:

```python
cause_explanations = []
for i, tc in enumerate(top_causes):
    location_context = _telemetry_location_context(round_number, tc["distance_m"], tc["cause_type"])
    cause_explanations.append({
        "cause_type": tc["cause_type"],
        "rank": i + 1,
        "distance_m": tc["distance_m"],
        "delta_speed_kph": tc["delta_speed_kph"],
        "gear_a": tc.get("gear_a"),
        "gear_b": tc.get("gear_b"),
        "sector": _sector_for_distance(tc["distance_m"]),
        "location_context": location_context,
        "explanation": _cause_explanation(tc["cause_type"], tc["distance_m"], location_context),
    })
```

Also use the primary context for `cause_explanation`:

```python
primary_location_context = (
    _telemetry_location_context(round_number, primary_cause["distance_m"], primary_cause["cause_type"])
    if primary_cause else None
)
cause_explanation = _cause_explanation(cause_type, primary_cause["distance_m"] if primary_cause else None, primary_location_context)
```

Keep `distance_m` in the payload for charts/maps.

- [ ] **Step 4: Run backend tests**

Run:

```powershell
& 'C:\Users\sanja\AppData\Local\Python\bin\python.exe' -m pytest server\tests\test_f1_data.py server\tests\test_chat.py -q
```

Expected: all pass.

---

### Task 3: Preserve Location Context Through Widget Mapping

**Files:**
- Modify: `server/chat.py` only if needed
- Test: `server/tests/test_chat.py`

- [ ] **Step 1: Add mapper test**

```python
def test_make_qualifying_battle_widget_preserves_location_context():
    import chat

    widget = chat._make_qualifying_battle_widget({
        "driver_a": "NOR",
        "driver_b": "PIA",
        "cause_explanations": [{
            "cause_type": "traction",
            "rank": 1,
            "distance_m": 500,
            "delta_speed_kph": 7.9,
            "location_context": {
                "label": "Exit of Turn 1",
                "plain": "on the run out of Turn 1",
                "technical": "corner exit from Turn 1",
                "phase": "corner_exit",
                "distance_m": 500,
                "corner": "Turn 1",
                "previous_corner": {"number": 1, "label": None, "distance_m": 300},
                "next_corner": {"number": 2, "label": None, "distance_m": 650},
            },
        }],
    })

    assert widget["cause_explanations"][0]["location_context"]["label"] == "Exit of Turn 1"
```

- [ ] **Step 2: Run test**

Expected: likely passes because `_make_qualifying_battle_widget` passes `cause_explanations` through wholesale.

- [ ] **Step 3: Patch only if needed**

If it fails, update `_make_qualifying_battle_widget` to preserve the full `cause_explanations` list.

---

### Task 4: Frontend Readable Marker Labels And Fallback Copy

**Files:**
- Modify: `client/src/components/chat-widgets/QualifyingBattleWidget.jsx`

- [ ] **Step 1: Add helper functions**

Near `causeWinner`, add:

```jsx
function locationLabel(cause) {
  return cause.location_context?.label ?? (cause.distance_m != null ? `${cause.distance_m}m` : 'distance n/a')
}

function locationPlain(cause) {
  return cause.location_context?.plain ?? (cause.distance_m != null ? `at ${cause.distance_m}m` : '')
}
```

- [ ] **Step 2: Update description generation**

Replace:

```jsx
const dist = typeof cause.distance_m === 'number' ? ` at ${cause.distance_m}m` : ''
const fn = CAUSE_DESC[cause.cause_type] ?? CAUSE_DESC.mixed
return fn(winner, loser, delta, dist)
```

with:

```jsx
const loc = locationPlain(cause)
const fn = CAUSE_DESC[cause.cause_type] ?? CAUSE_DESC.mixed
return fn(winner, loser, delta, loc ? ` ${loc}` : '').replace(/\s+/g, ' ')
```

- [ ] **Step 3: Improve `CAUSE_DESC` fallback copy**

Use:

```jsx
const CAUSE_DESC = {
  braking: (winner, loser, delta, loc) =>
    `${winner} carried the braking deeper${loc} while ${loser} slowed earlier${delta ? `, holding ${delta} more entry speed` : ''}.`,
  minimum_speed: (winner, loser, delta, loc) =>
    `${winner} carried more speed ${loc || 'through the corner'}${delta ? ` - ${delta} faster at the apex` : ''}.`,
  traction: (winner, loser, delta, loc) =>
    `${winner} got the power down sooner ${loc || 'on corner exit'}${delta ? `, opening a ${delta} gap onto the following straight` : ''}.`,
  straight_line_speed: (winner, loser, delta, loc) =>
    `${winner} was ${delta ? `${delta} quicker` : 'faster'} ${loc || 'on the straight'} - likely setup trim, DRS timing, or deployment.`,
  straight_line_speed_energy_limited: (winner, loser, delta, loc) =>
    `${winner} kept accelerating while ${loser} faded ${loc || 'late on the straight'} - an ERS deployment difference.`,
  mixed: (winner, loser, delta, loc) =>
    `${winner} was ${delta ? `${delta} ahead` : 'faster'} ${loc || 'in this part of the lap'} through a combination of factors.`,
}
```

- [ ] **Step 4: Update marker label display**

Replace:

```jsx
{distance_m != null ? `${distance_m}m` : 'distance n/a'}
```

with:

```jsx
{locationLabel(cause)}
```

- [ ] **Step 5: Keep raw distance available but demoted**

Do not remove `distance_m` from props; `SpeedTraceChart` and `TrackMap` still need it. Only stop showing it as the primary human label in the P/S/T details when `location_context` exists.

- [ ] **Step 6: Build frontend**

Run from `client/`:

```powershell
npm run build
```

Expected: Vite build succeeds.

---

### Task 5: Final Verification

**Files:**
- No additional files unless failures require fixes.

- [ ] **Step 1: Run full backend test suite**

```powershell
& 'C:\Users\sanja\AppData\Local\Python\bin\python.exe' -m pytest server\tests -q
```

Expected: all tests pass.

- [ ] **Step 2: Run frontend build**

```powershell
npm run build
```

Expected: Vite production build succeeds.

- [ ] **Step 3: Manual smoke check**

Ask:

```text
Why was Norris faster than Piastri in sprint qualifying at Miami?
```

Expected widget copy:

- P/S/T left label reads a readable track zone, not only `500m`.
- Main description uses phrases like "on the run out of Turn X", "through Turn Y", or "on the straight between Turn X and Turn Y".
- Backend explanation does not say "direction change" when a better corner context is available.
- Raw meter values may still exist in charts/map data, but not as the primary explanation label.

---

## Self-Review

- Spec coverage: covered backend context derivation, authoritative backend copy, lap wraparound, payload pass-through, frontend display, fallback behavior, and verification.
- Placeholder scan: no TBD/TODO placeholders.
- Type consistency: `location_context` fields are consistent across backend, tests, and frontend helpers.
