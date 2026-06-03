"""B6: multi-year integration + concurrency smokes.

The concurrency test runs always — it proves the per-future copy_context season
isolation in chat._execute_analysis_tool_calls has no cross-thread leakage. The
era-correctness end-to-end smokes need live LLM + data, so they are gated behind
RUN_INTEGRATION=1.
"""
import os
import time

import pytest


def test_concurrent_different_year_tool_calls_have_no_season_leak(monkeypatch):
    """Two simultaneous tool calls with different years, run through the real
    ThreadPoolExecutor + copy_context path, must each observe THEIR OWN active
    season — no leakage, no RuntimeError."""
    import chat
    import tools
    import f1_data

    def fake_inner(name, args):
        # Sleep so both calls are in-flight at once, widening any race window.
        time.sleep(0.05)
        return {"season": f1_data.active_season()}

    # Replace only the inner dispatch — the real execute_tool still sets/resets
    # the season ContextVar from each call's `year`, which is what we're testing.
    monkeypatch.setattr(tools, "_execute_tool_inner", fake_inner)

    calls = [
        ("get_race_results", {"year": 2024}),
        ("get_race_results", {"year": 2026}),
        ("get_race_results", {"year": 2022}),
    ]
    out = chat._execute_analysis_tool_calls(calls)

    by_year = {item["args"]["year"]: item["result"]["season"] for item in out}
    assert by_year == {2024: 2024, 2026: 2026, 2022: 2022}, (
        f"each call must see its own season, got {by_year}"
    )
    # And the ambient season is restored afterward (no leaked token).
    assert f1_data.active_season() == f1_data.CURRENT_YEAR


# ── INTEGRATION-gated era-correctness smokes (live LLM + data) ───────────────

_INTEGRATION = pytest.mark.skipif(
    not os.getenv("RUN_INTEGRATION"),
    reason="set RUN_INTEGRATION=1 to run live multi-year era smokes",
)


@_INTEGRATION
def test_2024_race_story_uses_drs_not_2026_mechanisms():
    from chat import answer_f1_payload
    out = answer_f1_payload("How did Verstappen's race go at Monza in 2024?")
    text = (out.get("answer") or "").lower()
    assert "override" not in text and "active aero" not in text and "z-mode" not in text


@_INTEGRATION
def test_cross_year_2024_vs_2025_returns_both_seasons():
    from chat import answer_f1_payload
    out = answer_f1_payload("Compare Verstappen's 2024 and 2025 seasons")
    text = (out.get("answer") or "")
    assert "2024" in text and "2025" in text
