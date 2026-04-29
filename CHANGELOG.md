# Changelog

## 0.2.0 — 2026-04-29

### Added
- **`X-Axor-Token` authentication on `/v1/records`.** Shared secret read
  from `INGEST_SHARED_SECRET` per request (rotation via env restart),
  compared in constant time with `hmac.compare_digest`. Requests
  without a valid token get HTTP 401.
- Lifespan logger emits a WARNING at startup when
  `INGEST_SHARED_SECRET` is not set, so deployments don't accidentally
  ship anonymous-write.
- Tests covering the auth-on / auth-off / wrong-token paths.

### Fixed
- **Cold-start connection pool race.** Two requests hitting the API
  before `lifespan.init_pool()` finished could both call
  `asyncpg.create_pool()`; the second overwrote the first, leaking
  the first pool's connections. Fixed with a module-level
  `asyncio.Lock` around init and close, with a re-check inside the
  lock.

## 0.1.0 — 2026-04-?? (pre-release)

Initial server.

### Added
- FastAPI ingest endpoint `POST /v1/records` (Postgres + asyncpg).
- Public `/stats` HTML page.
- slowapi rate limit (60/min/IP).
- Caddy TLS termination + Grafana dashboard wired through Docker
  Compose.
- Schema bootstrap via `migrations/001_init.sql`, mounted into the
  postgres container via `docker-entrypoint-initdb.d`.
- Retro-terminal landing page at the apex.

### Notes
- No migrations table — schema changes after first deploy require a
  manual `psql` apply.
- Server is deployed via Docker Compose; not published to PyPI.
