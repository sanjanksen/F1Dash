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

import logging
import math
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from editorial import client as _client

logger = logging.getLogger(__name__)


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
        "question": question[:1000],
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
    use_haiku_grader: bool | None = None,
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

    # CRAG-style Haiku grader. Drops "no" chunks; keeps "yes" verbatim;
    # surfaces "partial" with a flag the analyzer can hedge on.
    use_grader = use_haiku_grader if use_haiku_grader is not None else EDITORIAL_USE_HAIKU_GRADER
    if use_grader and survivors:
        graded = grade_chunks_with_haiku(question, survivors)
        new_survivors = []
        for c in graded:
            grade = c.get("_grade", "no")
            if grade == "no":
                c["_drop_reason"] = "haiku_no"
                continue
            new_survivors.append(c)
        survivors = new_survivors

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
    clean_survivors = []
    for c in survivors:
        clean = {k: v for k, v in c.items() if not k.startswith("_")}
        if c.get("_grade") and c.get("_grade") != "yes":
            # Surface partial-grade so the analyzer hedges (yes is the
            # default — no flag needed).
            clean["grade"] = c["_grade"]
        clean_survivors.append(clean)
    return {"kind": "editorial", "chunks": clean_survivors}


# Feature flag — set EDITORIAL_USE_HAIKU_GRADER=false in env to disable.
# Default ON because the cost is trivial (~$0.001 per query) and the precision
# upgrade over the cheap gate is real per CRAG (Yan et al. 2024).
def _haiku_grader_enabled_by_env() -> bool:
    return os.getenv("EDITORIAL_USE_HAIKU_GRADER", "true").lower() != "false"


EDITORIAL_USE_HAIKU_GRADER: bool = _haiku_grader_enabled_by_env()

# Model + token budget for the grader. Haiku is the right size — fast,
# cheap, instruction-following well enough for a 3-class classifier.
_GRADER_MODEL = "claude-haiku-4-5-20251001"
_GRADER_MAX_TOKENS = 8
_GRADER_MAX_WORKERS = 4

_GRADER_PROMPT = (
    "You judge whether an article snippet is relevant to answering an "
    "F1 question.\n\n"
    "Respond with exactly ONE word — yes, partial, or no — and nothing else.\n"
    "- yes: the snippet directly addresses or strongly informs the question\n"
    "- partial: the snippet is tangentially related but not the primary answer\n"
    "- no: the snippet is off-topic or about a different driver/team/race\n\n"
    "Question: {question}\n\n"
    "Snippet: {snippet}"
)


def _get_anthropic_client():
    """Return a cached anthropic.Anthropic client, or None if no key.
    Separate function so tests can patch it."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
    except ImportError:
        return None
    try:
        return anthropic.Anthropic()
    except Exception:
        return None


def _parse_grade(response_text: str | None) -> str:
    """Map a free-form Haiku response to 'yes' | 'partial' | 'no'.
    Defaults to 'no' on anything we don't recognise — fail safe."""
    if not response_text:
        return "no"
    t = response_text.strip().strip(".!?").lower()
    if "partial" in t:
        return "partial"
    if "yes" in t:
        return "yes"
    return "no"


def _grade_one_chunk(client, question: str, chunk: dict) -> dict:
    """Run one Haiku call. Returns the chunk with _grade added."""
    out = dict(chunk)
    snippet = (chunk.get("chunk_text") or "")[:800]  # cap to keep prompt small
    try:
        response = client.messages.create(
            model=_GRADER_MODEL,
            max_tokens=_GRADER_MAX_TOKENS,
            messages=[{
                "role": "user",
                "content": _GRADER_PROMPT.format(question=question, snippet=snippet),
            }],
        )
        content = response.content
        text = content[0].text if content else None
        out["_grade"] = _parse_grade(text)
    except Exception as e:
        logger.warning("Haiku grader call failed: %s", type(e).__name__)
        out["_grade"] = "no"  # fail safe
    return out


def grade_chunks_with_haiku(question: str, chunks: list[dict]) -> list[dict]:
    """Grade each chunk's relevance to the question via Claude Haiku.

    Returns the chunks with an added `_grade` field in {yes, partial, no}.
    Calls run in parallel. On any per-chunk failure or missing API key,
    the chunk's grade is 'no' — conservative default that keeps the cheap
    gate as the floor when the LLM judge is unavailable.
    """
    if not chunks:
        return []
    client = _get_anthropic_client()
    if client is None:
        # No key / no SDK — degrade to dropping everything, the cheap gate
        # already had its turn; without a judge we don't want to pass
        # marginal chunks through to the analyzer.
        return [{**c, "_grade": "no"} for c in chunks]

    with ThreadPoolExecutor(max_workers=_GRADER_MAX_WORKERS) as ex:
        futures = [ex.submit(_grade_one_chunk, client, question, c) for c in chunks]
        return [f.result() for f in futures]
