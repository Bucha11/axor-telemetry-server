#!/usr/bin/env bash
#
# Deploy axor-telemetry-server to a Hetzner (or any SSH-reachable) VPS.
#
# Usage:
#   SERVER=root@49.12.230.113 ./deploy.sh          # first deploy or update
#   SERVER=root@49.12.230.113 ./deploy.sh logs     # tail api logs
#   SERVER=root@49.12.230.113 ./deploy.sh down     # stop stack
#
# Prerequisites on the server:
#   - Ubuntu 24.04 with Docker + compose plugin installed
#   - Ports 80, 443 open in the host firewall (ufw)
#   - DNS A records for $TELEMETRY_DOMAIN and $GRAFANA_DOMAIN → this server IP
#
# Prerequisites locally:
#   - rsync, ssh
#   - .env file in this directory (copy from .env.example and fill in)
set -euo pipefail

SERVER="${SERVER:-}"
REMOTE_DIR="${REMOTE_DIR:-/srv/axor-telemetry}"

if [[ -z "$SERVER" ]]; then
    echo "error: SERVER env var is required (e.g. SERVER=root@49.12.230.113)" >&2
    exit 1
fi

ACTION="${1:-deploy}"

case "$ACTION" in
    deploy)
        if [[ ! -f .env ]]; then
            echo "error: .env not found. Copy .env.example and fill in:" >&2
            echo "  cp .env.example .env && \$EDITOR .env" >&2
            exit 1
        fi

        echo "→ Creating remote directory $REMOTE_DIR on $SERVER"
        ssh "$SERVER" "mkdir -p $REMOTE_DIR"

        echo "→ Syncing files to $SERVER:$REMOTE_DIR"
        rsync -avz --delete \
            --exclude='.git/' \
            --exclude='__pycache__/' \
            --exclude='.pytest_cache/' \
            --exclude='tests/' \
            --exclude='dist/' \
            --exclude='build/' \
            --exclude='*.egg-info/' \
            ./ "$SERVER:$REMOTE_DIR/"

        echo "→ Pulling images + (re)building api"
        ssh "$SERVER" "cd $REMOTE_DIR && docker compose pull && docker compose build --pull"

        echo "→ Starting stack"
        ssh "$SERVER" "cd $REMOTE_DIR && docker compose up -d"

        echo "→ Waiting 5s and checking health"
        sleep 5
        ssh "$SERVER" "cd $REMOTE_DIR && docker compose ps"

        echo
        echo "Deploy complete. Verify:"
        # Load domains from local .env for the hint
        TELEMETRY="$(grep '^TELEMETRY_DOMAIN=' .env | cut -d= -f2- | tr -d '"')"
        echo "  curl -sSf https://$TELEMETRY/healthz"
        ;;
    logs)
        ssh -t "$SERVER" "cd $REMOTE_DIR && docker compose logs -f --tail=100 api caddy"
        ;;
    down)
        ssh "$SERVER" "cd $REMOTE_DIR && docker compose down"
        ;;
    ps)
        ssh "$SERVER" "cd $REMOTE_DIR && docker compose ps"
        ;;
    *)
        echo "usage: SERVER=user@host $0 {deploy|logs|down|ps}" >&2
        exit 1
        ;;
esac
