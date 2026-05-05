# Telemetry Marker Location Copy Design

## Goal

Make qualifying battle P/S/T marker explanations understandable without requiring users to interpret raw lap distance values like `500m`.

## Problem

The current qualifying battle widget exposes telemetry markers by distance and uses generic phrases such as "direction change" or "straight-line run." This is technically accurate but hard to understand because users do not know where `500m`, `3200m`, or `3800m` are on the circuit.

## Design

Backend telemetry cause objects will include a derived `location_context` object. The object maps the marker distance to surrounding circuit corner markers and describes the track phase in plain language. This helper must not use nearest-corner-only logic; it should bias previous/next corner selection by cause type.

Shape:

```json
{
  "label": "Exit of Turn 2",
  "plain": "on the run out of Turn 2",
  "technical": "corner exit onto the following straight",
  "phase": "corner_exit",
  "distance_m": 500,
  "corner": "Turn 2",
  "next_corner": "Turn 3",
  "previous_corner": {
    "number": 2,
    "label": null,
    "distance_m": 430
  }
}
```

Location phase rules:

- `braking`: use "braking zone into Turn X" when the marker is before a nearby corner.
- `minimum_speed`: use "mid-corner at Turn X" when the marker is close to a corner.
- `traction`: use "exit of Turn X" when the marker is after a nearby corner.
- `straight_line_speed` and `straight_line_speed_energy_limited`: use "on the straight between Turn X and Turn Y" when between corner markers.
- Use lap wraparound for markers after the final corner or before Turn 1, so a late main-straight marker can still be described relative to the final corner and Turn 1.

If corner data is unavailable, use a softer fallback such as "early in the lap", "middle of the lap", or "late in the lap" and keep the numeric distance only as secondary metadata.

The backend owns the primary language in `location_context` and `_cause_explanation()`. The frontend should use that language when present and only use old distance-based copy as a compatibility fallback for older payloads.

## Frontend Behavior

The P/S/T row should render `location_context.label` in place of the raw `500m` label. Detailed copy should use `location_context.plain` or `location_context.technical` instead of injecting `at 500m`.

Example copy:

- Traction: "NOR got the power down sooner on the run out of Turn 2, opening a 7.9 kph gap onto the following straight."
- Minimum speed: "NOR carried more speed through Turn 11, 6.7 kph faster at the apex."
- Straight speed: "NOR was 5.2 kph quicker on the straight between Turn 13 and Turn 14, likely from setup trim, DRS timing, or deployment."

## Files

- Backend: `server/f1_data.py`
- Backend widget adapter: `server/chat.py` only if the widget mapper needs explicit pass-through changes
- Frontend: `client/src/components/chat-widgets/QualifyingBattleWidget.jsx`
- Tests: `server/tests/test_f1_data.py`, `server/tests/test_chat.py`

## Testing

Add focused tests for:

- `location_context` phase derivation from synthetic corner markers.
- `analyze_qualifying_battle` including `location_context` for every `cause_explanations` item.
- Lap-wrap behavior after the final corner / before Turn 1.
- Widget mapper preserving `location_context`.
- Frontend copy helpers preferring the readable label over raw meter text if practical with existing test tooling.

## Out Of Scope

- Changing telemetry cause ranking.
- Changing track map rendering.
- Adding new circuit-specific hand-authored phrases.
- Removing raw `distance_m` from the payload; it remains useful for charts and maps.
