"""Public /stats page — aggregate-only, no row-level. Cached in-process for 5 min."""

from __future__ import annotations

import time
from typing import Any

import asyncpg


_CACHE_TTL_S = 300
_cache: dict[str, Any] = {"t": 0.0, "html": ""}


_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Axor telemetry — community stats</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {{ font-family: -apple-system, system-ui, sans-serif; max-width: 720px;
            margin: 4rem auto; padding: 0 1.5rem; color: #111; line-height: 1.55; }}
    h1 {{ font-size: 1.4rem; margin: 0 0 0.3rem; }}
    .muted {{ color: #666; font-size: 0.9rem; }}
    .grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 1.2rem; margin: 2rem 0; }}
    .card {{ border: 1px solid #e4e4e4; border-radius: 6px; padding: 1rem 1.2rem; }}
    .big {{ font-size: 1.6rem; font-weight: 600; }}
    .label {{ font-size: 0.85rem; color: #666; text-transform: uppercase; letter-spacing: 0.04em; }}
    .cta {{ margin-top: 2.5rem; padding: 1.2rem; background: #f6f8fa;
            border-radius: 6px; font-size: 0.95rem; }}
    a {{ color: #0366d6; }}
    code {{ background: #f6f8fa; padding: 0.1rem 0.35rem; border-radius: 3px; }}
  </style>
</head>
<body>
  <h1>Axor telemetry — community stats</h1>
  <p class="muted">Anonymized traces from opt-in users. No inputs, no code, no paths.
     <a href="https://github.com/Bucha11/axor-core/blob/main/heuristic-changelog.md">heuristic changelog</a></p>

  <div class="grid">
    <div class="card"><div class="label">Records this month</div><div class="big">{records_this_month:,}</div></div>
    <div class="card"><div class="label">Unique contributors*</div><div class="big">{contributors:,}</div></div>
    <div class="card"><div class="label">Top signal</div><div class="big">{top_signal}</div><div class="muted">{top_signal_pct:.1f}% of tasks</div></div>
    <div class="card"><div class="label">Policy-adjusted rate</div><div class="big">{adjusted_rate:.1f}%</div></div>
  </div>
  <p class="muted">* by hashed IP bucket — no identification possible, rate-limit use only</p>

  <div class="cta">
    <strong>Your traces improve the free heuristic classifier.</strong><br>
    Monthly tuning deltas ship in axor-core updates. Enable with
    <code>AXOR_TELEMETRY=on</code> or <code>python -m axor_telemetry consent</code>.
  </div>
</body>
</html>"""


_AGGREGATE_SQL = """
WITH monthly AS (
    SELECT * FROM records
    WHERE received_at >= date_trunc('month', now())
),
by_signal AS (
    SELECT payload->>'signal_chosen' AS sig, count(*) AS n
    FROM monthly GROUP BY 1 ORDER BY n DESC
)
SELECT
    (SELECT count(*) FROM monthly)                                              AS n_records,
    (SELECT count(DISTINCT client_ip_hash) FROM monthly)                        AS n_contributors,
    (SELECT sig FROM by_signal LIMIT 1)                                         AS top_signal,
    (SELECT n FROM by_signal LIMIT 1)                                           AS top_signal_n,
    (SELECT count(*) FROM monthly WHERE (payload->>'policy_adjusted')::boolean) AS n_adjusted
"""


async def _aggregate(pool: asyncpg.Pool) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(_AGGREGATE_SQL)
    n = row["n_records"] or 0
    top_n = row["top_signal_n"] or 0
    return {
        "records_this_month": n,
        "contributors": row["n_contributors"] or 0,
        "top_signal": row["top_signal"] or "—",
        "top_signal_pct": (top_n / n * 100) if n else 0.0,
        "adjusted_rate": ((row["n_adjusted"] or 0) / n * 100) if n else 0.0,
    }


async def render(pool: asyncpg.Pool) -> str:
    now = time.time()
    if now - _cache["t"] < _CACHE_TTL_S and _cache["html"]:
        return _cache["html"]
    data = await _aggregate(pool)
    html = _TEMPLATE.format(**data)
    _cache["t"] = now
    _cache["html"] = html
    return html
