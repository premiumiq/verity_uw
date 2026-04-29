#!/bin/bash
# Start the Verity development stack.
#
# Brings up every docker-compose service, waits for postgres to accept
# connections, and applies the Verity DB schema via the `verity init` CLI
# entry point. Idempotent — safe to re-run.
#
# Stop with: ./scripts/stop.sh

set -euo pipefail

# Resolve repo root from this script's location so the script works no
# matter where it's invoked from.
cd "$(dirname "$0")/.."

echo "============================================"
echo " "
echo "                 _ _         "
echo " __   _____ _ __(_) |_ _   _ "
echo " \ \ / / _ \ '__| | __| | | |"
echo "  \ V /  __/ |  | | |_| |_| |"
echo "   \_/ \___|_|  |_|\__|\__, |"
echo "                       |___/ "
echo "============================================"
echo " "
echo "==> bringing up docker compose services"
docker compose up -d

echo "==> waiting for verity_postgres to accept connections"
for i in $(seq 1 30); do
    if docker exec verity_postgres pg_isready -U verityuser -d postgres -q 2>/dev/null; then
        echo "    postgres ready (after ${i}s)"
        break
    fi
    if [ "$i" = "30" ]; then
        echo "ERROR: postgres did not become ready within 30s"
        echo "Check logs with: docker logs verity_postgres"
        exit 1
    fi
    sleep 1
done

echo "==> applying Verity schema via 'verity init' inside verity_app"
# Use the verity CLI entry point rather than re-implementing schema apply
# in shell. The CLI path keeps a single source of truth for DDL ordering.
if ! docker exec verity_app verity init 2>&1 | tail -5; then
    echo ""
    echo "WARNING: 'verity init' did not complete cleanly."
    echo "Inspect with: docker logs verity_app"
fi

echo ""
echo "==> services up:"
docker compose ps --format 'table {{.Service}}\t{{.Status}}'

echo ""
echo "Endpoints:"
echo "  Verity API:    http://localhost:8000"
echo "  UW demo:       http://localhost:8001"
echo "  EDMS:          http://localhost:8002"
echo "  Postgres:      localhost:5432  (verityuser / veritypass123)"
echo "  MinIO console: http://localhost:9001"
echo ""
echo "Stop with: ./scripts/stop.sh"