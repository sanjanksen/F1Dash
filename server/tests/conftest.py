# server/tests/conftest.py
import sys
import os
from unittest.mock import MagicMock

import pytest

# Ensure server/ is on the path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Stub out heavy dependencies before any test module imports them.
for _mod in ('fastf1', 'fastf1.Cache'):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

# Prevent accidental real network calls in tests
if 'requests' not in sys.modules:
    sys.modules['requests'] = MagicMock()


@pytest.fixture(autouse=True)
def reset_resolver_caches():
    """Reset resolver module-level caches before each test to prevent leakage."""
    import resolver
    import circuits_cache
    circuits_cache._circuits_cache = []
    circuits_cache._circuits_cache_time = 0.0
    resolver._drivers_cache = []
    resolver._drivers_cache_time = 0.0
    yield
    circuits_cache._circuits_cache = []
    circuits_cache._circuits_cache_time = 0.0
    resolver._drivers_cache = []
    resolver._drivers_cache_time = 0.0


@pytest.fixture
def reset_feature_registry():
    """Snapshot FEATURE_REGISTRY + clear cached features.* modules, then restore.

    discover_features() uses importlib.import_module which is a no-op when the
    module is already in sys.modules. Tests that need discover_features() to
    actually re-run @register_feature decorators must drop the cached module.
    """
    from features.base import FEATURE_REGISTRY
    saved = dict(FEATURE_REGISTRY)
    FEATURE_REGISTRY.clear()
    cleared = [
        m for m in list(sys.modules)
        if m.startswith("features.") and m not in ("features.base", "features.registry")
    ]
    for m in cleared:
        sys.modules.pop(m, None)
    yield
    FEATURE_REGISTRY.clear()
    FEATURE_REGISTRY.update(saved)
