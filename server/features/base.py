"""Feature base class + registration decorator.

Each feature is a subclass of Feature with the five-method contract:
    - applies_to: tuple of entity-type strings (cheap broad filter)
    - is_relevant_for(question, resolved) -> float in [0, 1]
    - execute(**args) -> dict (the actual analysis)
    - make_widget(result) -> dict (widget payload)
    - should_show_widget(result) -> bool

Register with @register_feature; the registry is consulted by tools.py
(for execute_tool dispatch) and chat.py (for widget rendering).
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod


FEATURE_REGISTRY: dict[str, "Feature"] = {}


class Feature(ABC):
    """One analytical feature, fully self-contained."""

    name: str  # tool name; MUST be set on subclass
    applies_to: tuple[str, ...] = ()  # entity-type preconditions
    triggered_by_modes: frozenset[str] = frozenset()  # analysis_modes this feature serves
    tool_schema: dict = {}  # JSON schema for the tool's input args
    required_args: tuple[str, ...] = ()  # arg names that must be present
    description: str = ""  # human description for tool registration

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Direct subclasses of Feature must declare a name (string)
        if not hasattr(cls, "name") or not isinstance(getattr(cls, "name", None), str):
            raise TypeError(
                f"Feature subclass {cls.__name__} must set class attribute "
                f"`name` to a string"
            )

    @abstractmethod
    def is_relevant_for(self, question: str, resolved: dict | None) -> float:
        """Return relevance in [0, 1]. >= 0.5 fires by default."""

    @abstractmethod
    def execute(self, **args) -> dict:
        """Run the analysis. Return a dict the analyzer + widget consume."""

    @abstractmethod
    def make_widget(self, result: dict) -> dict:
        """Map the result to a widget payload (type + fields)."""

    @abstractmethod
    def should_show_widget(self, result: dict) -> bool:
        """Decide whether the widget for this result is worth rendering."""


def register_feature(cls):
    """Decorator that registers a Feature subclass in FEATURE_REGISTRY by name.

    Usage:
        @register_feature
        class MiniSectorsFeature(Feature):
            name = "compare_mini_sectors"
            ...
    """
    if not isinstance(cls, type) or not issubclass(cls, Feature):
        raise TypeError(f"@register_feature must decorate a Feature subclass; got {cls!r}")

    if cls.name in FEATURE_REGISTRY:
        raise ValueError(
            f"Feature name {cls.name!r} already registered "
            f"(by {type(FEATURE_REGISTRY[cls.name]).__name__})"
        )

    FEATURE_REGISTRY[cls.name] = cls()  # store instance
    return cls


_AUDIT_LOG: list[dict] = []


def audit_log(**fields) -> None:
    """Append a feature-decision record. Best-effort, never raises.

    Records are kept in-memory for the current process. In production,
    a periodic flush to JSONL would persist them; for hobby-scale this
    is fine.
    """
    try:
        fields["ts"] = time.time()
        _AUDIT_LOG.append(fields)
    except Exception:
        pass  # audit must never break the main flow


def get_audit_log() -> list[dict]:
    return list(_AUDIT_LOG)


def clear_audit_log() -> None:
    _AUDIT_LOG.clear()
