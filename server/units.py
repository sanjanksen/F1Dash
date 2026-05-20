"""Unit conversion helpers. Convert at boundaries; keep kph internally."""

KPH_PER_MS = 3.6


def ms_to_kph(value):
    if value is None:
        return None
    return value * KPH_PER_MS


def kph_to_ms(value):
    if value is None:
        return None
    return value / KPH_PER_MS


def ms_to_kph_series(values):
    return [ms_to_kph(v) for v in values]
