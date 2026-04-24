"""Public /stats page — aggregate-only, no row-level. 5-minute in-process cache."""

from __future__ import annotations

import html
import json
import time
from typing import Any

import asyncpg


_CACHE_TTL_S = 300
_cache: dict[str, Any] = {"t": 0.0, "html": ""}


# ── Aggregate query ──────────────────────────────────────────────────────────
#
# One round trip, multiple scalars + one list. Uses btree indexes:
#   idx_records_received_at  → month/24h filters
#   idx_records_signal       → GROUP BY payload->>'signal_chosen'
#   idx_records_adjusted     → partial index for adjusted=true

_SCALARS_SQL = """
WITH monthly AS (
    SELECT * FROM records WHERE received_at >= date_trunc('month', now())
),
daily AS (
    SELECT * FROM records WHERE received_at >= now() - interval '24 hours'
)
SELECT
    (SELECT count(*)                                  FROM records)            AS n_all,
    (SELECT count(*)                                  FROM monthly)            AS n_month,
    (SELECT count(*)                                  FROM daily)              AS n_day,
    (SELECT count(DISTINCT client_ip_hash)            FROM monthly)            AS n_contributors_month,
    (SELECT count(DISTINCT client_ip_hash)            FROM daily)              AS n_contributors_day,
    (SELECT count(*) FROM monthly WHERE (payload->>'policy_adjusted')::boolean) AS n_adjusted_month,
    (SELECT coalesce(avg((payload->>'confidence')::float), 0) FROM monthly)    AS avg_conf_month,
    (SELECT max(axor_version) FROM records)                                    AS latest_version
"""


_SIGNAL_DIST_SQL = """
SELECT payload->>'signal_chosen' AS sig, count(*) AS n
FROM records
WHERE received_at >= date_trunc('month', now())
GROUP BY 1
ORDER BY n DESC
LIMIT 10
"""


async def _aggregate(pool: asyncpg.Pool) -> dict:
    async with pool.acquire() as conn:
        scalars = await conn.fetchrow(_SCALARS_SQL)
        dist    = await conn.fetch(_SIGNAL_DIST_SQL)

    n_month = scalars["n_month"] or 0
    dist_rows = [(r["sig"], r["n"]) for r in dist]
    top_signal = dist_rows[0][0] if dist_rows else "—"
    top_pct    = (dist_rows[0][1] / n_month * 100) if n_month and dist_rows else 0.0

    return {
        "n_all":               scalars["n_all"] or 0,
        "n_month":             n_month,
        "n_day":               scalars["n_day"] or 0,
        "contrib_month":       scalars["n_contributors_month"] or 0,
        "contrib_day":         scalars["n_contributors_day"] or 0,
        "top_signal":          top_signal,
        "top_signal_pct":      top_pct,
        "adjust_rate_pct":     ((scalars["n_adjusted_month"] or 0) / n_month * 100) if n_month else 0.0,
        "avg_confidence_pct":  float(scalars["avg_conf_month"] or 0) * 100,
        "latest_version":      scalars["latest_version"] or "—",
        "signal_dist":         dist_rows,
    }


# ── HTML ─────────────────────────────────────────────────────────────────────
#
# Single-file, no JS build. Plotly from CDN for one chart. Everything else
# is inline SVG-free plain CSS so page weight stays under 400KB total.

_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Axor community telemetry</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="Anonymized classifier signals from opt-in Axor users. No task text, no file paths, no user IDs — ever.">
  <style>
    :root {{
      --text: #0d1117;
      --muted: #586069;
      --border: #e4e6eb;
      --accent: #1f6feb;
      --bg-card: #ffffff;
      --bg-soft: #f6f8fa;
      --good: #1a7f37;
      --warn: #bf8700;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
      max-width: 840px; margin: 3rem auto; padding: 0 1.5rem;
      color: var(--text); line-height: 1.55; background: #fafbfc;
    }}
    header {{ border-bottom: 1px solid var(--border); padding-bottom: 1.2rem; margin-bottom: 2rem; }}
    h1 {{ font-size: 1.5rem; margin: 0 0 0.25rem; letter-spacing: -0.01em; }}
    h2 {{ font-size: 1rem; margin: 2.5rem 0 0.8rem; text-transform: uppercase;
          letter-spacing: 0.05em; color: var(--muted); font-weight: 600; }}
    .muted {{ color: var(--muted); font-size: 0.9rem; }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    code {{ background: var(--bg-soft); padding: 0.12rem 0.4rem; border-radius: 4px;
            font-size: 0.88em; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}

    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 0.9rem; }}
    .card {{ background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px;
             padding: 0.9rem 1.1rem; min-width: 0; overflow: hidden; }}
    .card .label {{ font-size: 0.78rem; color: var(--muted);
                    text-transform: uppercase; letter-spacing: 0.04em; }}
    .card .big {{ font-size: 1.6rem; font-weight: 600; margin-top: 0.2rem; line-height: 1.15;
                  overflow-wrap: anywhere; word-break: break-word; }}
    .card .big.long {{ font-size: clamp(0.95rem, 2.4vw, 1.25rem); }}
    .card .sub {{ font-size: 0.85rem; color: var(--muted); margin-top: 0.1rem; }}

    #signal-chart {{ width: 100%; height: 340px; }}

    .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; }}
    @media (max-width: 600px) {{ .two-col {{ grid-template-columns: 1fr; }} }}
    .col-title {{ font-weight: 600; margin-bottom: 0.4rem; }}
    ul.checks {{ margin: 0; padding-left: 0; list-style: none; }}
    ul.checks li {{ padding: 0.25rem 0; }}
    .yes::before {{ content: "✓  "; color: var(--good); font-weight: 700; }}
    .no::before  {{ content: "✗  "; color: #cf222e; font-weight: 700; }}

    .cta {{ margin-top: 2.5rem; padding: 1.2rem 1.4rem; background: var(--bg-soft);
            border-left: 3px solid var(--accent); border-radius: 4px; }}
    .cta p {{ margin: 0.4rem 0; }}

    footer {{ margin-top: 3rem; padding-top: 1.2rem; border-top: 1px solid var(--border);
              font-size: 0.85rem; color: var(--muted); display: flex; justify-content: space-between;
              flex-wrap: wrap; gap: 0.5rem; }}
  </style>
</head>
<body>
  <header>
    <h1>Axor community telemetry</h1>
    <p class="muted">Anonymized classifier signals from opt-in users.
       No task text, no file paths, no user IDs — ever.
       <a href="{contract_url}">Data contract</a> · <a href="{changelog_url}">Heuristic changelog</a>
    </p>
  </header>

  <h2>This month</h2>
  <div class="grid">
    <div class="card">
      <div class="label">Records</div>
      <div class="big">{n_month_fmt}</div>
      <div class="sub">{n_day_fmt} in the last 24h</div>
    </div>
    <div class="card">
      <div class="label">Contributors*</div>
      <div class="big">{contrib_month_fmt}</div>
      <div class="sub">{contrib_day_fmt} active (24h)</div>
    </div>
    <div class="card">
      <div class="label">Top signal</div>
      <div class="big long">{top_signal}</div>
      <div class="sub">{top_signal_pct:.1f}% of tasks</div>
    </div>
    <div class="card">
      <div class="label">Avg confidence</div>
      <div class="big">{avg_confidence_pct:.0f}%</div>
      <div class="sub">Higher = heuristic sure</div>
    </div>
    <div class="card">
      <div class="label">Policy-adjusted</div>
      <div class="big">{adjust_rate_pct:.1f}%</div>
      <div class="sub">Lower = classifier right</div>
    </div>
    <div class="card">
      <div class="label">All-time</div>
      <div class="big">{n_all_fmt}</div>
      <div class="sub">Client v{latest_version}</div>
    </div>
  </div>
  <p class="muted" style="margin-top:0.6rem"><small>* by SHA-256 IP-bucket hash; no identification, used for rate-limit only</small></p>

  <h2>Signal distribution (this month, top 10)</h2>
  <div id="signal-chart" aria-label="Horizontal bar chart of signal counts"></div>

  <h2>What gets collected</h2>
  <div class="two-col">
    <div>
      <div class="col-title">Sent</div>
      <ul class="checks">
        <li class="yes">Chosen signal (e.g. <code>focused_generative</code>)</li>
        <li class="yes">Classifier name + confidence (0–1)</li>
        <li class="yes">128-int MinHash fingerprint of the input</li>
        <li class="yes">Tokens spent this turn</li>
        <li class="yes">Whether policy was corrected mid-run</li>
        <li class="yes"><code>axor_version</code> of your client</li>
      </ul>
    </div>
    <div>
      <div class="col-title">Not sent</div>
      <ul class="checks">
        <li class="no">Raw task text</li>
        <li class="no">File contents, paths, tool arguments</li>
        <li class="no">API keys, env vars, secrets</li>
        <li class="no">User ID, session ID, hostname</li>
        <li class="no">IP address (only SHA-256 hash truncated to 16 chars)</li>
      </ul>
    </div>
  </div>

  <div class="cta">
    <p><strong>Your traces improve the free heuristic classifier.</strong>
       Monthly tuning deltas ship in <a href="{core_repo}">axor-core</a> updates.</p>
    <p>Opt in:</p>
    <p>
      &bull; Env: <code>AXOR_TELEMETRY=local</code>
      (or <code>remote</code> to also ship batches)
    </p>
    <p>
      &bull; CLI: <code>python -m axor_telemetry consent</code>
    </p>
    <p>
      &bull; LangChain: <code>AxorMiddleware(telemetry="local")</code>
    </p>
  </div>

  <footer>
    <span>Server source: <a href="{server_repo}">axor-telemetry-server</a></span>
    <span>Refreshed at {timestamp}</span>
  </footer>

  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>
  <script>
    (function() {{
      var data = {chart_json};
      if (!data.labels.length) {{
        document.getElementById('signal-chart').innerHTML =
          '<p class="muted" style="text-align:center;padding:4rem 0">No signals recorded yet. Opt in to contribute the first.</p>';
        return;
      }}
      Plotly.newPlot('signal-chart', [{{
        type: 'bar',
        orientation: 'h',
        x: data.counts,
        y: data.labels,
        marker: {{color: '#1f6feb'}},
        hovertemplate: '%{{y}}: %{{x}} records<extra></extra>',
      }}], {{
        margin: {{t: 10, r: 20, b: 40, l: 180}},
        paper_bgcolor: 'transparent',
        plot_bgcolor: 'transparent',
        font: {{family: '-apple-system, system-ui, sans-serif', color: '#0d1117'}},
        xaxis: {{gridcolor: '#e4e6eb', title: 'records'}},
        yaxis: {{autorange: 'reversed'}},
      }}, {{displayModeBar: false, responsive: true}});
    }})();
  </script>
</body>
</html>"""


# Repo URLs are parameters so forks don't have to patch source.
_CORE_REPO     = "https://github.com/Bucha11/axor-core"
_SERVER_REPO   = "https://github.com/Bucha11/axor-telemetry-server"
_CONTRACT_URL  = "https://github.com/Bucha11/axor-core/blob/main/axor_core/contracts/trace.py"
_CHANGELOG_URL = "https://github.com/Bucha11/axor-core/blob/main/heuristic-changelog.md"


def _fmt(n: int) -> str:
    """Thousands-separated integer."""
    return f"{n:,}".replace(",", " ")


def _render_html(data: dict) -> str:
    labels = [html.escape(sig) for sig, _ in data["signal_dist"]]
    counts = [n for _, n in data["signal_dist"]]
    chart_json = json.dumps({"labels": labels, "counts": counts})

    return _TEMPLATE.format(
        n_all_fmt          = _fmt(data["n_all"]),
        n_month_fmt        = _fmt(data["n_month"]),
        n_day_fmt          = _fmt(data["n_day"]),
        contrib_month_fmt  = _fmt(data["contrib_month"]),
        contrib_day_fmt    = _fmt(data["contrib_day"]),
        top_signal         = html.escape(str(data["top_signal"])),
        top_signal_pct     = data["top_signal_pct"],
        avg_confidence_pct = data["avg_confidence_pct"],
        adjust_rate_pct    = data["adjust_rate_pct"],
        latest_version     = html.escape(str(data["latest_version"])),
        chart_json         = chart_json,
        core_repo          = _CORE_REPO,
        server_repo        = _SERVER_REPO,
        contract_url       = _CONTRACT_URL,
        changelog_url      = _CHANGELOG_URL,
        timestamp          = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
    )


async def render(pool: asyncpg.Pool) -> str:
    now = time.time()
    if now - _cache["t"] < _CACHE_TTL_S and _cache["html"]:
        return _cache["html"]
    data = await _aggregate(pool)
    html_out = _render_html(data)
    _cache["t"] = now
    _cache["html"] = html_out
    return html_out


def _reset_cache_for_tests() -> None:
    """Let tests bypass the TTL without touching module globals directly."""
    _cache["t"] = 0.0
    _cache["html"] = ""
