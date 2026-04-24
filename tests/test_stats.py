"""Unit tests for app.stats rendering + cache behavior."""
from __future__ import annotations

import time

import pytest

from app import stats as stats_mod


def _sample(**overrides):
    base = {
        "n_all": 12543, "n_month": 1024, "n_day": 127,
        "contrib_month": 47, "contrib_day": 12,
        "top_signal": "focused_generative", "top_signal_pct": 34.2,
        "adjust_rate_pct": 11.5, "avg_confidence_pct": 72.3,
        "latest_version": "0.3.0",
        "signal_dist": [
            ("focused_generative", 350),
            ("focused_readonly",   300),
            ("moderate_mutative",  200),
        ],
    }
    base.update(overrides)
    return base


def test_render_with_data_embeds_counts():
    html = stats_mod._render_html(_sample())
    assert "12 543" in html         # all-time
    assert "1 024" in html          # month
    assert "focused_generative" in html
    assert "34.2%" in html          # top signal pct
    assert "72%" in html            # avg confidence rounded


def test_render_empty_db_shows_placeholder():
    html = stats_mod._render_html(_sample(
        n_all=0, n_month=0, n_day=0,
        contrib_month=0, contrib_day=0,
        top_signal="—", top_signal_pct=0.0,
        adjust_rate_pct=0.0, avg_confidence_pct=0.0,
        latest_version="—", signal_dist=[],
    ))
    assert "No signals recorded yet" in html


def test_render_escapes_signal_names():
    """Defense in depth: server validates signal_chosen but don't trust it for HTML."""
    html = stats_mod._render_html(_sample(
        top_signal="<script>alert(1)</script>",
        signal_dist=[("<img src=x onerror=1>", 5)],
    ))
    assert "<script>alert(1)</script>" not in html  # escaped
    assert "&lt;script&gt;" in html
    assert "<img src=x onerror=1>" not in html
    assert "&lt;img src=x onerror=1&gt;" in html


def test_fmt_uses_non_breaking_spaces():
    assert stats_mod._fmt(0) == "0"
    assert stats_mod._fmt(1000) == "1 000"
    assert stats_mod._fmt(1234567) == "1 234 567"


async def test_cache_honors_ttl(monkeypatch):
    """Second call within TTL hits cache without touching the pool."""
    call_count = {"n": 0}

    async def fake_aggregate(_pool):
        call_count["n"] += 1
        return _sample()

    stats_mod._reset_cache_for_tests()
    monkeypatch.setattr(stats_mod, "_aggregate", fake_aggregate)

    await stats_mod.render(pool=None)
    await stats_mod.render(pool=None)
    await stats_mod.render(pool=None)

    assert call_count["n"] == 1


async def test_cache_invalidated_after_ttl(monkeypatch):
    """After the TTL expires, the aggregate is re-queried."""
    call_count = {"n": 0}

    async def fake_aggregate(_pool):
        call_count["n"] += 1
        return _sample()

    stats_mod._reset_cache_for_tests()
    monkeypatch.setattr(stats_mod, "_aggregate", fake_aggregate)

    await stats_mod.render(pool=None)
    assert call_count["n"] == 1

    # Force expiry by aging the cache timestamp past the TTL.
    stats_mod._cache["t"] = time.time() - (stats_mod._CACHE_TTL_S + 10)

    await stats_mod.render(pool=None)
    assert call_count["n"] == 2


async def test_aggregate_math_from_fake_pool():
    """Test the _aggregate layer directly with a scripted fake pool."""

    class _Conn:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            pass
        async def fetchrow(self, _):
            return {
                "n_all": 500, "n_month": 300, "n_day": 50,
                "n_contributors_month": 12, "n_contributors_day": 5,
                "n_adjusted_month": 30, "avg_conf_month": 0.75,
                "latest_version": "0.3.0",
            }
        async def fetch(self, _):
            return [
                {"sig": "focused_generative", "n": 150},
                {"sig": "focused_readonly",   "n": 100},
                {"sig": "moderate_mutative",  "n": 50},
            ]

    class _Pool:
        def acquire(self):
            return _Conn()

    data = await stats_mod._aggregate(_Pool())
    assert data["n_month"] == 300
    assert data["top_signal"] == "focused_generative"
    assert abs(data["top_signal_pct"] - 50.0) < 0.01    # 150/300 = 50%
    assert abs(data["adjust_rate_pct"] - 10.0) < 0.01   # 30/300 = 10%
    assert abs(data["avg_confidence_pct"] - 75.0) < 0.01


async def test_aggregate_zero_division_safe():
    class _Conn:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        async def fetchrow(self, _):
            return {
                "n_all": 0, "n_month": 0, "n_day": 0,
                "n_contributors_month": 0, "n_contributors_day": 0,
                "n_adjusted_month": 0, "avg_conf_month": 0.0,
                "latest_version": None,
            }
        async def fetch(self, _):
            return []

    class _Pool:
        def acquire(self): return _Conn()

    data = await stats_mod._aggregate(_Pool())
    assert data["adjust_rate_pct"] == 0.0
    assert data["top_signal_pct"] == 0.0
    assert data["top_signal"] == "—"
    assert data["latest_version"] == "—"
