# Editorial RAG Deterministic Gating Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate the editorial RAG knowledge base into F1Dash's deterministic analysis path so interpretive questions ("Why was Norris faster than Piastri?") get cited editorial context, while descriptive questions (sector deltas, lap times) skip retrieval entirely — using a cheap multi-factor gate that fails toward silence rather than noise.

**Architecture:** Add a new `server/editorial/relevance.py` module that gates retrieval per `analysis_mode`, then filters retrieved chunks by similarity threshold + resolver-subject intersection + recency multiplier. Wire it into `_retrieve_analysis_evidence` in `chat.py` as a new evidence type. The analyzer already has the `editorial_observation` hook from earlier work — it'll surface surviving chunks. Add a Supabase audit table so the gate's decisions are inspectable when it inevitably mis-filters.

**Tech Stack:** Python (FastAPI), Supabase (postgrest client + pgvector), Gemini embedding API, existing `editorial/search.py` and `chat.py`. No new dependencies. ~2 hours of focused work.

---

## Background and design rationale

The editorial RAG pipeline already works on the **agentic** path — Claude calls `search_editorial_content` when it sees a context-y question. The **deterministic** path (the `_try_deterministic_analysis` pipeline that runs for resolved analysis modes like `qualifying_battle`) has the analyzer prompt hooks (`editorial_observation` field in the JSON output schema) but no plumbing that actually retrieves editorial chunks to feed it.

This plan closes that gap.

**Research basis** (full report in conversation; key references):
- **CRAG** (Yan et al. 2024, arXiv:2401.15884) — the canonical relevance-gating pattern: grade each chunk `correct` / `incorrect` / `ambiguous`, drop incorrect, treat ambiguous specially.
- **Self-RAG** (Asai et al. 2024, ICLR oral) — same idea, but with fine-tuned reflection tokens. Skipped because it requires training.
- **Recency priors** (Grofsky 2025, arXiv:2509.19376) — `score × exp(-age/half-life)` beats elaborate temporal-RAG approaches on time-sensitive corpora.

**The chosen architecture is the minimum-viable version of CRAG:** no LLM judge, no cross-encoder rerank, no fine-tuning. Just similarity threshold + subject intersection + recency multiplier. Upgrades (Haiku grader, Cohere rerank) are explicitly deferred — they're future-work, not the starting point. The failure mode of the cheap gate is silence (no editorial context), which is the safer error than noise (irrelevant article cited as authoritative).

**Per-mode gating is the bigger lever than chunk-level filtering.** The `analysis_mode` resolver output already distinguishes interpretive ("why") from descriptive ("what") questions; we encode that distinction as a hardcoded set instead of paying for an LLM to decide each time.

---

## File Structure

| File | Responsibility | Status |
|---|---|---|
| `server/editorial/relevance.py` | The gating logic: per-mode whitelist, similarity threshold, subject intersection, recency multiplier, top-k filter | **Create** |
| `supabase/migrations/20260521130000_create_editorial_gate_audit.sql` | Table that logs every gate decision so we can audit false negatives | **Create** |
| `server/chat.py` | Wire `gated_editorial_lookup()` into `_retrieve_analysis_evidence`; render editorial evidence in `_build_analysis_user_prompt` | **Modify** |
| `server/tests/test_editorial_relevance.py` | Unit tests for each gate component + integration | **Create** |
| `server/tests/test_chat.py` | Add 2-3 integration tests for the deterministic path with editorial evidence | **Modify** |

No frontend changes — the analyzer already produces `editorial_observation` and the answer writer already knows how to render it inline.

---

## Task 1: Define the per-mode whitelist constant

**Files:**
- Create: `server/editorial/relevance.py`
- Test: `server/tests/test_editorial_relevance.py`

This is the cheapest gate — many modes skip retrieval entirely. The whitelist comes from the research conclusion: interpretive modes benefit from editorial; descriptive modes don't.

- [ ] **Step 1: Write the failing test**

Create `server/tests/test_editorial_relevance.py`:

```python
from editorial.relevance import (
    EDITORIAL_RELEVANT_MODES,
    should_retrieve_editorial,
)


def test_interpretive_modes_retrieve():
    """Interpretive modes ('why' questions) should retrieve editorial."""
    for mode in ("qualifying_battle", "race_pace_comparison",
                 "driver_comparison", "team_performance",
                 "team_circuit_fit"):
        assert should_retrieve_editorial(mode), f"{mode} should retrieve"


def test_descriptive_modes_skip():
    """Descriptive modes (telemetric / structural) should skip retrieval."""
    for mode in ("circuit_profile", "grip_comparison",
                 "sector_comparison", "corner_comparison"):
        assert not should_retrieve_editorial(mode), f"{mode} should skip"


def test_unknown_mode_skips():
    """Unknown modes default to skip — fail safe."""
    assert not should_retrieve_editorial("unknown_mode")
    assert not should_retrieve_editorial(None)
    assert not should_retrieve_editorial("")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server; python -m pytest tests/test_editorial_relevance.py::test_interpretive_modes_retrieve -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'editorial.relevance'`

- [ ] **Step 3: Create the module with the constant + helper**

Create `server/editorial/relevance.py`:

```python
"""Relevance gating for editorial RAG in the deterministic analysis path.

Two layers of gating:
1. Per-mode: only fire retrieval for interpretive analysis_modes (why was X
   faster?). Descriptive modes (sector deltas, circuit profile) skip
   retrieval entirely — no embedding call, no Supabase round-trip.
2. Per-chunk: after pgvector returns top-N candidates, filter by similarity
   threshold + resolver-subject intersection + recency multiplier. Anything
   that doesn't clear the bar is dropped.

Failure mode is silence: if nothing passes the gates, the analyzer gets no
editorial evidence and its prompt rule says to omit the editorial_observation
field. That's safer than confidently citing an irrelevant article.
"""
from __future__ import annotations

# Analysis modes where editorial context is consistently useful.
# Modes NOT in this set will skip editorial retrieval entirely — saves an
# embedding call + pgvector round-trip on every descriptive question.
EDITORIAL_RELEVANT_MODES: frozenset[str] = frozenset({
    "qualifying_battle",
    "race_pace_comparison",
    "driver_comparison",
    "team_performance",
    "team_circuit_fit",
})


def should_retrieve_editorial(analysis_mode: str | None) -> bool:
    """Return True if this analysis_mode should attempt editorial retrieval."""
    if not analysis_mode:
        return False
    return analysis_mode in EDITORIAL_RELEVANT_MODES
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd server; python -m pytest tests/test_editorial_relevance.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add server/editorial/relevance.py server/tests/test_editorial_relevance.py
git commit -m "feat(editorial): per-mode whitelist for deterministic editorial retrieval

Adds EDITORIAL_RELEVANT_MODES + should_retrieve_editorial(). Interpretive
modes (qualifying_battle, race_pace_comparison, driver_comparison,
team_performance, team_circuit_fit) will retrieve editorial chunks;
descriptive modes (sector deltas, circuit profile, grip comparison)
skip retrieval entirely.

Unknown modes default to False — fail safe."
```

---

## Task 2: Subject intersection filter

**Files:**
- Modify: `server/editorial/relevance.py`
- Test: `server/tests/test_editorial_relevance.py`

The resolver already produces structured entities (drivers, team, circuit, round). The `article_subjects` table stores per-article tags from the subject tagger. Intersection = "this article was tagged with at least one of the entities the user asked about."

- [ ] **Step 1: Write the failing test**

Append to `server/tests/test_editorial_relevance.py`:

```python
from editorial.relevance import build_resolver_subject_set, chunk_passes_subject_filter


def test_build_resolver_subject_set_includes_drivers_team_circuit():
    resolved = {
        "drivers": [{"code": "NOR"}, {"code": "PIA"}],
        "team": "McLaren",
        "circuit_slug": "imola",
    }
    subjects = build_resolver_subject_set(resolved)
    assert ("driver", "NOR") in subjects
    assert ("driver", "PIA") in subjects
    assert ("team", "mclaren") in subjects
    assert ("circuit", "imola") in subjects


def test_build_resolver_subject_set_handles_missing_fields():
    """Resolver output is sometimes partial — must not crash on missing keys."""
    assert build_resolver_subject_set({}) == frozenset()
    assert build_resolver_subject_set({"drivers": []}) == frozenset()
    assert build_resolver_subject_set(None) == frozenset()


def test_chunk_passes_subject_filter_when_overlap():
    """Chunk passes when its article shares at least one subject with the resolver."""
    chunk = {"article_subjects": [{"kind": "driver", "ref": "NOR"}]}
    resolver_subjects = frozenset({("driver", "NOR"), ("circuit", "imola")})
    assert chunk_passes_subject_filter(chunk, resolver_subjects)


def test_chunk_fails_subject_filter_when_no_overlap():
    """Chunk fails when its article has no matching subject."""
    chunk = {"article_subjects": [{"kind": "driver", "ref": "VER"}]}
    resolver_subjects = frozenset({("driver", "NOR"), ("circuit", "imola")})
    assert not chunk_passes_subject_filter(chunk, resolver_subjects)


def test_chunk_passes_when_resolver_subjects_empty():
    """If the resolver produced no entities, don't gate on subjects — fall
    back to similarity-only filtering. Returning False here would silently
    drop every chunk on under-specified questions."""
    chunk = {"article_subjects": [{"kind": "driver", "ref": "NOR"}]}
    assert chunk_passes_subject_filter(chunk, frozenset())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server; python -m pytest tests/test_editorial_relevance.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_resolver_subject_set'`

- [ ] **Step 3: Implement the subject helpers**

Append to `server/editorial/relevance.py`:

```python
def build_resolver_subject_set(resolved: dict | None) -> frozenset[tuple[str, str]]:
    """Convert resolver entities into a frozenset of (kind, ref) tuples that
    can be intersected with article_subjects rows.

    Drivers come as a list of dicts with a 'code' field (3-letter uppercase).
    Team comes as a string (canonicalised to lowercase for matching).
    Circuit comes as a slug (already lowercase).
    """
    if not resolved:
        return frozenset()

    subjects: set[tuple[str, str]] = set()

    for driver in (resolved.get("drivers") or []):
        code = (driver.get("code") or "").strip().upper()
        if code:
            subjects.add(("driver", code))

    team = (resolved.get("team") or "").strip().lower()
    if team:
        # Normalise team name to slug-ish form to match article_subjects.ref.
        # E.g. "Racing Bulls" -> "racing_bulls". The subject tagger uses the
        # same normalisation.
        subjects.add(("team", team.replace(" ", "_")))

    circuit_slug = (resolved.get("circuit_slug") or "").strip().lower()
    if circuit_slug:
        subjects.add(("circuit", circuit_slug))

    return frozenset(subjects)


def chunk_passes_subject_filter(
    chunk: dict,
    resolver_subjects: frozenset[tuple[str, str]],
) -> bool:
    """A chunk passes when its parent article's subjects intersect the
    resolver's. If the resolver produced no subjects (highly under-specified
    question), the filter is a no-op — fall through to similarity-only.
    """
    if not resolver_subjects:
        return True  # no resolver subjects → no filter, similarity must carry

    raw_subjects = chunk.get("article_subjects") or []
    chunk_subjects = {
        (s.get("kind"), s.get("ref"))
        for s in raw_subjects
        if s.get("kind") and s.get("ref")
    }
    return bool(chunk_subjects & resolver_subjects)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd server; python -m pytest tests/test_editorial_relevance.py -v`
Expected: PASS (8 tests total)

- [ ] **Step 5: Commit**

```bash
git add server/editorial/relevance.py server/tests/test_editorial_relevance.py
git commit -m "feat(editorial): subject-intersection filter for retrieved chunks

Adds build_resolver_subject_set() that turns resolver output into a
frozenset of (kind, ref) tuples (driver:NOR, team:mclaren, circuit:imola)
that intersects with article_subjects rows.

chunk_passes_subject_filter() returns True if the chunk's article has
at least one subject matching the resolver. When the resolver produced
no subjects, returns True unconditionally — similarity carries the load
on under-specified questions."
```

---

## Task 3: Recency multiplier

**Files:**
- Modify: `server/editorial/relevance.py`
- Test: `server/tests/test_editorial_relevance.py`

`score × exp(-age_days / half_life)`. Half-life of 21 days approximates "an article is half as relevant 3 weeks after publication." Tuned for the F1 race-weekend cadence (~24 weekends per year). Per Grofsky 2025 — a simple recency prior is surprisingly hard to beat with more elaborate methods.

- [ ] **Step 1: Write the failing test**

Append to `server/tests/test_editorial_relevance.py`:

```python
import math
from datetime import datetime, timedelta, timezone

from editorial.relevance import (
    HALF_LIFE_DAYS,
    apply_recency_multiplier,
)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def test_recency_multiplier_fresh_article_score_unchanged():
    """An article published today gets multiplier ≈ 1.0."""
    today = datetime.now(timezone.utc)
    adjusted = apply_recency_multiplier(0.80, _iso(today), now=today)
    assert abs(adjusted - 0.80) < 0.001


def test_recency_multiplier_one_half_life_halves_score():
    """At 21 days old, score should be ~0.5 of original."""
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=HALF_LIFE_DAYS)
    adjusted = apply_recency_multiplier(0.80, _iso(old), now=now)
    # exp(-21/21) = exp(-1) ≈ 0.368, so adjusted ≈ 0.80 * 0.368 ≈ 0.294
    expected = 0.80 * math.exp(-1)
    assert abs(adjusted - expected) < 0.001


def test_recency_multiplier_handles_missing_date():
    """Articles without published_at get a neutral 1.0 multiplier — no
    information, no penalty."""
    assert apply_recency_multiplier(0.80, None) == 0.80
    assert apply_recency_multiplier(0.80, "") == 0.80


def test_recency_multiplier_handles_unparseable_date():
    """Garbage in shouldn't crash — fall back to neutral."""
    assert apply_recency_multiplier(0.80, "not-a-date") == 0.80


def test_recency_multiplier_never_below_floor():
    """Very old articles still get a small positive multiplier so they can
    surface if similarity is very high. Floor at 0.05 to avoid total zero."""
    now = datetime.now(timezone.utc)
    very_old = now - timedelta(days=400)
    adjusted = apply_recency_multiplier(0.80, _iso(very_old), now=now)
    # 0.80 * exp(-400/21) ≈ 0.80 * 5e-9 → below floor → 0.80 * 0.05 = 0.04
    assert adjusted >= 0.80 * 0.05 - 0.001
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server; python -m pytest tests/test_editorial_relevance.py -v`
Expected: FAIL with `ImportError: cannot import name 'apply_recency_multiplier'`

- [ ] **Step 3: Implement the recency function**

Append to `server/editorial/relevance.py`:

```python
import math
from datetime import datetime, timezone


# Half-life for editorial relevance, in days. Tuned for the F1 race-weekend
# cadence — an article is half as relevant 3 weeks after publication, which
# matches the "every other weekend has a race" rhythm of the season.
HALF_LIFE_DAYS: float = 21.0

# Floor below which the recency multiplier is clamped. Prevents very old
# articles from being totally zeroed out — keeps the gate from suppressing
# a 5-year-old article that's still highly relevant by similarity.
RECENCY_FLOOR: float = 0.05


def _parse_published(published_at: str | None) -> datetime | None:
    if not published_at:
        return None
    try:
        # Handle both "2026-05-21" and "2026-05-21T13:42:00+00:00" forms.
        if "T" in published_at:
            dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(published_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def apply_recency_multiplier(
    score: float,
    published_at: str | None,
    *,
    now: datetime | None = None,
) -> float:
    """Multiply score by an exponential recency decay.

    score × max(exp(-age_days / HALF_LIFE_DAYS), RECENCY_FLOOR)

    Articles without published_at get a neutral 1.0 multiplier — no
    information means no penalty.
    """
    dt = _parse_published(published_at)
    if dt is None:
        return score

    if now is None:
        now = datetime.now(timezone.utc)

    age_days = max((now - dt).total_seconds() / 86400.0, 0.0)
    multiplier = math.exp(-age_days / HALF_LIFE_DAYS)
    multiplier = max(multiplier, RECENCY_FLOOR)
    return score * multiplier
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd server; python -m pytest tests/test_editorial_relevance.py -v`
Expected: PASS (13 tests total)

- [ ] **Step 5: Commit**

```bash
git add server/editorial/relevance.py server/tests/test_editorial_relevance.py
git commit -m "feat(editorial): recency multiplier with 21-day half-life

Adds apply_recency_multiplier(score, published_at) → score × exp(-age/21).
Floors at 0.05 of the original score so very-old-but-very-relevant
articles (e.g. archive pieces still cited by similarity) aren't totally
suppressed. Missing/unparseable published_at returns neutral 1.0.

21-day half-life matches the F1 race-weekend cadence."
```

---

## Task 4: Audit log table migration

**Files:**
- Create: `supabase/migrations/20260521130000_create_editorial_gate_audit.sql`

The gate's failure mode is silence. Without logging, we can't tell when it drops chunks we'd have wanted to keep. Cheap insurance: log every decision to a small table we can inspect later.

- [ ] **Step 1: Write the migration**

Create `supabase/migrations/20260521130000_create_editorial_gate_audit.sql`:

```sql
-- Audit log for the editorial RAG relevance gate.
--
-- Every call to gated_editorial_lookup writes one row here, recording what
-- the gate considered and what it chose to keep. Lets us inspect false
-- negatives (relevant chunks dropped) without instrumenting the chat layer.

create table editorial_gate_audit (
    id              bigint generated always as identity primary key,
    created_at      timestamptz not null default now(),
    question        text not null,
    analysis_mode   text not null,
    resolver_subjects jsonb,           -- snapshot of resolver entity set
    candidate_count int not null,      -- how many chunks came back from pgvector
    kept_count      int not null,      -- how many survived the gate
    threshold_used  float8,            -- the similarity threshold applied
    dropped         jsonb,             -- [{chunk_id, reason, similarity, age_days}]
    kept_chunk_ids  jsonb              -- [chunk_id, ...]
);

create index editorial_gate_audit_created_at_idx
    on editorial_gate_audit (created_at desc);
create index editorial_gate_audit_mode_idx
    on editorial_gate_audit (analysis_mode);

comment on table editorial_gate_audit is
    'Records each gate decision so we can audit false negatives — relevant
     chunks dropped by the cheap (threshold + subject + recency) filter.
     Inspect periodically; prune rows older than 90 days.';
```

- [ ] **Step 2: Verify migration syntactically valid**

There's no easy local Postgres for this — the migration runs via `supabase db push`. For now, do a syntactic dry-check by running:

```bash
cd C:/Users/sanja/Documents/Nerd/F1Dash
python -c "
content = open('supabase/migrations/20260521130000_create_editorial_gate_audit.sql').read()
assert 'create table editorial_gate_audit' in content
assert 'jsonb' in content
print('migration file looks well-formed')
"
```

Expected: prints `migration file looks well-formed`

- [ ] **Step 3: Commit the migration (do NOT push yet)**

```bash
git add supabase/migrations/20260521130000_create_editorial_gate_audit.sql
git commit -m "feat(editorial): migration for editorial_gate_audit table

Captures every gate decision so we can audit false negatives. The
gate fails toward silence — without this table, we'd never know when
relevant chunks get dropped.

Apply with: supabase db push (the user runs this manually after merge)."
```

The user will apply the migration with `supabase db push` after the branch is merged. Do NOT run `supabase db push` yourself — the user reviews migrations before pushing.

---

## Task 5: Audit logger function

**Files:**
- Modify: `server/editorial/client.py` (add `insert_gate_audit` helper)
- Modify: `server/editorial/relevance.py` (call it from `gated_editorial_lookup`)
- Test: `server/tests/test_editorial_relevance.py`

- [ ] **Step 1: Write the failing test**

Append to `server/tests/test_editorial_relevance.py`:

```python
from unittest.mock import patch

from editorial.relevance import log_gate_decision


def test_log_gate_decision_calls_supabase_insert():
    """log_gate_decision should write one row to editorial_gate_audit via
    the existing postgrest client wrapper."""
    candidates = [
        {"chunk_id": 1, "similarity": 0.72, "published_at": "2026-05-01"},
        {"chunk_id": 2, "similarity": 0.55, "published_at": "2026-05-15"},
    ]
    survivors = [
        {"chunk_id": 1, "similarity": 0.72, "published_at": "2026-05-01"},
    ]

    with patch("editorial.relevance._client") as mock_client:
        log_gate_decision(
            question="why was norris faster",
            analysis_mode="qualifying_battle",
            resolver_subjects=frozenset([("driver", "NOR")]),
            candidates=candidates,
            survivors=survivors,
            threshold_used=0.62,
        )
        mock_client.insert_gate_audit.assert_called_once()
        # The row passed in should contain question + counts
        row = mock_client.insert_gate_audit.call_args.args[0]
        assert row["question"] == "why was norris faster"
        assert row["analysis_mode"] == "qualifying_battle"
        assert row["candidate_count"] == 2
        assert row["kept_count"] == 1


def test_log_gate_decision_does_not_crash_on_db_unavailable():
    """If the audit insert fails, the main path must continue. Audit is
    best-effort, never blocking."""
    with patch("editorial.relevance._client") as mock_client:
        mock_client.insert_gate_audit.side_effect = Exception("supabase down")
        # Should not raise
        log_gate_decision(
            question="q",
            analysis_mode="qualifying_battle",
            resolver_subjects=frozenset(),
            candidates=[],
            survivors=[],
            threshold_used=0.62,
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server; python -m pytest tests/test_editorial_relevance.py::test_log_gate_decision_calls_supabase_insert -v`
Expected: FAIL with `ImportError: cannot import name 'log_gate_decision'`

- [ ] **Step 3: Add the insert helper to client.py**

Open `server/editorial/client.py`. After the `insert_subjects()` function, append:

```python
def insert_gate_audit(row: dict[str, Any]) -> None:
    """Best-effort insert into editorial_gate_audit. Never raises."""
    try:
        client = _get_supabase_client()
        client.from_("editorial_gate_audit").insert(row).execute()
    except Exception as e:
        logger.warning("insert_gate_audit failed: %s", type(e).__name__)
```

- [ ] **Step 4: Add log_gate_decision to relevance.py**

Append to `server/editorial/relevance.py`:

```python
import json
import logging

from editorial import client as _client

logger = logging.getLogger(__name__)


def log_gate_decision(
    *,
    question: str,
    analysis_mode: str,
    resolver_subjects: frozenset[tuple[str, str]],
    candidates: list[dict],
    survivors: list[dict],
    threshold_used: float,
) -> None:
    """Record one gate decision for later auditing. Best-effort — failures
    are logged but never raised."""
    survivor_ids = {c.get("chunk_id") for c in survivors if c.get("chunk_id")}
    dropped: list[dict] = []
    for c in candidates:
        cid = c.get("chunk_id")
        if cid in survivor_ids:
            continue
        dropped.append({
            "chunk_id": cid,
            "similarity": c.get("similarity"),
            "published_at": c.get("published_at"),
            "reason": c.get("_drop_reason", "below_threshold"),
        })

    row = {
        "question": question[:1000],  # cap to avoid huge audit rows
        "analysis_mode": analysis_mode,
        "resolver_subjects": [
            {"kind": k, "ref": r} for (k, r) in resolver_subjects
        ],
        "candidate_count": len(candidates),
        "kept_count": len(survivors),
        "threshold_used": threshold_used,
        "dropped": dropped,
        "kept_chunk_ids": list(survivor_ids),
    }
    try:
        _client.insert_gate_audit(row)
    except Exception as e:
        logger.warning("log_gate_decision audit insert failed: %s", type(e).__name__)
```

- [ ] **Step 5: Run tests to verify**

Run: `cd server; python -m pytest tests/test_editorial_relevance.py -v`
Expected: PASS (15 tests total)

- [ ] **Step 6: Commit**

```bash
git add server/editorial/client.py server/editorial/relevance.py server/tests/test_editorial_relevance.py
git commit -m "feat(editorial): audit logger for gate decisions

log_gate_decision() writes question, mode, candidate_count, kept_count,
dropped chunks (with reasons), and kept chunk IDs to editorial_gate_audit.

insert_gate_audit() in client.py is the postgrest wrapper. Both
functions are best-effort — audit failures never block the chat path."
```

---

## Task 6: The main `gated_editorial_lookup` function

**Files:**
- Modify: `server/editorial/relevance.py`
- Test: `server/tests/test_editorial_relevance.py`

The orchestrator. Pulls it all together: mode check → query construction → search → subject filter → recency-adjusted scoring → top-k cap → audit log.

- [ ] **Step 1: Write the failing test**

Append to `server/tests/test_editorial_relevance.py`:

```python
from unittest.mock import patch

from editorial.relevance import gated_editorial_lookup


def test_gated_lookup_skips_irrelevant_mode():
    """circuit_profile mode shouldn't even attempt retrieval."""
    with patch("editorial.relevance._search") as mock_search, \
         patch("editorial.relevance.log_gate_decision") as mock_log:
        result = gated_editorial_lookup(
            question="what's the circuit profile for Monaco",
            resolved={"drivers": [], "circuit_slug": "monaco"},
            analysis_mode="circuit_profile",
        )
        assert result is None
        mock_search.assert_not_called()
        mock_log.assert_not_called()  # not even logged — early exit


def test_gated_lookup_returns_none_when_no_candidates():
    """If pgvector returns nothing, return None — caller knows to skip."""
    with patch("editorial.relevance._search", return_value={"results": []}) as _, \
         patch("editorial.relevance.log_gate_decision") as mock_log:
        result = gated_editorial_lookup(
            question="why was norris faster",
            resolved={"drivers": [{"code": "NOR"}, {"code": "PIA"}]},
            analysis_mode="qualifying_battle",
        )
        assert result is None
        mock_log.assert_called_once()  # logged the empty candidate set


def test_gated_lookup_keeps_chunks_passing_all_gates():
    """High-similarity, subject-matching, recent chunk survives."""
    from datetime import datetime, timezone
    recent = datetime.now(timezone.utc).isoformat()
    fake_results = {
        "search_mode": "semantic",
        "results": [
            {
                "chunk_id": 101,
                "similarity": 0.82,
                "chunk_text": "Norris said McLaren brought a new floor...",
                "title": "McLaren Imola upgrade",
                "url": "https://the-race.com/x",
                "source": "The Race",
                "published_at": recent,
                "article_subjects": [
                    {"kind": "driver", "ref": "NOR"},
                    {"kind": "team", "ref": "mclaren"},
                ],
            },
        ],
    }
    with patch("editorial.relevance._search", return_value=fake_results), \
         patch("editorial.relevance.log_gate_decision"):
        result = gated_editorial_lookup(
            question="why was norris faster at Imola",
            resolved={
                "drivers": [{"code": "NOR"}, {"code": "PIA"}],
                "team": "McLaren",
                "circuit_slug": "imola",
            },
            analysis_mode="qualifying_battle",
        )
        assert result is not None
        assert result["kind"] == "editorial"
        assert len(result["chunks"]) == 1
        assert result["chunks"][0]["chunk_id"] == 101


def test_gated_lookup_drops_chunk_failing_subject_intersection():
    """High similarity but wrong driver/team → dropped."""
    from datetime import datetime, timezone
    recent = datetime.now(timezone.utc).isoformat()
    fake_results = {
        "search_mode": "semantic",
        "results": [
            {
                "chunk_id": 202,
                "similarity": 0.85,
                "chunk_text": "Verstappen took pole in Bahrain...",
                "url": "https://...",
                "source": "...",
                "published_at": recent,
                "article_subjects": [{"kind": "driver", "ref": "VER"}],
            },
        ],
    }
    with patch("editorial.relevance._search", return_value=fake_results), \
         patch("editorial.relevance.log_gate_decision"):
        result = gated_editorial_lookup(
            question="why was norris faster",
            resolved={"drivers": [{"code": "NOR"}, {"code": "PIA"}]},
            analysis_mode="qualifying_battle",
        )
        assert result is None  # everything dropped → return None


def test_gated_lookup_drops_chunk_below_similarity_threshold():
    """Subject-matching but low similarity → dropped."""
    from datetime import datetime, timezone
    recent = datetime.now(timezone.utc).isoformat()
    fake_results = {
        "search_mode": "semantic",
        "results": [
            {
                "chunk_id": 303,
                "similarity": 0.40,  # below 0.62 threshold
                "chunk_text": "some borderline content...",
                "url": "https://...",
                "source": "...",
                "published_at": recent,
                "article_subjects": [{"kind": "driver", "ref": "NOR"}],
            },
        ],
    }
    with patch("editorial.relevance._search", return_value=fake_results), \
         patch("editorial.relevance.log_gate_decision"):
        result = gated_editorial_lookup(
            question="why was norris faster",
            resolved={"drivers": [{"code": "NOR"}]},
            analysis_mode="qualifying_battle",
        )
        assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server; python -m pytest tests/test_editorial_relevance.py -v`
Expected: FAIL with `ImportError: cannot import name 'gated_editorial_lookup'`

- [ ] **Step 3: Implement gated_editorial_lookup**

Append to `server/editorial/relevance.py`:

```python
from editorial.search import search_editorial_content as _search


# Calibrate against a labelled set if you have one. 0.62 is a starting
# guess for Gemini gemini-embedding-2 1536-dim cosine similarity.
DEFAULT_SIMILARITY_THRESHOLD: float = 0.62

# Top-K to retrieve from pgvector before filtering. Higher = more chunks
# considered (better recall) but more downstream work. 10 is fine.
RETRIEVAL_LIMIT: int = 10

# After filtering, cap at this many surviving chunks. Don't flood the
# analyzer's context — pick the best few.
MAX_SURVIVORS: int = 3


def gated_editorial_lookup(
    *,
    question: str,
    resolved: dict | None,
    analysis_mode: str | None,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> dict | None:
    """Run editorial retrieval through the relevance gate.

    Returns:
        {"kind": "editorial", "chunks": [...]} when at least one chunk
        passes all gates.
        None when:
          - analysis_mode is not in the whitelist (early exit, no search)
          - pgvector returned zero candidates
          - all candidates were dropped by the gate

    Logs every non-early-exit decision to editorial_gate_audit.
    """
    if not should_retrieve_editorial(analysis_mode):
        return None

    resolver_subjects = build_resolver_subject_set(resolved)

    # Run the underlying retrieval. We accept whatever it returns — empty,
    # semantic, or FTS-mode results are all handled uniformly downstream.
    try:
        search_out = _search(query=question, limit=RETRIEVAL_LIMIT)
    except Exception as e:
        logger.warning("editorial _search crashed: %s", type(e).__name__)
        return None

    candidates: list[dict] = list(search_out.get("results") or [])

    # Apply each filter; tag drops with a reason for the audit log.
    survivors: list[dict] = []
    for c in candidates:
        sim = c.get("similarity")
        if sim is None or sim < similarity_threshold:
            c["_drop_reason"] = "below_threshold"
            continue
        if not chunk_passes_subject_filter(c, resolver_subjects):
            c["_drop_reason"] = "subject_mismatch"
            continue
        # Recency-adjust the similarity. We use it to re-rank survivors but
        # don't gate on it directly — high-similarity old articles still
        # survive thanks to RECENCY_FLOOR.
        c["_adjusted_score"] = apply_recency_multiplier(sim, c.get("published_at"))
        survivors.append(c)

    # Sort survivors by adjusted score, cap at MAX_SURVIVORS.
    survivors.sort(key=lambda c: c.get("_adjusted_score", 0.0), reverse=True)
    survivors = survivors[:MAX_SURVIVORS]

    # Best-effort audit log. Failure here never propagates.
    log_gate_decision(
        question=question,
        analysis_mode=analysis_mode,
        resolver_subjects=resolver_subjects,
        candidates=candidates,
        survivors=survivors,
        threshold_used=similarity_threshold,
    )

    if not survivors:
        return None

    # Strip internal-only fields before handing off to the analyzer.
    clean_survivors = [
        {k: v for k, v in c.items() if not k.startswith("_")}
        for c in survivors
    ]
    return {"kind": "editorial", "chunks": clean_survivors}
```

- [ ] **Step 4: Run tests**

Run: `cd server; python -m pytest tests/test_editorial_relevance.py -v`
Expected: PASS (20 tests total)

- [ ] **Step 5: Commit**

```bash
git add server/editorial/relevance.py server/tests/test_editorial_relevance.py
git commit -m "feat(editorial): gated_editorial_lookup orchestrator

Pulls together the three-layer gate: per-mode early exit, similarity
threshold (0.62), subject intersection with resolver entities, recency
multiplier (21-day half-life). Returns {kind: 'editorial', chunks: [...]}
or None.

Caps at 3 surviving chunks to avoid flooding the analyzer context.
Logs every decision to editorial_gate_audit (best-effort)."
```

---

## Task 7: Wire into the deterministic analysis path

**Files:**
- Modify: `server/chat.py` — `_retrieve_analysis_evidence` + `_build_analysis_user_prompt`
- Test: `server/tests/test_chat.py`

This is where it actually plugs into the user-facing flow. After the existing tool plan executes, attempt a gated editorial lookup. If it returns chunks, append them to evidence as a new entry. The analyzer prompt's `editorial_observation` rule already knows how to surface them.

- [ ] **Step 1: Read the existing `_retrieve_analysis_evidence` and `_build_analysis_user_prompt` to locate insertion points**

```bash
grep -n "_retrieve_analysis_evidence\|_build_analysis_user_prompt" server/chat.py | head -20
```

Note the function signatures — `_retrieve_analysis_evidence(plan, resolved, ...)` returns a list of evidence dicts. `_build_analysis_user_prompt(evidence, ...)` renders them into a prompt block.

- [ ] **Step 2: Write the failing integration test**

Append to `server/tests/test_chat.py`:

```python
from unittest.mock import patch


def test_deterministic_path_includes_editorial_evidence_when_gate_passes():
    """In a qualifying_battle mode, gated_editorial_lookup returns chunks;
    _retrieve_analysis_evidence must include them as 'editorial' evidence."""
    import chat
    fake_editorial = {
        "kind": "editorial",
        "chunks": [
            {
                "chunk_id": 99,
                "chunk_text": "McLaren brought a new floor to Imola.",
                "title": "Imola upgrades",
                "url": "https://the-race.com/imola",
                "source": "The Race",
                "published_at": "2026-05-15",
                "similarity": 0.78,
            },
        ],
    }
    plan = []  # empty regular plan; we're testing the editorial addition
    resolved = {
        "drivers": [{"code": "NOR"}, {"code": "PIA"}],
        "team": "McLaren",
        "circuit_slug": "imola",
        "analysis_mode": "qualifying_battle",
    }
    with patch("chat.gated_editorial_lookup", return_value=fake_editorial), \
         patch("chat._execute_analysis_tool_calls", return_value=[]):
        evidence = chat._retrieve_analysis_evidence(
            plan, resolved, question="why was norris faster at Imola",
        )
    editorial_items = [e for e in evidence if e.get("kind") == "editorial"]
    assert len(editorial_items) == 1
    assert editorial_items[0]["chunks"][0]["url"] == "https://the-race.com/imola"


def test_deterministic_path_omits_editorial_when_gate_returns_none():
    """If the gate returns None, no editorial entry is appended."""
    import chat
    plan = []
    resolved = {
        "drivers": [{"code": "NOR"}],
        "analysis_mode": "circuit_profile",  # not in whitelist
    }
    with patch("chat.gated_editorial_lookup", return_value=None), \
         patch("chat._execute_analysis_tool_calls", return_value=[]):
        evidence = chat._retrieve_analysis_evidence(
            plan, resolved, question="tell me about Monaco",
        )
    editorial_items = [e for e in evidence if e.get("kind") == "editorial"]
    assert editorial_items == []
```

- [ ] **Step 3: Run test to confirm it fails**

Run: `cd server; python -m pytest tests/test_chat.py::test_deterministic_path_includes_editorial_evidence_when_gate_passes -v`
Expected: FAIL — either ImportError (gated_editorial_lookup not imported in chat) or the test produces no editorial evidence.

- [ ] **Step 4: Import + call gated_editorial_lookup in chat.py**

In `server/chat.py`, near the top imports, add:

```python
from editorial.relevance import gated_editorial_lookup
```

In `_retrieve_analysis_evidence`, after the existing tool plan executes and evidence is gathered, append:

```python
    # Editorial RAG gate — only fires for interpretive analysis_modes.
    # Returns None when the mode isn't relevant or no chunks pass the gate.
    try:
        editorial_result = gated_editorial_lookup(
            question=question,
            resolved=resolved,
            analysis_mode=resolved.get("analysis_mode") if resolved else None,
        )
        if editorial_result is not None:
            evidence.append(editorial_result)
    except Exception as e:
        logger.warning("gated_editorial_lookup crashed: %s", type(e).__name__)
        # Failure must not block the deterministic path.
```

The function signature of `_retrieve_analysis_evidence` may not currently accept `question`. If it doesn't, add it as a keyword argument with a default of `""`, and pass it from the call site in `_try_deterministic_analysis` (the message the user sent).

- [ ] **Step 5: Update `_build_analysis_user_prompt` to render editorial evidence**

Find `_build_analysis_user_prompt` (it loops through evidence and formats each entry into the prompt). Add a branch for `kind == "editorial"`:

```python
        if entry.get("kind") == "editorial":
            chunks = entry.get("chunks") or []
            if not chunks:
                continue
            block = ["### Editorial context (use sparingly; cite source + date)"]
            for c in chunks:
                src = c.get("source") or "Unknown"
                date = c.get("published_at") or "n.d."
                title = c.get("title") or "(untitled)"
                url = c.get("url") or ""
                text = (c.get("chunk_text") or "").strip()
                block.append(
                    f"\n— {src}, {date}: {title}\n  {url}\n  {text}"
                )
            parts.append("\n".join(block))
            continue
```

(`parts` is the existing accumulator the function uses; the exact variable name may differ — match the existing code style.)

- [ ] **Step 6: Run the integration tests**

Run: `cd server; python -m pytest tests/test_chat.py -v --tb=short -k "editorial or deterministic"`
Expected: PASS (both new tests).

Also run the full chat suite to make sure nothing regressed:

```bash
cd server; python -m pytest tests/ -q 2>&1 | tail -3
```
Expected: 444 + 7 new = 451 passing (counts assume the tests added so far).

- [ ] **Step 7: Commit**

```bash
git add server/chat.py server/tests/test_chat.py
git commit -m "feat(editorial): wire gated_editorial_lookup into deterministic path

_retrieve_analysis_evidence now calls gated_editorial_lookup after the
existing tool plan executes. If editorial chunks survive the gate, they
join the analysis evidence as kind=editorial. The analyzer's
editorial_observation prompt hook (already in place from earlier work)
surfaces them in the JSON output.

Failure mode: any exception in the gate is logged at WARN and the
deterministic path continues without editorial context. Editorial is
strictly additive — its absence never breaks the analysis."
```

---

## Task 8: End-to-end smoke test

**Files:**
- Manual verification — no code changes.

This task isn't automated; it's the operator running a real chat query to confirm the pipeline produces editorial-grounded output.

- [ ] **Step 1: Apply the migration to Supabase**

```bash
cd C:/Users/sanja/Documents/Nerd/F1Dash
supabase db push
```

Expected: applies `20260521130000_create_editorial_gate_audit.sql`. Confirm the new table exists by listing tables in the Supabase dashboard.

- [ ] **Step 2: Start uvicorn**

```bash
cd C:/Users/sanja/Documents/Nerd/F1Dash/server
python -m uvicorn main:app --reload --port 8000
```

- [ ] **Step 3: Issue a real qualifying-battle question**

Ask the chat: *"Why was Norris faster than Piastri in qualifying at the 2024 British GP?"*

Expected:
- Deterministic path runs (resolver classifies as `qualifying_battle`).
- The qualifying-battle tool calls run as today.
- `gated_editorial_lookup` fires; if any 2024 British GP McLaren article exists in the corpus, surviving chunks land in evidence.
- The answer text includes a citation like *"Per The Race (2024-07-...)..."* when editorial chunks were present.

- [ ] **Step 4: Inspect the audit table**

In Supabase SQL editor:

```sql
select created_at, question, analysis_mode, candidate_count, kept_count, threshold_used
from editorial_gate_audit
order by created_at desc
limit 5;
```

Expected: at least one row for the question you just asked, with `analysis_mode = 'qualifying_battle'`. `kept_count` may be 0 or more depending on coverage.

- [ ] **Step 5: Issue a descriptive question that should skip retrieval**

Ask the chat: *"Show me the sector deltas for Norris and Piastri at Imola 2024."*

Expected:
- The chat answers using telemetry only.
- The `editorial_gate_audit` table has NO new row from this question (the per-mode whitelist short-circuits before any logging).

- [ ] **Step 6: Confirm the failure mode**

Ask the chat a qualifying-battle question for a race we *don't* have coverage on (e.g. an obscure 2024 race). The chat should still produce a coherent telemetry-based answer without claiming "no editorial available" — the `editorial_observation` field in the analyzer JSON should simply be absent.

---

## Validation Checklist

Cross-cutting. Run after Task 7 lands; re-run all of these before declaring complete.

- [ ] `cd server; python -m pytest tests/ -v` — full suite green; 451+ tests pass.
- [ ] `cd client; npm run build` — frontend still compiles (this plan doesn't touch the frontend but confirm).
- [ ] `grep -rn "search_editorial_content" server/chat.py` — referenced only from agentic tool dispatch and analyzer prompt; NOT directly called from deterministic path (it goes through `gated_editorial_lookup`).
- [ ] `grep -n "EDITORIAL_RELEVANT_MODES" server/editorial/relevance.py` — exactly one definition.
- [ ] `supabase db push` applied successfully; `editorial_gate_audit` table exists in the Supabase dashboard.
- [ ] After running the smoke-test questions in Task 8, the audit table has rows for the qualifying-battle question and none for the sector-deltas question.
- [ ] The chat answer to *"Why was Norris faster than Piastri at Imola 2024 quali?"* cites at least one editorial source if any 2024 Imola McLaren article is in the corpus — verify by inspecting the `editorial_observation` field in the analyzer's intermediate JSON if your debug logging surfaces it.

---

## Risks and Open Questions

Surfaced per CLAUDE.md risk protocol.

| Risk | Trigger | Proposed resolution | Decision needed by |
|---|---|---|---|
| **Threshold 0.62 is mis-calibrated for Gemini gemini-embedding-2.** Tested on small synthetic queries only. May drop too many real-world chunks, or pass through too many. | First week of production use | Inspect the audit table after a few days; if median `kept_count` is 0 or `dropped` is full of `below_threshold` entries that look relevant, lower to 0.55. Conversely if irrelevant chunks survive, raise to 0.70. | Post-launch |
| **`circuit_slug` field name in resolver output may differ from what we assume.** The plan assumes `resolved["circuit_slug"]` but the resolver may use `resolved["circuit"]["slug"]` or `resolved["event"]["slug"]`. | Task 7 testing | Inspect `resolver.py` and the resolver's actual output shape on a real query; adjust `build_resolver_subject_set` to match. Add a unit test for the actual shape. | Task 7 |
| **`article_subjects` may not be reliably populated** for older articles ingested before the subject tagger was wired up. | Anytime | Run a backfill script: re-tag subjects for all rows where `not exists (select 1 from article_subjects where article_id = articles.id)`. Out of scope for this plan; flag as follow-up. | Post-launch |
| **Audit table will grow unbounded.** Each chat query writes one row. At 100 queries/day, ~36k rows/year. Not huge for Supabase free tier (500 MB cap) but still worth pruning. | After a few weeks | Add a scheduled `delete from editorial_gate_audit where created_at < now() - interval '90 days'` in a Supabase Edge Function or a manual periodic cleanup. Out of scope here. | Post-launch |
| **Test mocking targets may not match the actual import structure.** The tests patch `chat.gated_editorial_lookup` and `editorial.relevance._search` — those must be the actual import paths in the implementation. | Task 6, 7 | The implementer should verify by running the failing tests first (red), confirming the import error matches expectation, then implementing. If the mock patch path is wrong, the test will pass even when it shouldn't. | During implementation |

---

## Non-Goals

- No LLM-based chunk relevance grading (CRAG-style with Haiku judge). Deferred until evidence shows the cheap gate is missing important articles.
- No cross-encoder reranking (Cohere Rerank, bge-reranker). Same deferral.
- No HyDE-style hypothetical-document expansion. Research showed it's the wrong tool for time-sensitive corpora.
- No per-question dynamic mode classification. The hardcoded `EDITORIAL_RELEVANT_MODES` whitelist is sufficient; we don't need an LLM to decide per-question.
- No changes to the agentic path. It already works via the `search_editorial_content` tool.
- No frontend changes. The `editorial_observation` field flows into the answer text; the existing answer-renderer handles it.
- No automatic pruning of the audit table — manual or post-MVP follow-up.

---

## References

- **CRAG: Corrective Retrieval Augmented Generation** — Yan et al. 2024, arXiv:2401.15884. The canonical paper for retrieval-result relevance gating. Our plan implements the cheap baseline; CRAG's full pipeline is the planned upgrade.
- **Self-RAG** — Asai et al. 2024, ICLR oral, arXiv:2310.11511. Inspiration for the "decide whether to retrieve at all" gate (our `EDITORIAL_RELEVANT_MODES`). We skip the fine-tuning requirement.
- **Solving Freshness in RAG** — Grofsky 2025, arXiv:2509.19376. Source of the simple recency-prior recommendation (`score × exp(-age/half-life)`).
- **HyDE critique** — Yoon et al. 2025, arXiv:2504.14175. Argues HyDE gains often come from training-data leakage; wrong tool for time-sensitive corpora. Justifies our decision to skip HyDE.
- Companion plan: `2026-05-19-counterfactual-race-simulation.md` — separate concern (post-race what-if simulator).
- F1Dash existing modules referenced: `server/editorial/search.py` (the underlying retrieval), `server/editorial/client.py` (postgrest wrapper), `server/chat.py` (`_retrieve_analysis_evidence`, `_try_deterministic_analysis`, both `ANALYSIS_SYSTEM_PROMPT` and `ANSWER_WRITER_SYSTEM_PROMPT` already carry the `editorial_observation` hook from the F33/F21 integration follow-up).
