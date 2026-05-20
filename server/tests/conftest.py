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
