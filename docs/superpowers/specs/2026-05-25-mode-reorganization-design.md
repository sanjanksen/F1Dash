# Mode Reorganization Design Spec

**Goal:** Replace the current 6-mode system (where `driver_comparison` is an overloaded catch-all) with 7 focused modes that fire only relevant tools for each question type.

**Architecture:** No change to the execution engine. Modes still work the same way: resolver classifies → mode selected → features tagged with that mode whose `applies_to` is satisfied fire in parallel → Claude analyzes → answer writer. Agentic fallback for unclassified questions.

**Principle:** Each mode fires the minimum set of tools that together provide complete analysis for that question type. No duplication (if tool A's output already contains tool B's data, don't fire both). No tools that require parameters the resolver can't provide.

---

## Modes

### 1. `qualifying_duel`

**Trigger:** Two drivers + qualifying or sprint-qualifying session

**Tools (7):**
| Tool | Why |
|---|---|
| `analyze_qualifying_battle` | Headline — sectors, markers, gap, energy callout |
| `compare_corner_profiles` | Corner-by-corner speed/technique comparison |
| `analyze_cornering_loads` | Grip commitment (merged into qualifying widget) |
| `analyze_energy_management` | Deployment differences between the two drivers |
| `get_qualifying_results` | Full classification for context |
| `get_driver_style_profile` ×2 | Explain technique differences |

**Not included:**
- `compare_mini_sectors` — needs `lap_number` resolver doesn't provide
- `get_qualifying_progression` — nice-to-have but not essential for a two-driver duel
- `get_speed_trap_leaderboard` — energy_management already surfaces speed differences
- `get_session_fastest_laps` — qualifying_battle already has this data

---

### 2. `race_duel`

**Trigger:** Two drivers + race session + comparison focus

**Tools (6):**
| Tool | Why |
|---|---|
| `analyze_race_pace_battle` | Headline — fuel-corrected pace, degradation, undercut signals |
| `get_driver_race_story` ×2 | Narrative context for each driver (includes strategy, SC impact, energy) |
| `get_safety_car_periods` | SC/VSC timing and who benefited |
| `get_driver_strategy` | Compound choices, pit laps, stint lengths |
| `get_session_weather` | Track temp evolution affecting degradation |

**Not included:**
- `analyze_stint_degradation` — race_pace_battle already computes both drivers' degradation internally
- `get_pit_stop_analysis` — driver_race_story already includes pit times
- `get_race_report` — redundant with two race stories
- `analyze_energy_management` — driver_race_story includes energy evidence
- `get_head_to_head` — season-wide, noise for single-race question

---

### 3. `cornering_grip`

**Trigger:** Two drivers + explicit grip/handling/cornering/driving-style focus

**Tools (5):**
| Tool | Why |
|---|---|
| `analyze_cornering_loads` | Lateral G, grip utilisation, commitment metrics |
| `compare_corner_profiles` | Corner-by-corner entry/apex/exit speed comparison |
| `analyze_race_cornering_profile` | Aggregated cornering stats across full race |
| `get_driver_style_profile` ×2 | Technique context (V-line vs U-line, etc.) |

**Not included:**
- `compare_mini_sectors` — needs `lap_number`
- `analyze_qualifying_battle` — not a grip question

---

### 4. `energy_deployment`

**Trigger:** Energy/ERS/clipping/deployment/battery question

**Tools (3):**
| Tool | Why |
|---|---|
| `analyze_energy_management` | Headline — clipping, lift-coast, deployment zones |
| `get_circuit_profile` | Circuit energy demand profile (clipping risk per sector) |
| `get_speed_trap_leaderboard` | Peak speeds revealing deployment differences |

**Not included:**
- `analyze_active_aero_usage` — needs `lap_number`
- Active aero and override analysis are agentic drill-downs

---

### 5. `driver_weekend`

**Trigger:** Single driver + "how did X do" / weekend recap / single-driver performance

**Tools (3):**
| Tool | Why |
|---|---|
| `get_driver_weekend_overview` | Headline — grid/finish, sessions summary |
| `get_driver_race_story` | Full race narrative (if race occurred) |
| `get_driver_style_profile` | Driver technique context |

**Not included:**
- `get_fp_summary` — needs `fp_number` resolver can't provide
- `get_driver_standings` — nice context but not essential
- `search_editorial_content` — agentic follow-up if needed

---

### 6. `team_analysis`

**Trigger:** Team question (performance, form, car characteristics)

**Tools (5):**
| Tool | Why |
|---|---|
| `analyze_team_performance` | Teammate corner comparison + stint degradation |
| `get_team_weekend_overview` | Headline — both drivers' results |
| `get_team_car_profile` | Car characteristics knowledge |
| `analyze_team_telemetry_traits` | Current car behavior vs field |
| `analyze_team_circuit_fit` | Historical over/under-performance |

**Not included:**
- `get_constructor_standings` — season context, not analysis
- `search_editorial_content` — agentic if needed

---

### 7. `circuit_preview`

**Trigger:** Circuit/track question without driver/team comparison focus

**Tools (3):**
| Tool | Why |
|---|---|
| `get_circuit_profile` | Character, sectors, energy profile, style verdict |
| `get_circuit_track_map` | Track shape geometry |
| `get_historical_circuit_performance` | Past poles/wins at this track |

**Not included:**
- `get_session_weather` — needs `session_type` for a specific session
- `get_fp_summary` — needs `fp_number`
- `search_editorial_content` — agentic if needed

---

## Agentic-Only Tools (drill-down / niche)

These stay in the LLM's tool list but never auto-fire in the deterministic path because they need parameters the resolver can't provide, or they're follow-up queries:

| Tool | Reason for agentic-only |
|---|---|
| `compare_mini_sectors` | Needs `lap_number` |
| `analyze_active_aero_usage` | Needs `lap_number` |
| `analyze_undercut_overcut` | Needs specific `driver_code` + `lap_number` |
| `get_head_to_head` | Season-wide, not session-specific |
| `get_race_report` | Redundant when driver stories are present |
| `get_fp_summary` | Needs `fp_number` |
| `get_pit_stop_analysis` | Subsumed by race stories |
| `get_qualifying_progression` | Nice-to-have follow-up |
| `get_speed_trap_leaderboard` | In energy mode; otherwise follow-up |
| `get_lap_telemetry` | Raw data dump |
| `get_driver_lap_times` | Raw lap-by-lap |
| `get_sector_comparison` | Subset of qualifying battle |
| `get_telemetry_comparison` | Raw overlay |
| `get_track_position_comparison` | Niche |
| `get_circuit_details` | Raw metadata |
| `get_circuit_corners` | Raw corner list |
| `get_session_results` | Raw classification |
| `get_clean_pace_summary` | Subset of pace battle |
| `get_session_fastest_laps` | Follow-up |
| `get_season_schedule` | Simple factual lookup |
| `get_driver_season_stats` | Simple factual lookup |
| `get_driver_standings` | Simple factual lookup |
| `get_constructor_standings` | Simple factual lookup |
| `get_session_weather` | In race_duel; otherwise agentic |
| `search_editorial_content` | Intent-gated, not mode-gated |

---

## Resolver Changes

The resolver's `_detect_analysis_mode()` needs to map to the new mode names:

| Old mode | New mode | Routing logic |
|---|---|---|
| `driver_comparison` (quali) | `qualifying_duel` | 2 drivers + session Q/SQ |
| `driver_comparison` (race) | `race_duel` | 2 drivers + session R/S |
| `driver_comparison` (general) | falls to agentic | No session → can't route deterministically |
| `race_pace_comparison` | `race_duel` | Merged — same tools |
| `grip_comparison` | `cornering_grip` | Explicit grip/style keywords |
| `team_performance` | `team_analysis` | Merged with team_circuit_fit |
| `team_circuit_fit` | `team_analysis` | Same mode now |
| `circuit_profile` | `circuit_preview` | Renamed |
| _(new)_ | `energy_deployment` | Energy/ERS/clipping keywords |
| _(new)_ | `driver_weekend` | Single driver + no comparison focus |

---

## Implementation Notes

- Each feature's `triggered_by_modes` frozenset gets updated to reflect new mode names
- `_build_analysis_plan` in `chat.py` uses `features_for_mode()` which already reads `triggered_by_modes` — no structural change needed
- Thread pool stays at 4 workers — max mode size is 7 tools (qualifying_duel), which queues fine
- Features that appear in multiple modes (e.g., `get_driver_style_profile` in qualifying_duel + cornering_grip + driver_weekend) just have multiple entries in their `triggered_by_modes` frozenset
- `applies_to` still filters at runtime — e.g., `get_driver_race_story` in driver_weekend only fires if a race session exists

---

## Success Criteria

1. "How did Leclerc outqualify Norris at Miami?" → `qualifying_duel` fires 7 tools, produces qualifying widget + corner analysis + energy callout
2. "Compare Norris and Piastri's race in Canada" → `race_duel` fires 6 tools, produces race pace widget + strategy context + weather
3. "Who has better grip, Verstappen or Hamilton?" → `cornering_grip` fires 5 tools, produces corner analysis widget + style comparison
4. "How is Leclerc managing energy vs Norris?" → `energy_deployment` fires 3 tools, produces energy widget
5. "How did Antonelli do this weekend?" → `driver_weekend` fires 3 tools, produces weekend recap
6. "How is Ferrari doing?" → `team_analysis` fires 5 tools, produces team performance widget
7. "Tell me about Monza" → `circuit_preview` fires 3 tools, produces circuit profile widget
