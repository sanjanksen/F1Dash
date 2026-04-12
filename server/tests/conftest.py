# server/tests/conftest.py
import sys
import os
from unittest.mock import MagicMock

# Ensure server/ is on the path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Stub out heavy dependencies before any test module imports them.
# This prevents FastF1 and requests from making real network calls during tests.
for _mod in ('fastf1', 'fastf1.Cache'):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()
