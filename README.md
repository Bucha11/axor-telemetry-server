# axor-telemetry-server

Ingest endpoint + public stats page for opt-in anonymized traces from
axor clients. Stores records in Postgres, exposes a public `/stats` page,
and serves a private Grafana dashboard on a separate subdomain.

## Architecture

```
Caddy (TLS)
  ├─ telemetry.$DOMAIN → FastAPI api
  │                       ├─ POST /v1/records   (ingest, rate-limited)
  │                       ├─ GET  /stats        (public aggregate page)
  │                       └─ GET  /healthz
  └─ grafana.$DOMAIN   → Grafana (private, basic auth)
                          └─ datasource: Postgres

Postgres (JSONB column for payload)
```

## Local development

```bash
cp .env.example .env
docker compose up -d --build
curl http://localhost/healthz                    # via caddy (set TELEMETRY_DOMAIN=localhost in .env for local)
# or, bypass caddy:
docker compose exec api curl localhost:8000/healthz
```

Tests (mocks the DB pool):

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

## Production deploy (Hetzner CX22)

1. Point DNS A-records `telemetry.$DOMAIN` and `grafana.$DOMAIN` at the VPS IP.
2. Copy `.env.example` to `.env`, set strong passwords and real domain.
3. `docker compose up -d`. Caddy auto-provisions TLS via Let's Encrypt.

## What's stored, what isn't

Stored in each record:

- `signal_chosen`, `classifier_used`, `confidence`
- `tokens_spent`, `policy_adjusted`
- `fingerprint` (MinHash or other; opaque integer list)
- `axor_version`, `schema_version`

Not stored anywhere:

- Raw task input
- File paths, code snippets, tool output
- User IP (only sha256[:16] hash for rate-limit bucketing)

See the schema in [`app/schemas.py`](app/schemas.py) — it's the wire contract.

## License

MIT
