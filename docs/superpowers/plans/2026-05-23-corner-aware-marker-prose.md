# Corner-Aware Marker Prose Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace "around 3100m" / "around 4700m" raw-distance phrasing in qualifying_battle marker prose with named corner labels ("T10 apex", "T16 exit", "back straight"), falling back to distance only when corner data is unavailable.

**Architecture:** Each marker already carries `corner_name`, `corner_number`, and `location_label` fields (populated by `_resolve_corner_for_distance` at marker-pick time) on the marker dict itself — NOT on `location_context`. Two prose paths still ignore these marker fields: (1) `_cause_explanation` in `server/f1_data.py`, which gets a `_telemetry_location_context` dict whose `plain` field uses raw-distance phrasing; (2) `locationPlain` in `client/src/components/chat-widgets/QualifyingBattleWidget.jsx`, which falls back to distance when `cause.location_label` starts with `"around"`. The fix: pass marker's `corner_name`/`location_label` explicitly into `_cause_explanation` (after moving it to module scope so it's testable), and have `locationPlain` prefer the marker's resolved corner label over the context-derived "around <distance>m" string. `CAUSE_DESC` templates already consume `locationPlain(cause)` — no template changes needed.

**Tech Stack:** Python 3, React/JSX. No new dependencies. Tests via pytest from `server/`.

---

## Background

The qualifying_battle widget produces marker cards like:

```
Primary @ around 3100m, sector2, LEC gained, Min speed
"Leclerc carried more speed around 3100m - 2.0 kph faster at the apex."
```

The "around 3100m" phrasing happens in two places:

1. **Backend `_cause_explanation`** (`server/f1_data.py:4305`) — builds the explanation string the analyzer LLM and widget both read.
2. **Frontend `CAUSE_DESC` templates** (`client/src/components/chat-widgets/QualifyingBattleWidget.jsx:~130-150`) — produce the auxiliary description sentence in each marker card.

The markers ALREADY carry resolved corner labels via fields set by `_resolve_corner_for_distance`:

- `corner_name` — e.g. `"Tamburello"`, `"T10"`, or `None` if no circuit data
- `corner_number` — e.g. `10`, or `None`
- `location_label` — human-readable string: `"T10 apex"`, `"T11 → T12 straight"`, or `"around 4700m"` as the documented fallback

The fix: have both prose paths prefer `location_label` (or `corner_name`) over the raw distance phrasing. The distance can stay as a parenthetical hint ("at T10, 3100m") for accuracy when the corner is named.

---

## File Structure

| File | Status | Role |
|---|---|---|
| `server/f1_data.py` | Modify | `_cause_explanation` and the location helpers it uses — prefer corner-aware label over raw distance |
| `client/src/components/chat-widgets/QualifyingBattleWidget.jsx` | Modify | `CAUSE_DESC` description templates — read `cause.location_label` / `cause.corner_name` first |
| `server/tests/test_f1_data.py` | Modify | Add tests that `_cause_explanation` uses corner labels when present and falls back to distance when absent |

No new files. No interface changes to other modules. The marker payload shape is unchanged — only the prose strings it produces.

---

## Pre-flight: Known test-impact list (per Codex audit)

These existing tests assert on raw-distance phrasing and will need updating when the new corner-aware labels land. Update assertions to accept EITHER the corner label OR the distance fallback, OR pin the test fixtures to use synthetic distances that don't map to known corners (so the distance fallback path is exercised).

- `server/tests/test_chat.py:509, 541, 548, 552`
- `server/tests/test_f1_data.py:1170-1171, 1227, 1455-1462`

When updating, prefer the first option: assert "either form is acceptable" via `assert "T10" in text or "1500m" in text`. Do NOT loosen the new corner-aware tests added by this plan.

---

## Task 0: Move `_cause_explanation` to module scope

`_cause_explanation` is currently a nested function inside `analyze_qualifying_battle` (server/f1_data.py around line 4305). That makes it untestable in isolation. Promote it to module scope before changing its signature.

**Files:**
- Modify: `server/f1_data.py` — relocate the function

- [ ] **Step 1: Locate the nested definition**

In `server/f1_data.py`, find `analyze_qualifying_battle`. Inside it, around line 4305, you'll see `def _cause_explanation(cause_type, distance_m, location_context, ...)`. Read it end-to-end. Note every parameter, every return path, and every free variable it captures from the enclosing `analyze_qualifying_battle` scope.

If it captures ANY closure variables (e.g., `driver_a`, `driver_b`, `faster_driver` from the outer scope), those become explicit parameters when you promote.

- [ ] **Step 2: Promote to module scope**

Move the function definition OUT of `analyze_qualifying_battle` to a position adjacent to the other module-level helpers (e.g., just above `_resolve_corner_for_distance` or near `_telemetry_location_context`). Convert any closure-captured variables into explicit keyword arguments with sensible defaults.

After moving, the function signature should look something like:

```python
def _cause_explanation(
    cause_type: str,
    distance_m: float | None,
    location_context: dict | None,
    *,
    gainer_driver: str | None = None,
    corner_name: str | None = None,
    location_label: str | None = None,
) -> str:
    """Build the per-marker explanation sentence. Prefers corner-aware
    labels when provided; falls back to location_context.plain when not;
    falls back to 'around <distance>m' when neither is available.
    """
    ...
```

(The actual body stays the same for now — the label-preference logic comes in Task 1.)

- [ ] **Step 3: Update call sites inside `analyze_qualifying_battle`**

Find every call to `_cause_explanation` inside `analyze_qualifying_battle`. After the move, these calls should still work but may need explicit kwargs for any previously closure-captured variables.

- [ ] **Step 4: Run the full suite — no behavior change yet**

```bash
cd server
python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: 753 passing. This task is a pure refactor — no behavioral change.

- [ ] **Step 5: Commit**

```bash
git add server/f1_data.py
git commit -m "refactor(f1_data): promote _cause_explanation to module scope

Was nested inside analyze_qualifying_battle, making it untestable in
isolation. Now module-level; closure captures (if any) become explicit
kwargs. No behavioral change.

Plan: docs/superpowers/plans/2026-05-23-corner-aware-marker-prose.md Task 0"
```

---

## Task 1: Corner-aware `_cause_explanation`

**Files:**
- Modify: `server/f1_data.py:4305` (the `_cause_explanation` function definition)
- Modify: any nearby helpers it calls that produce location phrasing
- Test: `server/tests/test_f1_data.py`

**Critical context from audit:**
- `location_context` is built by `_telemetry_location_context` (server/f1_data.py:~3565). Its keys are `label`, `plain`, `technical`, `phase`, `corner`, `previous_corner`, `next_corner`. **NOT** `corner_name` or `location_label`.
- The marker dict (`tc`) DOES have `corner_name`, `corner_number`, `location_label` — populated at line 3840-3843 by `_resolve_corner_for_distance`.
- So `_cause_explanation` needs the corner fields passed in explicitly from the marker dict, NOT pulled from location_context.

- [ ] **Step 1: Read the current `_cause_explanation`**

Now that it's module-scope (Task 0), read it end to end. Note exactly how it builds the location phrase — probably calls `_specific_location_plain(location_context)` which returns `location_context.get("plain")`. That `plain` field contains the raw-distance phrasing.

- [ ] **Step 2: Write the failing tests**

Append to `server/tests/test_f1_data.py`. The tests pass `corner_name` / `location_label` as the explicit new params on `_cause_explanation` — these come from the marker dict, not from location_context:

```python
def test_cause_explanation_uses_corner_name_when_provided():
    """When the caller passes the marker's resolved corner_name, the
    explanation must surface it instead of 'around <distance>m'."""
    from f1_data import _cause_explanation
    # location_context with no corner-aware fields (this is what
    # _telemetry_location_context returns when no nearby corner matches).
    location_context = {"plain": "around 3100m", "label": "around 3100m"}
    text = _cause_explanation(
        "minimum_speed", 3100.0, location_context,
        gainer_driver="LEC",
        corner_name="T10",
        location_label="T10 apex",
    )
    assert "T10" in text, f"Expected 'T10' in explanation; got: {text}"
    assert "around 3100m" not in text, (
        f"Should not use raw distance when corner_name is given: {text}"
    )


def test_cause_explanation_uses_straight_label_when_provided():
    """When the marker is on a straight (location_label like 'T11 → T12 straight'),
    use that label instead of distance."""
    from f1_data import _cause_explanation
    location_context = {"plain": "around 4500m", "label": "around 4500m"}
    text = _cause_explanation(
        "straight_line_speed", 4500.0, location_context,
        gainer_driver="LEC",
        corner_name=None,
        location_label="T11 → T12 straight",
    )
    assert "straight" in text.lower(), f"Expected straight label; got: {text}"
    assert "around 4500m" not in text, (
        f"Should not use raw distance when location_label is given: {text}"
    )


def test_cause_explanation_falls_back_to_distance_when_no_corner_or_label():
    """When neither corner_name nor a named location_label is provided,
    fall back to the distance phrasing in location_context.plain."""
    from f1_data import _cause_explanation
    location_context = {"plain": "around 3100m", "label": "around 3100m"}
    text = _cause_explanation(
        "minimum_speed", 3100.0, location_context, gainer_driver="LEC",
        # corner_name + location_label deliberately omitted (None default)
    )
    assert "3100" in text, f"Expected distance fallback; got: {text}"
```

- [ ] **Step 3: Run tests to verify red**

```bash
cd server
python -m pytest tests/test_f1_data.py::test_cause_explanation_uses_corner_label_when_provided tests/test_f1_data.py::test_cause_explanation_uses_straight_label_for_between_corners -v
```

Expected: at least one FAIL — explanation contains "around 3100m" or "around 4500m" instead of the corner/straight label.

The third test (`falls_back_to_distance_when_no_corner`) may already PASS because the existing implementation likely uses distance phrasing already. That's fine.

- [ ] **Step 4: Update `_cause_explanation`'s signature + body**

Add the two new optional kwargs and a label-preference helper at the top of the function body. The preference order: explicit `corner_name` → explicit `location_label` (when not "around ..." form) → `location_context.plain` → "around <distance>m".

```python
def _cause_explanation(
    cause_type: str,
    distance_m: float | None,
    location_context: dict | None,
    *,
    gainer_driver: str | None = None,
    corner_name: str | None = None,
    location_label: str | None = None,
) -> str:
    """Per-marker explanation prose. Prefers corner-aware labels from the
    marker dict when supplied; falls back to location_context.plain; then
    to raw distance.
    """
    def _location_phrase() -> str:
        # 1. Explicit corner name from marker (highest priority).
        if corner_name:
            return f"at {corner_name}"
        # 2. Explicit location_label from marker, IF it's not the
        #    'around <distance>m' fallback form.
        if location_label and not location_label.startswith("around "):
            if "straight" in location_label.lower():
                return f"on the {location_label}"
            return f"at {location_label}"
        # 3. location_context.plain (may already be 'around <distance>m').
        if location_context and location_context.get("plain"):
            plain = location_context["plain"]
            if not plain.startswith("around "):
                return plain  # Named phrase from context — use as-is.
            return plain  # 'around <distance>m' — last resort phrasing.
        # 4. Distance-only fallback.
        if distance_m is not None:
            return f"around {distance_m:.0f}m"
        return ""

    loc = _location_phrase()
    gainer = gainer_driver or "the faster driver"
    # ... existing cause_type → template dispatch, but use `loc` for the
    # location phrase instead of building it inline from distance_m ...
```

Update the existing cause_type templates inside the function body to interpolate `loc` instead of `f"around {distance_m:.0f}m"`.

- [ ] **Step 5: Update callers to pass marker fields**

In `analyze_qualifying_battle`, find every call to `_cause_explanation`. There are two:

1. Top-level `cause_explanation` (around line 4466) — built from `primary_cause`. Pass `corner_name=primary_cause.get("corner_name")` and `location_label=primary_cause.get("location_label")`.

2. Per-marker `cause_explanations` list comprehension (around line 4499) — already iterates over `tc` (the marker dict). Add `corner_name=tc.get("corner_name"), location_label=tc.get("location_label")` to that call.

- [ ] **Step 5: Run tests to verify green**

```bash
cd server
python -m pytest tests/test_f1_data.py -k "cause_explanation" -v
```

Expected: 3 tests pass.

- [ ] **Step 6: Full suite check**

```bash
cd server
python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: 753 passing (existing) + 3 new = 756 passing.

If any existing test breaks because its assertion encoded the old "around <distance>m" phrasing, update it to assert on the corner label OR loosen the check to "either form is acceptable." Do not loosen the new tests.

- [ ] **Step 7: Commit**

```bash
git add server/f1_data.py server/tests/test_f1_data.py
git commit -m "feat(quali-battle): _cause_explanation uses corner-aware location labels

Each marker in top_causes carries corner_name / location_label fields
resolved at pick time by _resolve_corner_for_distance. The prose path
was still defaulting to 'around <distance>m'.

After: prose says 'LEC carried more speed at T10' instead of 'LEC
carried more speed around 3100m'. Distance phrasing is the documented
fallback when no corner is matched (between-corner sections or circuits
without published corner data).

Plan: docs/superpowers/plans/2026-05-23-corner-aware-marker-prose.md Task 1"
```

---

## Task 2: Corner-aware `locationPlain` in JSX

**Files:**
- Modify: `client/src/components/chat-widgets/QualifyingBattleWidget.jsx` — `locationPlain` helper only

**Audit context:** `CAUSE_DESC` templates ALREADY consume `locationPlain(cause)`. No template changes needed. The bug is purely in `locationPlain` — it falls back to raw distance instead of preferring `cause.corner_name` / `cause.location_label`.

- [ ] **Step 1: Read the current `locationPlain`**

In `QualifyingBattleWidget.jsx`, find `function locationPlain(cause)`. Note its current fallback chain.

- [ ] **Step 2: Update `locationPlain` to prefer marker corner fields**

```js
function locationPlain(cause) {
  // Prefer the resolved corner/straight label set by the backend's
  // _resolve_corner_for_distance (corner_name and location_label fields
  // on the marker dict). Falls back to distance only when neither is
  // present or both are the 'around <distance>m' fallback form.
  if (cause.corner_name) return `at ${cause.corner_name}`
  if (cause.location_label && !cause.location_label.startsWith('around ')) {
    return cause.location_label.includes('straight')
      ? `on the ${cause.location_label}`
      : `at ${cause.location_label}`
  }
  if (typeof cause.distance_m === 'number') {
    return `around ${cause.distance_m.toFixed(0)}m`
  }
  return ''
}
```

- [ ] **Step 3: Build cleanly**

```bash
cd client
npm run build
```

- [ ] **Step 4: Commit**

```bash
git add client/src/components/chat-widgets/QualifyingBattleWidget.jsx
git commit -m "fix(client): locationPlain prefers corner_name / location_label

CAUSE_DESC templates already passed locationPlain(cause) as the loc
argument. The bug was that locationPlain fell back to raw distance
even when the marker had a resolved corner_name. Now: corner_name
wins, then location_label (if not the 'around X' fallback form),
then distance phrasing as last resort.

Plan: docs/superpowers/plans/2026-05-23-corner-aware-marker-prose.md Task 2"
```

---

## Task 3: Marker card location chip leads with corner label

**Files:**
- Modify: `client/src/components/chat-widgets/QualifyingBattleWidget.jsx` — the marker card layout, specifically the location chip below the rank label

Currently the marker card shows two location elements:
- Rank label ("Primary", "Secondary")
- Location chip ("around 3100m" — the raw distance)
- Sector chip ("sector2")

The location chip should lead with the corner label.

- [ ] **Step 1: Find the location chip render**

In `MechanismRow` (around line 183 of `QualifyingBattleWidget.jsx`), find the JSX that renders `locationLabel(cause)`. The current output is something like:

```jsx
<div className="mt-0.5 font-mono-data text-xs text-muted-foreground">
  {locationLabel(cause)}
</div>
```

`locationLabel` is a separate helper from `locationPlain`. It produces the chip-label form (no "at" / "on the" prefix).

- [ ] **Step 2: Update `locationLabel` to prefer corner labels**

```js
function locationLabel(cause) {
  // For the marker card's location chip. No prepositions — just the label.
  if (cause.corner_name) return cause.corner_name
  if (cause.location_label) return cause.location_label
  if (typeof cause.distance_m === 'number') {
    return `around ${cause.distance_m.toFixed(0)}m`
  }
  return ''
}
```

- [ ] **Step 3: Build + commit**

```bash
cd client
npm run build
```

```bash
git add client/src/components/chat-widgets/QualifyingBattleWidget.jsx
git commit -m "fix(client): marker card location chip leads with corner name

Marker cards show the resolved corner label in the location chip
(e.g. 'T10' or 'T11 → T12 straight') instead of '3100m' when circuit
corner data is available. Falls back to distance phrasing when no
corner is resolved.

Plan: docs/superpowers/plans/2026-05-23-corner-aware-marker-prose.md Task 3"
```

---

## Validation Checklist

After all 3 tasks:

- [ ] Backend tests: `cd server; python -m pytest tests/ -q 2>&1 | tail -3` — expect 756 passing
- [ ] Client builds: `cd client; npm run build` — clean
- [ ] Live smoke test in chat (if available): ask the same quali question. Marker cards should show "T10" or similar named labels, with descriptions like "Leclerc carried more speed at T10 — 2.0 kph faster at the apex." Distance-only labels should appear only when corner data is absent (e.g., on straights between named corners if circuit data doesn't include those, or on circuits without published corner data).

---

## Risks

| Risk | Trigger | Resolution |
|---|---|---|
| **Some 2026 circuits lack corner names** in the API — only have numbers | Live use on those circuits | Already handled: fallback chain uses corner_number → location_label → distance. User sees "T10" instead of named-corner ("Tamburello"). That's acceptable. |
| **A test asserts the old "around <distance>m" phrasing on a fixture where corner data IS present** | Task 1 Step 6 (full suite) | Update the assertion to expect the corner label OR loosen to "either form is acceptable." Don't loosen the new tests. |
| **`locationLabel` and `locationPlain` are subtly different** (chip vs sentence form) | Task 2 + 3 | They share the same prefer-corner-label logic but differ in preposition. Keep them as separate functions with the prefer-corner-label fallback chain duplicated, OR extract a shared `resolveLocationName(cause)` helper that returns the raw name without prepositions. Either is fine. |
| **`_specific_location_plain` is called from places other than `_cause_explanation`** | Task 1 Step 4 — refactor touches a shared helper | Grep for callers before changing return contract. If callers expect None-vs-string semantics that change, adjust caller signature or keep old helper and add a new `_corner_aware_location_plain` for the new path. |

---

## Non-Goals

- Adding corner names to circuits that don't have them. Use what `get_circuit_corners` returns.
- Reworking the marker picker — corner labels are already resolved at pick time.
- Touching widgets other than `qualifying_battle`. (race_pace_battle, corner_comparison, etc. are out of scope.)
- Localization / multi-language corner names. English-only.

---

## References

- `_resolve_corner_for_distance` in `server/f1_data.py:3424` — the resolver that populates `corner_name`/`corner_number`/`location_label` on markers
- `_summarize_telemetry_battle` in `server/f1_data.py:3714` — calls the resolver per marker
- `get_circuit_corners` in `server/f1_data.py` — the API-backed circuit corner data source
- Prior commit `2bb74f9` — added corner-name resolution to marker cards (incomplete: prose still used distance)
