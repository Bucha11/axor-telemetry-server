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

### One-time server prep

SSH in as `root` (or a sudoer) and run:

```bash
apt update && apt upgrade -y
apt install -y fail2ban ufw
curl -fsSL https://get.docker.com | sh
ufw allow 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp
ufw --force enable
```

### Local prep

```bash
cp .env.example .env
# Edit .env:
#   POSTGRES_PASSWORD=$(openssl rand -hex 32)
#   GRAFANA_ADMIN_PASSWORD=$(openssl rand -hex 16)
#   TELEMETRY_DOMAIN=telemetry.useaxor.net
#   GRAFANA_DOMAIN=grafana.useaxor.net
#   ACME_EMAIL=you@example.com
```

### DNS (before deploy — Caddy's ACME needs it)

In your DNS provider, add A-records pointing at the VPS IP:

| Name         | Type | Value            | Proxy |
|--------------|------|------------------|-------|
| `telemetry`  | A    | `<your VPS IP>`  | off   |
| `grafana`    | A    | `<your VPS IP>`  | off   |

If you're behind Cloudflare, keep proxy OFF (gray cloud) so Caddy can
complete the Let's Encrypt HTTP-01 challenge.

### Deploy

```bash
SERVER=root@<your VPS IP> ./deploy.sh
```

The script rsyncs the repo to `/srv/axor-telemetry` on the server, pulls
images, builds the api, and brings up the stack. Caddy requests TLS certs
on first boot — watch the caddy container logs if something goes wrong.

### Verify

```bash
curl -sSf https://telemetry.useaxor.net/healthz
# → "ok"
```

Grafana:

```
https://grafana.useaxor.net/
# user: admin
# pass: the GRAFANA_ADMIN_PASSWORD you set in .env
```

### Other commands

```bash
SERVER=root@<ip> ./deploy.sh logs     # tail api + caddy logs
SERVER=root@<ip> ./deploy.sh ps       # container status
SERVER=root@<ip> ./deploy.sh down     # stop the stack (keeps volumes)
```

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
