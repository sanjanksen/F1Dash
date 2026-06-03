import time

from f1_data import get_circuits, active_season

_CIRCUITS_CACHE_TTL = 3600  # 1 hour

# Season-keyed cache: year -> (fetched_at, circuits). Lives here (not f1_data)
# so resolve_round can be imported by f1_data callers without a cycle:
# f1_data imports resolve_round LOCALLY (inside functions), keeping this
# top-level dependency one-directional.
_by_year: dict[int, tuple[float, list[dict]]] = {}


def _cached_circuits(year: int | None = None) -> list[dict]:
    y = year or active_season()
    now = time.time()
    hit = _by_year.get(y)
    if hit and now - hit[0] <= _CIRCUITS_CACHE_TTL:
        return hit[1]
    try:
        data = get_circuits(y)
        _by_year[y] = (now, data)
        return data
    except Exception:
        return hit[1] if hit else []


def clear_circuits_cache() -> None:
    _by_year.clear()


def resolve_round(year: int, *, country: str | None = None,
                  event_name: str | None = None) -> int | None:
    for c in _cached_circuits(year):
        if country and (c.get("country", "").lower() == country.lower()):
            return c.get("round")
        if event_name and event_name.lower() in (c.get("event_name", "").lower()):
            return c.get("round")
    return None
