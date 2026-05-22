"""Feature discovery, candidate filtering, and relevance ranking."""
from __future__ import annotations

import importlib
import logging
import pkgutil
import time
from typing import Iterable

from features.base import Feature, FEATURE_REGISTRY, audit_log

logger = logging.getLogger(__name__)


def discover_features() -> int:
    """Walk the `features` package and import every submodule.

    Each module's @register_feature decorator runs as a side effect of
    import, populating FEATURE_REGISTRY. Idempotent — re-importing is a
    no-op because the registry rejects duplicate names.

    Returns the number of features in the registry after discovery.
    """
    import features  # the package itself
    for module_info in pkgutil.walk_packages(features.__path__, prefix="features."):
        if module_info.name in ("features.base", "features.registry"):
            continue
        if module_info.ispkg:
            continue
        try:
            importlib.import_module(module_info.name)
        except Exception as e:
            logger.warning(
                "discover_features: failed to import %s: %s",
                module_info.name, type(e).__name__,
            )
    return len(FEATURE_REGISTRY)


def _resolved_entity_types(resolved: dict | None) -> set[str]:
    """Map a resolver output to the set of entity-type strings present.

    Conventions:
        - 2+ drivers -> "pair_of_drivers"
        - 1+ drivers -> "driver"
        - team present -> "team"
        - circuit_slug present -> "circuit"
        - round_number present + session_type in {R, S} -> "race_session"
        - round_number present + session_type in {Q, SQ} -> "quali_session"
        - round_number present + session_type in {FP1, FP2, FP3} -> "practice_session"
        - any round_number -> "session"
        - lap_number present -> "lap"
    """
    if not resolved:
        return set()
    types: set[str] = set()
    drivers = resolved.get("drivers") or []
    if len(drivers) >= 2:
        types.add("pair_of_drivers")
    if len(drivers) >= 1:
        types.add("driver")
    if resolved.get("team"):
        types.add("team")
    if resolved.get("circuit_slug"):
        types.add("circuit")
    session = (resolved.get("session_type") or "").upper()
    if resolved.get("round_number"):
        if session in ("R", "S"):
            types.add("race_session")
        elif session in ("Q", "SQ"):
            types.add("quali_session")
        elif session in ("FP1", "FP2", "FP3"):
            types.add("practice_session")
        types.add("session")
    if resolved.get("lap_number") is not None:
        types.add("lap")
    return types


def candidates_for(resolved: dict | None) -> list[Feature]:
    """Return features whose applies_to is satisfied by the resolved entities."""
    types = _resolved_entity_types(resolved)
    out: list[Feature] = []
    for feat in FEATURE_REGISTRY.values():
        if not feat.applies_to:
            out.append(feat)
            continue
        if all(req in types for req in feat.applies_to):
            out.append(feat)
    return out


def features_for_mode(mode: str | None, resolved: dict | None) -> list[Feature]:
    """Registry-driven mode->features lookup.

    Returns features whose triggered_by_modes contains `mode` AND whose
    applies_to is satisfied by the resolved entity types. Replaces the
    hardcoded mode->tools dict in chat.py's _build_analysis_plan.

    Returns empty list if mode is None/falsy, unknown, or no features match.
    """
    if not mode:
        return []
    types = _resolved_entity_types(resolved)
    out: list[Feature] = []
    for feat in FEATURE_REGISTRY.values():
        if mode not in feat.triggered_by_modes:
            continue
        if feat.applies_to and not all(req in types for req in feat.applies_to):
            continue
        out.append(feat)
    return out


def rank_by_relevance(
    question: str,
    resolved: dict | None,
    candidates: Iterable[Feature],
) -> list[tuple[Feature, float]]:
    """Ask each candidate is_relevant_for, return [(feature, score)] sorted desc.

    Scores are clamped to [0.0, 1.0]. Predicate exceptions are caught and
    treated as 0.0 (skip the feature).
    """
    scored: list[tuple[Feature, float]] = []
    for feat in candidates:
        try:
            raw = float(feat.is_relevant_for(question, resolved))
        except Exception as e:
            logger.warning(
                "is_relevant_for raised for %s: %s",
                feat.name, type(e).__name__,
            )
            raw = 0.0
        score = max(0.0, min(1.0, raw))
        scored.append((feat, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def run_pipeline(
    question: str,
    resolved: dict | None,
    args_by_feature: dict[str, dict] | None = None,
    threshold: float = 0.5,
) -> list[tuple[Feature, dict, dict | None]]:
    """End-to-end registry pipeline: candidates → rank → execute → widget gate → audit.

    Returns one (feature, execute_result, widget_or_none) per feature that
    cleared applies_to AND scored at or above `threshold`. The audit log is
    populated as a side effect for both fired and skipped features.

    feature.execute() exceptions are caught — the entry's result becomes
    {"available": False, "error": <ExceptionType>} and the widget gate
    decides whether to emit a widget for it (usually False).
    """
    args_by_feature = args_by_feature or {}
    out: list[tuple[Feature, dict, dict | None]] = []

    cands = candidates_for(resolved)
    for feat, score in rank_by_relevance(question, resolved, cands):
        if score < threshold:
            audit_log(
                feature_name=feat.name,
                question=question,
                applies_to_passed=True,
                relevance_score=score,
                executed=False,
                widget_emitted=False,
                duration_ms=0,
            )
            continue

        args = args_by_feature.get(feat.name, {})
        t0 = time.time()
        try:
            result = feat.execute(**args)
        except Exception as e:
            logger.warning(
                "run_pipeline: feature %s execute() raised %s",
                feat.name, type(e).__name__,
            )
            result = {"available": False, "error": type(e).__name__}
        duration_ms = int((time.time() - t0) * 1000)

        try:
            show = feat.should_show_widget(result)
        except Exception as e:
            logger.warning(
                "run_pipeline: feature %s should_show_widget raised %s",
                feat.name, type(e).__name__,
            )
            show = False

        widget = None
        if show:
            try:
                widget = feat.make_widget(result)
            except Exception as e:
                logger.warning(
                    "run_pipeline: feature %s make_widget raised %s",
                    feat.name, type(e).__name__,
                )
                widget = None

        audit_log(
            feature_name=feat.name,
            question=question,
            applies_to_passed=True,
            relevance_score=score,
            executed=True,
            widget_emitted=widget is not None,
            duration_ms=duration_ms,
        )
        out.append((feat, result, widget))

    return out
