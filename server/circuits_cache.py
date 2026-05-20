import time

from f1_data import get_circuits

_circuits_cache: list[dict] = []
_circuits_cache_time: float = 0.0
_CIRCUITS_CACHE_TTL = 3600  # 1 hour


def _cached_circuits() -> list[dict]:
    global _circuits_cache, _circuits_cache_time
    if not _circuits_cache or time.time() - _circuits_cache_time > _CIRCUITS_CACHE_TTL:
        try:
            _circuits_cache = get_circuits()
            _circuits_cache_time = time.time()
        except Exception:
            pass
    return _circuits_cache
